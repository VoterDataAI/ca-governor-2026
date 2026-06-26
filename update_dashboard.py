#!/usr/bin/env python3
"""
update_dashboard.py — CA Governor 2026 canvass tracker dashboard updater
Reads: sos_snapshots.json + counties_data.json
Writes: index.html (published directly to GitHub Pages)

Usage:
    python3 update_dashboard.py
    python3 update_dashboard.py --html index.html
    python3 update_dashboard.py --snapshots sos_snapshots.json --counties counties_data.json
"""

import json
import re
import argparse
from datetime import datetime
from pathlib import Path

# ── CLI args ──────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument('--snapshots', default='sos_snapshots.json')
parser.add_argument('--counties',  default='counties_data.json')
parser.add_argument('--html',      default='index.html')
parser.add_argument('--out',       default=None,
                    help='Output path (defaults to overwriting --html)')
args = parser.parse_args()
OUT_PATH = args.out or args.html

# ── Hardcoded election night baseline (S1–S7, final/frozen) ──────────────────
EN_SNAPSHOTS = [
    {"id":"S1","datetime":"Jun 2 · 10:50p","type":"Election night","pcts":"76.1%",
     "hilton":1169795,"hilton_pct":26.9,"becerra":1120455,"becerra_pct":25.7,
     "steyer":862336,"steyer_pct":19.8,"gap":307459,"gap_delta":"—","d_bat":"—","gap_dir":"r"},
    {"id":"S2","datetime":"Jun 2 · 11:46p","type":"Election night","pcts":"80.9%",
     "hilton":1272843,"hilton_pct":27.5,"becerra":1179775,"becerra_pct":25.5,
     "steyer":908505,"steyer_pct":19.6,"gap":364338,"gap_delta":"↑+56,879","d_bat":"50.6%","gap_dir":"r"},
    {"id":"S3","datetime":"Jun 2 · 12:10a","type":"Election night","pcts":"82.3%",
     "hilton":1285021,"hilton_pct":27.6,"becerra":1188080,"becerra_pct":25.5,
     "steyer":915827,"steyer_pct":19.6,"gap":369194,"gap_delta":"↑+4,856","d_bat":"56.2%","gap_dir":"r"},
    {"id":"S4","datetime":"Jun 2 · 12:24a","type":"Election night","pcts":"87.3%",
     "hilton":1310392,"hilton_pct":27.6,"becerra":1211441,"becerra_pct":25.5,
     "steyer":932645,"steyer_pct":19.6,"gap":377747,"gap_delta":"↑+8,553","d_bat":"65.2%","gap_dir":"r"},
    {"id":"S5","datetime":"Jun 3 · 1:06a","type":"Election night","pcts":"94.6%",
     "hilton":1336484,"hilton_pct":27.7,"becerra":1230085,"becerra_pct":25.5,
     "steyer":946775,"steyer_pct":19.6,"gap":389709,"gap_delta":"↑+11,962","d_bat":"62.0% ↓","gap_dir":"r"},
    {"id":"S6","datetime":"Jun 3 · 1:35a","type":"Election night","pcts":"94.8%",
     "hilton":1351236,"hilton_pct":27.7,"becerra":1240220,"becerra_pct":25.4,
     "steyer":954467,"steyer_pct":19.6,"gap":396769,"gap_delta":"↑+7,060","d_bat":"est.","gap_dir":"r"},
    {"id":"S7","datetime":"Jun 3 · 4:44a","type":"100% final EN","pcts":"100%",
     "hilton":1386966,"hilton_pct":27.8,"becerra":1267070,"becerra_pct":25.4,
     "steyer":979007,"steyer_pct":19.6,"gap":407959,"gap_delta":"↑+11,190","d_bat":"FINAL EN","gap_dir":"r"},
]

# S7 baseline for "since election night" deltas
EN_H = 1386966
EN_B = 1267070
EN_S = 979007
EN_H_PCT = 27.8
EN_B_PCT = 25.4
EN_TOTAL_GOV = 4994976  # S7 total gov votes

# EN party totals for D-R gap baseline
EN_D_VOTES = 2896001  # C1 Dem total (proxy for EN)
EN_R_VOTES = 2029821  # C1 Rep total

# ── Load data files ───────────────────────────────────────────────────────────
def load_json(path, label):
    p = Path(path)
    if not p.exists():
        print(f"  WARNING: {label} not found at {path} — skipping those updates")
        return None
    with open(p) as f:
        return json.load(f)

snapshots = load_json(args.snapshots, 'sos_snapshots.json')
counties  = load_json(args.counties,  'counties_data.json')

if not snapshots:
    print("ERROR: sos_snapshots.json required. Exiting.")
    exit(1)

# ── Backfill / assign snapshot_ids ───────────────────────────────────────────
changed = False
for i, snap in enumerate(snapshots):
    expected_id = f"C{i+1}"
    if snap.get('snapshot_id') != expected_id:
        snap['snapshot_id'] = expected_id
        changed = True
if changed:
    with open(args.snapshots, 'w') as f:
        json.dump(snapshots, f, indent=2)
    print(f"  Backfilled snapshot_ids C1–C{len(snapshots)} into {args.snapshots}")

# ── Parse reporting_time → display strings ───────────────────────────────────
MONTH_MAP = {
    'January':'Jan','February':'Feb','March':'Mar','April':'Apr',
    'May':'May','June':'Jun','July':'Jul','August':'Aug',
    'September':'Sep','October':'Oct','November':'Nov','December':'Dec'
}

def parse_reporting_time(rt):
    """'June 5, 2026, 5:21 p.m.' → ('Jun 5', '5:21p', 'Jun5 5p')"""
    rt = rt.strip()
    m = re.match(r'(\w+)\s+(\d+),\s+\d+,\s+(\d+:\d+)\s+(a\.m\.|p\.m\.)', rt)
    if not m:
        return rt, rt, rt
    month  = MONTH_MAP.get(m.group(1), m.group(1))
    day    = m.group(2)
    time   = m.group(3)
    ampm   = 'a' if 'a.m.' in m.group(4) else 'p'
    # Table format: "Jun 5 · 5:21p"
    table  = f"{month} {day} · {time}{ampm}"
    # Chart label: "C7·Jun5 5p"  (no spaces around dot, compact)
    chart  = f"{month}{day} {time.split(':')[0]}{ampm}"
    return table, chart, f"{month} {day}, {time} {m.group(4)}"

