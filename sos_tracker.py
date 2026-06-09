"""
CA Governor 2026 — SOS Results Tracker
=======================================
Polls the California Secretary of State's raw JSON API for governor race
updates. Targets the API endpoint directly to avoid JS-rendering/caching
issues with the main results page.

SETUP (one time):
  pip install requests python-dotenv

OPTIONAL — email alerts:
  Create a .env file in the same folder with:
    EMAIL_FROM=you@gmail.com
    EMAIL_TO=you@gmail.com
    EMAIL_PASSWORD=your_app_password   # Gmail App Password, not your main password

USAGE:
  python sos_tracker.py                  # polls every 30 minutes (default)
  python sos_tracker.py --interval 15    # polls every 15 minutes
  python sos_tracker.py --once           # run once and exit (good for testing)
  python sos_tracker.py --notify email   # send email alerts on new batches

WHAT IT DOES:
  - Fetches live JSON directly from the CA SOS API (bypasses JS rendering)
  - Compares Hilton, Becerra, Steyer, Bianco totals to last saved snapshot
  - If totals changed: prints full batch analysis (new votes, batch share %,
    R vs D gap, lead growing/shrinking)
  - Saves each snapshot to a local JSON log file for your records
  - Optionally emails you when a new batch drops
"""

import requests
import json
import os
import time
import argparse
import smtplib
from datetime import datetime
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ── CONFIG ────────────────────────────────────────────────────────────────────

# Raw JSON API endpoints — these return structured data directly,
# bypassing the JavaScript-rendered results page entirely.
# Primary endpoint: api.sos.ca.gov (confirmed working during election night)
# Fallback endpoint: dp.electionresults.sos.ca.gov with JSON Accept header
API_ENDPOINTS = [
    "https://api.sos.ca.gov/returns/governor",
    "https://dp.electionresults.sos.ca.gov/returns/governor",
]

SNAPSHOT_FILE = str(Path(__file__).parent / "sos_snapshots.json")
CANDIDATES_TO_TRACK = ["Steve Hilton", "Xavier Becerra", "Tom Steyer", "Chad Bianco"]
DEFAULT_INTERVAL_MINUTES = 30

# ── FETCH ─────────────────────────────────────────────────────────────────────

def fetch_results():
    """
    Fetch the latest governor race JSON from the SOS API.
    Tries primary endpoint first, falls back to secondary if needed.
    Uses cache-busting headers to ensure we always get fresh data.
    """
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": "https://dp.electionresults.sos.ca.gov/",
        "Origin": "https://dp.electionresults.sos.ca.gov",
    }

    for endpoint in API_ENDPOINTS:
        try:
            # Cache-bust with a timestamp query param so CDN never serves stale data
            url = f"{endpoint}?_={int(time.time())}"
            print(f"  → Trying: {endpoint}")

            response = requests.get(url, headers=headers, timeout=20)
            response.raise_for_status()

            # Try parsing as JSON directly
            try:
                data = response.json()
                if data and ("candidates" in data or "Reporting" in data):
                    print(f"  ✓ Got valid JSON from {endpoint}")
                    return data
                else:
                    print(f"  ✗ Response missing expected fields — trying next endpoint")
                    continue
            except ValueError:
                # Try stripping JSONP/Angular wrapper if present
                text = response.text.strip()
                if "(" in text and text.endswith(")"):
                    try:
                        inner = text[text.index("(") + 1 : text.rindex(")")]
                        data = json.loads(inner)
                        if data and "candidates" in data:
                            print(f"  ✓ Got valid JSONP from {endpoint}")
                            return data
                    except (ValueError, json.JSONDecodeError):
                        pass
                print(f"  ✗ Could not parse response from {endpoint}")
                continue

        except requests.exceptions.ConnectionError:
            print(f"  ✗ Connection error: {endpoint}")
            continue
        except requests.exceptions.Timeout:
            print(f"  ✗ Timeout: {endpoint}")
            continue
        except requests.exceptions.HTTPError as e:
            print(f"  ✗ HTTP {e.response.status_code}: {endpoint}")
            continue
        except Exception as e:
            print(f"  ✗ Unexpected error ({endpoint}): {e}")
            continue

    print("  [ERROR] All endpoints failed.")
    return None


# ── PARSE ─────────────────────────────────────────────────────────────────────

def parse_votes(vote_str):
    """Safely parse a vote count string like '1,386,966' to int."""
    try:
        return int(str(vote_str).replace(",", "").strip())
    except (ValueError, AttributeError):
        return 0


