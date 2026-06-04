import re
from pathlib import Path
from datetime import datetime

DASHBOARD_FILE = "ca_governor_2026_dashboard.html"

# =============================================================
#  EDIT THIS SECTION WITH LATEST COUNTY DATA
#  Last updated: June 3, 2026, 5:48 p.m. · Statewide: 5,338,094 ballots
#  ballots    = total ballots cast (integer)
#  turnout    = turnout % (float, e.g. 22.4)
#  color      = bar color: "blue" | "red" | "purple" | "mixed"
#  star_note  = optional footnote string, or None
# =============================================================

TOP_10 = [
    {"name": "Los Angeles",    "ballots": 1395987, "turnout": 23.7, "color": "blue",   "star_note": None},
    {"name": "Orange",         "ballots": 544338,  "turnout": 28.5, "color": "red",    "star_note": None},
    {"name": "San Diego",      "ballots": 503793,  "turnout": 24.9, "color": "purple", "star_note": None},
    {"name": "Riverside",      "ballots": 287863,  "turnout": 20.0, "color": "blue",   "star_note": None},
    {"name": "San Bernardino", "ballots": 224573,  "turnout": 18.2, "color": "red",    "star_note": None},
    {"name": "Santa Clara",    "ballots": 208299,  "turnout": 19.4, "color": "blue",   "star_note": None},
    {"name": "Sacramento",     "ballots": 183951,  "turnout": 20.0, "color": "blue",   "star_note": None},
    {"name": "Contra Costa",   "ballots": 174683,  "turnout": 23.9, "color": "blue",   "star_note": None},
    {"name": "Alameda",        "ballots": 167794,  "turnout": 17.3, "color": "blue",   "star_note": None},
    {"name": "Kern",           "ballots": 152582,  "turnout": 33.0, "color": "red",
     "star_note": "★ Kern's 33% turnout — highest among large counties — drove S5 R batch bounce. Final 83k votes came in after midnight."},
]

# Canvass outstanding tracker
# outstanding = string estimate e.g. "~450–800k out" or "COMPLETE"
# lean        = "d" | "mixed" | "r"
# lean_note   = short label

CANVASS_COUNTIES = [
    {"name": "Los Angeles",    "ballots_cast": 1395987, "outstanding": "~400–600k out", "lean": "d",     "lean_note": "Strong D · Latino VBM"},
    {"name": "Orange",         "ballots_cast": 544338,  "outstanding": "~100k out",     "lean": "mixed", "lean_note": "Mixed · competitive"},
    {"name": "Riverside",      "ballots_cast": 287863,  "outstanding": "~150k out",     "lean": "d",     "lean_note": "D-leaning VBM"},
    {"name": "San Bernardino", "ballots_cast": 224573,  "outstanding": "~150k out",     "lean": "mixed", "lean_note": "Mixed · some R"},
    {"name": "Santa Clara",    "ballots_cast": 208299,  "outstanding": "~120k out",     "lean": "d",     "lean_note": "Strong D · tech"},
    {"name": "Sacramento",     "ballots_cast": 183951,  "outstanding": "~80k out",      "lean": "d",     "lean_note": "D-leaning"},
    {"name": "Alameda",        "ballots_cast": 167794,  "outstanding": "~100k out",     "lean": "d",     "lean_note": "Strong D · Oakland"},
    {"name": "Placer",         "ballots_cast": 106094,  "outstanding": "~40k out",      "lean": "mixed", "lean_note": "R-leaning · suburbs"},
    {"name": "San Joaquin",    "ballots_cast": 74248,   "outstanding": "~50k out",      "lean": "mixed", "lean_note": "Mixed · Central Valley"},
    {"name": "Solano",         "ballots_cast": 71362,   "outstanding": "~40k out",      "lean": "d",     "lean_note": "D-leaning"},
]

CANVASS_FOOTER = (
    "Canvass deadline: July 10, 2026. Statewide total now 5,338,094 ballots (up from 5,195,070 election night). "
    "Late VBM + provisionals structurally favor Becerra. His final certified % will be higher than 25.4%."
)

VENTURA_NOTE = "★ Ventura: 138,898 ballots · 26.4% turnout · SF status · final report 1:51 a.m."

# =============================================================
#  SCRIPT — no need to edit below this line
# =============================================================

COLOR_MAP = {
    "blue":   "var(--blue)",
    "red":    "var(--red)",
    "purple": "var(--purple)",
    "mixed":  "rgba(255,255,255,0.2)",
}