# ── Derive canvass snapshot rows ──────────────────────────────────────────────
canvass_rows = []
prev_gap = None

for i, snap in enumerate(snapshots):
    cid  = snap['snapshot_id']
    h    = snap['candidates']['Steve Hilton']['votes']
    b    = snap['candidates']['Xavier Becerra']['votes']
    s    = snap['candidates']['Tom Steyer']['votes']
    h_p  = snap['candidates']['Steve Hilton']['pct']
    b_p  = snap['candidates']['Xavier Becerra']['pct']
    s_p  = snap['candidates']['Tom Steyer']['pct']
    total = snap['total_gov_votes']

    raw_gap  = h - s        # positive = Hilton leads Steyer, negative = Steyer leads Hilton
    abs_gap  = abs(raw_gap)
    gap_dir  = 'r' if raw_gap > 0 else 'b'

    # Gap delta vs previous canvass (H-S)
    EN_H_S = EN_H - EN_S   # S7 H-S baseline: 1,386,966 - 979,007 = 407,959
    if prev_gap is None:
        prev = EN_H_S
    else:
        prev = prev_gap

    delta_raw = raw_gap - prev
    if delta_raw < 0:
        gap_delta = f"↓{delta_raw:,}".replace('-','−')  # Steyer closing on Hilton
        delta_dir = 'b'  # blue — Steyer gained
    elif delta_raw > 0:
        gap_delta = f"↑+{delta_raw:,}"
        delta_dir = 'r'  # red — Hilton gained
    else:
        gap_delta = "—"
        delta_dir = 'n'  # neutral — no change

    # Batch D share — share of newly added governor votes going to D candidates
    if i == 0:
        prev_total = EN_TOTAL_GOV
        prev_d     = EN_D_VOTES
        prev_r     = EN_R_VOTES
    else:
        prev_snap  = snapshots[i-1]
        prev_total = prev_snap['total_gov_votes']
        prev_d     = prev_snap['party_totals']['Dem']
        prev_r     = prev_snap['party_totals']['Rep']

    batch_total = total - prev_total
    batch_d     = snap['party_totals']['Dem'] - prev_d
    batch_r     = snap['party_totals']['Rep'] - prev_r

    if batch_total > 0:
        d_bat_pct = round(batch_d / batch_total * 100, 1)
        d_bat     = f"{d_bat_pct}%"
    else:
        d_bat = "—"

    table_dt, chart_label, _ = parse_reporting_time(snap['reporting_time'])

    # Peak detection — C1 had the highest Hilton lead
    is_peak = (cid == 'C1')
    is_cur  = (i == len(snapshots) - 1)

    canvass_rows.append({
        "id": cid, "datetime": table_dt, "chart_label": chart_label,
        "hilton": h, "hilton_pct": h_p,
        "becerra": b, "becerra_pct": b_p,
        "steyer": s, "steyer_pct": s_p,
        "raw_gap": raw_gap, "abs_gap": abs_gap, "gap_dir": gap_dir,
        "gap_delta": gap_delta, "delta_dir": delta_dir, "d_bat": d_bat,
        "batch_h": round(batch_r > 0 and (h - (snapshots[i-1]['candidates']['Steve Hilton']['votes'] if i>0 else EN_H)) / batch_total * 100, 1) if batch_total > 0 else 0,
        "batch_b": round((b - (snapshots[i-1]['candidates']['Xavier Becerra']['votes'] if i>0 else EN_B)) / batch_total * 100, 1) if batch_total > 0 else 0,
        "batch_s": round((s - (snapshots[i-1]['candidates']['Tom Steyer']['votes'] if i>0 else EN_S)) / batch_total * 100, 1) if batch_total > 0 else 0,
        "is_peak": is_peak, "is_cur": is_cur,
        "party_d": snap['party_totals']['Dem'],
        "party_r": snap['party_totals']['Rep'],
        "total_gov": total,
    })
    prev_gap = raw_gap

# ── Current (latest) snapshot ─────────────────────────────────────────────────
cur = canvass_rows[-1]
H   = cur['hilton']
B   = cur['becerra']
S   = cur['steyer']
H_P = cur['hilton_pct']
B_P = cur['becerra_pct']
S_P = cur['steyer_pct']
# H-B gap for alert/card/lead logic (independent of H-S table gap)
HB_RAW  = H - B       # negative = Becerra leads
HB_ABS  = abs(HB_RAW)
GAP     = HB_RAW
ABS_GAP = HB_ABS
LEADER  = 'Becerra' if GAP < 0 else 'Hilton'
LEADER_COLOR = '#2563eb' if GAP < 0 else '#e03030'
TOTAL_GOV = cur['total_gov']
D_VOTES   = cur['party_d']
R_VOTES   = cur['party_r']
CID       = cur['id']
CDT       = cur['datetime']
SNAP_COUNT = len(EN_SNAPSHOTS) + len(canvass_rows)

# Since election night deltas
H_DELTA = H - EN_H
B_DELTA = B - EN_B
S_DELTA = S - EN_S
H_PCT_DELTA = round(H_P - EN_H_PCT, 1)
B_PCT_DELTA = round(B_P - EN_B_PCT, 1)

# Placement
if GAP < 0:  # Becerra leads
    b_place = "1st"; b_place_label = "Democrat · 1st place"
    h_place = "2nd"; h_place_label = "Republican · 2nd place"
else:
    h_place = "1st"; h_place_label = "Republican · 1st place"
    b_place = "2nd"; b_place_label = "Democrat · 2nd place"

# B-S gap
BS_GAP = B - S

# D-R aggregate
D_PCT  = round(D_VOTES / TOTAL_GOV * 100, 1)
R_PCT  = round(R_VOTES / TOTAL_GOV * 100, 1)
DR_GAP = D_VOTES - R_VOTES
EN_DR_GAP = EN_D_VOTES - EN_R_VOTES

# Cand card bar widths (relative to leader = 100%)
leader_votes = max(H, B)
H_BAR = round(H / leader_votes * 100, 1)
B_BAR = round(B / leader_votes * 100, 1)
S_BAR = round(S / leader_votes * 100, 1)

# Snapshots logged label
en_count = len(EN_SNAPSHOTS)
cv_count = len(canvass_rows)