def parse_snapshot(data):
    """Extract key fields from the raw SOS JSON response."""
    if not data:
        return None

    snapshot = {
        "fetched_at": datetime.now().isoformat(),
        "reporting_time": data.get("ReportingTime", "Unknown"),
        "reporting_pct": data.get("Reporting", "Unknown"),
        "candidates": {},
        "party_totals": {"Dem": 0, "Rep": 0, "NPP": 0, "Lib": 0, "PF": 0, "Other": 0},
        "total_gov_votes": 0,
    }

    candidates = data.get("candidates", [])
    for c in candidates:
        name   = c.get("Name", "").strip()
        party  = c.get("Party", "").strip()
        votes  = parse_votes(c.get("Votes", 0))
        pct    = float(c.get("Percent", 0) or 0)

        # Party aggregate totals
        if party == "Dem":
            snapshot["party_totals"]["Dem"] += votes
        elif party == "Rep":
            snapshot["party_totals"]["Rep"] += votes
        elif party == "NPP":
            snapshot["party_totals"]["NPP"] += votes
        elif party == "Lib":
            snapshot["party_totals"]["Lib"] += votes
        elif party in ("P&F", "PF"):
            snapshot["party_totals"]["PF"] += votes
        else:
            snapshot["party_totals"]["Other"] += votes

        snapshot["total_gov_votes"] += votes

        # Store tracked candidates
        if name in CANDIDATES_TO_TRACK:
            snapshot["candidates"][name] = {
                "votes": votes,
                "party": party,
                "pct": pct,
            }

    return snapshot


# ── COMPARE ───────────────────────────────────────────────────────────────────

def has_changed(current, previous):
    """Return True if any tracked candidate vote total changed."""
    if previous is None:
        return True
    for name in CANDIDATES_TO_TRACK:
        curr_v = current["candidates"].get(name, {}).get("votes", 0)
        prev_v = previous["candidates"].get(name, {}).get("votes", 0)
        if curr_v != prev_v:
            return True
    return False


def compute_batch(current, previous):
    """
    Calculate new votes and batch share % for tracked candidates since
    the last snapshot. Batch share is each candidate's % of new votes
    added across all tracked candidates in this drop.
    """
    batch_new   = {}
    total_new   = 0

    for name in CANDIDATES_TO_TRACK:
        curr_v = current["candidates"].get(name, {}).get("votes", 0)
        prev_v = previous["candidates"].get(name, {}).get("votes", 0) if previous else 0
        new_v  = max(0, curr_v - prev_v)
        batch_new[name] = new_v
        total_new += new_v

    batch_share = {}
    for name in CANDIDATES_TO_TRACK:
        batch_share[name] = round(batch_new[name] / total_new * 100, 1) if total_new > 0 else 0.0

    return batch_new, batch_share, total_new


# ── DISPLAY ───────────────────────────────────────────────────────────────────

DIV  = "─" * 64
HDIV = "═" * 64

