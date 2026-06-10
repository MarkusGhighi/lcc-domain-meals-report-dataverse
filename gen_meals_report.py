#!/usr/bin/env python3
"""Generate the LCC interactive meals report from Dataverse tables.
   Run with --serve to start a local refresh server (default: generate + serve).
   Run with --no-serve to just generate the HTML file.
"""

import html
import json
import os
import shutil
import sys
import base64 as _b64
import subprocess
import threading
import webbrowser
from pathlib import Path
from datetime import datetime
from collections import Counter, defaultdict
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

BASE_DIR = Path(__file__).resolve().parent
OUT_PATH = str(BASE_DIR / "Meals_Report_py.html")
DATAVERSE_EXPORT_SCRIPT = BASE_DIR / "dataverse_export_report_data.ps1"
OFFLINE_IMPORT_DIR = BASE_DIR.parent / "Systemfiles" / "dataverse_import"
SERVE_PORT = 8050

COLORS = ["#333F68","#ED1B25","#00679D","#3385B0","#6EA5C5","#8B1520","#5576A8","#A0C5D9","#7BAFCC","#1A2A50"]


# ── Read Dataverse ────────────────────────────────────────────────────────────

PARTICIPANT_FIELD_MAP = {
    "new_no": "NO.",
    "new_firstnameandsurname": "FirstName_and_Surname",
    "new_idnumber": "IDNumber",
    "new_dateofbirth": "Date of Birth",
    "new_ageformula": "Age",
    "new_age": "Age",
    "new_agegroupformula": "Age Group",
    "new_agegroup": "Age Group",
    "new_gender": "Gender",
    "new_race": "Race",
    "new_disabled": "Disabled",
    "new_specifydisability": "Specify Disability",
    "new_dateofadmission": "Date of Admission",
    "new_powerappsid": "__PowerAppsId__",
    "new_legacypowerappsid": "__PowerAppsId__",
}

SCAN_FIELD_MAP = {
    "new_firstnameandsurname": "FirstName_and_Surname",
    "new_idnumber": "IDNumber",
    "new_scantimestamp": "ScanTimestamp",
    "new_ageformula": "Age",
    "new_age": "Age",
    "new_gender": "Gender",
    "new_race": "Race",
    "new_disabled": "Disabled",
    "new_newqrcode": "NewQRCode",
    "new_powerappsid": "__PowerAppsId__",
    "new_legacypowerappsid": "__PowerAppsId__",
}


def normalize_dataverse_rows(rows, field_map):
    normalized = []
    for row in rows:
        item = {}
        for source, target in field_map.items():
            if source in row and row[source] is not None and item.get(target, "") == "":
                item[target] = str(row[source])
        normalized.append(item)
    return normalized