# ── Build snapshot table HTML ─────────────────────────────────────────────────
def fmt_gap_td(row):
    raw = row['raw_gap']
    abs_g = row['abs_gap']
    if raw < 0:
        return f'<td style="color:var(--blue);font-weight:600;">−{abs_g:,}</td>'
    elif row['is_peak']:
        return f'<td style="color:var(--red);">+{abs_g:,}</td>'
    else:
        return f'<td style="color:var(--red);">+{abs_g:,}</td>'

def snap_row_html(r, row_class=""):
    hs_gap = r['hilton'] - r['steyer']
    hs_abs = abs(hs_gap)
    if hs_gap > 0:
        hs_str   = f'+{hs_abs:,}'
        hs_color = 'var(--red)'
    else:
        hs_str   = f'−{hs_abs:,}'
        hs_color = 'var(--blue)'

    if r.get('is_peak'):
        gap_delta_td = f'<td style="color:var(--text-dim);">{r["gap_delta"]}</td>'
    elif r['delta_dir'] == 'r':
        gap_delta_td = f'<td style="color:var(--red);">{r["gap_delta"]}</td>'
    elif r['delta_dir'] == 'b':
        gap_delta_td = f'<td style="color:var(--blue);">{r["gap_delta"]}</td>'
    else:
        gap_delta_td = f'<td style="color:var(--text-dim);">{r["gap_delta"]}</td>'

    d_bat_td = f'<td style="color:var(--blue);">{r["d_bat"]}</td>' if '%' in str(r["d_bat"]) else f'<td style="color:var(--text-dim);">{r["d_bat"]}</td>'

    return f'''          <tr class="{row_class}"><td>{r["id"]}</td><td>{r["datetime"]}</td><td style="color:var(--blue);">Canvass</td><td>100%</td><td>{r["hilton"]:,}</td><td>{r["hilton_pct"]}%</td><td>{r["becerra"]:,}</td><td>{r["becerra_pct"]}%</td><td>{r["steyer"]:,}</td><td>{r["steyer_pct"]}%</td><td style="color:{hs_color};{'font-weight:600;' if r.get('is_cur') else ''}">{hs_str}</td>{gap_delta_td}{d_bat_td}</tr>'''

tbody_html = ""
# EN rows (static)
for r in EN_SNAPSHOTS:
    row_class = "en"
    hs_gap = r['hilton'] - r['steyer']
    hs_str = f'+{hs_gap:,}' if hs_gap > 0 else f'−{abs(hs_gap):,}'
    hs_color = 'var(--red)' if hs_gap > 0 else 'var(--blue)'
    delta_color = 'var(--red)' if r['gap_dir'] == 'r' else 'var(--blue)'
    tbody_html += f'''          <tr class="{row_class}"><td>{r["id"]}</td><td>{r["datetime"]}</td><td>{r["type"]}</td><td>{r["pcts"]}</td><td>{r["hilton"]:,}</td><td>{r["hilton_pct"]}%</td><td>{r["becerra"]:,}</td><td>{r["becerra_pct"]}%</td><td>{r["steyer"]:,}</td><td>{r["steyer_pct"]}%</td><td style="color:{hs_color};">{hs_str}</td><td style="color:{delta_color};">{r["gap_delta"]}</td><td style="color:var(--text-dim);">{r["d_bat"]}</td></tr>\n'''

# Canvass rows
for r in canvass_rows:
    if r['is_peak']:
        row_class = "peak"
    elif r['is_cur']:
        row_class = "cur"
    else:
        row_class = ""
    tbody_html += snap_row_html(r, row_class) + "\n"

# ── Build chart data arrays ───────────────────────────────────────────────────
# ALL_LABS: S1–S7 + all canvass
EN_CHART_LABS  = ['S1·10:50p','S2·11:46p','S3·12:10a','S4·12:24a','S5·1:06a','S6·1:35a','S7·4:44a']
CV_CHART_LABS  = [f"C{r['id'][1:]}·{r['chart_label']}" for r in canvass_rows]
ALL_LABS       = EN_CHART_LABS + CV_CHART_LABS

EN_H_PCTS = [26.9,27.5,27.6,27.6,27.7,27.7,27.8]
EN_B_PCTS = [25.7,25.5,25.5,25.5,25.5,25.4,25.4]
EN_S_PCTS = [19.8,19.6,19.6,19.6,19.6,19.6,19.6]

hiltonAll  = EN_H_PCTS  + [r['hilton_pct']  for r in canvass_rows]
becerraAll = EN_B_PCTS  + [r['becerra_pct'] for r in canvass_rows]
steyerAll  = EN_S_PCTS  + [r['steyer_pct']  for r in canvass_rows]

# Gap chart: canvass only (absolute H-B gap, positive = Hilton leads)
CV_GAP_LABS = [f"C{r['id'][1:]}·{r['chart_label']}" for r in canvass_rows]
cvGap       = [r['raw_gap'] for r in canvass_rows]

# Batch share chart: S2 onward EN (hardcoded) + all canvass
BATCH_LABS_EN = ['S2·11:46p','S3·12:10a','S4·12:24a','S5·1:06a']
BATCH_H_EN    = [49.4,43.8,41.2,49.4]
BATCH_B_EN    = [28.4,29.9,37.9,35.3]
BATCH_S_EN    = [22.1,26.3,27.3,26.8]

BATCH_LABS_CV = CV_CHART_LABS
BATCH_H_CV    = []
BATCH_B_CV    = []
BATCH_S_CV    = []
for i, r in enumerate(canvass_rows):
    if i == 0:
        prev_h = EN_H; prev_b = EN_B; prev_s = EN_S; prev_total = EN_TOTAL_GOV
    else:
        prev_h = canvass_rows[i-1]['hilton']
        prev_b = canvass_rows[i-1]['becerra']
        prev_s = canvass_rows[i-1]['steyer']
        prev_total = canvass_rows[i-1]['total_gov']
    batch_total = r['total_gov'] - prev_total
    if batch_total > 0:
        BATCH_H_CV.append(round((r['hilton']  - prev_h) / batch_total * 100, 1))
        BATCH_B_CV.append(round((r['becerra'] - prev_b) / batch_total * 100, 1))
        BATCH_S_CV.append(round((r['steyer']  - prev_s) / batch_total * 100, 1))
    else:
        BATCH_H_CV.append(None)
        BATCH_B_CV.append(None)
        BATCH_S_CV.append(None)