def print_snapshot(current, previous=None):
    """Print a formatted batch analysis to the terminal."""
    print(f"\n{HDIV}")
    print(f"  CA GOVERNOR 2026 — {'FIRST SNAPSHOT' if not previous else 'NEW BATCH DETECTED'}")
    print(HDIV)
    print(f"  Reported:    {current['reporting_time']}")
    print(f"  Precincts:   {current['reporting_pct']}")
    print(f"  Fetched at:  {current['fetched_at']}")
    print(f"  Total gov votes: {current['total_gov_votes']:,}")
    print(DIV)

    # Candidate totals
    print(f"  {'CANDIDATE':<22} {'PARTY':<5} {'VOTES':>12}  {'CUM%':>6}  {'CHANGE':>10}")
    print(DIV)

    for name in CANDIDATES_TO_TRACK:
        curr = current["candidates"].get(name, {})
        prev_v = previous["candidates"].get(name, {}).get("votes", 0) if previous else 0
        delta  = curr.get("votes", 0) - prev_v
        delta_str = f"+{delta:,}" if delta >= 0 else f"{delta:,}"
        print(f"  {name:<22} {curr.get('party','?'):<5} {curr.get('votes',0):>12,}  {curr.get('pct',0):>5.1f}%  {delta_str:>10}")

    print(DIV)

    # Batch share analysis
    if previous:
        batch_new, batch_share, total_new = compute_batch(current, previous)

        hilton_bat  = batch_share.get("Steve Hilton", 0)
        becerra_bat = batch_share.get("Xavier Becerra", 0)
        steyer_bat  = batch_share.get("Tom Steyer", 0)
        bianco_bat  = batch_share.get("Chad Bianco", 0)

        r_bat = hilton_bat + bianco_bat
        d_bat = becerra_bat + steyer_bat

        print(f"  BATCH ANALYSIS  ({total_new:,} new votes in this drop)")
        print(DIV)
        print(f"  {'Hilton':<18} {hilton_bat:>5.1f}%  ({batch_new.get('Steve Hilton',0):>8,} new)")
        print(f"  {'Becerra':<18} {becerra_bat:>5.1f}%  ({batch_new.get('Xavier Becerra',0):>8,} new)")
        print(f"  {'Steyer':<18} {steyer_bat:>5.1f}%  ({batch_new.get('Tom Steyer',0):>8,} new)")
        print(f"  {'Bianco':<18} {bianco_bat:>5.1f}%  ({batch_new.get('Chad Bianco',0):>8,} new)")
        print(DIV)
        print(f"  R combined batch:      {r_bat:>5.1f}%")
        print(f"  D combined batch:      {d_bat:>5.1f}%")
        print(f"  Historical R baseline:  67.0%  ", end="")
        if hilton_bat < 50:
            print("← D gaining (mail-in effect)")
        elif hilton_bat < 60:
            print("← Mixed batch")
        else:
            print("← R holding advantage (election day vote)")
        print(DIV)

    # Key gaps
    hilton_v  = current["candidates"].get("Steve Hilton", {}).get("votes", 0)
    becerra_v = current["candidates"].get("Xavier Becerra", {}).get("votes", 0)
    steyer_v  = current["candidates"].get("Tom Steyer", {}).get("votes", 0)

    hb_gap = hilton_v - becerra_v
    bs_gap = becerra_v - steyer_v

    if previous:
        prev_hb = (previous["candidates"].get("Steve Hilton", {}).get("votes", 0) -
                   previous["candidates"].get("Xavier Becerra", {}).get("votes", 0))
        hb_delta = hb_gap - prev_hb
        direction = "↑ growing" if hb_delta > 0 else "↓ shrinking" if hb_delta < 0 else "→ flat"
        print(f"  Hilton lead over Becerra:  +{hb_gap:,}  ({direction}, {hb_delta:+,} this batch)")
    else:
        print(f"  Hilton lead over Becerra:  +{hb_gap:,}")

    print(f"  Becerra lead over Steyer:  +{bs_gap:,}")

    # Party totals
    print(DIV)
    d_total = current["party_totals"]["Dem"]
    r_total = current["party_totals"]["Rep"]
    total   = current["total_gov_votes"]
    d_pct   = round(d_total / total * 100, 1) if total > 0 else 0
    r_pct   = round(r_total / total * 100, 1) if total > 0 else 0
    print(f"  Total D votes (all D candidates):  {d_total:>12,}  ({d_pct:.1f}%)")
    print(f"  Total R votes (all R candidates):  {r_total:>12,}  ({r_pct:.1f}%)")
    print(f"  D-R aggregate gap:                 +{d_total - r_total:>10,} D advantage")
    print(f"{HDIV}\n")


def format_alert_text(current, previous):
    """Format a concise plain-text alert for email notifications."""
    batch_new, batch_share, total_new = compute_batch(current, previous)

    hilton  = current["candidates"].get("Steve Hilton", {})
    becerra = current["candidates"].get("Xavier Becerra", {})
    steyer  = current["candidates"].get("Tom Steyer", {})
    gap     = hilton.get("votes", 0) - becerra.get("votes", 0)

    prev_gap = (previous["candidates"].get("Steve Hilton", {}).get("votes", 0) -
                previous["candidates"].get("Xavier Becerra", {}).get("votes", 0))
    gap_delta = gap - prev_gap
    direction = "↑ growing" if gap_delta > 0 else "↓ shrinking" if gap_delta < 0 else "→ flat"

    d_bat_pct = (batch_share.get("Xavier Becerra", 0) + batch_share.get("Tom Steyer", 0))

    return f"""CA GOVERNOR 2026 UPDATE
{current['reporting_time']} · {current['reporting_pct']}

CUMULATIVE TOTALS:
  Hilton  (R): {hilton.get('votes',0):>12,}  ({hilton.get('pct',0):.1f}%)
  Becerra (D): {becerra.get('votes',0):>12,}  ({becerra.get('pct',0):.1f}%)
  Steyer  (D): {steyer.get('votes',0):>12,}  ({steyer.get('pct',0):.1f}%)

THIS BATCH ({total_new:,} new votes):
  Hilton:         {batch_share.get('Steve Hilton',0):.1f}%  (+{batch_new.get('Steve Hilton',0):,})
  Becerra:        {batch_share.get('Xavier Becerra',0):.1f}%  (+{batch_new.get('Xavier Becerra',0):,})
  Steyer:         {batch_share.get('Tom Steyer',0):.1f}%  (+{batch_new.get('Tom Steyer',0):,})
  D combined:     {d_bat_pct:.1f}%

Hilton lead: +{gap:,}  ({direction}, {gap_delta:+,} this batch)

---
Source: api.sos.ca.gov/returns/governor
Canvass certification: July 10, 2026
"""


# ── NOTIFICATIONS ─────────────────────────────────────────────────────────────