def read_dataverse():
    """Read Meal Participant and Meal Scan Log rows through Dataverse Web API."""
    if not DATAVERSE_EXPORT_SCRIPT.exists():
        raise FileNotFoundError(f"Dataverse export script not found: {DATAVERSE_EXPORT_SCRIPT}")

    cmd = [
        shutil.which("pwsh") or shutil.which("powershell") or "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(DATAVERSE_EXPORT_SCRIPT),
    ]
    result = subprocess.run(cmd, cwd=BASE_DIR, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        details = (result.stderr or result.stdout).strip()
        if "--offline-fallback" in sys.argv:
            return read_dataverse_import_files()
        raise RuntimeError(f"Dataverse export failed: {details}")

    payload = json.loads(result.stdout)
    master = normalize_dataverse_rows(payload.get("meal_participants", []), PARTICIPANT_FIELD_MAP)
    scans = normalize_dataverse_rows(payload.get("meal_scan_logs", []), SCAN_FIELD_MAP)
    return master, scans


def read_dataverse_import_files():
    """Offline verification fallback from the Dataverse import export files."""
    participants_path = OFFLINE_IMPORT_DIR / "meal_participants.json"
    scan_logs_path = OFFLINE_IMPORT_DIR / "meal_scan_logs.json"
    participants = json.loads(participants_path.read_text(encoding="utf-8"))
    scan_logs = json.loads(scan_logs_path.read_text(encoding="utf-8"))
    return (
        normalize_dataverse_rows(participants, PARTICIPANT_FIELD_MAP),
        normalize_dataverse_rows(scan_logs, SCAN_FIELD_MAP),
    )


master_rows, scan_rows = read_dataverse()


# ── Quick stats for initial KPI cards ────────────────────────────────────────

total_members  = len(master_rows)
total_scans    = len(scan_rows)
disabled_count = sum(1 for r in master_rows if r.get("Disabled", "").strip().lower() == "yes")
female_count   = sum(1 for r in master_rows if r.get("Gender", "").strip().upper() == "F")
male_count     = sum(1 for r in master_rows if r.get("Gender", "").strip().upper() == "M")

age_group_counts = sorted(
    Counter(r.get("Age Group", "") or "(blank)" for r in master_rows).items(),
    key=lambda x: -x[1]
)

# Shared IDs: IDNumbers that appear with multiple different names
_id_names = defaultdict(set)
for r in master_rows:
    _idnum = r.get("IDNumber", "").strip()
    _name  = r.get("FirstName_and_Surname", "").strip()
    if _idnum and _name:
        _id_names[_idnum].add(_name)
shared_id_count = sum(1 for names in _id_names.values() if len(names) > 1)

now = datetime.now().strftime("%d %B %Y, %H:%M")

master_json = json.dumps(master_rows, ensure_ascii=False)
scan_json   = json.dumps(scan_rows,   ensure_ascii=False)
colors_json = json.dumps(COLORS)

py_version = sys.version.split()[0]

_LOGO_PATH = Path(os.environ.get("LCC_REPORT_LOGO", BASE_DIR / "assets" / "Lesedi Logo.png"))
try:
    with open(_LOGO_PATH, "rb") as _f:
        _logo_b64 = "data:image/png;base64," + _b64.b64encode(_f.read()).decode()
except Exception:
    _logo_b64 = ""

# ── HTML ──────────────────────────────────────────────────────────────────────

page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>LCC Domain Meals Report</title>
<style>
  :root {{
    --bg:#f5f6f9; --card:#fff; --border:#d8dbe8;
    --accent:#00679D; --text:#1a1c2e; --muted:#6b6f84; --hbg:#333F68;
  }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Segoe UI',Arial,sans-serif;background:var(--bg);color:var(--text);font-size:14px}}
  header{{background:var(--hbg);color:#faf9f5;padding:24px 32px;display:flex;align-items:center;justify-content:space-between}}
  header h1{{font-size:1.5rem;font-weight:600}}
  header .sub{{font-size:.8rem;color:#b0aea5;margin-top:4px}}
  .content{{padding:28px 32px;max-width:1400px;margin:0 auto}}

  /* KPI cards as buttons */
  .kpi-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:16px;margin-bottom:28px}}
  .kpi{{background:var(--card);border:2px solid var(--border);border-radius:8px;padding:20px;
        cursor:pointer;transition:all .18s ease;user-select:none}}
  .kpi:hover{{border-color:var(--accent);transform:translateY(-2px);box-shadow:0 4px 12px rgba(0,0,0,.08)}}
  .kpi.active{{border-color:var(--accent);background:#edf4fa;box-shadow:0 0 0 3px rgba(0,103,157,.18)}}
  .kpi .val{{font-size:2.2rem;font-weight:700;color:var(--accent);line-height:1}}
  .kpi .lbl{{font-size:.78rem;color:var(--muted);margin-top:6px;text-transform:uppercase;letter-spacing:.5px}}
  .kpi .filter-badge{{display:none;font-size:.7rem;margin-top:6px;color:var(--accent);font-weight:600}}
  .kpi.active .filter-badge{{display:block}}

  .sec-title{{font-size:1rem;font-weight:600;margin-bottom:14px;padding-bottom:6px;
              border-bottom:2px solid var(--accent);display:inline-block}}
  .chart-subtitle{{font-size:.78rem;color:var(--muted);margin-bottom:12px}}
  .card{{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:20px;margin-bottom:24px}}
  .two-col{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}
  .three-col{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:20px}}
  @media(max-width:900px){{.two-col,.three-col{{grid-template-columns:1fr}}}}

  .barchart{{display:flex;flex-direction:column;gap:8px;margin-top:8px}}
  .bar-row{{display:flex;align-items:center;gap:8px}}
  .bar-label{{width:150px;font-size:12px;text-align:right;color:var(--muted);flex-shrink:0;
              overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
  .bar-wrap{{flex:1;background:#e8eaf2;border-radius:4px;height:22px;overflow:hidden}}
  .bar-fill{{height:100%;border-radius:4px;transition:width .35s ease}}
  .bar-val{{font-size:11px;color:var(--muted);width:90px;flex-shrink:0}}

  .legend{{display:flex;flex-wrap:wrap;gap:10px;margin-top:12px}}
  .legend-item{{display:flex;align-items:center;gap:6px;font-size:12px}}
  .dot{{width:12px;height:12px;border-radius:50%;display:inline-block;flex-shrink:0}}

  .section{{margin-bottom:32px}}
  .table-wrap{{overflow-x:auto;max-height:480px;overflow-y:auto}}
  table{{border-collapse:collapse;width:100%;font-size:12px}}
  th{{background:var(--hbg);color:#faf9f5;padding:8px 10px;text-align:left;font-weight:500;
      position:sticky;top:0;z-index:1}}
  td{{padding:7px 10px;border-bottom:1px solid var(--border)}}
  tr:hover td{{background:#f5f4f0}}
  .mono{{font-family:monospace;font-size:11px}}
  .badge{{display:inline-block;padding:2px 7px;border-radius:10px;font-size:11px;font-weight:600}}
  .badge-ok{{background:#e8f0f8;color:#00679D}}
  .badge-warn{{background:#fceaea;color:#ED1B25}}

  .tab-nav{{display:flex;gap:4px;margin-bottom:16px;flex-wrap:wrap}}
  .tab-btn{{padding:7px 16px;border:1px solid var(--border);border-radius:6px;background:white;
            cursor:pointer;font-size:13px;font-weight:500;transition:all .15s}}
  .tab-btn.active{{background:var(--hbg);color:white;border-color:var(--hbg)}}
  .tab-content{{display:none}}
  .tab-content.active{{display:block}}

  .reset-btn{{float:right;font-size:12px;color:#ED1B25;cursor:pointer;border:none;
              background:none;text-decoration:underline;padding:2px 0}}
  .date-filter-bar{{display:flex;flex-wrap:wrap;gap:12px;align-items:center;
                    margin-bottom:24px;padding:14px 16px;background:var(--card);
                    border:1px solid var(--border);border-radius:8px}}
  .date-filter-bar .df-lbl{{font-size:.75rem;text-transform:uppercase;letter-spacing:.5px;
                             color:var(--muted);font-weight:600}}
  .date-filter-bar .df-group{{display:flex;align-items:center;gap:8px}}
  .date-filter-bar label{{font-size:12px;color:var(--muted)}}
  .date-filter-bar input[type=date]{{
    padding:5px 10px;border:1px solid var(--border);border-radius:6px;
    font-size:12px;font-family:inherit;background:white;cursor:pointer;
    color:var(--text);outline:none;transition:border-color .15s}}
  .date-filter-bar input[type=date]:focus{{border-color:var(--accent)}}
  .date-filter-bar input[type=date].active{{border-color:var(--accent);background:#f0f8f6}}
  .df-clear{{padding:5px 12px;border:1px solid var(--border);border-radius:6px;
             background:white;cursor:pointer;font-size:12px;color:var(--muted);transition:all .15s}}
  .df-clear:hover{{border-color:#ED1B25;color:#ED1B25}}
  .df-info{{font-size:11px;color:var(--accent);font-weight:600;margin-left:4px}}
  footer{{text-align:center;color:var(--muted);font-size:11px;padding:24px;
          border-top:1px solid var(--border);margin-top:20px}}
  @keyframes spin {{ from{{transform:rotate(0deg)}} to{{transform:rotate(360deg)}} }}
  .spinning svg {{ animation: spin .8s linear infinite; }}
  .ts-badge{{display:inline-block;background:#f0f4fc;color:#2B5DAD;border:1px solid #c8d4ee;
             border-radius:4px;padding:2px 7px;font-size:11px;margin:2px 3px 2px 0;white-space:nowrap;font-family:monospace}}
  .multi-hidden{{display:none}}
  .summary-stat{{display:flex;align-items:center;justify-content:space-between;
                 padding:10px 14px;background:#f8f7f2;border-radius:6px;border:1px solid var(--border)}}
  .summary-stat .s-val{{font-size:1.6rem;font-weight:700;color:#C41230}}
  .summary-stat .s-lbl{{font-size:.75rem;color:var(--muted);text-transform:uppercase;letter-spacing:.4px}}
  .export-btn{{
    display:inline-flex;align-items:center;gap:7px;
    padding:8px 16px;border-radius:6px;border:none;
    background:#ED1B25;color:#fff;font-size:13px;font-weight:600;
    cursor:pointer;transition:background .15s;text-decoration:none;
    white-space:nowrap}}
  .export-btn:hover{{background:#c41520}}
  .export-btn:active{{background:#8B1520}}
  .export-btn svg{{flex-shrink:0}}
</style>
<script src="https://cdn.jsdelivr.net/npm/xlsx-js-style@1.2.0/dist/xlsx.bundle.js"></script>
</head>
<body>
<header>
  <div style="display:flex;align-items:center;gap:18px">
    {f'<div style="background:#fff;border-radius:8px;padding:6px 12px;display:flex;align-items:center;box-shadow:0 2px 8px rgba(0,0,0,.25)"><img src="{_logo_b64}" alt="Lesedi Community Centre" style="height:56px;width:auto;display:block"></div>' if _logo_b64 else ''}
    <div>
      <h1>LCC Domain Meals Report</h1>
      <div class="sub">Generated: {now}</div>
    </div>
  </div>
  <div style="display:flex;flex-direction:column;align-items:flex-end;gap:10px">
    <div style="font-size:13px;color:#b0aea5">Dataverse &mdash; LCC Domain</div>
    <div style="display:flex;gap:8px">
      <button class="export-btn" style="background:#3a4e8c" onclick="refreshPage()" id="refreshBtn" title="Dataverse-Daten neu laden">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/>
          <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
        </svg>
        Refresh
      </button>
      <button class="export-btn" onclick="exportToExcel()">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
        Export Excel
      </button>
    </div>
  </div>
</header>

<div class="content">

  <!-- KPI cards (act as filter buttons) -->
  <div class="kpi-grid" id="kpiGrid">
    <div class="kpi active" data-filter="all" onclick="applyFilter(this)">
      <div class="val" id="kpi-total">{total_members}</div>
      <div class="lbl">Total Members</div>
      <div class="filter-badge">&#x2713; All members</div>
    </div>
    <div class="kpi" data-filter="scans" onclick="applyFilter(this)">
      <div class="val">{total_scans}</div>
      <div class="lbl">Meal Scans</div>
      <div class="filter-badge">&#x2713; Showing scan data</div>
    </div>
    <div class="kpi" data-filter="disabled" onclick="applyFilter(this)">
      <div class="val" id="kpi-disabled">{disabled_count}</div>
      <div class="lbl">With Disability</div>
      <div class="filter-badge">&#x2713; Disabled only</div>
    </div>
    <div class="kpi" data-filter="female" onclick="applyFilter(this)">
      <div class="val" id="kpi-female">{female_count}</div>
      <div class="lbl">Female Members</div>
      <div class="filter-badge">&#x2713; Female only</div>
    </div>
    <div class="kpi" data-filter="male" onclick="applyFilter(this)">
      <div class="val" id="kpi-male">{male_count}</div>
      <div class="lbl">Male Members</div>
      <div class="filter-badge">&#x2713; Male only</div>
    </div>
    <div class="kpi" data-filter="sharedid" onclick="applyFilter(this)">
      <div class="val" id="kpi-sharedid">{shared_id_count}</div>
      <div class="lbl">Shared IDs</div>
      <div class="filter-badge">&#x2713; IDs with multiple names</div>
    </div>
  </div>

  <!-- Date range filter -->
  <div class="date-filter-bar" id="dateFilterBar">
    <span class="df-lbl">&#128197; Date Filter:</span>
    <div class="df-group">
      <label for="dateFrom">From</label>
      <input type="date" id="dateFrom" onchange="applyDateFilter()">
    </div>
    <div class="df-group">
      <label for="dateTo">To</label>
      <input type="date" id="dateTo" onchange="applyDateFilter()">
    </div>
    <button class="df-clear" onclick="clearDateFilter()">&#x2715; Clear</button>
    <span class="df-info" id="dfInfo"></span>
  </div>

  <!-- Demographics charts -->
  <div class="section" id="masterSection">
    <div class="sec-title" id="chartTitle">Demographics &mdash; Master List</div>
    <div class="three-col">
      <div class="card">
        <strong>Gender</strong>
        <div class="chart-subtitle" id="genderSubtitle"></div>
        <div id="chartGender"></div>
      </div>
      <div class="card">
        <strong>Race</strong>
        <div class="chart-subtitle" id="raceSubtitle"></div>
        <div id="chartRace"></div>
      </div>
      <div class="card">
        <strong>Age Group</strong>
        <div class="chart-subtitle" id="ageSubtitle"></div>
        <div id="chartAge"></div>
      </div>
    </div>
  </div>

  <!-- Scan section (hidden anchor for show/hide logic) -->
  <div id="scanSection" style="display:none"></div>

  <!-- Multiple Meals section -->
  <div class="section" id="multiMealsSection" style="display:none">
    <div class="sec-title">Multiple Meals Received</div>
    <div class="two-col" style="margin-bottom:20px">
      <div class="card">
        <strong>Distribution &mdash; Meals per Person</strong>
        <div class="chart-subtitle" id="multiMealsSubtitle"></div>
        <div id="chartMultiMeals"></div>
      </div>
      <div class="card" style="display:flex;flex-direction:column">
        <strong>Summary</strong>
        <div id="multiMealsSummary" style="margin-top:14px;display:flex;flex-direction:column;gap:10px"></div>
      </div>
    </div>
    <div class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
        <strong>Members with more than one Meal <span id="multiMealsCount" style="font-size:.8rem;color:var(--muted);font-weight:400"></span></strong>
        <input id="multiMealsSearch" type="text" placeholder="Search name / ID…"
          style="padding:5px 10px;border:1px solid var(--border);border-radius:6px;font-size:12px;outline:none;width:200px"
          oninput="filterMultiTable(this.value)">
      </div>
      <div class="table-wrap" id="multiMealsTableWrap"></div>
    </div>
  </div>

  <!-- Full data tables -->
  <div class="section">
    <div class="sec-title">Full Data</div>
    <div class="tab-nav">
      <button class="tab-btn active" onclick="showTab('master',this)">Master List (<span id="masterCount">{total_members}</span> members)</button>
      <button class="tab-btn" onclick="showTab('scanlog',this)">Scan Meal Log ({total_scans} entries)</button>
    </div>
    <div id="master" class="tab-content active card">
      <div id="masterTableWrap"></div>
    </div>
    <div id="scanlog" class="tab-content card">
      <div id="scanlogTableWrap"></div>
    </div>
  </div>

</div>

<footer>Dataverse: Meal Participant + Meal Scan Log &mdash; Report generated {now} &mdash; Python {py_version}</footer>

<script>
let MASTER = {master_json};
let SCANS  = {scan_json};
const COLORS = {colors_json};

// ── Join: enrich SCANS with Master data via IDNumber ─────────────────────────
let MASTER_BY_ID = {{}};
let SCANS_JOINED = [];
let SHARED_IDS = {{}};

function rebuildJoin() {{
  MASTER_BY_ID = {{}};
  MASTER.forEach(r => {{
    const id = (r['IDNumber'] || '').trim();
    if (id) MASTER_BY_ID[id] = r;
  }});
  SCANS_JOINED = SCANS.map(s => {{
    const id = (s['IDNumber'] || '').trim();
    const m  = MASTER_BY_ID[id] || {{}};
    return Object.assign({{}}, s, {{
      'Age Group':       m['Age Group']       || '(not in master)',
      'Date of Admission': m['Date of Admission'] || '',
      '_matched': !!m['IDNumber']
    }});
  }});

  // Build shared IDs map: IDNumber → Set of unique names
  SHARED_IDS = {{}};
  MASTER.forEach(r => {{
    const id = (r['IDNumber']||'').trim();
    const nm = (r['FirstName_and_Surname']||'').trim();
    if (id && nm) {{
      if (!SHARED_IDS[id]) SHARED_IDS[id] = new Set();
      SHARED_IDS[id].add(nm);
    }}
  }});
}}
rebuildJoin();

let currentFilter = 'all';
let currentDataset = 'master'; // 'master' or 'scans'
let _exportRows = [];        // active filtered dataset rows (scans or master)
let _exportMasterRows = [];  // filtered master rows (for scan mode: only matched members)

// ── Timestamp formatting ──────────────────────────────────────────────────────

// Strip seconds from timestamps: "2026-03-10 10:22:45" → "2026-03-10 10:22"
function trimTimestamp(val) {{
  if (!val) return val;
  // Match "YYYY-MM-DD HH:MM:SS" or "YYYY-MM-DDTHH:MM:SS" and drop :SS(.xxx)
  return val.replace(/([0-9]{{2}}:[0-9]{{2}}):[0-9]{{2}}([.].*)?$/, '$1');
}}

// ── Date filter ───────────────────────────────────────────────────────────────

// Parse various date formats → 'YYYY-MM-DD' or null
function parseDate(val) {{
  if (!val) return null;
  val = val.trim();
  // ISO / timestamp: "2026-03-10 10:22..." or "2026-03-10T..."
  if (/^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}/.test(val)) return val.slice(0, 10);
  // DD/MM/YYYY or D/M/YYYY
  const dm = val.match(/^([0-9]{{1,2}})[/]([0-9]{{1,2}})[/]([0-9]{{4}})/);
  if (dm) return `${{dm[3]}}-${{dm[2].padStart(2,'0')}}-${{dm[1].padStart(2,'0')}}`;
  return null;
}}

function getDateField() {{
  return currentDataset === 'scans' ? 'ScanTimestamp' : 'Date of Admission';
}}

function filterByDateField(rows, field) {{
  const from = document.getElementById('dateFrom').value;
  const to   = document.getElementById('dateTo').value;
  if (!from && !to) return rows;
  return rows.filter(r => {{
    const d = parseDate(r[field] || '');
    if (!d) return false;
    if (from && d < from) return false;
    if (to   && d > to)   return false;
    return true;
  }});
}}

function filterByDate(rows) {{
  return filterByDateField(rows, getDateField());
}}

function applyDateFilter() {{
  const from = document.getElementById('dateFrom').value;
  const to   = document.getElementById('dateTo').value;
  document.getElementById('dateFrom').classList.toggle('active', !!from);
  document.getElementById('dateTo').classList.toggle('active', !!to);
  const activeKpi = document.querySelector('.kpi.active');
  if (activeKpi) applyFilter(activeKpi);
}}

function clearDateFilter() {{
  document.getElementById('dateFrom').value = '';
  document.getElementById('dateTo').value   = '';
  document.getElementById('dateFrom').classList.remove('active');
  document.getElementById('dateTo').classList.remove('active');
  document.getElementById('dfInfo').textContent = '';
  const activeKpi = document.querySelector('.kpi.active');
  if (activeKpi) applyFilter(activeKpi);
}}

// Set min/max bounds on date inputs from actual data
function initDateBounds() {{
  const scanDates   = SCANS_JOINED.map(r => parseDate(r['ScanTimestamp'])).filter(Boolean).sort();
  const masterDates = MASTER.map(r => parseDate(r['Date of Admission'])).filter(Boolean).sort();
  // Store for dynamic update
  window._scanDateRange   = {{ min: scanDates[0],   max: scanDates[scanDates.length-1] }};
  window._masterDateRange = {{ min: masterDates[0], max: masterDates[masterDates.length-1] }};
  updateDateBounds();
}}

function updateDateBounds() {{
  const r = currentDataset === 'scans' ? window._scanDateRange : window._masterDateRange;
  if (!r) return;
  document.getElementById('dateFrom').min = r.min || '';
  document.getElementById('dateFrom').max = r.max || '';
  document.getElementById('dateTo').min   = r.min || '';
  document.getElementById('dateTo').max   = r.max || '';
  // Update placeholder via title tooltip
  document.getElementById('dateFrom').title = r.min ? `Earliest: ${{r.min}}` : '';
  document.getElementById('dateTo').title   = r.max ? `Latest: ${{r.max}}`   : '';
}}

// ── Filter logic ──────────────────────────────────────────────────────────────

function getBaseData() {{
  return currentDataset === 'scans' ? SCANS_JOINED : MASTER;
}}

function applyGenderFilter(rows, filter) {{
  if (filter === 'female') return rows.filter(r => (r['Gender']||'').trim().toUpperCase() === 'F');
  if (filter === 'male')   return rows.filter(r => (r['Gender']||'').trim().toUpperCase() === 'M');
  return rows;
}}

function applyFilter(card) {{
  const filter = card.dataset.filter;

  // Switch dataset when clicking Meal Scans / Total Members
  if (filter === 'scans')    currentDataset = 'scans';
  if (filter === 'all')      currentDataset = 'master';
  if (filter === 'disabled') currentDataset = 'master';
  if (filter === 'sharedid') currentDataset = 'master';
  // female/male keep current dataset

  currentFilter = filter;
  document.querySelectorAll('.kpi').forEach(k => k.classList.remove('active'));
  card.classList.add('active');

  const isScan = currentDataset === 'scans';
  const base   = getBaseData();

  // Update date input bounds when dataset switches
  updateDateBounds();

  // Apply gender/disabled sub-filter
  let rows = base;
  if (filter === 'female') rows = applyGenderFilter(base, 'female');
  else if (filter === 'male') rows = applyGenderFilter(base, 'male');
  else if (filter === 'disabled') rows = MASTER.filter(r => (r['Disabled']||'').trim().toLowerCase() === 'yes');
  else if (filter === 'sharedid') rows = MASTER.filter(r => {{
    const id = (r['IDNumber']||'').trim();
    return SHARED_IDS[id] && SHARED_IDS[id].size > 1;
  }});

  // Apply date filter
  const beforeDate = rows.length;
  rows = filterByDate(rows);
  const dateFrom = document.getElementById('dateFrom').value;
  const dateTo   = document.getElementById('dateTo').value;
  const dfInfo   = document.getElementById('dfInfo');
  if (dateFrom || dateTo) {{
    dfInfo.textContent = `${{rows.length}} of ${{beforeDate}} in range`;
  }} else {{
    dfInfo.textContent = '';
  }}

  // Update KPI card counts dynamically based on active date filter + dataset
  const scanFiltered   = filterByDateField(SCANS_JOINED, 'ScanTimestamp');
  const masterFiltered = filterByDateField(MASTER, 'Date of Admission');

  // When Meal Scans is active: Total Members = unique matched master members in filtered scans
  const totalVal = isScan
    ? new Set(scanFiltered.filter(r => r['_matched']).map(r => (r['IDNumber']||'').trim())).size
    : masterFiltered.length;

  document.querySelector('.kpi[data-filter="all"] .val').textContent     = totalVal;
  document.querySelector('.kpi[data-filter="scans"] .val').textContent   = scanFiltered.length;
  document.querySelector('.kpi[data-filter="female"] .val').textContent  = isScan
    ? scanFiltered.filter(r => (r['Gender']||'').trim().toUpperCase()==='F').length
    : masterFiltered.filter(r => (r['Gender']||'').trim().toUpperCase()==='F').length;
  document.querySelector('.kpi[data-filter="male"] .val').textContent    = isScan
    ? scanFiltered.filter(r => (r['Gender']||'').trim().toUpperCase()==='M').length
    : masterFiltered.filter(r => (r['Gender']||'').trim().toUpperCase()==='M').length;
  document.querySelector('.kpi[data-filter="disabled"] .val').textContent = masterFiltered.filter(r => (r['Disabled']||'').trim().toLowerCase()==='yes').length;
  document.querySelector('.kpi[data-filter="sharedid"] .val').textContent = Object.values(SHARED_IDS).filter(s => s.size > 1).length;

  // Update Total Members label text to reflect context
  document.querySelector('.kpi[data-filter="all"] .lbl').textContent = isScan ? 'Unique Members Scanned' : 'Total Members';

  // Label for chart title
  const datasetLabel = isScan ? 'Scan Log' : 'Master List';
  const filterLabel  = {{
    all: datasetLabel, scans: 'Scan Log',
    female: 'Female \u2014 ' + datasetLabel,
    male:   'Male \u2014 '   + datasetLabel,
    disabled: 'Disabled \u2014 Master List',
    sharedid: 'Shared IDs \u2014 Master List'
  }}[filter] || datasetLabel;

  // Show/hide scan section
  document.getElementById('scanSection').style.display = isScan ? '' : '';

  // Render charts — Age Group chart only makes sense for master data
  document.getElementById('chartTitle').textContent = 'Demographics \u2014 ' + filterLabel;
  ['genderSubtitle','raceSubtitle','ageSubtitle'].forEach(id =>
    document.getElementById(id).textContent = rows.length + ' records'
  );
  renderBarChart('chartGender', countBy(rows, 'Gender'));
  renderBarChart('chartRace',   countBy(rows, 'Race'));
  // Age Group: always available — scans are enriched via IDNumber join
  document.getElementById('chartAge').parentElement.style.display = '';
  renderBarChart('chartAge', countBy(rows, 'Age Group'));

  document.getElementById('scanSection').style.display = isScan ? '' : 'none';

  // Full data: when in scan mode, show only master members whose IDNumber appears in filtered scans
  const scannedIds = new Set(rows.map(r => (r['IDNumber']||'').trim()).filter(Boolean));
  let masterRows = isScan ? MASTER.filter(r => scannedIds.has((r['IDNumber']||'').trim())) : rows;
  if (filter === 'sharedid') masterRows = masterRows.slice().sort((a,b) => (a['IDNumber']||'').localeCompare(b['IDNumber']||''));
  renderMasterTable(masterRows);
  document.getElementById('masterCount').textContent = masterRows.length;
  document.getElementById('scanlogTableWrap').innerHTML = buildScanTable(isScan ? rows : SCANS);

  // Multiple meals section
  renderMultiMeals(isScan ? rows : []);

  // Store for Excel export
  _exportRows       = rows;
  _exportMasterRows = masterRows;
}}

// ── Chart rendering ───────────────────────────────────────────────────────────

function countBy(rows, key) {{
  const counts = {{}};
  rows.forEach(r => {{
    const v = (r[key] || '(blank)').trim() || '(blank)';
    counts[v] = (counts[v] || 0) + 1;
  }});
  return Object.entries(counts).sort((a,b) => b[1]-a[1]);
}}

function renderBarChart(elId, dist) {{
  const total = dist.reduce((s,[,n]) => s+n, 0);
  const bars = dist.map(([label, count], i) => {{
    const pct = total ? (count/total*100).toFixed(1) : 0;
    const color = COLORS[i % COLORS.length];
    return `<div class="bar-row">
      <div class="bar-label" title="${{label}}">${{esc(label)}}</div>
      <div class="bar-wrap"><div class="bar-fill" style="width:${{pct}}%;background:${{color}}"></div></div>
      <div class="bar-val">${{count}} (${{pct}}%)</div>
    </div>`;
  }}).join('');

  const legend = dist.map(([label, count], i) => {{
    const pct = total ? (count/total*100).toFixed(1) : 0;
    const color = COLORS[i % COLORS.length];
    return `<div class="legend-item"><span class="dot" style="background:${{color}}"></span>${{esc(label)}} <strong>${{count}}</strong> (${{pct}}%)</div>`;
  }}).join('');

  document.getElementById(elId).innerHTML =
    `<div class="barchart">${{bars}}</div><div class="legend">${{legend}}</div>`;
}}

function renderScanCharts() {{
  document.getElementById('chartTitle').textContent = 'Demographics \u2014 Scan Log';
  document.getElementById('scanlogTableWrap').innerHTML = buildScanTable(SCANS_JOINED);
}}

// ── Multiple Meals ────────────────────────────────────────────────────────────

let _multiData = []; // [{{name, id, count, timestamps, ageGroup, gender}}]

function renderMultiMeals(scanRows) {{
  const section = document.getElementById('multiMealsSection');
  const isScan  = currentDataset === 'scans';
  section.style.display = isScan ? '' : 'none';
  if (!isScan) return;

  // Group by IDNumber (fallback to name)
  const groups = {{}};
  scanRows.forEach(r => {{
    const key  = ((r['IDNumber']||'').trim()) || (r['FirstName_and_Surname']||'?').trim();
    if (!groups[key]) groups[key] = {{
      name: (r['FirstName_and_Surname']||'').trim(),
      id:   (r['IDNumber']||'').trim(),
      ageGroup: r['Age Group'] || '',
      gender:   (r['Gender']||'').trim(),
      timestamps: []
    }};
    const ts = (r['ScanTimestamp']||'').trim();
    if (ts) groups[key].timestamps.push(ts);
    else    groups[key].timestamps.push('(no timestamp)');
  }});

  // Filter to those with more than 1 meal
  _multiData = Object.values(groups)
    .filter(g => g.timestamps.length > 1)
    .sort((a,b) => b.timestamps.length - a.timestamps.length);

  // Summary stats
  const total    = _multiData.length;
  const maxMeals = total ? _multiData[0].timestamps.length : 0;
  const avgMeals = total ? (_multiData.reduce((s,g)=>s+g.timestamps.length,0)/total).toFixed(1) : '0';
  document.getElementById('multiMealsCount').textContent = `— ${{total}} member${{total!==1?'s':''}}`;
  document.getElementById('multiMealsSummary').innerHTML = `
    <div class="summary-stat"><div><div class="s-val">${{total}}</div><div class="s-lbl">Members w/ &gt;1 Meal</div></div></div>
    <div class="summary-stat"><div><div class="s-val">${{maxMeals}}</div><div class="s-lbl">Most Meals by one Person</div></div></div>
    <div class="summary-stat"><div><div class="s-val">${{avgMeals}}</div><div class="s-lbl">Avg Meals (multi-meal members)</div></div></div>`;

  // Bar chart: count per meal-frequency bucket (2, 3, 4, 5+)
  const buckets = {{}};
  _multiData.forEach(g => {{
    const b = g.timestamps.length >= 5 ? '5+' : String(g.timestamps.length);
    buckets[b] = (buckets[b]||0) + 1;
  }});
  const bucketOrder = ['2','3','4','5+'];
  const dist = [];
  bucketOrder.forEach(b => {{ if (buckets[b]) dist.push([b+' meals', buckets[b]]); }});
  document.getElementById('multiMealsSubtitle').textContent =
    total ? `${{total}} member${{total!==1?'s':''}} received more than one meal` : 'No duplicate meals in current filter';
  renderBarChart('chartMultiMeals', dist);

  // Table
  renderMultiTable(_multiData);
}}

function renderMultiTable(data) {{
  if (!data.length) {{
    document.getElementById('multiMealsTableWrap').innerHTML =
      '<p style="color:var(--muted);font-size:13px;padding:12px 0">No members with more than one meal in the current filter.</p>';
    return;
  }}
  const rows = data.map(g => {{
    const tsBadges = g.timestamps.map(t => `<span class="ts-badge">${{esc(trimTimestamp(t))}}</span>`).join('');
    return `<tr>
      <td>${{esc(g.name)}}</td>
      <td class="mono">${{esc(g.id)}}</td>
      <td style="text-align:center;font-weight:700;color:#C41230">${{g.timestamps.length}}</td>
      <td>${{esc(g.ageGroup)}}</td>
      <td>${{esc(g.gender)}}</td>
      <td style="min-width:260px">${{tsBadges}}</td>
    </tr>`;
  }}).join('');
  document.getElementById('multiMealsTableWrap').innerHTML = `
    <table>
      <thead><tr>
        <th>Name</th><th>ID Number</th><th style="text-align:center">Meals</th>
        <th>Age Group</th><th>Gender</th><th>Scan Timestamps</th>
      </tr></thead>
      <tbody>${{rows}}</tbody>
    </table>`;
}}

function filterMultiTable(q) {{
  const lq = q.trim().toLowerCase();
  if (!lq) {{ renderMultiTable(_multiData); return; }}
  const filtered = _multiData.filter(g =>
    g.name.toLowerCase().includes(lq) || g.id.toLowerCase().includes(lq));
  renderMultiTable(filtered);
}}

// ── Table rendering ───────────────────────────────────────────────────────────

function buildMasterTable(rows) {{
  const cols = ['NO.','FirstName_and_Surname','IDNumber','Age','Age Group','Gender','Race','Disabled','Date of Admission'];
  const head = cols.map(c => `<th>${{esc(c)}}</th>`).join('');
  const body = rows.map(r => {{
    const dis = (r['Disabled']||'').trim().toLowerCase() === 'yes'
      ? `<span class="badge badge-warn">Yes</span>`
      : `<span class="badge badge-ok">No</span>`;
    const cells = cols.map(c => {{
      if (c === 'Disabled') return `<td>${{dis}}</td>`;
      if (c === 'IDNumber') return `<td class="mono">${{esc(r[c]||'')}}</td>`;
      if (c === 'Date of Admission') return `<td>${{esc(trimTimestamp(r[c]||''))}}</td>`;
      return `<td>${{esc(r[c]||'')}}</td>`;
    }}).join('');
    return `<tr>${{cells}}</tr>`;
  }}).join('');
  return `<div class="table-wrap"><table><thead><tr>${{head}}</tr></thead><tbody>${{body}}</tbody></table></div>`;
}}

function buildScanTable(rows) {{
  const cols = ['FirstName_and_Surname','IDNumber','ScanTimestamp','Age Group','Gender','Race','Disabled','Date of Admission'];
  const head = cols.map(c => `<th>${{esc(c)}}</th>`).join('');
  const body = rows.map(r => {{
    const dis = (r['Disabled']||'').trim().toLowerCase() === 'yes'
      ? `<span class="badge badge-warn">Yes</span>`
      : `<span class="badge badge-ok">No</span>`;
    const matched = r['_matched'];
    const cells = cols.map(c => {{
      if (c === 'Disabled') return `<td>${{dis}}</td>`;
      if (c === 'IDNumber') return `<td class="mono">${{esc(r[c]||'')}}</td>`;
      if (c === 'ScanTimestamp') return `<td>${{esc(trimTimestamp(r[c]||''))}}</td>`;
      if (c === 'Date of Admission') return `<td>${{esc(trimTimestamp(r[c]||''))}}</td>`;
      if (c === 'Age Group') {{
        const ag = r[c] || '';
        const style = ag === '(not in master)' ? 'color:#b0aea5;font-style:italic' : '';
        return `<td style="${{style}}">${{esc(ag)}}</td>`;
      }}
      return `<td>${{esc(r[c]||'')}}</td>`;
    }}).join('');
    return `<tr>${{cells}}</tr>`;
  }}).join('');
  return `<div class="table-wrap"><table><thead><tr>${{head}}</tr></thead><tbody>${{body}}</tbody></table></div>`;
}}

function renderMasterTable(rows) {{
  document.getElementById('masterTableWrap').innerHTML = buildMasterTable(rows);
}}

// ── Excel export ──────────────────────────────────────────────────────────────

async function refreshPage() {{
  const btn = document.getElementById('refreshBtn');
  btn.disabled = true;
  btn.classList.add('spinning');

  try {{
    const resp = await fetch('http://localhost:{SERVE_PORT}/api/refresh');
    if (!resp.ok) throw new Error('Server returned ' + resp.status);
    const data = await resp.json();

    // Update global data
    MASTER = data.master;
    SCANS  = data.scans;

    // Rebuild join, reset filters, re-render everything
    rebuildJoin();
    document.getElementById('dateFrom').value = '';
    document.getElementById('dateTo').value   = '';
    currentFilter  = 'all';
    currentDataset = 'master';
    document.querySelectorAll('.kpi').forEach(k => k.classList.remove('active'));
    document.querySelector('.kpi[data-filter="all"]').classList.add('active');
    initDateBounds();
    applyFilter(document.querySelector('.kpi[data-filter="all"]'));

    // Show refreshed timestamp
    const sub = document.querySelector('header .sub');
    if (sub) sub.textContent = 'Refreshed: ' + new Date().toLocaleString()
      + '  \\u2014  Master: ' + data.master.length + ' / Scans: ' + data.scans.length;

  }} catch(err) {{
    alert('Refresh fehlgeschlagen.\\n\\nStelle sicher, dass das Python-Skript noch l\\u00e4uft:\\n'
        + 'python gen_meals_report.py\\n\\nFehler: ' + err.message);
  }}

  btn.classList.remove('spinning');
  btn.disabled = false;
}}

function exportToExcel() {{
  const isScan = currentDataset === 'scans';
  const wb = XLSX.utils.book_new();

  // ── Style helpers ──────────────────────────────────────────────────────────
  const HEADER_FILL = {{ fgColor: {{ rgb: "1C2B6E" }} }};  // dark navy
  const HEADER_FONT = {{ bold: true, color: {{ rgb: "FFFFFF" }}, sz: 11 }};
  const HEADER_ALIGN = {{ horizontal: "center", vertical: "center" }};
  const HEADER_BORDER = {{
    top:    {{ style: "thin", color: {{ rgb: "FFFFFF" }} }},
    bottom: {{ style: "thin", color: {{ rgb: "FFFFFF" }} }},
    left:   {{ style: "thin", color: {{ rgb: "FFFFFF" }} }},
    right:  {{ style: "thin", color: {{ rgb: "FFFFFF" }} }}
  }};
  const CELL_BORDER = {{
    top:    {{ style: "thin", color: {{ rgb: "DDDDDD" }} }},
    bottom: {{ style: "thin", color: {{ rgb: "DDDDDD" }} }},
    left:   {{ style: "thin", color: {{ rgb: "DDDDDD" }} }},
    right:  {{ style: "thin", color: {{ rgb: "DDDDDD" }} }}
  }};
  const EVEN_FILL = {{ fgColor: {{ rgb: "F0F4FA" }} }};
  const RED_FONT  = {{ bold: true, color: {{ rgb: "C41230" }}, sz: 11 }};

  function styleSheet(ws, colCount, rowCount, opts) {{
    if (!ws['!cols']) ws['!cols'] = [];
    // Auto-width columns
    for (let c = 0; c < colCount; c++) {{
      ws['!cols'][c] = {{ wch: 18 }};
    }}
    // Style header row
    for (let c = 0; c < colCount; c++) {{
      const addr = XLSX.utils.encode_cell({{ r: 0, c: c }});
      if (!ws[addr]) continue;
      ws[addr].s = {{
        fill: HEADER_FILL,
        font: HEADER_FONT,
        alignment: HEADER_ALIGN,
        border: HEADER_BORDER
      }};
    }}
    // Style data rows
    for (let r = 1; r <= rowCount; r++) {{
      for (let c = 0; c < colCount; c++) {{
        const addr = XLSX.utils.encode_cell({{ r: r, c: c }});
        if (!ws[addr]) ws[addr] = {{ v: '', t: 's' }};
        const isEven = r % 2 === 0;
        const st = {{ border: CELL_BORDER, alignment: {{ vertical: "center" }} }};
        if (isEven) st.fill = EVEN_FILL;
        // Highlight meal count column in red if specified
        if (opts && opts.redCol === c && r >= 1) {{
          st.font = RED_FONT;
          st.alignment = {{ horizontal: "center", vertical: "center" }};
        }}
        ws[addr].s = st;
      }}
    }}
    // Freeze header row
    ws['!freeze'] = {{ xSplit: 0, ySplit: 1 }};
    // Auto-filter
    ws['!autofilter'] = {{ ref: XLSX.utils.encode_range({{ s: {{ r:0, c:0 }}, e: {{ r: rowCount, c: colCount-1 }} }}) }};
  }}

  // ── Sheet 1 — active filtered data ────────────────────────────────────────
  const masterCols = ['NO.','FirstName_and_Surname','IDNumber','Age','Age Group','Gender','Race','Disabled','Date of Admission'];
  const scanCols   = ['FirstName_and_Surname','IDNumber','ScanTimestamp','Age Group','Gender','Race','Disabled','Date of Admission'];
  const mainCols = isScan ? scanCols : masterCols;
  const mainAoa  = [mainCols, ..._exportRows.map(r => mainCols.map(c => (c === 'ScanTimestamp' || c === 'Date of Admission') ? trimTimestamp(r[c]||'') : (r[c] || '')))];
  const wsMain   = XLSX.utils.aoa_to_sheet(mainAoa);
  styleSheet(wsMain, mainCols.length, _exportRows.length, null);
  XLSX.utils.book_append_sheet(wb, wsMain, isScan ? 'Meal Scan Log' : 'Master List');

  // ── Sheet 2 — Multiple Meals (always included if data exists) ──────────────
  // Build multi-meal data from current scans (even in master mode, use all scans)
  const scanSource = isScan ? _exportRows : SCANS_JOINED;
  const mGroups = {{}};
  scanSource.forEach(r => {{
    const key = ((r['IDNumber']||'').trim()) || (r['FirstName_and_Surname']||'?').trim();
    if (!mGroups[key]) mGroups[key] = {{
      name: (r['FirstName_and_Surname']||'').trim(),
      id:   (r['IDNumber']||'').trim(),
      ageGroup: r['Age Group'] || '',
      gender:   (r['Gender']||'').trim(),
      timestamps: []
    }};
    const ts = (r['ScanTimestamp']||'').trim();
    mGroups[key].timestamps.push(ts || '(no timestamp)');
  }});
  const allMembers = Object.values(mGroups)
    .sort((a,b) => b.timestamps.length - a.timestamps.length);

  if (allMembers.length) {{
    const multiHeader = ['Name','ID Number','Meal Count','Age','Age Group','Gender','Race','Disabled','Date of Admission','Scan Timestamps'];
    const multiRows   = allMembers.map(g => {{
      const m = MASTER_BY_ID[g.id] || {{}};
      return [
        g.name, g.id, g.timestamps.length,
        m['Age'] || '', g.ageGroup, g.gender,
        m['Race'] || '', m['Disabled'] || '', trimTimestamp(m['Date of Admission'] || ''),
        g.timestamps.map(trimTimestamp).join('  |  ')
      ];
    }});
    const wsMulti = XLSX.utils.aoa_to_sheet([multiHeader, ...multiRows]);
    const totalRows = allMembers.length;
    styleSheet(wsMulti, multiHeader.length, totalRows, {{ redCol: 2 }});
    // Wider columns for name and timestamps
    wsMulti['!cols'][0] = {{ wch: 28 }};  // Name
    wsMulti['!cols'][1] = {{ wch: 18 }};  // ID
    wsMulti['!cols'][2] = {{ wch: 12 }};  // Meal Count
    wsMulti['!cols'][3] = {{ wch: 8 }};   // Age
    wsMulti['!cols'][4] = {{ wch: 14 }};  // Age Group
    wsMulti['!cols'][5] = {{ wch: 10 }};  // Gender
    wsMulti['!cols'][6] = {{ wch: 12 }};  // Race
    wsMulti['!cols'][7] = {{ wch: 10 }};  // Disabled
    wsMulti['!cols'][8] = {{ wch: 18 }};  // Date of Admission
    wsMulti['!cols'][9] = {{ wch: 55 }};  // Scan Timestamps
    XLSX.utils.book_append_sheet(wb, wsMulti, 'Meals Overview');
  }}

  // ── Filename ──────────────────────────────────────────────────────────────
  const dateStr  = new Date().toISOString().slice(0,10);
  const fromVal  = document.getElementById('dateFrom').value;
  const toVal    = document.getElementById('dateTo').value;
  const datePart = fromVal || toVal ? `_${{fromVal||''}}-${{toVal||''}}` : '';
  const filterName = {{ all:'master', scans:'scans', female:'female', male:'male', disabled:'disabled' }}[currentFilter] || 'export';
  const filename = `Meals_Report_${{filterName}}${{datePart}}_${{dateStr}}.xlsx`;

  XLSX.writeFile(wb, filename);
}}

// ── Tab switching ─────────────────────────────────────────────────────────────

function showTab(id, btn) {{
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
}}

// ── Utility ───────────────────────────────────────────────────────────────────

function esc(s) {{
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}

// ── Init ──────────────────────────────────────────────────────────────────────

(function init() {{
  initDateBounds();
  applyFilter(document.querySelector('.kpi[data-filter="all"]'));

  // Render scan log table (always)
  document.getElementById('scanlogTableWrap').innerHTML = buildScanTable(SCANS_JOINED);

  // Hide refresh button when not on localhost (e.g. GitHub Pages)
  if (window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1') {{
    document.getElementById('refreshBtn').style.display = 'none';
  }}
}})();
</script>
</body>
</html>
"""

Path(OUT_PATH).write_text(page, encoding="utf-8")
print(f"Report saved: {OUT_PATH}")


# ── Local refresh server ─────────────────────────────────────────────────────

class RefreshHandler(BaseHTTPRequestHandler):
    """Tiny HTTP handler: serves the HTML + provides /api/refresh endpoint."""

    def do_GET(self):
        if self.path == "/api/refresh":
            self._handle_refresh()
        elif self.path in ("/", "/index.html"):
            self._serve_html()
        else:
            self.send_error(404)

    def do_OPTIONS(self):
        """Handle CORS preflight for fetch from file:// origin."""
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")

    def _handle_refresh(self):
        try:
            master, scans = read_dataverse()
            payload = json.dumps({"master": master, "scans": scans}, ensure_ascii=False)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self._cors_headers()
            self.end_headers()
            self.wfile.write(payload.encode("utf-8"))
            print(f"  [~] Refreshed - Master: {len(master)} rows, Scans: {len(scans)} rows")
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self._cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def _serve_html(self):
        data = Path(OUT_PATH).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        # Suppress default request logging (noisy)
        pass


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

def run_server():
    server = ThreadingHTTPServer(("127.0.0.1", SERVE_PORT), RefreshHandler)
    print(f"\n  [*] Refresh-Server laeuft auf http://localhost:{SERVE_PORT}")
    print(f"  [>] Report: http://localhost:{SERVE_PORT}/")
    print(f"  [x] Beenden: Ctrl+C\n")
    webbrowser.open(f"http://localhost:{SERVE_PORT}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer gestoppt.")
        server.server_close()


if "--no-serve" not in sys.argv:
    run_server()
else:
    print("  (Server übersprungen — nur HTML generiert)")