ALL_BATCH_LABS = BATCH_LABS_EN + BATCH_LABS_CV
ALL_BATCH_H    = BATCH_H_EN    + BATCH_H_CV
ALL_BATCH_B    = BATCH_B_EN    + BATCH_B_CV
ALL_BATCH_S    = BATCH_S_EN    + BATCH_S_CV
BATCH_BASELINE = [67] * len(ALL_BATCH_LABS)

def js_arr(lst):
    def fmt(v):
        return 'null' if v is None else str(v)
    return '[' + ','.join(fmt(v) for v in lst) + ']'

def js_str_arr(lst):
    return '[' + ','.join(f"'{v}'" for v in lst) + ']'

# ── Counties section HTML ─────────────────────────────────────────────────────
if counties:
    c_data      = counties['counties']
    sw_ballots  = counties['statewide_cast']
    sw_turnout  = counties['statewide_turnout_pct']
    sw_out      = counties['statewide_unprocessed']
    sw_cure     = counties['statewide_to_cure']
    c_as_of     = counties['as_of']

    top10 = sorted(c_data, key=lambda x: x['ballots_cast'], reverse=True)[:10]
    max_ballots = top10[0]['ballots_cast']

    lean_css = {
        "Strong D":   "lean-d",
        "D-leaning":  "lean-d",
        "Mixed":      "lean-mix",
        "R-leaning":  "lean-r",
        "Strong R":   "lean-r",
        "":           "lean-mix",
    }

    # Hardcoded county partisan leans (stable, based on historical registration + vote patterns)
    county_lean = {
        "Alameda": "Strong D", "Alpine": "D-leaning", "Amador": "R-leaning",
        "Butte": "R-leaning", "Calaveras": "R-leaning", "Colusa": "R-leaning",
        "Contra Costa": "D-leaning", "Del Norte": "R-leaning", "El Dorado": "Strong R",
        "Fresno": "Mixed", "Glenn": "R-leaning", "Humboldt": "D-leaning",
        "Imperial": "D-leaning", "Inyo": "R-leaning", "Kern": "R-leaning",
        "Kings": "R-leaning", "Lake": "D-leaning", "Lassen": "Strong R",
        "Los Angeles": "Strong D", "Madera": "R-leaning", "Marin": "Strong D",
        "Mariposa": "R-leaning", "Mendocino": "D-leaning", "Merced": "Mixed",
        "Modoc": "Strong R", "Mono": "Mixed", "Monterey": "D-leaning",
        "Napa": "D-leaning", "Nevada": "Mixed", "Orange": "Mixed",
        "Placer": "R-leaning", "Plumas": "R-leaning", "Riverside": "Mixed",
        "Sacramento": "D-leaning", "San Benito": "Mixed", "San Bernardino": "Mixed",
        "San Diego": "Mixed", "San Francisco": "Strong D", "San Joaquin": "Mixed",
        "San Luis Obispo": "Mixed", "San Mateo": "Strong D", "Santa Barbara": "Mixed",
        "Santa Clara": "Strong D", "Santa Cruz": "Strong D", "Shasta": "Strong R",
        "Sierra": "R-leaning", "Siskiyou": "R-leaning", "Solano": "D-leaning",
        "Sonoma": "Strong D", "Stanislaus": "Mixed", "Sutter": "R-leaning",
        "Tehama": "Strong R", "Trinity": "R-leaning", "Tulare": "Strong R",
        "Tuolumne": "R-leaning", "Ventura": "Mixed", "Yolo": "Strong D",
        "Yuba": "R-leaning",
    }

    # Top 10 bar rows
    top10_html = ""
    for c in top10:
        pct_of_max = round(c['ballots_cast'] / max_ballots * 100, 1)
        color = "var(--blue)"
        lean = c.get('lean','')
        if lean == 'R-leaning':
            color = "var(--red)"
        elif lean == 'Mixed':
            color = "var(--purple)"
        top10_html += f'''        <div class="bar-row"><span class="bar-name" style="width:130px;">{c["name"]}</span><div class="bar-track"><div class="bar-fill-inner" style="width:{pct_of_max}%;background:{color};"></div></div><span class="bar-val">{c["ballots_cast"]:,} · {c["turnout_pct"]}%</span></div>\n'''
    top10_src = f'Source: CA SOS county reporting status · {c_as_of} · Statewide: {sw_ballots:,} ballots cast · {sw_turnout}% turnout.'

    # BAR table rows — counties with unprocessed > 20k, sorted by unprocessed desc
    bar_counties = [c for c in c_data if c.get('unprocessed',0) > 20000]
    bar_counties.sort(key=lambda x: x.get('unprocessed',0), reverse=True)

    bar_rows_html = ""
    for c in bar_counties:
        lean = county_lean.get(c['name'], 'Mixed')
        css  = lean_css.get(lean, 'lean-mix')
        if lean in ('R-leaning', 'Strong R'):
            lean_html = f'<span style="font-size:10px;padding:2px 6px;border-radius:3px;background:rgba(224,48,48,0.15);color:var(--red);">{lean}</span>'
        elif lean in ('Strong D', 'D-leaning'):
            lean_html = f'<span style="font-size:10px;padding:2px 6px;border-radius:3px;background:rgba(37,99,235,0.15);color:var(--blue);">{lean}</span>'
        else:
            lean_html = f'<span style="font-size:10px;padding:2px 6px;border-radius:3px;background:rgba(124,58,237,0.15);color:var(--purple);">{lean}</span>'
        is_cur_class = ' class="cur"' if c['name'] == 'Los Angeles' else ''
        proc = c.get('bar_processed', c['ballots_cast'])
        to_cure = c.get('to_cure', 0)
        bar_rows_html += f'''            <tr{is_cur_class}><td><strong>{c["name"]}</strong></td><td>{proc:,}</td><td style="color:var(--gold);">{c.get("unprocessed",0):,}</td><td style="color:var(--text-dim);">{to_cure:,}</td><td>{lean_html}</td></tr>\n'''

    if sw_out and sw_cure:
        bar_note_html = f'<strong style="color:var(--text);">Statewide: {sw_out:,} ballots outstanding · {sw_cure:,} left to cure.</strong> The outstanding universe is overwhelmingly D-leaning — LA alone has {[c for c in c_data if c["name"]=="Los Angeles"][0].get("unprocessed",0):,} remaining.'
    else:
        bar_note_html = f'<strong style="color:var(--text);">Unprocessed ballot data pending.</strong> Next BAR report expected soon — statewide outstanding count will update when available.'