def send_email(subject, body):
    """Send an email alert via Gmail SMTP."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    email_from     = os.getenv("EMAIL_FROM")
    email_to       = os.getenv("EMAIL_TO")
    email_password = os.getenv("EMAIL_PASSWORD")

    if not all([email_from, email_to, email_password]):
        print("  [EMAIL] Skipped — set EMAIL_FROM / EMAIL_TO / EMAIL_PASSWORD in .env")
        return

    try:
        msg = MIMEMultipart()
        msg["From"]    = email_from
        msg["To"]      = email_to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(email_from, email_password)
            server.sendmail(email_from, email_to, msg.as_string())
        print(f"  [EMAIL] Alert sent to {email_to}")

    except smtplib.SMTPAuthenticationError:
        print("  [EMAIL] Authentication failed — check EMAIL_PASSWORD in .env")
    except Exception as e:
        print(f"  [EMAIL] Failed to send: {e}")


# ── SNAPSHOT LOG ──────────────────────────────────────────────────────────────

def load_snapshots():
    """Load the local snapshot log from disk."""
    if Path(SNAPSHOT_FILE).exists():
        try:
            with open(SNAPSHOT_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            print(f"  [WARN] Could not read {SNAPSHOT_FILE} — starting fresh")
    return []


def save_snapshot(snapshot, all_snapshots):
    """Append latest snapshot to the local log file."""
    all_snapshots.append(snapshot)
    try:
        with open(SNAPSHOT_FILE, "w") as f:
            json.dump(all_snapshots, f, indent=2)
        print(f"  [LOG] Snapshot saved to {SNAPSHOT_FILE} ({len(all_snapshots)} total)")
    except IOError as e:
        print(f"  [WARN] Could not save snapshot: {e}")


# ── MAIN LOOP ─────────────────────────────────────────────────────────────────

def run(interval_minutes=DEFAULT_INTERVAL_MINUTES, notify=None, run_once=False):
    """Main polling loop."""
    print(f"\n{HDIV}")
    print(f"  CA GOVERNOR 2026 — SOS TRACKER STARTED")
    print(f"  API:      {API_ENDPOINTS[0]}")
    print(f"  Fallback: {API_ENDPOINTS[1]}")
    print(f"  Interval: every {interval_minutes} minutes")
    print(f"  Tracking: {', '.join(CANDIDATES_TO_TRACK)}")
    print(f"  Log file: {SNAPSHOT_FILE}")
    print(f"  Press Ctrl+C to stop")
    print(f"{HDIV}\n")

    all_snapshots = load_snapshots()
    last_snapshot = all_snapshots[-1] if all_snapshots else None

    if last_snapshot:
        print(f"  [LOG] Loaded {len(all_snapshots)} prior snapshots.")
        print(f"        Last known: {last_snapshot.get('reporting_time', 'unknown')}\n")

    poll_count = 0

    while True:
        poll_count += 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] Poll #{poll_count}")

        raw_data = fetch_results()
        current  = parse_snapshot(raw_data)

        if current is None:
            print(f"  [WARN] No valid data — retrying in {interval_minutes} min\n")

        elif has_changed(current, last_snapshot):
            print_snapshot(current, last_snapshot)

            if notify == "email" and last_snapshot:
                hilton_pct = current["candidates"].get("Steve Hilton", {}).get("pct", 0)
                subject = (
                    f"CA Gov Update: {current['reporting_pct']} · "
                    f"Hilton {hilton_pct:.1f}% · "
                    f"{current['reporting_time']}"
                )
                send_email(subject, format_alert_text(current, last_snapshot))

            save_snapshot(current, all_snapshots)
            last_snapshot = current

        else:
            pct = current.get("reporting_pct", "unknown") if current else "unknown"
            print(f"  No change. Still at: {pct}\n")

        if run_once:
            print("  [--once] Done.\n")
            break

        print(f"  Next poll in {interval_minutes} minutes...\n")
        time.sleep(interval_minutes * 60)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Poll CA SOS governor results JSON API and alert on new batches.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python sos_tracker.py                  # poll every 30 min
  python sos_tracker.py --interval 15    # poll every 15 min
  python sos_tracker.py --once           # test: fetch once and exit
  python sos_tracker.py --notify email   # email alerts on new batches
        """
    )
    parser.add_argument(
        "--interval", type=int, default=DEFAULT_INTERVAL_MINUTES,
        metavar="MINUTES",
        help=f"Polling interval in minutes (default: {DEFAULT_INTERVAL_MINUTES})"
    )
    parser.add_argument(
        "--notify", choices=["email"], default=None,
        help="Send notification when a new batch is detected"
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Fetch once and exit (useful for testing)"
    )

    args = parser.parse_args()

    try:
        run(
            interval_minutes=args.interval,
            notify=args.notify,
            run_once=args.once,
        )
    except KeyboardInterrupt:
        print("\n\n  Tracker stopped. Goodbye.\n")