LEAN_CLASS = {
    "d":     "lean-d",
    "mixed": "lean-mixed",
    "r":     "lean-r",
}

def fmt(n):
    return f"{n:,}"

def build_top10_html(counties):
    max_ballots = max(c["ballots"] for c in counties)
    rows = []
    for c in counties:
        bar_width = round(c["ballots"] / max_ballots * 100, 1)
        color     = COLOR_MAP.get(c["color"], "var(--blue)")
        name      = c["name"]
        val       = f'{fmt(c["ballots"])} · {c["turnout"]}%'
        rows.append(
            f'        <div class="bar-row">'
            f'<span class="bar-name" style="width:120px;">{name}</span>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{bar_width}%;background:{color};"></div></div>'
            f'<span class="bar-val">{val}</span></div>'
        )
    footnotes = []
    for c in counties:
        if c.get("star_note"):
            footnotes.append(
                f'        <div style="font-family:var(--mono);font-size:10px;color:var(--text-dim);margin-top:10px;">'
                f'{c["star_note"]}</div>'
            )
    footnotes.append(
        f'        <div style="font-family:var(--mono);font-size:10px;color:var(--text-dim);margin-top:4px;">'
        f'{VENTURA_NOTE}</div>'
    )
    return "\n".join(rows + footnotes)

def build_canvass_html(counties):
    rows = []
    for c in counties:
        lean_class = LEAN_CLASS.get(c["lean"], "lean-mixed")
        rows.append(
            f'        <div class="canvass-row">\n'
            f'          <span class="canvass-county">{c["name"]}</span>\n'
            f'          <span class="canvass-ballots">{fmt(c["ballots_cast"])} cast</span>\n'
            f'          <span class="canvass-outstanding">{c["outstanding"]}</span>\n'
            f'          <span class="canvass-lean {lean_class}">{c["lean_note"]}</span>\n'
            f'        </div>'
        )
    rows.append(
        f'        <div style="margin-top:14px;padding:10px 14px;background:var(--surface2);border-radius:4px;'
        f'border-left:2px solid var(--blue);font-family:var(--mono);font-size:11px;color:var(--text-mid);line-height:1.6;">\n'
        f'          {CANVASS_FOOTER}\n'
        f'        </div>'
    )
    return "\n".join(rows)

def update_top10(html, counties):
    new_block = build_top10_html(counties)
    pattern = (
        r'(<div class="section-label" style="margin-bottom:12px;">Top 10 Counties by Ballots Cast</div>\s*)'
        r'(.*?)'
        r'(</div>\s*\n\s*<div class="card">\s*\n\s*<div class="section-label"[^>]*>Canvass Outstanding)'
    )
    replacement = r'\g<1>' + new_block + '\n      \g<3>'
    result = re.sub(pattern, replacement, html, flags=re.DOTALL)
    if result == html:
        print("  [WARN] Top 10 block not updated — pattern not matched")
    return result

def update_canvass(html, counties):
    new_block = build_canvass_html(counties)
    pattern = (
        r'(<div class="section-label" style="margin-bottom:12px;">Canvass Outstanding[^<]*</div>\s*)'
        r'(.*?)'
        r'(</div>\s*\n\s*</div>\s*\n\s*</div>\s*\n\s*<!-- TAB: VERDICT -->)'
    )
    replacement = r'\g<1>' + new_block + '\n      \g<3>'
    result = re.sub(pattern, replacement, html, flags=re.DOTALL)
    if result == html:
        print("  [WARN] Canvass outstanding block not updated — pattern not matched")
    return result

def main():
    print("\n" + "="*56)
    print("  CA GOVERNOR 2026 — COUNTY DATA UPDATER")
    print("="*56)

    path = Path(DASHBOARD_FILE)
    if not path.exists():
        print(f"  [ERROR] {DASHBOARD_FILE} not found.")
        return

    html = path.read_text()

    print(f"  Updating top 10 counties...")
    html = update_top10(html, TOP_10)

    print(f"  Updating canvass outstanding tracker...")
    html = update_canvass(html, CANVASS_COUNTIES)

    path.write_text(html)

    now = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    print(f"  ✓ County data updated: {DASHBOARD_FILE}")
    print(f"  ✓ Run at: {now}")
    print("="*56 + "\n")

if __name__ == "__main__":
    main()