else:
    # No counties file — preserve existing counties section as-is
    top10_html = "<!-- counties_data.json not found — counties tab unchanged -->"
    top10_src  = ""
    bar_rows_html = ""
    bar_note_html = ""
    sw_ballots = None; sw_turnout = None; sw_out = None; sw_cure = None; c_as_of = ""

# ── Alert box text ────────────────────────────────────────────────────────────
if GAP < 0:
    becerra_lead_streak = sum(1 for r in canvass_rows if r['hilton'] - r['becerra'] < 0)
    if becerra_lead_streak <= 1:
        alert_leader_str = f"Becerra has taken the lead"
    else:
        alert_leader_str = f"Becerra continues to expand his lead"
    alert_gap_str    = f'Becerra now leads Hilton by <strong>+{ABS_GAP:,}</strong>'
    alert_trail_str  = f"Becerra's certified lead expected to grow through July 10."
else:
    alert_leader_str = f"Hilton leads"
    alert_gap_str    = f'Hilton leads Becerra by <strong>+{ABS_GAP:,}</strong>'
    alert_trail_str  = f"Canvass continues — {sw_out:,} ballots outstanding statewide." if sw_out else ""

# Delta from previous canvass snapshot (H-B basis)
if len(canvass_rows) >= 2:
    prev_row   = canvass_rows[-2]
    prev_hb    = prev_row['hilton'] - prev_row['becerra']
    cur_hb     = H - B
    gap_change = cur_hb - prev_hb
    abs_change = abs(gap_change)
    if gap_change < 0:
        delta_str = f"Becerra gained <strong>+{abs_change:,}</strong> on Hilton since {prev_row['id']} ({prev_row['datetime']})"
    elif gap_change > 0:
        delta_str = f"Hilton gained <strong>+{abs_change:,}</strong> on Becerra since {prev_row['id']} ({prev_row['datetime']})"
    else:
        delta_str = f"No change in margin since {prev_row['id']} ({prev_row['datetime']})"
else:
    delta_str = ""

c1_gap = abs(canvass_rows[0]['hilton'] - canvass_rows[0]['becerra'])
alert_html = f'''<strong>Canvass update {CID} · {CDT} — {alert_leader_str}.</strong> {alert_gap_str} — a complete reversal from Hilton\'s peak lead of +{c1_gap:,} at C1 (Jun 3). Becerra advances to the November general election. <strong>{sw_out:,} ballots remain outstanding statewide</strong> per the BAR unprocessed ballots report ({c_as_of}) — the vast majority in D-leaning counties. {alert_trail_str}''' if sw_out else f'''<strong>Canvass update {CID} · {CDT} — {alert_leader_str}.</strong> {alert_gap_str}. Becerra advances to the November general election.'''

# ── Header subtitle ───────────────────────────────────────────────────────────
hdr_sub = f"Latest: {CID} · {CDT.replace(' · ', ', ')} · {SNAP_COUNT} total snapshots · Unofficial results"

# ── Lead card label ───────────────────────────────────────────────────────────
lead_label = f"{LEADER} lead · {CID}"
lead_val   = f'+{ABS_GAP:,}'
lead_color = LEADER_COLOR
if GAP < 0:
    lead_sub   = f"was +{c1_gap:,} Hilton at peak (C1)"
    lead_delta = "↓ Hilton lead gone · Becerra now leads"
    lead_delta_color = "#2563eb"
else:
    lead_sub   = f"was +{c1_gap:,} Becerra at peak"
    lead_delta = f"↑ Hilton leads · canvass ongoing"
    lead_delta_color = "#e03030"

# ── D-R gap card ──────────────────────────────────────────────────────────────
dr_gap_m   = round(DR_GAP / 1_000_000, 2)
dr_gap_str = f'+{dr_gap_m:.2f}M D'.replace('.00','').replace('0M','M')
en_dr_m    = round(EN_DR_GAP / 1_000_000, 2)
dr_added   = DR_GAP - EN_DR_GAP
dr_added_k = round(dr_added / 1000)

# ── Total gov votes card ──────────────────────────────────────────────────────
canvass_added = TOTAL_GOV - EN_TOTAL_GOV
canvass_added_m = round(canvass_added / 1_000_000, 2)

# ── Pct deltas ────────────────────────────────────────────────────────────────
h_pct_sign  = f'−{abs(H_PCT_DELTA)}pts' if H_PCT_DELTA < 0 else f'+{H_PCT_DELTA}pts'
b_pct_sign  = f'+{B_PCT_DELTA}pts' if B_PCT_DELTA > 0 else f'−{abs(B_PCT_DELTA)}pts'

# ── Read and update HTML ──────────────────────────────────────────────────────
with open(args.html) as f:
    html = f.read()

def set_id_content(html, id_, new_content):
    """Replace the inner content of the first element with the given id."""
    pattern = rf'(id="{re.escape(id_)}"[^>]*>)(.*?)(<)'
    replacement = rf'\g<1>{new_content}\3'
    result = re.sub(pattern, replacement, html, count=1, flags=re.DOTALL)
    if result == html and f'id="{id_}"' not in html:
        print(f"  WARNING: id='{id_}' not found in HTML")
    return result

def set_id_style_attr(html, id_, style_attr, new_val):
    """Update a specific style property on an element with the given id."""
    pattern = rf'(id="{re.escape(id_)}"[^>]*style=")([^"]*?)(")'
    def replacer(m):
        style = m.group(2)
        prop  = style_attr + ':'
        if prop in style:
            style = re.sub(rf'{re.escape(style_attr)}:[^;]+', f'{style_attr}:{new_val}', style)
        else:
            style = style.rstrip(';') + f';{style_attr}:{new_val}'
        return m.group(1) + style + m.group(3)
    return re.sub(pattern, replacer, html, count=1)

def set_width_style(html, id_, new_width_pct):
    """Update width:X% in the style of element with given id."""
    pattern = rf'(id="{re.escape(id_)}"[^>]*style=")([^"]*?)(")'
    def replacer(m):
        style = re.sub(r'width:[^;%]+%', f'width:{new_width_pct}%', m.group(2))
        return m.group(1) + style + m.group(3)
    return re.sub(pattern, replacer, html, count=1)

# ── Candidate cards — update by data-candidate attribute ─────────────────────
def update_ccard(html, candidate, votes, pct, pct_delta_str, pct_sign, place_label, bar_width, lead_or_trail, abs_gap, bs_gap=None):
    """Update all fields within a candidate card identified by data-candidate."""
    pattern = rf'(data-candidate="{re.escape(candidate)}".*?)(</div>\s*</div>\s*</div>)'

    def replacer(m):
        block = m.group(1)
        # votes
        block = re.sub(r'(<div class="cvotes">)[^<]*(</div>)',
                       rf'\g<1>{votes:,}\2', block)
        # pct line
        if candidate == 'becerra':
            if lead_or_trail == 'leads':
                cpct_str = f'{pct}% · leads Hilton by {abs_gap:,}'
            else:
                cpct_str = f'{pct}% · trails Becerra by {abs_gap:,}'
        elif candidate == 'hilton':
            if lead_or_trail == 'leads':
                cpct_str = f'{pct}% · leads Becerra by {abs_gap:,}'
            else:
                cpct_str = f'{pct}% · trails Becerra by {abs_gap:,}'
        else:  # steyer
            hs_gap = H - S
            cpct_str = f'{pct}% · trails Hilton by {hs_gap:,}'
        block = re.sub(r'(<div class="cpct">)[^<]*(</div>)',
                       rf'\g<1>{cpct_str}\2', block)
        # delta
        since_en = votes - (EN_H if candidate=='hilton' else EN_B if candidate=='becerra' else EN_S)
        en_pct   = EN_H_PCT if candidate=='hilton' else EN_B_PCT if candidate=='becerra' else 19.6
        pct_d    = round(pct - en_pct, 1)
        pct_d_str = f'+{pct_d}pts ↑' if pct_d > 0 else f'{pct_d}pts'
        delta_str = f'+{since_en:,} since election night · {pct_d_str}'
        block = re.sub(r'(<div class="cdelta"[^>]*>)[^<]*(</div>)',
                       rf'\g<1>{delta_str}\2', block)
        # party/place label
        block = re.sub(r'(<div class="cparty">)[^<]*(</div>)',
                       rf'\g<1>{place_label}\2', block)
        # bar width
        block = re.sub(r'(class="cbar-fill"[^>]*style=")[^"]*(")',
                       lambda m, bw=bar_width: m.group(1) + f'width:{bw}%' + m.group(2), block)
        return m.group(0)[:m.group(0).index(m.group(1))] + block + m.group(2)

    return re.sub(pattern, replacer, html, count=1, flags=re.DOTALL)

# Becerra card
if GAP < 0:  # Becerra leads
    html = update_ccard(html, 'becerra', B, B_P, b_pct_sign, b_pct_sign, b_place_label, B_BAR, 'leads', ABS_GAP)
    html = update_ccard(html, 'hilton',  H, H_P, h_pct_sign, h_pct_sign, h_place_label, H_BAR, 'trails', ABS_GAP)
else:
    html = update_ccard(html, 'hilton',  H, H_P, h_pct_sign, h_pct_sign, h_place_label, H_BAR, 'leads', ABS_GAP)
    html = update_ccard(html, 'becerra', B, B_P, b_pct_sign, b_pct_sign, b_place_label, B_BAR, 'trails', ABS_GAP)
html = update_ccard(html, 'steyer', S, S_P, '', '', 'Democrat · 3rd · eliminated', S_BAR, 'eliminated', ABS_GAP, BS_GAP)

# ── crank / placement numbers ─────────────────────────────────────────────────
# Swap the "1" and "2" crank numbers based on who leads
if GAP < 0:  # Becerra 1st, Hilton 2nd — already correct in current HTML
    pass  # crank values are visual only; placement labels updated in ccard above

# ── Header ────────────────────────────────────────────────────────────────────
html = set_id_content(html, 'hdr-sub', hdr_sub)
html = set_id_content(html, 'hdr-total-ballots', f'{TOTAL_GOV:,}')
html = set_id_content(html, 'hdr-total-ballots-label', 'Governor race votes counted')
if sw_ballots:
    html = set_id_content(html, 'hdr-turnout', f'{sw_turnout}%')
if sw_out:
    html = set_id_content(html, 'hdr-gov-votes', f'{sw_out:,}')
    html = set_id_content(html, 'hdr-gov-votes-label', 'Ballots still outstanding')
html = set_id_content(html, 'hdr-lead',       f'+{ABS_GAP:,}')
html = set_id_content(html, 'hdr-lead-label', f'{LEADER} lead · current')
html = set_id_style_attr(html, 'hdr-lead', 'color', LEADER_COLOR)

# Update last-fetched timestamp
now_str = datetime.now().strftime('%-I:%M %p').lower().replace(' ', ' ')
html = set_id_content(html, 'hdr-last-fetched', f'Last updated: {CID} · {CDT}')

# ── Alert box ─────────────────────────────────────────────────────────────────
# Alert box — full inner content replacement (avoids accumulation bug)
alert_marker = 'id="alert-box"'
alert_start = html.find(alert_marker)
if alert_start != -1:
    tag_end   = html.index('>', alert_start) + 1
    close_idx = html.index('</div>', tag_end)
    html = html[:tag_end] + alert_html + html[close_idx:]
else:
    print("  WARNING: id='alert-box' not found in HTML")

# ── Grid-4 stat cards ─────────────────────────────────────────────────────────
def update_card(html, card_id, label, val, val_color, sub, delta, delta_color):
    """Replace an entire card div by walking the HTML to find its matching closing tag."""
    marker = f'<div class="card" id="{card_id}"'
    start = html.find(marker)
    if start == -1:
        print(f"  WARNING: card '{card_id}' not found")
        return html
    # Walk forward counting <div and </div> to find the balanced closing tag
    depth = 0
    i = start
    while i < len(html):
        if html[i:i+4] == '<div':
            depth += 1
            i += 4
        elif html[i:i+6] == '</div>':
            depth -= 1
            if depth == 0:
                end = i + 6  # include the closing </div>
                break
            i += 6
        else:
            i += 1
    else:
        print(f"  WARNING: card '{card_id}' closing tag not found")
        return html

    new_card = (
        f'<div class="card" id="{card_id}">'
        f'<div class="card-label" id="{card_id}-label">{label}</div>'
        f'<div class="card-val" style="color:{val_color};">{val}</div>'
        f'<div class="card-sub">{sub}</div>'
        f'<div class="card-delta" style="color:{delta_color};">{delta}</div>'
        f'</div>'
    )
    return html[:start] + new_card + html[end:]

html = update_card(html, 'card-lead',
    label=lead_label, val=lead_val, val_color=lead_color,
    sub=lead_sub, delta=lead_delta, delta_color=lead_delta_color)

html = update_card(html, 'card-dr-gap',
    label='D-R aggregate gap', val=dr_gap_str, val_color='#2563eb',
    sub=f'was +{en_dr_m:.2f}M election night'.replace('.00M','M'),
    delta=f'+{dr_added_k}k D added in canvass', delta_color='#2563eb')

html = update_card(html, 'card-total-votes',
    label='Total gov votes', val=f'{TOTAL_GOV:,}', val_color='var(--text)',
    sub=f'was {EN_TOTAL_GOV:,} election night',
    delta=f'+{canvass_added_m:.2f}M canvass votes added'.replace('.00M','M'), delta_color='var(--text-dim)')

html = update_card(html, 'card-hilton-pct',
    label='Hilton pct', val=f'{H_P}%', val_color='#e03030',
    sub=f'was {EN_H_PCT}% election night',
    delta=f'{h_pct_sign} as D VBM dilutes', delta_color='#2563eb')

html = update_card(html, 'card-becerra-pct',
    label='Becerra pct', val=f'{B_P}%', val_color='#2563eb',
    sub=f'was {EN_B_PCT}% election night',
    delta=f'{b_pct_sign} rising each batch', delta_color='#2563eb')

# Pct counted = ballots counted / (ballots counted + outstanding)
# Numerator from SOS snapshots (current); denominator stable even with stale county data
if sw_ballots and sw_out:
    pct_counted = round(sw_ballots / (sw_ballots + sw_out) * 100, 1)
    pct_counted_str = f'{pct_counted}% of returned ballots counted'
    unproc_cure_str = f'{sw_cure:,} left to cure'
    unproc_color = 'var(--gold)'
else:
    pct_counted_str = f'{SNAP_COUNT} snapshots logged'
    unproc_cure_str = 'county data unavailable'
    unproc_color = 'var(--text-dim)'

html = update_card(html, 'card-snapshots',
    label='Unprocessed Ballots',
    val=f'{sw_out:,}' if sw_out else 'N/A',
    val_color=unproc_color,
    sub=unproc_cure_str,
    delta=pct_counted_str,
    delta_color='var(--text-dim)')

# ── Battle bar ────────────────────────────────────────────────────────────────
html = set_id_content(html, 'battle-r-label', f'Republican {R_PCT}%')
html = set_id_content(html, 'battle-d-label', f'Democrat {D_PCT}%')
html = set_width_style(html, 'battle-r-fill', R_PCT)
html = set_width_style(html, 'battle-d-fill', D_PCT)
html = set_id_content(html, 'battle-r-votes', f'{R_VOTES:,} votes · R candidates')
html = set_id_content(html, 'battle-d-votes', f'{D_VOTES:,} votes · D candidates')
en_dr_k = round(EN_DR_GAP/1000)
dr_added_k2 = round((DR_GAP - EN_DR_GAP)/1000)

def fmt_votes(n):
    """Format vote count: use M for >= 1000k, otherwise k."""
    k = round(n / 1000)
    if k >= 1000:
        return f'{n/1_000_000:.2f}M'.rstrip('0').rstrip('.')+'M' if False else f'{round(n/1_000_000, 2)}M'
    return f'{k}k'

en_dr_fmt    = fmt_votes(EN_DR_GAP)
cur_dr_fmt   = fmt_votes(DR_GAP)
added_dr_fmt = fmt_votes(DR_GAP - EN_DR_GAP)
html = set_id_content(html, 'battle-note',
    f'D-R gap grew from +{en_dr_fmt} election night to +{cur_dr_fmt} at {CID} — +{added_dr_fmt} D added during canvass. D-heavy late VBM from LA, Alameda, Riverside, and Santa Clara driving the shift.')

# ── Snapshot table ────────────────────────────────────────────────────────────
pattern = r'(<tbody id="snap-tbody">)(.*?)(</tbody>)'
html = re.sub(pattern, rf'\g<1>\n{tbody_html}        \3', html, count=1, flags=re.DOTALL)

# ── Chart data arrays ─────────────────────────────────────────────────────────
# Replace the JS variable declarations
def replace_js_var(html, varname, new_val_str):
    pattern = rf'(const {re.escape(varname)}\s*=\s*)(\[.*?\])(;)'
    result = re.sub(pattern, rf'\g<1>{new_val_str}\3', html, count=1, flags=re.DOTALL)
    if result == html:
        print(f"  WARNING: JS var '{varname}' not updated")
    return result

html = replace_js_var(html, 'ALL_LABS',    js_str_arr(ALL_LABS))
html = replace_js_var(html, 'hiltonAll',   js_arr(hiltonAll))
html = replace_js_var(html, 'becerraAll',  js_arr(becerraAll))
html = replace_js_var(html, 'steyerAll',   js_arr(steyerAll))
html = replace_js_var(html, 'CV_LABS',     js_str_arr(CV_GAP_LABS))
html = replace_js_var(html, 'cvGap',       js_arr(cvGap))
html = replace_js_var(html, 'BATCH_LABS',  js_str_arr(ALL_BATCH_LABS))

# Batch share chart datasets
def replace_chart_data(html, label_str, new_data_str):
    pattern = rf"(label:'{re.escape(label_str)}'[^}}]*data:)(\[.*?\])"
    result = re.sub(pattern, rf'\g<1>{new_data_str}', html, count=1, flags=re.DOTALL)
    if result == html:
        print(f"  WARNING: chart dataset '{label_str}' not updated")
    return result

html = replace_chart_data(html, 'Hilton (R)',   js_arr(ALL_BATCH_H))
html = replace_chart_data(html, 'Becerra (D)',  js_arr(ALL_BATCH_B))
html = replace_chart_data(html, 'Steyer (D)',   js_arr(ALL_BATCH_S))
html = replace_chart_data(html, 'R 2:1 baseline', js_arr(BATCH_BASELINE))

# ── Counties tab ──────────────────────────────────────────────────────────────
if counties:
    # Top 10 bar rows
    pattern = r'(class="sl" style="margin-bottom:12px;">Top 10 counties.*?</div>\n)(.*?)(        <div style="font-family:var\(--mono\).*?Source:.*?</div>)'
    html = re.sub(pattern, rf'\g<1>{top10_html}        \g<3>', html, count=1, flags=re.DOTALL)

    # Top 10 source line — full replacement using marker search
    src_marker = 'class="counties-source"'
    src_idx = html.find(src_marker)
    if src_idx != -1:
        src_start = html.index('>', src_idx) + 1
        src_end   = html.index('</div>', src_start)
        html = html[:src_start] + top10_src + html[src_end:]
    else:
        print("  WARNING: counties source line (class='counties-source') not found in HTML")

    # BAR table rows
    pattern = r'(<tbody>)(.*?)(</tbody>)'
    # Ensure BAR table is in its own card with correct heading
    if 'Unprocessed ballots by county — BAR report' not in html:
        html = html.replace(
            '</div>\n        <div class="bar-table-wrap">',
            '</div>\n      </div>\n      <div class="card">\n        <div class="sl" style="margin-bottom:12px;">Unprocessed ballots by county — BAR report</div>\n        <div class="bar-table-wrap">',
            1)
        print("  Fixed: BAR table split into separate card")

    # Replace the BAR table tbody — find it by its proximity to bar-table-wrap
    bar_wrap_idx = html.find('class="bar-table-wrap"')
    if bar_wrap_idx == -1:
        bar_wrap_idx = html.find('bar-table-wrap')
    if bar_wrap_idx != -1:
        tbody_start = html.find('<tbody>', bar_wrap_idx)
        tbody_end   = html.find('</tbody>', tbody_start) + len('</tbody>')
        if tbody_start != -1 and tbody_end > tbody_start:
            html = html[:tbody_start] + f'<tbody>\n{bar_rows_html}          </tbody>' + html[tbody_end:]
        else:
            print("  WARNING: BAR tbody not found after bar-table-wrap")
    else:
        # Fallback: replace second tbody
        tbodies = list(re.finditer(r'<tbody>(.*?)</tbody>', html, re.DOTALL))
        if len(tbodies) >= 2:
            second = tbodies[1]
            html = html[:second.start()] + f'<tbody>\n{bar_rows_html}          </tbody>' + html[second.end():]
        else:
            print("  WARNING: Could not locate BAR table tbody")

    # BAR note
    pattern = r'(<div style="margin-top:12px;padding:10px 14px;background:var\(--surface2\);border-radius:4px;border-left:2px solid var\(--blue\);font-family:var\(--mono\);font-size:11px;color:var\(--text-mid\);line-height:1\.6;">)(.*?)(</div>)'
    html = re.sub(pattern, rf'\g<1>{bar_note_html}\3', html, count=1, flags=re.DOTALL)

    # BAR report header stats
    if sw_out:
        pattern = r'(Statewide: <strong[^>]*>)[^<]*(</strong>)'
        html = re.sub(pattern, rf'\g<1>{sw_out:,} ballots still outstanding\2', html, count=1)

# ── Party aggregate label + legend + footer ──────────────────────────────────
# "Party aggregate vote — CX latest" label
html = re.sub(
    r'(Party aggregate vote — )C\d+( latest)',
    rf'\g<1>{CID}\2', html, count=1)

# Batch shares label inside canvas element
html = re.sub(
    r'(Batch shares S2–)C\d+(\.</canvas>)',
    rf'\g<1>{CID}\2', html, count=1)

# "Blue row = latest (CX)" legend
html = re.sub(
    r'(Blue row = latest \()C\d+(\))',
    rf'\g<1>{CID}\2', html, count=1)

# "S1–S7 = election night drops · C1–CX = canvass updates" legend
html = re.sub(
    r'(C1–)C\d+( = canvass updates)',
    rf'\g<1>{CID}\2', html, count=1)

# Comment above JS arrays "S1-S7 + C1-CX"
html = re.sub(
    r'(// ALL \d+ SNAPSHOTS: S1-S7 \+ C1-)C\d+',
    rf'\g<1>{CID}', html, count=1)

# Footer "Dashboard last updated ..."
snap_date = CDT.replace(' · ', ' ')  # e.g. "Jun 7 5:08p"
_, _, full_dt = parse_reporting_time(snapshots[-1]['reporting_time'])
html = re.sub(
    r'Dashboard last updated [A-Za-z]+ \d+, \d+[^<]*\.',
    f'Dashboard last updated {full_dt.rstrip(".")}.', html, count=1)

# ── Also update the inline JS lead block (the existing one at bottom) ─────────
old_js_block = r'(\(function\(\)\{.*?const hilton\s*=\s*)\d+(.*?const becerra\s*=\s*)\d+'
html = re.sub(old_js_block, rf'\g<1>{H}\g<2>{B}', html, count=1, flags=re.DOTALL)

# ── Write output ──────────────────────────────────────────────────────────────
with open(OUT_PATH, 'w') as f:
    f.write(html)

print(f"\n{'='*60}")
print(f"Dashboard updated → {OUT_PATH}")
print(f"  Latest:      {CID} · {CDT}")
print(f"  {LEADER} leads:  +{ABS_GAP:,}")
print(f"  Hilton:      {H:,} ({H_P}%)")
print(f"  Becerra:     {B:,} ({B_P}%)")
print(f"  Steyer:      {S:,} ({S_P}%)")
print(f"  Total gov:   {TOTAL_GOV:,}")
if sw_ballots:
    print(f"  Total cast:  {sw_ballots:,} ({sw_turnout}% turnout)")
    if sw_out:
        print(f"  Outstanding: {sw_out:,} · {sw_cure:,} to cure")
    else:
        print(f"  Outstanding: pending BAR update")
print(f"  Snapshots:   {SNAP_COUNT} ({en_count} EN + {cv_count} canvass)")
print(f"  Charts:      {len(ALL_LABS)} labels · {len(ALL_BATCH_LABS)} batch points")
print(f"{'='*60}")
print(f"\nTo publish: git add index.html && git commit -m '{CID} update' && git push")
