from __future__ import annotations

from datetime import datetime
import json
import re
from pathlib import Path

from flask import Flask, Response, request, send_file

from .config import DEFAULT_NEAR_TERM_DAYS, OUTPUT_DIR, PROJECT_ROOT
from .dashboard_model import build_dashboard_model
from .data import load_records
from .exports import create_powerpoint
from .milestone_analysis import gaps_to_dataframe, load_milestone_gap_model
from .milestone_export import create_milestone_powerpoint


TEMPLATE_PATH = PROJECT_ROOT / "docs" / "defender_for_cloud_dashboard (2).html"


def create_app() -> Flask:
    app = Flask(__name__, static_folder=str(PROJECT_ROOT / "assets"))

    @app.get("/")
    def index() -> Response:
        return Response(render_shell_html("acr"), mimetype="text/html")

    @app.get("/acr")
    def acr() -> Response:
        return Response(render_shell_html("acr"), mimetype="text/html")

    @app.get("/milestones")
    def milestones() -> Response:
        return Response(render_shell_html("milestones"), mimetype="text/html")

    @app.get("/embed/acr")
    def acr_embed() -> Response:
        return Response(render_dashboard_html(embed=True), mimetype="text/html")

    @app.get("/embed/milestones")
    def milestones_embed() -> Response:
        near_term_days = _near_term_days()
        try:
            model = load_milestone_gap_model(near_term_days=near_term_days)
        except (FileNotFoundError, ValueError) as exc:
            return Response(render_milestone_error_html(str(exc), embed=True), mimetype="text/html")
        return Response(render_milestone_html(model, embed=True), mimetype="text/html")

    @app.get("/milestones/gaps.csv")
    def milestone_gaps_csv() -> Response:
        try:
            model = load_milestone_gap_model(near_term_days=_near_term_days())
        except (FileNotFoundError, ValueError) as exc:
            return _milestone_load_error_response(exc)
        table = gaps_to_dataframe(model)
        csv_text = "\ufeff" + table.to_csv(index=False)
        return Response(
            csv_text,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=defender-milestone-gaps.csv"},
        )

    @app.get("/milestones/export-ppt")
    def milestone_export_ppt():
        try:
            model = load_milestone_gap_model(near_term_days=_near_term_days())
        except (FileNotFoundError, ValueError) as exc:
            return _milestone_load_error_response(exc)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"defender-milestone-gaps-{stamp}.pptx"
        output_path = OUTPUT_DIR / filename
        create_milestone_powerpoint(model, output_path)
        return send_file(output_path, as_attachment=True, download_name=filename)

    @app.get("/export-ppt")
    def export_ppt():
        bundle = load_records(metric_name="$ ACR")
        model = build_dashboard_model(bundle.records)
        threshold = _export_threshold()
        output_path = OUTPUT_DIR / "defender-acr-opportunities-dashboard.pptx"
        create_powerpoint(bundle.records, model, bundle.source_path.name, output_path, threshold)
        return send_file(output_path, as_attachment=True)

    return app


def _milestone_load_error_response(exc: Exception) -> Response:
    return Response(str(exc), status=400, mimetype="text/plain")


def _export_threshold() -> float:
    raw_value = request.args.get("threshold", "8")
    try:
        threshold = float(raw_value)
    except ValueError:
        threshold = 8.0
    return min(20.0, max(0.0, threshold))


def _near_term_days() -> int:
    raw_value = request.args.get("near_term_days", str(DEFAULT_NEAR_TERM_DAYS))
    try:
        days = int(raw_value)
    except ValueError:
        days = DEFAULT_NEAR_TERM_DAYS
    return min(365, max(0, days))


def render_shell_html(active: str) -> str:
    frame_src = "/embed/milestones" if active == "milestones" else "/embed/acr"
    if active == "milestones" and request.query_string:
        frame_src = f"{frame_src}?{request.query_string.decode('utf-8', errors='ignore')}"
    active_title = "Milestone gaps" if active == "milestones" else "ACR dashboard"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
{THEME_SCRIPT}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{active_title}</title>
<style>
{CLAWPILOT_THEME_CSS}
{APP_MENU_CSS}
{SHELL_CSS}
</style>
</head>
<body class="app-shell-page">
{shell_menu_html(active)}
<iframe id="dashboard-frame" name="dashboard-frame" src="{frame_src}" title="{active_title}"></iframe>
<script>
const dashboardFrame = document.getElementById('dashboard-frame');
const shellLinks = [...document.querySelectorAll('.app-menu a[data-dashboard]')];

function activateDashboard(link, pushHistory = true) {{
  shellLinks.forEach(item => item.classList.toggle('active', item === link));
  dashboardFrame.src = link.dataset.src;
  document.title = link.textContent.trim();
  if (pushHistory) history.pushState({{dashboard: link.dataset.dashboard}}, '', link.dataset.url);
}}

shellLinks.forEach(link => {{
  link.addEventListener('click', event => {{
    event.preventDefault();
    activateDashboard(link);
  }});
}});

window.addEventListener('popstate', () => {{
  const isMilestone = window.location.pathname.startsWith('/milestones');
  const target = shellLinks.find(link => link.dataset.dashboard === (isMilestone ? 'milestones' : 'acr'));
  if (target) activateDashboard(target, false);
}});
</script>
</body>
</html>"""


def render_dashboard_html(*, embed: bool = False) -> str:
    bundle = load_records(metric_name="$ ACR")
    model = build_dashboard_model(bundle.records)
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    template = template.replace(
        '<script src="https://cdn.sheetjs.com/xlsx-0.20.2/package/dist/xlsx.full.min.js"></script>',
        "",
    )
    template = template.replace(
        '<button class="import-btn" id="import-btn">📂 Import new Excel</button>',
        '<button class="import-btn" id="import-btn" disabled>Loaded from inputfolder</button>'
        '<a class="import-btn" href="/export-ppt" style="text-decoration:none;">Export PowerPoint</a>',
    )
    template = template.replace(
        '<div class="import-status" id="import-status">Showing data from initial export</div>',
        f'<div class="import-status success" id="import-status">Loaded {bundle.source_path.name}</div>',
    )
    template = template.replace(
        'Upload a fresh "ACR Details by … Month" export to refresh the entire dashboard.',
        "Replace the workbook in inputfolder and refresh this page to reload the dashboard.",
    )
    template = _monthly_acr_labels(template)
    template = _opportunity_map_labels(template)
    template = _split_opportunity_pages(template)
    template = _inject_opportunity_map(template)
    if not embed:
        template = _inject_app_menu(template, active="acr")
    data_json = json.dumps(model, ensure_ascii=False, allow_nan=False)
    return re.sub(
        r"let DATA = .*?;\s*\n\n// ============ Helpers ============",
        f"let DATA = {data_json};\n\n// ============ Helpers ============",
        template,
        count=1,
        flags=re.DOTALL,
    )


def render_milestone_error_html(message: str, *, embed: bool = False) -> str:
    menu_html = "" if embed else app_menu_html("milestones")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
{THEME_SCRIPT}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Defender milestone gaps</title>
<style>
{CLAWPILOT_THEME_CSS}
{MILESTONE_BASE_CSS}
</style>
</head>
<body class="milestone-page">
{menu_html}
<main class="shell">
  <section class="hero">
    <p class="eyebrow">Milestone gap analysis</p>
    <h1>Defender milestone attach gaps</h1>
    <p class="hero-copy">The milestone view could not load because the source files are unavailable or invalid.</p>
  </section>
  <section class="card">
    <h2>Load error</h2>
    <p class="error-text">{_html_escape(message)}</p>
  </section>
</main>
</body>
</html>"""


def render_milestone_html(model: dict, *, embed: bool = False) -> str:
    data_json = _safe_json_script(model)
    near_term_days = int(model.get("near_term_days", DEFAULT_NEAR_TERM_DAYS))
    menu_html = "" if embed else app_menu_html("milestones")
    milestone_page_path = "/embed/milestones" if embed else "/milestones"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
{THEME_SCRIPT}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Defender milestone gaps</title>
<style>
{CLAWPILOT_THEME_CSS}
{MILESTONE_BASE_CSS}
</style>
</head>
<body class="milestone-page">
{menu_html}
<main class="shell">
  <section class="hero">
    <div>
      <p class="eyebrow">Migration to Defender attach</p>
      <h1>Defender milestone gap overview</h1>
      <p class="hero-copy">Find accounts and opportunities where migration milestones exist but Defender for Cloud milestones are missing under the requested strict matching rules.</p>
    </div>
    <div class="source-card">
      <span>Sources</span>
      <strong id="source-summary"></strong>
    </div>
  </section>

  <nav class="dashboard-tabs" aria-label="Milestone dashboard sections">
    <a href="#overview-section" class="active">Overview</a>
    <a href="#gap-analysis-section">Gap Analysis</a>
    <a href="#detail-table-section">All Gaps Table</a>
    <a href="#methodology-section">Methodology</a>
  </nav>

  <section class="toolbar card">
    <label>Search
      <input id="search-input" type="search" placeholder="Account, opportunity, workload, owner">
    </label>
    <label>Gap type
      <select id="gap-filter">
        <option value="all">All gaps</option>
        <option value="Account-level gap">Account-level gaps</option>
        <option value="Opportunity-level gap">Opportunity-level gaps</option>
      </select>
    </label>
    <label>Priority
      <select id="priority-filter">
        <option value="all">All priorities</option>
        <option value="HIGH">HIGH</option>
        <option value="MEDIUM">MEDIUM</option>
        <option value="LOW">LOW</option>
      </select>
    </label>
    <label>Workload
      <select id="workload-filter"><option value="all">All workloads</option></select>
    </label>
    <label>Near-term days
      <input id="near-term-days" type="number" min="0" max="365" step="1" value="{near_term_days}">
    </label>
    <button id="apply-near-term" class="secondary-button" type="button">Apply</button>
    <a id="csv-link" class="secondary-button" href="/milestones/gaps.csv?near_term_days={near_term_days}">Download CSV</a>
    <a id="ppt-link" class="primary-button" href="/milestones/export-ppt?near_term_days={near_term_days}">Export PowerPoint</a>
    <button id="print-button" class="secondary-button" type="button">Print / PDF</button>
  </section>

  <section class="how-to-read">
    <strong>How to read this:</strong> Account-level gaps show customers with Migration milestones but no Defender milestones. Opportunity-level gaps show attached accounts where the same Migration Opportunity ID has no Defender milestone.
  </section>

  <section id="overview-section">
    <section id="summary-grid" class="summary-grid"></section>
  </section>

  <section id="gap-analysis-section" class="grid-two">
    <div class="card">
      <div class="section-heading">
        <h2>Priority distribution</h2>
        <p>High priority is driven by committed milestones or near-term estimated dates.</p>
      </div>
      <div id="priority-bars" class="bar-list"></div>
    </div>
    <div class="card">
      <div class="section-heading">
        <h2>Gap type distribution</h2>
        <p>Account-level gaps are accounts with no Defender milestones; opportunity-level gaps are strict same-Opportunity-ID misses.</p>
      </div>
      <div id="gap-bars" class="bar-list"></div>
    </div>
  </section>

  <section class="card">
    <div class="section-heading">
      <h2>Top 10 highest priority gaps</h2>
      <p>Sorted by priority, committed status, estimated date, then migration pipeline size.</p>
    </div>
    <div id="top-gaps" class="responsive-table"></div>
  </section>

  <section class="card">
    <div class="section-heading">
      <h2>Workload concentration</h2>
      <p>Largest workload categories among current gaps.</p>
    </div>
    <div id="workload-bars" class="bar-list compact"></div>
  </section>

  <section id="detail-table-section" class="card">
    <div class="section-heading">
      <h2>All milestone gaps</h2>
      <p>Click a row to drill into priority rationale, owners, and milestone names.</p>
    </div>
    <div id="result-count" class="result-count"></div>
    <div id="gap-table" class="responsive-table"></div>
  </section>

  <section id="details-panel" class="card details-panel" hidden></section>

  <section id="methodology-section" class="methodology card">
    <h2>Methodology</h2>
    <p><strong>Account-level gap:</strong> account has Migration milestones but no Defender for Cloud milestones.</p>
    <p><strong>Attached account:</strong> account appears in both workbooks.</p>
    <p><strong>Opportunity-level gap:</strong> for attached accounts, a Migration Opportunity ID has no Defender milestone with the same account and Opportunity ID.</p>
    <p><strong>Priority:</strong> HIGH = committed milestone or estimated date within the selected near-term window; MEDIUM = uncommitted with a recognized workload; LOW = unclear or edge-case workload.</p>
  </section>
</main>
<script id="milestone-data" type="application/json">{data_json}</script>
<script>
const DATA = JSON.parse(document.getElementById('milestone-data').textContent);
const priorityRank = {{HIGH: 0, MEDIUM: 1, LOW: 2}};
let selectedRowIndex = null;

const fmt = {{
  int: value => Number(value || 0).toLocaleString('en-US'),
  money: value => Number(value || 0).toLocaleString('en-US', {{style: 'currency', currency: 'USD', maximumFractionDigits: 0}}),
  date: value => value || '-',
}};

function escapeHtml(value) {{
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}}

function workloadParts(row) {{
  return String(row.workload || '').split(';').map(part => part.trim()).filter(Boolean);
}}

function populateFilters() {{
  const workloads = [...new Set(DATA.gaps.flatMap(workloadParts))].sort((a, b) => a.localeCompare(b));
  const select = document.getElementById('workload-filter');
  select.innerHTML = '<option value="all">All workloads</option>' + workloads.map(workload => `<option value="${{escapeHtml(workload)}}">${{escapeHtml(workload)}}</option>`).join('');
}}

function filteredRows() {{
  const search = document.getElementById('search-input').value.trim().toLowerCase();
  const gapType = document.getElementById('gap-filter').value;
  const priority = document.getElementById('priority-filter').value;
  const workload = document.getElementById('workload-filter').value;
  return DATA.gaps.filter(row => {{
    if (gapType !== 'all' && row.gap_type !== gapType) return false;
    if (priority !== 'all' && row.priority !== priority) return false;
    if (workload !== 'all' && !workloadParts(row).includes(workload)) return false;
    if (!search) return true;
    return [row.account, row.opportunity_id, row.workload, row.owner, row.owner_role, row.priority_reason]
      .some(value => String(value || '').toLowerCase().includes(search));
  }});
}}

function renderSummary() {{
  const summary = DATA.summary;
  const visible = filteredRows();
  const visibleAccounts = new Set(visible.map(row => row.account_key)).size;
  const visibleOpps = new Set(visible.map(row => `${{row.account_key}}|${{row.opportunity_id || ''}}`)).size;
  const cards = [
    ['Accounts with gaps', fmt.int(summary.total_accounts_with_gaps), `${{fmt.int(visibleAccounts)}} visible`],
    ['Opportunities with gaps', fmt.int(summary.total_opportunities_with_gaps), `${{fmt.int(visibleOpps)}} visible`],
    ['Account-level gaps', fmt.int(summary.account_level_gaps), `${{fmt.int(summary.account_level_gap_accounts)}} accounts`],
    ['Opportunity-level gaps', fmt.int(summary.opportunity_level_gaps), 'strict Opportunity ID'],
    ['Attached accounts', fmt.int(summary.attached_accounts), 'Migration + Defender'],
    ['High priority', fmt.int(DATA.priority_counts.HIGH), 'committed or near-term'],
  ];
  document.getElementById('summary-grid').innerHTML = cards.map(([label, value, note]) => `
    <article class="kpi-card card">
      <span>${{escapeHtml(label)}}</span>
      <strong>${{escapeHtml(value)}}</strong>
      <small>${{escapeHtml(note)}}</small>
    </article>
  `).join('');
}}

function renderBars(targetId, rows) {{
  const maxValue = Math.max(...rows.map(row => row.value), 1);
  document.getElementById(targetId).innerHTML = rows.map(row => `
    <div class="bar-row">
      <div class="bar-label"><strong>${{escapeHtml(row.label)}}</strong><span>${{fmt.int(row.value)}}</span></div>
      <div class="bar-track"><div class="bar-fill ${{row.className || ''}}" style="width:${{Math.max(2, row.value / maxValue * 100)}}%"></div></div>
    </div>
  `).join('');
}}

function renderCharts() {{
  renderBars('priority-bars', [
    {{label: 'HIGH', value: DATA.priority_counts.HIGH || 0, className: 'priority-high-bg'}},
    {{label: 'MEDIUM', value: DATA.priority_counts.MEDIUM || 0, className: 'priority-medium-bg'}},
    {{label: 'LOW', value: DATA.priority_counts.LOW || 0, className: 'priority-low-bg'}},
  ]);
  renderBars('gap-bars', [
    {{label: 'Account-level gap', value: DATA.gap_type_counts['Account-level gap'] || 0, className: 'priority-high-bg'}},
    {{label: 'Opportunity-level gap', value: DATA.gap_type_counts['Opportunity-level gap'] || 0, className: 'priority-medium-bg'}},
  ]);
  renderBars('workload-bars', DATA.workload_counts.map(row => ({{label: row.workload, value: row.count, className: 'accent-bg'}})));
}}

function priorityTag(priority) {{
  return `<span class="tag priority-${{String(priority).toLowerCase()}}">${{escapeHtml(priority)}}</span>`;
}}

function tableHtml(rows, compact = false) {{
  if (!rows.length) return '<div class="empty">No gaps match the current filters.</div>';
  const displayed = compact ? rows.slice(0, 10) : rows;
  return `
    <table>
      <thead>
        <tr>
          <th>Account</th>
          <th>Opportunity ID</th>
          <th>Gap type</th>
          <th>Workload</th>
          <th>Estimated date</th>
          <th>Priority</th>
          <th class="num">Migration pipeline</th>
          <th>Owner</th>
        </tr>
      </thead>
      <tbody>
        ${{displayed.map(row => `
          <tr class="clickable" data-row-index="${{DATA.gaps.indexOf(row)}}">
            <td><strong>${{escapeHtml(row.account)}}</strong></td>
            <td><code>${{escapeHtml(row.opportunity_id || '-')}}</code></td>
            <td>${{escapeHtml(row.gap_type)}}</td>
            <td>${{escapeHtml(row.workload)}}</td>
            <td>${{escapeHtml(fmt.date(row.estimated_date))}}</td>
            <td>${{priorityTag(row.priority)}}</td>
            <td class="num">${{escapeHtml(fmt.money(row.acr_pipeline))}}</td>
            <td>${{escapeHtml(row.owner || row.owner_role || '-')}}</td>
          </tr>
        `).join('')}}
      </tbody>
    </table>`;
}}

function attachRowHandlers() {{
  document.querySelectorAll('tr.clickable').forEach(row => {{
    row.addEventListener('click', () => showDetails(Number(row.getAttribute('data-row-index'))));
  }});
}}

function showDetails(index) {{
  selectedRowIndex = index;
  const row = DATA.gaps[index];
  if (!row) return;
  const panel = document.getElementById('details-panel');
  panel.hidden = false;
  panel.innerHTML = `
    <div class="section-heading">
      <h2>${{escapeHtml(row.account)}}</h2>
      <p>${{escapeHtml(row.gap_type)}} | Opportunity ${{escapeHtml(row.opportunity_id || '-')}}</p>
    </div>
    <div class="detail-grid">
      <div><span>Priority</span><strong>${{escapeHtml(row.priority)}}</strong><small>${{escapeHtml(row.priority_reason)}}</small></div>
      <div><span>Estimated date</span><strong>${{escapeHtml(fmt.date(row.estimated_date))}}</strong><small>${{escapeHtml(row.commitment || '-')}}</small></div>
      <div><span>Pipeline</span><strong>${{escapeHtml(fmt.money(row.acr_pipeline))}}</strong><small>${{escapeHtml(row.status || '-')}}</small></div>
      <div><span>Owner</span><strong>${{escapeHtml(row.owner || '-')}}</strong><small>${{escapeHtml(row.owner_role || '-')}}</small></div>
    </div>
    <h3>Migration milestones in this gap</h3>
    <ul class="milestone-list">${{(row.milestones || []).map(name => `<li>${{escapeHtml(name)}}</li>`).join('') || '<li>No milestone names available.</li>'}}</ul>
  `;
  panel.scrollIntoView({{behavior: 'smooth', block: 'nearest'}});
}}

function renderTables() {{
  const rows = filteredRows().sort((a, b) =>
    priorityRank[a.priority] - priorityRank[b.priority] ||
    Number(b.has_committed) - Number(a.has_committed) ||
    String(a.estimated_date || '9999-12-31').localeCompare(String(b.estimated_date || '9999-12-31')) ||
    (b.acr_pipeline || 0) - (a.acr_pipeline || 0)
  );
  document.getElementById('result-count').textContent = `${{fmt.int(rows.length)}} visible gap rows`;
  document.getElementById('top-gaps').innerHTML = tableHtml(DATA.top_gaps, true);
  document.getElementById('gap-table').innerHTML = tableHtml(rows);
  attachRowHandlers();
}}

function render() {{
  renderSummary();
  renderTables();
}}

function updateLinks() {{
  const days = document.getElementById('near-term-days').value || DATA.near_term_days;
  document.getElementById('csv-link').href = `/milestones/gaps.csv?near_term_days=${{encodeURIComponent(days)}}`;
  document.getElementById('ppt-link').href = `/milestones/export-ppt?near_term_days=${{encodeURIComponent(days)}}`;
}}

document.getElementById('source-summary').textContent = `${{DATA.sources.migration}} + ${{DATA.sources.defender}}`;
populateFilters();
renderCharts();
render();
['search-input', 'gap-filter', 'priority-filter', 'workload-filter'].forEach(id => {{
  document.getElementById(id).addEventListener('input', render);
  document.getElementById(id).addEventListener('change', render);
}});
document.getElementById('near-term-days').addEventListener('input', updateLinks);
document.getElementById('apply-near-term').addEventListener('click', () => {{
  const days = document.getElementById('near-term-days').value || DATA.near_term_days;
  window.location.href = `{milestone_page_path}?near_term_days=${{encodeURIComponent(days)}}`;
}});
document.getElementById('print-button').addEventListener('click', () => window.print());
</script>
</body>
</html>"""


def _monthly_acr_labels(template: str) -> str:
    replacements = {
        "Avg Daily ACR basis": "Monthly ACR basis",
        "High Opportunity</div><div class=\"val\" id=\"kpi-high\">–</div><div class=\"delta\">customers to prioritize": "High Opportunity</div><div class=\"val\" id=\"kpi-high\">–</div><div class=\"delta\">customers to prioritize",
        "&lt; $50/day total ACR": "&lt; $1,500/month total ACR",
        "Defender for Cloud — Daily ACR across all customers": "Defender for Cloud — Monthly ACR across all customers",
        "Sum of avg daily ACR by month": "Sum of monthly ACR by month",
        "Top 15 customers by Defender for Cloud daily ACR": "Top 15 customers by Defender for Cloud monthly ACR",
        "Product mix — daily ACR trend by service": "Product mix — monthly ACR trend by service",
        "Absolute daily ACR": "Absolute monthly ACR",
        "Bubble size = total daily ACR.": "Bubble size = total monthly ACR.",
        "DfC as % of total daily ACR for this customer": "DfC as % of total monthly ACR for this customer",
        "All workloads ranked by current daily ACR.": "All workloads ranked by current monthly ACR.",
        "top 10 by total daily ACR.": "top 10 by total monthly ACR.",
        "Sorted by total daily ACR": "Sorted by total monthly ACR",
        "Daily ACR — does DfC track with the rest of the footprint?": "Monthly ACR — does DfC track with the rest of the footprint?",
        "Total Daily ACR": "Total Monthly ACR",
        "DfC Daily ACR": "DfC Monthly ACR",
        "Total $/day": "Monthly Total ACR",
        "DfC $/day": "Monthly DfC ACR",
        "<div class=\"num\">$/day</div>": "<div class=\"num\">Monthly ACR</div>",
        "+ '/day'": "",
        "})/day": "})",
        "})}/day": "})}",
        "Customer ACR under $50/day — sales priority low": "Customer ACR under $1,500/month - sales priority low",
        "Total ACR under $50/day": "Total ACR under $1,500/month",
        "DfC base under $1/day": "DfC base under $30/month",
        "DfC base &lt; $1/day": "DfC base &lt; $30/month",
        "$ Average Daily ACR": "$ ACR",
        "Average Daily ACR": "Monthly ACR",
    }
    for old, new in replacements.items():
        template = template.replace(old, new)
    return template


THEME_SCRIPT = """<script>
  (() => {
    const param = new URLSearchParams(window.location.search).get("clawpilotTheme");
    const theme =
      param || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    document.documentElement.setAttribute("data-theme", theme);
  })();
</script>"""


CLAWPILOT_THEME_CSS = """:root {
  color-scheme: light;
  --cp-bg: #f7f4ef;
  --cp-bg-elevated: #fcfbf8;
  --cp-surface: #ffffff;
  --cp-surface-soft: #f5f5f5;
  --cp-border: #dedede;
  --cp-border-strong: #919191;
  --cp-text: #242424;
  --cp-text-muted: #5c5c5c;
  --cp-text-soft: #6f6f6f;
  --cp-accent: #b11f4b;
  --cp-accent-hover: #9a1a41;
  --cp-accent-soft: rgba(177, 31, 75, 0.08);
  --cp-accent-fg: #ffffff;
  --cp-success: #16a34a;
  --cp-danger: #dc2626;
  --cp-warning: #f59e0b;
  --cp-link: #0078d4;
  --cp-shadow: 0 18px 48px rgba(0, 0, 0, 0.12);
  --cp-overlay: rgba(255, 255, 255, 0.8);
  --cp-panel: rgba(255, 255, 255, 0.86);
  --cp-panel-strong: rgba(255, 255, 255, 0.96);
  --cp-sheen: rgba(255, 255, 255, 0.55);
  --cp-highlight: rgba(177, 31, 75, 0.12);
  --cp-dashboard-bg: #f3f2f1;
  --cp-dashboard-surface: #ffffff;
  --cp-dashboard-surface-soft: #faf9f8;
  --cp-dashboard-border: #edebe9;
  --cp-dashboard-text: #201f1e;
  --cp-dashboard-muted: #605e5c;
  --cp-dashboard-hero: #0078d4;
  --cp-dashboard-hero-strong: #006cbe;
  --cp-dashboard-on-hero: #ffffff;
  --cp-dashboard-on-hero-muted: #deecf9;
  --cp-dashboard-hero-panel: rgba(255, 255, 255, 0.32);
  --cp-dashboard-nav: #201f1e;
  --cp-dashboard-nav-text: #a19f9d;
  --cp-dashboard-callout: #fff8ed;
  --cp-dashboard-card-shadow: 0 1px 2px rgba(0,0,0,0.05);
  --cp-priority-high-bg: #fde7e9;
  --cp-priority-high-fg: #a4262c;
  --cp-priority-medium-bg: #fff4ce;
  --cp-priority-medium-fg: #8e562e;
  --cp-priority-low-bg: #dff6dd;
  --cp-priority-low-fg: #107c10;
}
html[data-theme="dark"] {
  color-scheme: dark;
  --cp-bg: #3d3b3a;
  --cp-bg-elevated: #343231;
  --cp-surface: #292929;
  --cp-surface-soft: #2e2e2e;
  --cp-border: #474747;
  --cp-border-strong: #5f5f5f;
  --cp-text: #dedede;
  --cp-text-muted: #919191;
  --cp-text-soft: #b0b0b0;
  --cp-accent: #fd8ea1;
  --cp-accent-hover: #fb7b91;
  --cp-accent-soft: rgba(253, 142, 161, 0.14);
  --cp-accent-fg: #1a1a1a;
  --cp-success: #4ade80;
  --cp-danger: #f87171;
  --cp-warning: #fbbf24;
  --cp-link: #4da6ff;
  --cp-shadow: 0 18px 48px rgba(0, 0, 0, 0.32);
  --cp-overlay: rgba(41, 41, 41, 0.88);
  --cp-panel: rgba(41, 41, 41, 0.72);
  --cp-panel-strong: rgba(41, 41, 41, 0.96);
  --cp-sheen: rgba(255, 255, 255, 0.04);
  --cp-highlight: rgba(253, 142, 161, 0.12);
  --cp-dashboard-bg: #f3f2f1;
  --cp-dashboard-surface: #ffffff;
  --cp-dashboard-surface-soft: #faf9f8;
  --cp-dashboard-border: #edebe9;
  --cp-dashboard-text: #201f1e;
  --cp-dashboard-muted: #605e5c;
  --cp-dashboard-hero: #0078d4;
  --cp-dashboard-hero-strong: #006cbe;
  --cp-dashboard-on-hero: #ffffff;
  --cp-dashboard-on-hero-muted: #deecf9;
  --cp-dashboard-hero-panel: rgba(255, 255, 255, 0.32);
  --cp-dashboard-nav: #201f1e;
  --cp-dashboard-nav-text: #a19f9d;
  --cp-dashboard-callout: #fff8ed;
  --cp-dashboard-card-shadow: 0 1px 2px rgba(0,0,0,0.05);
  --cp-priority-high-bg: #fde7e9;
  --cp-priority-high-fg: #a4262c;
  --cp-priority-medium-bg: #fff4ce;
  --cp-priority-medium-fg: #8e562e;
  --cp-priority-low-bg: #dff6dd;
  --cp-priority-low-fg: #107c10;
}"""


APP_MENU_CSS = """
.app-menu {
  display: flex;
  gap: 12px;
  align-items: center;
  margin: 0 10px 8px;
  padding: 10px 0 0;
  background: var(--cp-dashboard-bg);
  border-bottom: 1px solid var(--cp-dashboard-border);
}
.app-menu a {
  color: var(--cp-dashboard-muted);
  text-decoration: none;
  font-weight: 700;
  padding: 12px 14px 10px;
  border-bottom: 4px solid transparent;
}
.app-menu a.active {
  color: var(--cp-link);
  border-bottom-color: var(--cp-link);
}
.app-menu a:not(.active):hover {
  color: var(--cp-link);
  border-bottom-color: var(--cp-link);
}
"""


SHELL_CSS = """
.app-shell-page {
  height: 100dvh;
  overflow: hidden;
  background: var(--cp-dashboard-bg);
}
.app-shell-page .app-menu {
  margin-bottom: 8px;
}
#dashboard-frame {
  display: block;
  width: 100%;
  height: calc(100dvh - 64px);
  margin: 0;
  border: 0;
  background: var(--cp-dashboard-bg);
}
@media (max-width: 720px) {
  .app-shell-page {
    overflow: auto;
  }
  .app-shell-page .app-menu {
    flex-wrap: wrap;
  }
  #dashboard-frame {
    height: calc(100dvh - 118px);
  }
}
"""


MILESTONE_BASE_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, sans-serif;
  background: var(--cp-dashboard-bg);
  color: var(--cp-dashboard-text);
  padding: 20px;
  line-height: 1.4;
}
h1 { font-size: 22px; color: var(--cp-dashboard-text); }
h2 { font-size: 16px; margin: 24px 0 12px 0; color: var(--cp-dashboard-text); }
h3 { font-size: 14px; margin: 16px 0 8px 0; color: var(--cp-dashboard-muted); font-weight: 600; }
p { margin: 0; }
.shell { max-width: none; margin: 0; padding: 0; }
.hero {
  background: linear-gradient(135deg, var(--cp-dashboard-hero), var(--cp-dashboard-hero-strong));
  color: var(--cp-dashboard-on-hero);
  padding: 20px 28px;
  border-radius: 8px;
  margin-bottom: 20px;
  box-shadow: var(--cp-dashboard-card-shadow);
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}
.hero > div:first-child { flex: 1; min-width: 280px; }
.hero h1 { color: var(--cp-dashboard-on-hero); margin: 0; }
.eyebrow {
  color: var(--cp-dashboard-on-hero-muted);
  font-size: 12px;
  margin: 0 0 6px;
  font-weight: 600;
  letter-spacing: 0;
  text-transform: none;
}
.hero-copy {
  color: var(--cp-dashboard-on-hero-muted);
  font-size: 12px;
  margin-top: 6px;
  max-width: 760px;
}
.source-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: flex-end;
  text-align: right;
}
.source-card span {
  font-size: 11px;
  color: var(--cp-dashboard-on-hero-muted);
  text-transform: none;
  letter-spacing: 0;
  font-weight: 400;
}
.source-card strong {
  font-size: 10px;
  color: var(--cp-dashboard-on-hero-muted);
  max-width: 280px;
  line-height: 1.3;
}
.dashboard-tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 16px;
  border-bottom: 1px solid var(--cp-dashboard-border);
}
.dashboard-tabs a {
  padding: 10px 18px;
  text-decoration: none;
  font-size: 13px;
  font-weight: 600;
  color: var(--cp-dashboard-muted);
  border-bottom: 2px solid transparent;
}
.dashboard-tabs a.active {
  color: var(--cp-link);
  border-bottom-color: var(--cp-link);
}
.dashboard-tabs a:hover:not(.active) {
  color: var(--cp-dashboard-text);
  background: var(--cp-dashboard-surface-soft);
}
.card {
  background: var(--cp-dashboard-surface);
  padding: 16px 18px;
  border-radius: 6px;
  box-shadow: var(--cp-dashboard-card-shadow);
  margin-bottom: 16px;
}
.toolbar {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
  align-items: center;
  flex-wrap: wrap;
}
label {
  display: grid;
  gap: 4px;
  font-size: 12px;
  color: var(--cp-dashboard-muted);
}
input, select {
  padding: 6px 10px;
  font-size: 13px;
  border: 1px solid var(--cp-border-strong);
  border-radius: 4px;
  font-family: inherit;
  background: var(--cp-dashboard-surface);
  color: var(--cp-dashboard-text);
  min-width: 150px;
}
input:focus, select:focus {
  outline: 2px solid var(--cp-link);
  border-color: var(--cp-link);
}
button, a.primary-button, a.secondary-button {
  border: none;
  padding: 8px 16px;
  font-size: 13px;
  font-weight: 600;
  border-radius: 4px;
  cursor: pointer;
  font-family: inherit;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.primary-button {
  background: var(--cp-accent);
  color: var(--cp-accent-fg);
}
.primary-button:hover { background: var(--cp-accent-hover); }
.secondary-button {
  background: var(--cp-dashboard-surface);
  color: var(--cp-link);
  box-shadow: var(--cp-dashboard-card-shadow);
}
.secondary-button:hover { background: var(--cp-dashboard-surface-soft); }
.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 20px;
}
.kpi-card {
  position: relative;
  border-left: 4px solid var(--cp-link);
  margin-bottom: 0;
  padding: 16px 18px;
}
.kpi-card:nth-child(1),
.kpi-card:nth-child(4),
.kpi-card:nth-child(6) { border-left-color: var(--cp-danger); }
.kpi-card:nth-child(2) { border-left-color: var(--cp-warning); }
.kpi-card:nth-child(3),
.kpi-card:nth-child(5) { border-left-color: var(--cp-success); }
.kpi-card span {
  color: var(--cp-dashboard-muted);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.kpi-card strong {
  font-size: 26px;
  font-weight: 600;
  margin-top: 4px;
  display: block;
  color: var(--cp-dashboard-text);
}
.kpi-card small {
  font-size: 12px;
  margin-top: 2px;
  color: var(--cp-dashboard-muted);
  display: block;
}
.how-to-read {
  background: var(--cp-dashboard-callout);
  border-left: 3px solid var(--cp-warning);
  padding: 8px 12px;
  border-radius: 4px;
  font-size: 12px;
  color: var(--cp-dashboard-text);
  margin: 12px 0;
}
.grid-two {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.section-heading { margin-bottom: 12px; }
.section-heading h2 {
  margin: 0 0 4px;
  font-size: 14px;
  font-weight: 600;
  color: var(--cp-dashboard-text);
}
.section-heading p {
  font-size: 11px;
  color: var(--cp-dashboard-muted);
  margin: 0;
}
.bar-list { display: grid; gap: 12px; }
.bar-label {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 12px;
  margin-bottom: 4px;
}
.bar-label span { color: var(--cp-dashboard-muted); }
.bar-track {
  height: 10px;
  overflow: hidden;
  background: var(--cp-dashboard-surface-soft);
  border-radius: 4px;
  border: 1px solid var(--cp-dashboard-border);
}
.bar-fill { height: 100%; background: var(--cp-accent); }
.priority-high-bg { background: var(--cp-danger); }
.priority-medium-bg { background: var(--cp-warning); }
.priority-low-bg { background: var(--cp-success); }
.accent-bg { background: var(--cp-link); }
.responsive-table {
  max-height: 500px;
  overflow-y: auto;
  border: 1px solid var(--cp-dashboard-border);
  border-radius: 4px;
}
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th {
  background: var(--cp-dashboard-surface-soft);
  padding: 8px 10px;
  text-align: left;
  font-weight: 600;
  color: var(--cp-dashboard-text);
  border-bottom: 1px solid var(--cp-dashboard-border);
  position: sticky;
  top: 0;
  z-index: 1;
}
td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--cp-dashboard-border);
  vertical-align: top;
}
tr.clickable { cursor: pointer; }
tr.clickable:hover { background: var(--cp-dashboard-bg); }
.num { text-align: right; font-variant-numeric: tabular-nums; }
code { font-family: Consolas, "Courier New", Courier, monospace; }
.tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
}
.priority-high { color: var(--cp-priority-high-fg); background: var(--cp-priority-high-bg); }
.priority-medium { color: var(--cp-priority-medium-fg); background: var(--cp-priority-medium-bg); }
.priority-low { color: var(--cp-priority-low-fg); background: var(--cp-priority-low-bg); }
.result-count { color: var(--cp-dashboard-muted); font-size: 12px; margin-bottom: 8px; }
.details-panel { border: 1px solid var(--cp-dashboard-border); }
.detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}
.detail-grid > div {
  background: var(--cp-dashboard-surface-soft);
  border: 1px solid var(--cp-dashboard-border);
  border-radius: 4px;
  padding: 10px;
}
.detail-grid span { color: var(--cp-dashboard-muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }
.detail-grid strong { display: block; margin-top: 4px; font-size: 16px; font-weight: 600; }
.detail-grid small { display: block; color: var(--cp-dashboard-muted); margin-top: 2px; font-size: 11px; }
.milestone-list { margin-left: 18px; }
.milestone-list li { margin-bottom: 4px; font-size: 12px; }
.methodology p { color: var(--cp-dashboard-muted); margin-bottom: 8px; font-size: 12px; }
.error-text { color: var(--cp-danger); font-size: 12px; }
.empty { padding: 12px; color: var(--cp-dashboard-muted); font-size: 12px; }
@media (max-width: 1100px) {
  .grid-two { grid-template-columns: 1fr; }
  .hero { flex-direction: column; align-items: flex-start; }
  .source-card { align-items: flex-start; text-align: left; }
}
@media print {
  .toolbar, .app-menu { display: none; }
  body { background: var(--cp-dashboard-surface); padding: 0; }
  .card, .hero { break-inside: avoid; box-shadow: none; }
}
"""


def app_menu_html(active: str) -> str:
    acr_class = "active" if active == "acr" else ""
    milestone_class = "active" if active == "milestones" else ""
    return (
        '<nav class="app-menu" aria-label="Dashboard menu">'
        f'<a class="{acr_class}" href="/">ACR dashboard</a>'
        f'<a class="{milestone_class}" href="/milestones">Milestone gaps</a>'
        "</nav>"
    )


def shell_menu_html(active: str) -> str:
    acr_class = "active" if active == "acr" else ""
    milestone_class = "active" if active == "milestones" else ""
    return (
        '<nav class="app-menu" aria-label="Dashboard menu">'
        f'<a class="{acr_class}" href="/" data-dashboard="acr" data-src="/embed/acr" data-url="/">ACR dashboard</a>'
        f'<a class="{milestone_class}" href="/milestones" data-dashboard="milestones" data-src="/embed/milestones" data-url="/milestones">Milestone gaps</a>'
        "</nav>"
    )


def _inject_app_menu(template: str, *, active: str) -> str:
    if "clawpilotTheme" not in template:
        template = template.replace("<head>", f"<head>\n{THEME_SCRIPT}", 1)
    if "--cp-bg:" not in template:
        template = template.replace("<style>", f"<style>\n{CLAWPILOT_THEME_CSS}\n{APP_MENU_CSS}", 1)
    elif ".app-menu" not in template:
        template = template.replace("</style>", f"{APP_MENU_CSS}\n</style>", 1)
    menu = app_menu_html(active)
    next_template, count = re.subn(r"(<body[^>]*>)", rf"\1\n{menu}", template, count=1)
    if count != 1:
        raise ValueError("Could not inject dashboard menu into HTML template.")
    return next_template


def _safe_json_script(model: dict) -> str:
    return json.dumps(model, ensure_ascii=False, allow_nan=False).replace("</", "<\\/")


def _html_escape(value: object) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _opportunity_map_labels(template: str) -> str:
    replacements = {
        '<button class="tab" data-tab="opportunity">Opportunity Matrix</button>': '<button class="tab" data-tab="opportunity">Service Attach Opportunities</button>',
        "Opportunity Quadrant — DfC growth vs. other Azure growth": "Service attach opportunities - workloads you sell but don't protect",
        "3-month trend leading up to the latest full month. Bottom-right = top opportunity (Other Azure growing, DfC flat or shrinking). Bubble size = total monthly ACR. Bubble color = priority (red/orange/green) — a green bubble in the red zone means the customer is in the high-opp geometry but already has heavy DfC penetration, so priority is lower. Click any bubble to drill down.": "Ranked by per-service Defender attach gap. Each account is buying Azure workloads without the matching Defender plan turned on. The largest gap service, the total monthly and annual attach opportunity, and the recommended sales play are shown per account. Click any row to drill down.",
        "3-month trend leading up to the latest full month. Bottom-right = top opportunity (Other Azure growing, DfC flat or shrinking).": "Ranked by per-service Defender attach gap. Click any row to drill down.",
        "Other Azure 3-month change": "Growth gap",
        "DfC 3-month change": "DfC penetration",
    }
    for old, new in replacements.items():
        template = template.replace(old, new)
    return template


def _split_opportunity_pages(template: str) -> str:
    """Split service attach actions and trend divergence into separate tabs."""

    template = re.sub(
        r'(<button class="tab" data-tab="opportunity">Service Attach Opportunities</button>\s*)'
        r'(<button class="tab" data-tab="drilldown">Customer Drill-Down</button>)',
        r'\1  <button class="tab" data-tab="divergence">Defender Coverage Drift</button>\n  \2',
        template,
        count=1,
    )
    template = template.replace(
        '<!-- ============ OPPORTUNITY MATRIX ============ -->',
        '<!-- ============ SERVICE ATTACH OPPORTUNITIES ============ -->',
        1,
    )
    template = template.replace(
        '<!-- ============ DRILL-DOWN ============ -->',
        '<!-- ============ DIVERGENCE STORIES ============ -->\n'
        '<div class="panel" id="panel-divergence"></div>\n\n'
        '<!-- ============ DRILL-DOWN ============ -->',
        1,
    )
    return template


def _inject_opportunity_map(template: str) -> str:
    template = template.replace(
        '<div class="note" id="cust-signal"></div>',
        '<div class="note" id="cust-signal"></div>\n  <div id="cust-sales-stories"></div>',
        1,
    )
    color_anchor = (
        "note.style.color = opp.opportunity === 'High' ? '#5d1014' : "
        "opp.opportunity === 'Medium' ? '#5d3a00' : '#0e3a0e';"
    )
    template = template.replace(
        color_anchor,
        color_anchor + "\n  renderCustomerSalesStories('', name);",
        1,
    )
    script = r'''
const DEFAULT_DFC_SHARE_THRESHOLD = 6;
let dfcShareThreshold = DEFAULT_DFC_SHARE_THRESHOLD;

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function fmtThreshold(value) {
  return Number.isInteger(value) ? `${value}%` : `${value.toFixed(1)}%`;
}

// Re-run the opportunity classifier against the selected attach baseline so the
// slider actually drives priority (not just sorting). Mutates DATA.opportunity
// rows in place and recomputes DATA.counts. Safe to call when DATA is empty.
function reclassifyOpportunities(thresholdPct) {
  if (!DATA || !Array.isArray(DATA.opportunity) || !window.AcrModel ||
      typeof AcrModel.classifyOpportunity !== 'function') {
    return;
  }
  const threshold = (Number.isFinite(thresholdPct) ? thresholdPct : DEFAULT_DFC_SHARE_THRESHOLD) / 100;
  for (const row of DATA.opportunity) {
    const [priority, notes] = AcrModel.classifyOpportunity({
      dfc_current: row.dfc_current,
      total_current: row.total_current,
      dfc_ratio: (Number(row.dfc_ratio) || 0) / 100,
      dfc_3m: row.dfc_3m,
      other_3m: row.other_3m,
      growth_cat_3m: (row.growth_cat_3m == null ? null : row.growth_cat_3m),
      growth_cat_names: row.growth_cat_names || null,
      threshold: threshold,
    });
    row.opportunity = priority;
    row.notes = notes;
  }
  DATA.counts = {
    high:      DATA.opportunity.filter(r => r.opportunity === 'High').length,
    medium:    DATA.opportunity.filter(r => r.opportunity === 'Medium').length,
    low:       DATA.opportunity.filter(r => r.opportunity === 'Low').length,
    too_small: DATA.opportunity.filter(r => r.opportunity === 'Too small').length,
    total:     (DATA.customers && DATA.customers.length) || DATA.opportunity.length,
  };
}

let _thresholdRenderTimer = null;
// Heavy re-render (heatmap + the currently-selected customer detail, which
// redraws charts) is debounced so dragging the slider stays smooth.
function applyThresholdRender() {
  if (typeof renderKpis === 'function') renderKpis();
  if (_thresholdRenderTimer) clearTimeout(_thresholdRenderTimer);
  _thresholdRenderTimer = setTimeout(() => {
    _thresholdRenderTimer = null;
    renderOpportunityHeatmap();
    const sel = document.getElementById('customer-select');
    const drill = document.getElementById('panel-drilldown');
    if (sel && sel.value && drill && drill.classList.contains('active') &&
        typeof renderCustomerDetail === 'function') {
      renderCustomerDetail(sel.value);
    }
  }, 120);
}

function ensureDfcThresholdControl() {
  if (document.getElementById('dfc-threshold')) return;
  const filter = document.getElementById('quadrant-filter');
  if (!filter || !filter.parentElement) return;
  const wrap = document.createElement('label');
  wrap.id = 'dfc-threshold-wrap';
  wrap.setAttribute('for', 'dfc-threshold');
  wrap.style.display = 'flex';
  wrap.style.alignItems = 'center';
  wrap.style.gap = '8px';
  wrap.style.minWidth = '360px';
  wrap.innerHTML = `
    Defender share threshold
    <input id="dfc-threshold" type="range" min="0" max="20" step="0.5" value="${DEFAULT_DFC_SHARE_THRESHOLD}" aria-label="Defender for Cloud share threshold" style="width:180px;">
    <strong id="dfc-threshold-value">${fmtThreshold(DEFAULT_DFC_SHARE_THRESHOLD)}</strong>
    <span id="dfc-threshold-count" style="color:#605e5c;"></span>`;
  filter.parentElement.appendChild(wrap);
  updateExportLink();
  document.getElementById('dfc-threshold').addEventListener('input', e => {
    const next = parseFloat(e.target.value);
    dfcShareThreshold = Number.isFinite(next) ? next : DEFAULT_DFC_SHARE_THRESHOLD;
    const valEl = document.getElementById('dfc-threshold-value');
    if (valEl) valEl.textContent = fmtThreshold(dfcShareThreshold);
    updateExportLink();
    reclassifyOpportunities(dfcShareThreshold);
    applyThresholdRender();
  });
}

function updateExportLink() {
  const exportLink = document.querySelector('a[href^="/export-ppt"]');
  if (exportLink) exportLink.href = `/export-ppt?threshold=${encodeURIComponent(dfcShareThreshold)}`;
}

function ensureActionQueueShell() {
  if (document.getElementById('action-queue-section')) return;
  const chart = document.getElementById('chart-quadrant');
  const chartBox = chart?.closest('.chart-box');
  if (!chartBox || !chartBox.parentElement) return;
  const section = document.createElement('div');
  section.id = 'action-queue-section';
  section.innerHTML = `
    <div class="cards">
      <div class="card high"><div class="label">Annualized DfC Attach Opportunity</div><div class="val" id="action-annual-opportunity">-</div><div class="delta" id="action-annual-opportunity-note">per-service attach gap, annualized</div></div>
      <div class="card medium"><div class="label">Monthly DfC Attach Gap</div><div class="val" id="action-monthly-gap">-</div><div class="delta" id="action-monthly-gap-note">per-service attach gap, latest month</div></div>
      <div class="card"><div class="label">Accounts With Attach Gaps</div><div class="val" id="action-below-threshold">-</div><div class="delta" id="action-below-threshold-note">accounts with a per-service gap</div></div>
    </div>`;
  chartBox.parentElement.insertBefore(section, chartBox);
}

function ensureMergedQueueControls() {
  if (document.getElementById('action-queue-limit')) return;
  const filter = document.getElementById('quadrant-filter');
  if (!filter || !filter.parentElement) return;
  const wrap = document.createElement('div');
  wrap.style.display = 'flex';
  wrap.style.alignItems = 'center';
  wrap.style.gap = '8px';
  wrap.style.flexWrap = 'wrap';
  wrap.innerHTML = `
    <label for="action-queue-search">Search
      <input id="action-queue-search" type="search" placeholder="Customer, service, action..." aria-label="Search service attach opportunities" style="min-width:260px;">
    </label>
    <label>Rows
      <select id="action-queue-limit">
        <option value="10">Top 10</option>
        <option value="25" selected>Top 25</option>
        <option value="all">All visible</option>
      </select>
    </label>
    <button class="import-btn" id="copy-action-queue" type="button">Copy action list</button>
    <button class="import-btn" id="download-action-queue" type="button">Download CSV</button>
    <span id="action-queue-status" style="font-size:12px;color:#605e5c;"></span>`;
  filter.parentElement.appendChild(wrap);
  document.getElementById('action-queue-search').addEventListener('input', renderOpportunityHeatmap);
  document.getElementById('action-queue-limit').addEventListener('change', renderOpportunityHeatmap);
  document.getElementById('copy-action-queue').addEventListener('click', copyActionQueue);
  document.getElementById('download-action-queue').addEventListener('click', downloadActionQueueCsv);
}


// ---- Manager-level divergence stories ------------------------------------
let _divOverlay = null;
let _divLastFocus = null;

function storyValue(story, camelName, snakeName, fallback = null) {
  if (!story || typeof story !== 'object') return fallback;
  if (story[camelName] !== undefined && story[camelName] !== null) return story[camelName];
  if (story[snakeName] !== undefined && story[snakeName] !== null) return story[snakeName];
  return fallback;
}

function _storyCustomerKey(value) {
  return String(value ?? '').trim().toLowerCase();
}

function sortDivergenceStoryList(stories) {
  const rank = {High: 0, Medium: 1, Low: 2};
  return stories.slice().sort((a, b) =>
    ((rank[storyValue(a, 'severity', 'severity', 'Low')] ?? 9) - (rank[storyValue(b, 'severity', 'severity', 'Low')] ?? 9)) ||
    ((storyValue(b, 'gapDollars', 'gap_dollars', 0) || 0) - (storyValue(a, 'gapDollars', 'gap_dollars', 0) || 0)) ||
    ((storyValue(b, 'latestWorkloadAcr', 'latest_workload_acr', 0) || 0) - (storyValue(a, 'latestWorkloadAcr', 'latest_workload_acr', 0) || 0)) ||
    String(storyValue(a, 'customer', 'customer', '')).localeCompare(String(storyValue(b, 'customer', 'customer', ''))) ||
    String(storyValue(a, 'planLabel', 'plan_label', '')).localeCompare(String(storyValue(b, 'planLabel', 'plan_label', ''))));
}

function divergenceStories() {
  const sa = DATA.service_attach || {};
  let stories = Array.isArray(sa.divergenceStories) ? sa.divergenceStories :
    (Array.isArray(sa.divergence_stories) ? sa.divergence_stories : []);
  if (!stories.length && Array.isArray(sa.dossiers)) {
    stories = sa.dossiers.flatMap(d => {
      const items = Array.isArray(d.divergenceStories) ? d.divergenceStories :
        (Array.isArray(d.divergence_stories) ? d.divergence_stories : []);
      return items.map(s => ({customer: d.customer, ...s}));
    });
  }
  return sortDivergenceStoryList(stories);
}

function storyDossier(customer) {
  const target = _storyCustomerKey(customer);
  if (!target) return null;
  const dossiers = (DATA.service_attach && Array.isArray(DATA.service_attach.dossiers)) ? DATA.service_attach.dossiers : [];
  return dossiers.find(d => _storyCustomerKey(d.customer) === target) || null;
}

function storyOpportunity(story) {
  const dossier = storyDossier(storyValue(story, 'customer', 'customer', ''));
  if (!dossier || !Array.isArray(dossier.opportunities)) return null;
  const plan = storyValue(story, 'planLabel', 'plan_label', '');
  return dossier.opportunities.find(o => String(o.planLabel || o.plan_label || '') === String(plan)) || null;
}

function storyAccountAcr(customer) {
  const target = _storyCustomerKey(customer);
  if (!target || !DATA || !Array.isArray(DATA.opportunity)) return 0;
  const row = DATA.opportunity.find(r => _storyCustomerKey(r.customer) === target);
  return row ? (row.total_monthly_current || row.total_current || 0) : 0;
}

function divergenceSeverityRank(severity) {
  return ({High: 0, Medium: 1, Low: 2})[severity] ?? 9;
}

function divergenceSeverityTag(severity) {
  const sev = ['High', 'Medium', 'Low'].includes(severity) ? severity : 'Low';
  const cls = sev === 'High' ? 'high' : (sev === 'Medium' ? 'medium' : 'low');
  return '<span class="tag ' + cls + ' div-severity-badge" role="button" tabindex="0" ' +
    'title="Why is divergence severity ' + escapeHtml(sev) + '? Click for the divergence grading.">' +
    escapeHtml(sev) + ' <span class="prio-badge-i" aria-hidden="true">&#9432;</span></span>';
}

function ensureDivergenceModal() {
  if (_divOverlay) return _divOverlay;
  const style = document.createElement('style');
  style.textContent =
    '.div-severity-badge{cursor:pointer;user-select:none}' +
    '.div-severity-badge:hover{filter:brightness(.96);box-shadow:0 0 0 1px rgba(0,0,0,.15)}' +
    '.div-severity-badge:focus-visible{outline:2px solid #0078d4;outline-offset:1px}' +
    '.div-overlay{position:fixed;inset:0;background:rgba(15,23,42,.55);display:flex;align-items:flex-start;justify-content:center;z-index:3980;padding:40px 16px;overflow:auto}' +
    '.div-overlay[hidden]{display:none}' +
    '.div-dialog{position:relative;background:#fff;border-radius:10px;max-width:1120px;width:100%;box-shadow:0 20px 60px rgba(0,0,0,.3)}' +
    '.div-close{position:absolute;top:8px;right:12px;border:none;background:transparent;font-size:28px;line-height:1;cursor:pointer;color:#605e5c;z-index:1}' +
    '.div-close:hover{color:#201f1e}.div-close:focus-visible{outline:2px solid #0078d4;outline-offset:1px}' +
    '.div-body{padding:24px 28px 28px}.div-body h2{margin:0 34px 4px 0;font-size:20px;color:#201f1e}.div-sub{font-size:12px;color:#605e5c;margin-bottom:14px}' +
    '.div-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:0 0 14px}.div-kpi{border:1px solid #eef1f5;border-radius:8px;padding:10px;background:#fff}.div-kpi .big{font-size:20px;font-weight:700;color:#201f1e}.div-kpi .lbl{font-size:11px;color:#605e5c;margin-top:3px}' +
    '.div-comparison{border:1px solid #edebe9;border-radius:8px;margin-top:10px;background:#fff;overflow:hidden}.div-comparison summary{list-style:none;cursor:pointer;padding:12px 14px}.div-comparison summary::-webkit-details-marker{display:none}.div-comparison[open] summary{border-bottom:1px solid #edebe9;background:#faf9f8}' +
    '.div-comp-grid{display:grid;grid-template-columns:minmax(220px,1.4fr) repeat(4,minmax(110px,.7fr)) minmax(220px,1.4fr);gap:10px;align-items:start}.div-comp-grid .num{text-align:right;font-variant-numeric:tabular-nums}' +
    '.div-comp-label{font-size:12px;color:#605e5c}.div-comp-main{font-weight:700;color:#201f1e}.div-comp-detail{padding:0 14px 14px}.div-rubric{margin:0;padding-left:18px;color:#323130}.div-rubric li{margin-bottom:6px}' +
    '@media(max-width:780px){.div-comp-grid{grid-template-columns:1fr}.div-comp-grid .num{text-align:left}}';
  document.head.appendChild(style);
  const overlay = document.createElement('div');
  overlay.id = 'divergence-modal';
  overlay.className = 'div-overlay';
  overlay.setAttribute('hidden', '');
  overlay.innerHTML =
    '<div class="div-dialog" role="dialog" aria-modal="true" aria-labelledby="div-modal-title">' +
    '<button class="div-close" type="button" aria-label="Close">&times;</button>' +
    '<div class="div-body" id="div-modal-body"></div></div>';
  overlay.addEventListener('click', e => { if (e.target === overlay) closeDivergenceModal(); });
  overlay.querySelector('.div-close').addEventListener('click', closeDivergenceModal);
  overlay.addEventListener('keydown', e => {
    if (e.key !== 'Tab') return;
    const nodes = overlay.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
    const focusable = Array.prototype.filter.call(nodes, el => !el.disabled && el.offsetParent !== null);
    if (!focusable.length) return;
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
  document.body.appendChild(overlay);
  _divOverlay = overlay;
  return overlay;
}

function closeDivergenceModal() {
  if (_divOverlay) _divOverlay.setAttribute('hidden', '');
  if (_divLastFocus && typeof _divLastFocus.focus === 'function') {
    try { _divLastFocus.focus(); } catch (_) {}
  }
  _divLastFocus = null;
}

function divergenceSeverityExplanationHtml(currentSeverity) {
  const sev = ['High', 'Medium', 'Low'].includes(currentSeverity) ? currentSeverity : 'Low';
  const meta = {
    High: {color: '#d13438', bg: '#fdf3f4', text: 'urgent divergence'},
    Medium: {color: '#ff8c00', bg: '#fffaf0', text: 'meaningful divergence'},
    Low: {color: '#107c10', bg: '#f3f9ef', text: 'watch-list divergence'},
  }[sev];
  return `
    <div class="prio-head" style="border-left:6px solid ${meta.color};background:${meta.bg};">
      <div class="prio-head-tier" style="color:${meta.color};">${escapeHtml(sev)} divergence severity</div>
      <h2 id="div-modal-title">How divergence severity is calculated</h2>
      <p>Divergence severity is separate from Service Attach priority. It ranks how strongly Azure workload momentum and the matching Defender plan trend are moving apart.</p>
    </div>
    <section class="prio-section">
      <h3>Current tier: ${escapeHtml(meta.text)}</h3>
      <ul class="div-rubric">
        <li><strong>High:</strong> material workload growth with Defender flat/zero, Defender regression while workload is stable or growing, or the largest momentum spread signals an urgent coverage review.</li>
        <li><strong>Medium:</strong> workload and Defender trends are materially misaligned, but the evidence is less severe or lower confidence than a High story.</li>
        <li><strong>Low:</strong> Defender is broadly tracking, or the divergence is small enough to monitor before using as a sales motion.</li>
      </ul>
    </section>
    <div class="note" style="margin-top:10px;border-left-color:#0078d4;background:#f0f6fc;color:#243a5e;">
      <strong>Directional signal:</strong> this is a trend-comparison story, not proof of missing protection. Validate resource scope, entitlements, and pricing drivers before forecasting.
    </div>`;
}

function openDivergenceSeverityExplainer(severity) {
  const overlay = ensureDivergenceModal();
  document.getElementById('div-modal-body').innerHTML = divergenceSeverityExplanationHtml(severity);
  overlay.removeAttribute('hidden');
  const closeBtn = overlay.querySelector('.div-close');
  if (closeBtn) closeBtn.focus();
}

function ensureDivergenceInteractions() {
  if (window.__divergenceInteractionsWired) return;
  window.__divergenceInteractionsWired = true;
  document.addEventListener('click', e => {
    if (!e.target.closest) return;
    const badge = e.target.closest('.div-severity-badge');
    if (!badge) return;
    e.stopPropagation();
    e.preventDefault();
    _divLastFocus = badge;
    openDivergenceSeverityExplainer((badge.textContent || '').replace(/\s+.*/, '').trim());
  }, true);
  document.addEventListener('keydown', e => {
    if (e.key !== 'Enter' && e.key !== ' ' && e.key !== 'Spacebar') return;
    if (!e.target.closest) return;
    const badge = e.target.closest('.div-severity-badge');
    if (!badge) return;
    e.stopPropagation();
    e.preventDefault();
    _divLastFocus = badge;
    openDivergenceSeverityExplainer((badge.textContent || '').replace(/\s+.*/, '').trim());
  }, true);
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    if (!_divOverlay || _divOverlay.hasAttribute('hidden')) return;
    closeDivergenceModal();
  }, true);
}

function _storySeries(story, opp, camelName, snakeName, startCamel, startSnake, endCamel, endSnake) {
  const raw = opp ? (opp[camelName] || opp[snakeName]) : null;
  if (Array.isArray(raw) && raw.length) return raw.map(v => Number(v) || 0);
  const start = Number(storyValue(story, startCamel, startSnake, 0)) || 0;
  const end = Number(storyValue(story, endCamel, endSnake, 0)) || 0;
  return [start, end];
}

function _storyMonths(story, seriesLen) {
  const months = (DATA.service_attach && Array.isArray(DATA.service_attach.months)) ? DATA.service_attach.months : (DATA.months || []);
  if (Array.isArray(months) && months.length === seriesLen) return months;
  const compared = storyValue(story, 'monthsCompared', 'months_compared', []);
  if (Array.isArray(compared) && compared.length) return compared;
  return ['Start', 'End'];
}

function _seriesSpark(values, color) {
  const vals = (Array.isArray(values) ? values : []).map(v => Number(v) || 0);
  if (!vals.length) return '';
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = Math.max(1, max - min);
  const w = 220, h = 54;
  const points = vals.map((v, i) => {
    const x = vals.length === 1 ? w / 2 : (i / (vals.length - 1)) * w;
    const y = h - ((v - min) / span) * (h - 8) - 4;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="54" aria-hidden="true"><polyline fill="none" stroke="${color}" stroke-width="3" points="${points}"/></svg>`;
}

function _storyEvidencePanel(story) {
  const opp = storyOpportunity(story);
  const workload = _storySeries(story, opp, 'workloadSeries', 'workload_series', 'workloadStart', 'workload_start', 'workloadEnd', 'workload_end');
  const defender = _storySeries(story, opp, 'defenderSeries', 'defender_series', 'defenderStart', 'defender_start', 'defenderEnd', 'defender_end');
  const months = _storyMonths(story, Math.max(workload.length, defender.length));
  const firstMonth = months[0] || 'Start';
  const lastMonth = months[months.length - 1] || 'End';
  const workloadCats = storyValue(story, 'workloadSl2Categories', 'workload_sl2_categories', []);
  const cats = Array.isArray(workloadCats) ? workloadCats.filter(Boolean).join(', ') : String(workloadCats || '');
  const plan = storyValue(story, 'planLabel', 'plan_label', 'Defender plan');
  const pricing = storyValue(story, 'pricingDriver', 'pricing_driver', 'Pricing driver varies by plan');
  const caveat = storyValue(story, 'caveatText', 'caveat_text', 'Treat this as a directional coverage review signal until validated.');
  return `
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin-top:12px;">
      <div style="border:1px solid #edebe9;border-radius:8px;padding:12px;background:#faf9f8;">
        <div style="font-size:11px;color:#605e5c;text-transform:uppercase;letter-spacing:.04em;">Azure workload trend</div>
        <div style="font-weight:700;margin-top:3px;">${escapeHtml(cats || 'Mapped workload')}</div>
        <div style="font-size:12px;color:#605e5c;margin-top:2px;">${escapeHtml(firstMonth)} to ${escapeHtml(lastMonth)}</div>
        ${_seriesSpark(workload, '#0078d4')}
        <div style="display:flex;justify-content:space-between;font-size:12px;margin-top:4px;"><span>${fmt.money2(workload[0] || 0)}</span><strong>${fmt.money2(workload[workload.length - 1] || 0)}</strong></div>
      </div>
      <div style="border:1px solid #edebe9;border-radius:8px;padding:12px;background:#faf9f8;">
        <div style="font-size:11px;color:#605e5c;text-transform:uppercase;letter-spacing:.04em;">Matching Defender trend</div>
        <div style="font-weight:700;margin-top:3px;">${escapeHtml(plan)}</div>
        <div style="font-size:12px;color:#605e5c;margin-top:2px;">${escapeHtml(firstMonth)} to ${escapeHtml(lastMonth)}</div>
        ${_seriesSpark(defender, '#d13438')}
        <div style="display:flex;justify-content:space-between;font-size:12px;margin-top:4px;"><span>${fmt.money2(defender[0] || 0)}</span><strong>${fmt.money2(defender[defender.length - 1] || 0)}</strong></div>
      </div>
    </div>
    <div class="note" style="margin-top:10px;border-left-color:#0078d4;background:#f0f6fc;color:#243a5e;">
      <strong>Pricing context:</strong> ${escapeHtml(pricing)}. ${escapeHtml(caveat)}
    </div>`;
}

function ensureDivergenceStoriesShell() {
  if (document.getElementById('divergence-stories-section')) return;
  ensureDivergenceInteractions();
  const host = document.getElementById('panel-divergence');
  if (!host) return;
  const section = document.createElement('div');
  section.id = 'divergence-stories-section';
  section.innerHTML = `
    <div class="cards">
      <div class="card high"><div class="label">Coverage drift signals</div><div class="val" id="divergence-total">-</div><div class="delta">workload and Defender trends misaligned</div></div>
      <div class="card medium"><div class="label">Accounts affected</div><div class="val" id="divergence-accounts">-</div><div class="delta">unique customers to review</div></div>
      <div class="card high"><div class="label">High severity</div><div class="val" id="divergence-high">-</div><div class="delta">regression or no-coverage stories</div></div>
      <div class="card"><div class="label">Largest momentum spread</div><div class="val" id="divergence-spread" style="font-size:22px;">-</div><div class="delta" id="divergence-top-plan-note">top affected Defender plan</div></div>
    </div>
    <div class="chart-box">
      <div class="title">Defender Coverage Drift</div>
      <div class="sub">Customers where an Azure workload trend and its mapped Defender plan trend are moving apart.</div>
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:10px 0 8px;">
        <label>Filter:
          <select id="divergence-filter">
            <option value="HighMed" selected>High + Medium</option>
            <option value="High">High</option>
            <option value="Medium">Medium</option>
            <option value="Low">Low</option>
            <option value="All">All stories</option>
          </select>
        </label>
        <label for="divergence-search">Search
          <input id="divergence-search" type="search" placeholder="Customer, service, action..." aria-label="Search Defender coverage drift signals" style="min-width:260px;">
        </label>
        <label>Rows
          <select id="divergence-limit">
            <option value="10">Top 10</option>
            <option value="25" selected>Top 25</option>
            <option value="all">All visible</option>
          </select>
        </label>
        <button class="import-btn" id="copy-divergence-stories" type="button">Copy stories</button>
        <button class="import-btn" id="download-divergence-stories" type="button">Download CSV</button>
        <span id="divergence-status" style="font-size:12px;color:#605e5c;"></span>
      </div>
      <div id="divergence-table"></div>
      <div class="note" style="margin-top:10px;border-left-color:#0078d4;background:#f0f6fc;color:#243a5e;">
        <strong>Directional signal:</strong> Defender Coverage Drift compares ACR momentum and mapped Defender plan attach. Pricing drivers differ by plan, and usage-priced services may flag coverage gaps without a reliable dollar estimate. Validate resource scope and entitlement before forecasting.
      </div>
    </div>`;
  host.appendChild(section);
  document.getElementById('divergence-filter').addEventListener('change', renderDivergenceStories);
  document.getElementById('divergence-search').addEventListener('input', renderDivergenceStories);
  document.getElementById('divergence-limit').addEventListener('change', renderDivergenceStories);
  document.getElementById('copy-divergence-stories').addEventListener('click', copyDivergenceStories);
  document.getElementById('download-divergence-stories').addEventListener('click', downloadDivergenceStoriesCsv);
}

function setDivergenceStatus(message) {
  const status = document.getElementById('divergence-status');
  if (status) status.textContent = message;
}

function storyToDivergenceRow(s) {
  const workloadCats = storyValue(s, 'workloadSl2Categories', 'workload_sl2_categories', []);
  const evidence = storyValue(s, 'evidenceBullets', 'evidence_bullets', []);
  const rawSeverity = storyValue(s, 'severity', 'severity', 'Low');
  const severity = ['High', 'Medium', 'Low'].includes(rawSeverity) ? rawSeverity : 'Low';
  const customer = storyValue(s, 'customer', 'customer', '');
  return {
    rawStory: s,
    customer,
    headline: storyValue(s, 'headline', 'headline', ''),
    plan: storyValue(s, 'planLabel', 'plan_label', ''),
    storyType: _storyTypeLabel(s),
    severity,
    accountAcr: storyAccountAcr(customer),
    workloadChange: storyValue(s, 'workloadPctChange', 'workload_pct_change', null),
    defenderChange: storyValue(s, 'defenderPctChange', 'defender_pct_change', null),
    spread: storyValue(s, 'momentumSpread', 'momentum_spread', 0),
    confidence: storyValue(s, 'confidence', 'confidence', ''),
    recommendedAction: storyValue(s, 'recommendedAction', 'recommended_action', ''),
    pricingDriver: storyValue(s, 'pricingDriver', 'pricing_driver', ''),
    caveat: storyValue(s, 'caveatText', 'caveat_text', ''),
    gapDollars: storyValue(s, 'gapDollars', 'gap_dollars', 0),
    latestWorkloadAcr: storyValue(s, 'latestWorkloadAcr', 'latest_workload_acr', 0),
    latestDefenderAcr: storyValue(s, 'latestDefenderAcr', 'latest_defender_acr', 0),
    workloadDelta: storyValue(s, 'workloadDelta', 'workload_delta', 0),
    defenderDelta: storyValue(s, 'defenderDelta', 'defender_delta', 0),
    workloadCategories: Array.isArray(workloadCats) ? workloadCats.join(', ') : String(workloadCats || ''),
    evidence: Array.isArray(evidence) ? evidence.join(' ') : String(evidence || ''),
  };
}

function normalizedDivergenceRows() {
  const term = (document.getElementById('divergence-search')?.value || '').trim().toLowerCase();
  const filter = document.getElementById('divergence-filter')?.value || 'HighMed';
  return divergenceStories().map(storyToDivergenceRow).filter(row => {
    if (filter === 'High' || filter === 'Medium' || filter === 'Low') {
      if (row.severity !== filter) return false;
    } else if (filter === 'HighMed' && row.severity !== 'High' && row.severity !== 'Medium') {
      return false;
    }
    if (!term) return true;
    return [row.customer, row.headline, row.plan, row.severity, row.confidence,
      row.storyType, row.recommendedAction, row.pricingDriver, row.workloadCategories, row.evidence]
      .some(value => String(value ?? '').toLowerCase().includes(term));
  });
}

function sortDivergenceRows(rows) {
  return rows.slice().sort((a, b) =>
    divergenceSeverityRank(a.severity) - divergenceSeverityRank(b.severity) ||
    (Number(b.spread) || 0) - (Number(a.spread) || 0) ||
    (Number(b.gapDollars) || 0) - (Number(a.gapDollars) || 0) ||
    (Number(b.latestWorkloadAcr) || 0) - (Number(a.latestWorkloadAcr) || 0) ||
    String(a.plan || '').localeCompare(String(b.plan || '')));
}

function divergenceCustomerRows() {
  const groups = new Map();
  normalizedDivergenceRows().forEach(row => {
    const key = _storyCustomerKey(row.customer);
    if (!key) return;
    let group = groups.get(key);
    if (!group) {
      group = {
        customer: row.customer,
        accountAcr: row.accountAcr || 0,
        stories: [],
        storyCount: 0,
        severity: 'Low',
        maxSpread: 0,
        totalGap: 0,
        topStory: row,
      };
      groups.set(key, group);
    }
    group.stories.push(row);
  });
  groups.forEach(group => {
    group.stories = sortDivergenceRows(group.stories);
    group.storyCount = group.stories.length;
    group.topStory = group.stories[0];
    group.severity = group.topStory ? group.topStory.severity : 'Low';
    group.maxSpread = Math.max(...group.stories.map(r => Number(r.spread) || 0), 0);
    group.totalGap = group.stories.reduce((sum, r) => sum + (Number(r.gapDollars) || 0), 0);
    group.accountAcr = group.accountAcr || (group.topStory ? group.topStory.accountAcr : 0);
  });
  return Array.from(groups.values()).sort((a, b) =>
    divergenceSeverityRank(a.severity) - divergenceSeverityRank(b.severity) ||
    (Number(b.maxSpread) || 0) - (Number(a.maxSpread) || 0) ||
    (Number(b.totalGap) || 0) - (Number(a.totalGap) || 0) ||
    (Number(b.accountAcr) || 0) - (Number(a.accountAcr) || 0) ||
    String(a.customer || '').localeCompare(String(b.customer || '')));
}

function visibleDivergenceCustomerRows() {
  const rows = divergenceCustomerRows();
  const limit = document.getElementById('divergence-limit')?.value || '10';
  return limit === 'all' ? rows : rows.slice(0, parseInt(limit, 10));
}

function updateDivergenceKpis(allStories) {
  const totalEl = document.getElementById('divergence-total');
  const accountsEl = document.getElementById('divergence-accounts');
  const highEl = document.getElementById('divergence-high');
  const spreadEl = document.getElementById('divergence-spread');
  const topNoteEl = document.getElementById('divergence-top-plan-note');
  if (totalEl) totalEl.textContent = allStories.length.toLocaleString('en-US');
  if (accountsEl) {
    const accounts = new Set(allStories.map(s => _storyCustomerKey(storyValue(s, 'customer', 'customer', ''))).filter(Boolean));
    accountsEl.textContent = accounts.size.toLocaleString('en-US');
  }
  if (highEl) highEl.textContent = allStories.filter(s => storyValue(s, 'severity', 'severity', '') === 'High').length.toLocaleString('en-US');
  const counts = new Map();
  let largestSpread = null;
  allStories.forEach(s => {
    const label = storyValue(s, 'planLabel', 'plan_label', '') || 'Unmapped plan';
    counts.set(label, (counts.get(label) || 0) + 1);
    const spread = Number(storyValue(s, 'momentumSpread', 'momentum_spread', 0)) || 0;
    if (largestSpread === null || spread > largestSpread) largestSpread = spread;
  });
  const top = Array.from(counts.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0];
  if (spreadEl) spreadEl.textContent = largestSpread == null ? '\u2013' : fmt.pct(largestSpread);
  if (topNoteEl) topNoteEl.textContent = top ? `${top[0]} (${top[1]} ${top[1] === 1 ? 'story' : 'stories'})` : 'no story data';
}

function renderDivergenceStories() {
  ensureDivergenceStoriesShell();
  const host = document.getElementById('divergence-table');
  if (!host) return;
  const allStories = divergenceStories();
  updateDivergenceKpis(allStories);
  const allCustomerRows = divergenceCustomerRows();
  const rows = visibleDivergenceCustomerRows();
  if (!allStories.length) {
    host.innerHTML = '<div style="padding:24px;color:#605e5c;text-align:center;border:1px dashed #c8c6c4;border-radius:8px;">No Defender coverage drift detected in this workbook yet. When workload ACR grows while the mapped Defender plan lags or declines, signals will appear here.</div>';
    setDivergenceStatus('');
    return;
  }
  if (!rows.length) {
    host.innerHTML = '<div style="padding:24px;text-align:center;color:#605e5c;border:1px dashed #c8c6c4;border-radius:8px;">No Defender coverage drift signals match the current filter or search.</div>';
    setDivergenceStatus(`0 of ${allCustomerRows.length.toLocaleString('en-US')} customers visible`);
    return;
  }
  const maxSpread = Math.max(...rows.map(r => Math.max(0, Number(r.maxSpread) || 0)), 1);
  const spreadHeat = value => {
    const intensity = Math.max(0.08, Math.min(0.85, (Math.max(0, Number(value) || 0)) / maxSpread));
    return `background: color-mix(in srgb, #d13438 ${Math.round(intensity * 70)}%, white);font-weight:700;`;
  };
  host.innerHTML = `
    <div class="scroll-table" style="max-height:620px;">
      <table>
        <thead>
          <tr>
            <th>Customer</th>
            <th>Severity</th>
            <th class="num">Account ACR/mo</th>
            <th class="num">Divergence services</th>
            <th>Top Defender plan</th>
            <th class="num">Top workload change</th>
            <th class="num">Top Defender change</th>
            <th class="num">Largest trend difference</th>
            <th>Recommended action</th>
            <th>Conversation angle</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((r, index) => {
            const top = r.topStory || {};
            return `
              <tr class="clickable" data-divergence-customer="${escapeHtml(r.customer)}" tabindex="0" aria-label="Open divergence story details for ${escapeHtml(r.customer)}">
                <td><strong>${escapeHtml(r.customer)}</strong></td>
                <td>${divergenceSeverityTag(r.severity)}</td>
                <td class="num">${fmt.money2(r.accountAcr || 0)}</td>
                <td class="num">${r.storyCount.toLocaleString('en-US')} ${r.storyCount === 1 ? 'service' : 'services'}</td>
                <td>${escapeHtml(top.plan || '')}<br><span style="font-size:12px;color:#605e5c;">${escapeHtml(top.storyType || '')}</span></td>
                <td class="num"><strong>${fmt.pct(top.workloadChange)}</strong><br><span style="font-size:12px;color:#605e5c;">${fmt.money2(top.workloadDelta || 0)}</span></td>
                <td class="num"><strong>${fmt.pct(top.defenderChange)}</strong><br><span style="font-size:12px;color:#605e5c;">${fmt.money2(top.defenderDelta || 0)}</span></td>
                <td class="num" style="${spreadHeat(r.maxSpread)}">${fmt.pct(r.maxSpread)}</td>
                <td>${escapeHtml(top.recommendedAction || '')}<br><span style="font-size:12px;color:#605e5c;">${escapeHtml(top.confidence || 'unknown')} confidence</span></td>
                <td>${escapeHtml(top.headline || '')}${top.workloadCategories ? `<br><span style="font-size:12px;color:#605e5c;">Workload: ${escapeHtml(top.workloadCategories)}</span>` : ''}</td>
              </tr>`;
          }).join('')}
        </tbody>
      </table>
    </div>`;
  document.querySelectorAll('#divergence-table tr[data-divergence-customer]').forEach(tr => {
    const open = () => {
      _divLastFocus = tr;
      openDivergenceCustomerModal(tr.getAttribute('data-divergence-customer'));
    };
    tr.addEventListener('click', e => {
      if (e.target.closest && e.target.closest('.div-severity-badge')) return;
      open();
    });
    tr.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        open();
      }
    });
  });
  setDivergenceStatus(`${rows.length.toLocaleString('en-US')} of ${allCustomerRows.length.toLocaleString('en-US')} customers visible`);
}

function divergenceStoriesText() {
  return visibleDivergenceCustomerRows().map((r, index) => {
    const top = r.topStory || {};
    return `${index + 1}. ${r.customer} | ${r.severity} | ${r.storyCount} divergence service(s) | Top: ${top.plan || ''} | ${top.headline || ''} | Workload ${fmt.pct(top.workloadChange)} vs Defender ${fmt.pct(top.defenderChange)} | Trend difference ${fmt.pct(r.maxSpread)} | ${top.recommendedAction || ''}`;
  }
  ).join('\n');
}

function customerDivergenceStories(name) {
  const target = _storyCustomerKey(name);
  if (!target) return [];
  const sa = DATA.service_attach || {};
  const dossiers = Array.isArray(sa.dossiers) ? sa.dossiers : [];
  const dossier = dossiers.find(d => _storyCustomerKey(d.customer) === target);
  if (dossier) {
    const direct = Array.isArray(dossier.divergenceStories) ? dossier.divergenceStories :
      (Array.isArray(dossier.divergence_stories) ? dossier.divergence_stories : []);
    return sortDivergenceStoryList(direct.map(s => ({customer: dossier.customer, ...s})));
  }
  return sortDivergenceStoryList(divergenceStories().filter(s =>
    _storyCustomerKey(storyValue(s, 'customer', 'customer', '')) === target));
}

function _storyTypeLabel(story) {
  const raw = String(storyValue(story, 'storyType', 'story_type', '') || 'Divergence');
  return raw.replace(/[_-]+/g, ' ').replace(/\b\w/g, ch => ch.toUpperCase());
}

function _storyEvidenceList(story) {
  const evidence = storyValue(story, 'evidenceBullets', 'evidence_bullets', []);
  if (Array.isArray(evidence)) return evidence.filter(Boolean).slice(0, 4);
  return String(evidence || '').split(/\s*[;|]\s*/).filter(Boolean).slice(0, 4);
}

function openDivergenceCustomerModal(name) {
  const customer = String(name || '');
  const rows = sortDivergenceRows(customerDivergenceStories(customer).map(storyToDivergenceRow));
  if (!rows.length) return;
  const severity = rows[0].severity || 'Low';
  const maxSpread = Math.max(...rows.map(r => Number(r.spread) || 0), 0);
  const totalGap = rows.reduce((sum, r) => sum + (Number(r.gapDollars) || 0), 0);
  const top = rows[0];
  const overlay = ensureDivergenceModal();
  const comparisonHtml = rows.map((r, index) => {
    const sevClass = String(r.severity).toLowerCase() === 'high' ? 'high' : (String(r.severity).toLowerCase() === 'medium' ? 'medium' : 'low');
    const evidence = r.evidence ? `<div style="margin-top:10px;font-size:12px;color:#323130;"><strong>Evidence:</strong> ${escapeHtml(r.evidence)}</div>` : '';
    return `
      <details class="div-comparison" ${index === 0 ? 'open' : ''} data-divergence-story-card>
        <summary>
          <div class="div-comp-grid">
            <div>
              <div class="div-comp-label">Defender service + Azure workload</div>
              <div class="div-comp-main">${escapeHtml(r.plan)}</div>
              <div style="font-size:12px;color:#605e5c;margin-top:3px;">${escapeHtml(r.workloadCategories || 'Mapped Azure workload')}</div>
            </div>
            <div class="num"><div class="div-comp-label">Severity</div>${divergenceSeverityTag(r.severity)}</div>
            <div class="num"><div class="div-comp-label">Workload trend</div><strong>${fmt.pct(r.workloadChange)}</strong><br><span style="font-size:12px;color:#605e5c;">${fmt.money2(r.workloadDelta || 0)}</span></div>
            <div class="num"><div class="div-comp-label">Defender trend</div><strong>${fmt.pct(r.defenderChange)}</strong><br><span style="font-size:12px;color:#605e5c;">${fmt.money2(r.defenderDelta || 0)}</span></div>
            <div class="num"><div class="div-comp-label">Trend difference</div><strong>${fmt.pct(r.spread)}</strong><br><span style="font-size:12px;color:#605e5c;">workload minus Defender</span></div>
            <div>
              <div class="div-comp-label">Recommended action</div>
              <div class="div-comp-main">${escapeHtml(r.recommendedAction)}</div>
              <div style="font-size:12px;color:#605e5c;margin-top:3px;">${escapeHtml(r.storyType)} · ${escapeHtml(r.confidence || 'unknown')} confidence</div>
            </div>
          </div>
        </summary>
        <div class="div-comp-detail" style="border-left:4px solid ${sevClass === 'high' ? '#d13438' : sevClass === 'medium' ? '#ff8c00' : '#107c10'};">
          ${_storyEvidencePanel(r.rawStory)}
          ${evidence}
          <div class="note" style="margin:10px 0 0;border-left-color:#0078d4;background:#f0f6fc;color:#243a5e;">
            <strong>Pricing context:</strong> ${escapeHtml(r.pricingDriver || 'Pricing varies by plan')}. ${escapeHtml(r.caveat || 'Treat as directional until validated.')}
          </div>
        </div>
      </details>`;
  }).join('');
  document.getElementById('div-modal-body').innerHTML = `
    <h2 id="div-modal-title">${escapeHtml(customer)} coverage drift signals</h2>
    <div class="div-sub">Per Defender service comparison against the corresponding Azure workload. Highest-opportunity divergences are listed first.</div>
    <div class="div-kpis">
      <div class="div-kpi"><div class="big">${divergenceSeverityTag(severity)}</div><div class="lbl">Highest divergence severity</div></div>
      <div class="div-kpi"><div class="big">${rows.length.toLocaleString('en-US')}</div><div class="lbl">Defender services to review</div></div>
      <div class="div-kpi"><div class="big">${fmt.pct(maxSpread)}</div><div class="lbl">Largest workload-vs-Defender trend difference</div></div>
      <div class="div-kpi"><div class="big">${fmt.money2(totalGap)}</div><div class="lbl">Quantified gap where available</div></div>
    </div>
    <div class="note" style="margin-bottom:12px;border-left-color:#0078d4;background:#f0f6fc;color:#243a5e;">
      <strong>Top story:</strong> ${escapeHtml(top.headline || '')}
    </div>
    ${comparisonHtml}`;
  overlay.removeAttribute('hidden');
  const closeBtn = overlay.querySelector('.div-close');
  if (closeBtn) closeBtn.focus();
}

function _storyTrendLine(story) {
  const workloadChange = storyValue(story, 'workloadPctChange', 'workload_pct_change', null);
  const defenderChange = storyValue(story, 'defenderPctChange', 'defender_pct_change', null);
  const workloadDelta = storyValue(story, 'workloadDelta', 'workload_delta', null);
  const defenderDelta = storyValue(story, 'defenderDelta', 'defender_delta', null);
  let line = 'Workload ' + fmt.pct(workloadChange) + ' (' + fmt.money2(workloadDelta || 0) + ') vs Defender ' +
    fmt.pct(defenderChange) + ' (' + fmt.money2(defenderDelta || 0) + ')';
  const spread = storyValue(story, 'momentumSpread', 'momentum_spread', null);
  if (spread !== null && spread !== undefined && !isNaN(spread)) line += ' · spread ' + fmt.pct(spread);
  return line;
}

function _storyMomentumLine(story) {
  const workloadCats = storyValue(story, 'workloadSl2Categories', 'workload_sl2_categories', []);
  const cats = Array.isArray(workloadCats) ? workloadCats.filter(Boolean).join(', ') : String(workloadCats || '');
  const latestWorkload = storyValue(story, 'latestWorkloadAcr', 'latest_workload_acr', null);
  const latestDefender = storyValue(story, 'latestDefenderAcr', 'latest_defender_acr', null);
  const parts = [];
  if (cats) parts.push('Workload: ' + cats);
  if (latestWorkload !== null || latestDefender !== null) {
    parts.push('Latest ACR: workload ' + fmt.money2(latestWorkload || 0) + ' vs Defender ' + fmt.money2(latestDefender || 0));
  }
  return parts.join(' · ');
}

function customerSalesStoriesText(name) {
  return customerDivergenceStories(name).slice(0, 3).map((s, index) => {
    const plan = storyValue(s, 'planLabel', 'plan_label', 'Unmapped plan');
    const severity = storyValue(s, 'severity', 'severity', 'Low');
    const headline = storyValue(s, 'headline', 'headline', '');
    const action = storyValue(s, 'recommendedAction', 'recommended_action', '');
    const pricing = storyValue(s, 'pricingDriver', 'pricing_driver', 'Pricing varies by plan');
    const caveat = storyValue(s, 'caveatText', 'caveat_text', 'Treat as directional until validated.');
    const evidence = _storyEvidenceList(s).join('; ');
    return `${index + 1}. ${headline} | ${_storyTypeLabel(s)} / ${severity} | ${plan} | ${_storyTrendLine(s)} | Evidence: ${evidence} | Pricing: ${pricing}. ${caveat} | Action: ${action}`;
  }).join('\n');
}

function setCustomerStoriesStatus(idp, message) {
  const status = document.getElementById((idp || '') + 'cust-sales-stories-status');
  if (status) status.textContent = message;
}

function copyCustomerSalesStories(idp, name) {
  const text = customerSalesStoriesText(name);
  if (!text) { setCustomerStoriesStatus(idp, 'Nothing to copy'); return; }
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).then(
      () => setCustomerStoriesStatus(idp, 'Copied'),
      () => setCustomerStoriesStatus(idp, 'Copy failed')
    );
    return;
  }
  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.style.position = 'fixed';
  textarea.style.left = '-9999px';
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand('copy');
  document.body.removeChild(textarea);
  setCustomerStoriesStatus(idp, copied ? 'Copied' : 'Copy failed');
}

function ensureCustomerSalesStoriesCopy() {
  if (window.__customerSalesStoriesCopyWired) return;
  window.__customerSalesStoriesCopyWired = true;
  document.addEventListener('click', function (event) {
    const btn = event.target.closest('[data-customer-stories-copy]');
    if (!btn) return;
    const wrap = btn.closest('[data-customer-stories-name]');
    copyCustomerSalesStories(btn.getAttribute('data-customer-stories-prefix') || '', wrap ? wrap.getAttribute('data-customer-stories-name') : '');
  });
}

function renderCustomerSalesStories(idp, name) {
  idp = idp || '';
  const host = document.getElementById(idp + 'cust-sales-stories');
  if (!host) return;
  const sa = (typeof DATA !== 'undefined' && DATA) ? DATA.service_attach : null;
  if (!sa || !Array.isArray(sa.dossiers)) {
    host.innerHTML = '';
    host.style.display = 'none';
    return;
  }
  ensureCustomerSalesStoriesCopy();
  const stories = customerDivergenceStories(name).slice(0, 3);
  host.style.display = '';
  if (!stories.length) {
    host.innerHTML =
      '<div class="note" style="margin-top:14px;border-left-color:#c8c6c4;background:#faf9f8;color:#605e5c;font-size:12px;">' +
      'No sales stories detected for this customer yet.</div>';
    return;
  }
  const cards = stories.map(function (s) {
    const severity = storyValue(s, 'severity', 'severity', 'Low');
    const sevClass = String(severity).toLowerCase() === 'high' ? 'high' : (String(severity).toLowerCase() === 'medium' ? 'medium' : 'low');
    const plan = storyValue(s, 'planLabel', 'plan_label', 'Unmapped plan');
    const headline = storyValue(s, 'headline', 'headline', 'Divergence story');
    const action = storyValue(s, 'recommendedAction', 'recommended_action', 'Validate Defender attach motion.');
    const pricing = storyValue(s, 'pricingDriver', 'pricing_driver', 'Pricing driver varies by plan');
    const caveat = storyValue(s, 'caveatText', 'caveat_text', 'Treat as directional until validated.');
    const momentum = _storyMomentumLine(s);
    const evidence = _storyEvidenceList(s);
    const evidenceHtml = evidence.length
      ? '<ul style="margin:8px 0 0 18px;padding:0;color:#323130;line-height:1.45;">' + evidence.map(item => '<li>' + escapeHtml(item) + '</li>').join('') + '</ul>'
      : '<div style="font-size:12px;color:#605e5c;margin-top:8px;">No detailed evidence bullets available.</div>';
    return '<details data-customer-divergence-card style="border:1px solid #edebe9;border-left:4px solid ' + (sevClass === 'high' ? '#d13438' : sevClass === 'medium' ? '#ff8c00' : '#107c10') +
      ';border-radius:8px;background:#fff;padding:0;">' +
        '<summary style="list-style:none;cursor:pointer;padding:12px 14px;">' +
        '<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start;flex-wrap:wrap;">' +
          '<div style="min-width:220px;flex:1 1 320px;">' +
            '<div style="font-weight:700;color:#201f1e;">' + escapeHtml(headline) + '</div>' +
            '<div style="font-size:12px;color:#605e5c;margin-top:3px;">' + escapeHtml(plan) + '</div>' +
          '</div>' +
          '<div style="display:flex;gap:6px;flex-wrap:wrap;">' +
            '<span class="tag ' + sevClass + '">' + escapeHtml(_storyTypeLabel(s)) + '</span>' +
            '<span class="tag ' + sevClass + '">' + escapeHtml(severity) + '</span>' +
          '</div>' +
        '</div>' +
        '<div style="margin-top:10px;font-size:12px;color:#323130;"><strong>Trend:</strong> ' + escapeHtml(_storyTrendLine(s)) + '</div>' +
        (momentum ? '<div style="margin-top:4px;font-size:12px;color:#605e5c;">' + escapeHtml(momentum) + '</div>' : '') +
        '<div style="font-size:12px;color:#605e5c;margin-top:8px;">Open to compare workload trend and mapped Defender trend side-by-side.</div>' +
        '</summary>' +
        '<div style="border-top:1px solid #edebe9;padding:0 14px 12px;">' +
        _storyEvidencePanel(s) +
        evidenceHtml +
        '<div style="margin-top:10px;font-size:12px;color:#605e5c;"><strong>Pricing:</strong> ' + escapeHtml(pricing) + '. ' + escapeHtml(caveat) + '</div>' +
        '<div class="note" style="margin:10px 0 0;border-left-color:#0078d4;background:#f0f6fc;color:#243a5e;font-size:12px;">' +
          '<strong>Recommended action:</strong> ' + escapeHtml(action) + '</div>' +
        '</div>' +
      '</details>';
  }).join('');
  host.innerHTML =
    '<div class="chart-box" style="margin-top:18px;" data-customer-stories-name="' + escapeHtml(name) + '">' +
      '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">' +
        '<div><div class="title">Sales Stories</div>' +
        '<div class="sub">Top Defender attach divergence narratives for this customer.</div></div>' +
        '<div style="display:flex;align-items:center;gap:8px;">' +
          '<button class="import-btn" type="button" data-customer-stories-copy="1" data-customer-stories-prefix="' + escapeHtml(idp) + '">Copy</button>' +
          '<span id="' + escapeHtml(idp) + 'cust-sales-stories-status" style="font-size:12px;color:#605e5c;"></span>' +
        '</div>' +
      '</div>' +
      '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px;margin-top:10px;">' + cards + '</div>' +
    '</div>';
}

function copyDivergenceStories() {
  const text = divergenceStoriesText();
  if (!text) { setDivergenceStatus('Nothing to copy'); return; }
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).then(
      () => setDivergenceStatus('Copied'),
      () => setDivergenceStatus('Copy failed')
    );
    return;
  }
  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.style.position = 'fixed';
  textarea.style.left = '-9999px';
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand('copy');
  document.body.removeChild(textarea);
  setDivergenceStatus(copied ? 'Copied' : 'Copy failed');
}

function downloadDivergenceStoriesCsv() {
  const rows = visibleDivergenceCustomerRows();
  if (!rows.length) { setDivergenceStatus('Nothing to download'); return; }
  const headers = ['Customer', 'Severity', 'Account ACR/mo', 'Divergence services', 'Top Defender plan', 'Top workload change', 'Top Defender change', 'Largest trend difference', 'Top recommended action', 'Top conversation angle'];
  const lines = [
    headers.map(csvCell).join(','),
    ...rows.map(r => {
      const top = r.topStory || {};
      return [
        r.customer,
        r.severity,
        r.accountAcr,
        r.storyCount,
        top.plan || '',
        top.workloadChange,
        top.defenderChange,
        r.maxSpread,
        top.recommendedAction || '',
        top.headline || '',
      ].map(csvCell).join(',');
    })
  ];
  const blob = new Blob([lines.join('\r\n')], {type: 'text/csv;charset=utf-8'});
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'defender-divergence-stories.csv';
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
  setDivergenceStatus('CSV downloaded');
}

function hasServiceAttachData() {
  return !!(DATA.service_attach && Array.isArray(DATA.service_attach.dossiers) && DATA.service_attach.dossiers.length);
}

let __slDossierMap = null;
function slDossierMap() {
  if (__slDossierMap) return __slDossierMap;
  const m = new Map();
  const dossiers = (DATA.service_attach && DATA.service_attach.dossiers) || [];
  dossiers.forEach(d => {
    if (!d || !d.customer) return;
    m.set(d.customer, d);
    const norm = '~' + String(d.customer).trim().toLowerCase();
    if (!m.has(norm)) m.set(norm, d);
  });
  __slDossierMap = m;
  return m;
}

const SL_RANK_LABEL = {0: 'High', 1: 'Medium', 2: 'Low'};

function slAttach(customer) {
  if (!hasServiceAttachData()) return null;
  const m = slDossierMap();
  let d = m.get(customer);
  if (!d && customer != null) d = m.get('~' + String(customer).trim().toLowerCase());
  if (!d) return null;
  const opps = Array.isArray(d.opportunities) ? d.opportunities : [];
  const dollarOpps = opps.filter(o => (o.gapDollars || 0) > 0);
  let topGapOpp = null;
  if (dollarOpps.length) {
    topGapOpp = dollarOpps.slice().sort((a, b) =>
      (b.gapDollars || 0) - (a.gapDollars || 0) ||
      ((a.priorityRank == null ? 9 : a.priorityRank) - (b.priorityRank == null ? 9 : b.priorityRank)))[0];
  } else if (opps.length) {
    topGapOpp = opps.slice().sort((a, b) =>
      ((a.priorityRank == null ? 9 : a.priorityRank) - (b.priorityRank == null ? 9 : b.priorityRank)))[0];
  }
  let priorityRank = 9;
  opps.forEach(o => {
    const r = (o.priorityRank == null ? 9 : o.priorityRank);
    if (r < priorityRank) priorityRank = r;
  });
  const gapMonthly = d.totalGapDollars || 0;
  return {
    dossier: d,
    gapMonthly,
    gapAnnual: gapMonthly * 12,
    topGapOpp,
    topServiceLabel: topGapOpp ? topGapOpp.planLabel : null,
    topServiceGap: topGapOpp ? (topGapOpp.gapDollars || 0) : 0,
    topServiceOpener: topGapOpp ? topGapOpp.opener : null,
    signal: topGapOpp ? topGapOpp.signal : null,
    gapServiceCount: dollarOpps.length,
    priority: SL_RANK_LABEL[priorityRank] || 'Low',
    priorityRank: priorityRank === 9 ? 3 : priorityRank,
    uncoveredEligibleCount: d.uncoveredEligibleCount || 0,
    hasGap: (gapMonthly > 0) || ((d.uncoveredEligibleCount || 0) > 0)
  };
}

function rowPriorityTag(row) {
  const sl = slAttach(row.customer);
  return sl ? sl.priority : row.opportunity;
}

function filteredOpportunityRows() {
  const filter = document.getElementById('quadrant-filter').value;
  const slMode = hasServiceAttachData();
  let rows;
  if (slMode) {
    rows = DATA.opportunity.filter(r => {
      const sl = slAttach(r.customer);
      return sl ? sl.hasGap : r.opportunity !== 'Too small';
    });
  } else {
    rows = DATA.opportunity.filter(r => r.opportunity !== 'Too small');
  }
  if (filter === 'High') rows = rows.filter(r => rowPriorityTag(r) === 'High');
  else if (filter === 'Medium') rows = rows.filter(r => rowPriorityTag(r) === 'Medium');
  else if (filter === 'HighMed') rows = rows.filter(r => rowPriorityTag(r) === 'High' || rowPriorityTag(r) === 'Medium');
  return rows;
}

function actionDetails(row) {
  const sl = slAttach(row.customer);
  if (sl) {
    const planLabel = sl.topServiceLabel || 'eligible Defender plans';
    let recommendedAction;
    let conversationAngle;
    let actionReason;
    if (sl.topServiceGap > 0) {
      recommendedAction = `Pitch ${planLabel}`;
      conversationAngle = sl.topServiceOpener || `${row.customer} is buying workloads protected by ${planLabel} but isn't attaching it — roughly a ${fmt.money2(sl.topServiceGap)}/mo gap.`;
      actionReason = `Largest per-service attach gap: ${planLabel} at ${fmt.money2(sl.topServiceGap)}/mo.`;
    } else if (sl.uncoveredEligibleCount > 0) {
      recommendedAction = `Enable ${planLabel}`;
      conversationAngle = sl.topServiceOpener || `${row.customer} runs eligible workloads with no matching Defender plan turned on.`;
      actionReason = `${sl.uncoveredEligibleCount} eligible workload${sl.uncoveredEligibleCount === 1 ? '' : 's'} with no Defender coverage.`;
    } else {
      recommendedAction = 'Maintain Defender coverage';
      conversationAngle = `Defender attach is on track across ${row.customer}'s eligible workloads.`;
      actionReason = 'No measurable per-service attach gap.';
    }
    return {
      belowThreshold: sl.hasGap,
      estimatedGap: sl.gapMonthly,
      estimatedAnnualOpportunity: sl.gapAnnual,
      recommendedAction,
      conversationAngle,
      actionReason,
      perServicePriority: sl.priority,
      priorityRank: sl.priorityRank,
      topServiceLabel: sl.topServiceLabel,
      topServiceGap: sl.topServiceGap,
      gapServiceCount: sl.gapServiceCount,
      signal: sl.signal,
      hasGap: sl.hasGap,
      sl: true
    };
  }
  const belowThreshold = (row.dfc_ratio || 0) < dfcShareThreshold;
  const estimatedGap = Math.max(0, (row.total_monthly_current || row.total_current || 0) * (dfcShareThreshold / 100) - (row.dfc_monthly_current || row.dfc_current || 0));
  const estimatedAnnualOpportunity = estimatedGap * 12;
  const products = DATA.customer_data?.[row.customer]?.products || [];
  const workload = (products.find(p => p.product !== 'Defender for Cloud' && (p.current || 0) > 0) || {}).product || 'core Azure workloads';
  let recommendedAction = 'Monitor Defender attach';
  let conversationAngle = `Confirm Defender for Cloud coverage keeps pace with ${workload}.`;
  let actionReason = row.notes && row.notes !== '-' ? row.notes : 'No urgent attach gap under the selected threshold.';
  if ((row.dfc_monthly_current || row.dfc_current || 0) < 30 && (row.total_monthly_current || row.total_current || 0) > 3000) {
    recommendedAction = 'Start DfC attach discovery';
    conversationAngle = `Open with current ${workload} usage and validate whether Defender for Cloud is enabled.`;
    actionReason = 'Little or no Defender for Cloud ACR against a meaningful Azure footprint.';
  } else if (belowThreshold && (row.growth_gap || 0) > 0) {
    recommendedAction = 'Prioritize attach expansion';
    conversationAngle = `Lead with ${workload} growth and the Defender share gap to the selected threshold.`;
    actionReason = 'Azure footprint is growing faster than Defender for Cloud attach.';
  } else if (belowThreshold) {
    recommendedAction = 'Expand Defender coverage';
    conversationAngle = `Review Defender for Cloud coverage across ${workload} and adjacent services.`;
    actionReason = 'Defender for Cloud share is below the selected threshold.';
  } else if ((row.dfc_3m_delta || 0) < 0) {
    recommendedAction = 'Review DfC decline';
    conversationAngle = 'Validate whether Defender usage declined because of optimization, churn, or reporting timing.';
    actionReason = 'Defender for Cloud ACR is declining over the 3-month window.';
  }
  const legacyRank = ({High: 0, Medium: 1, Low: 2, 'Too small': 3})[row.opportunity];
  return {
    belowThreshold,
    estimatedGap,
    estimatedAnnualOpportunity,
    recommendedAction,
    conversationAngle,
    actionReason,
    perServicePriority: row.opportunity,
    priorityRank: legacyRank == null ? 3 : legacyRank,
    topServiceLabel: null,
    topServiceGap: 0,
    gapServiceCount: belowThreshold ? 1 : 0,
    signal: null,
    hasGap: belowThreshold,
    sl: false
  };
}

function actionQueueRows() {
  const term = (document.getElementById('action-queue-search')?.value || '').trim().toLowerCase();
  return filteredOpportunityRows()
    .map(row => ({...row, ...actionDetails(row)}))
    .filter(row => {
      if (!term) return true;
      return [
        row.customer,
        row.perServicePriority,
        row.topServiceLabel,
        row.recommendedAction,
        row.actionReason,
        row.conversationAngle,
      ].some(value => String(value ?? '').toLowerCase().includes(term));
    })
    .sort((a, b) =>
      Number(b.hasGap) - Number(a.hasGap) ||
      (a.priorityRank - b.priorityRank) ||
      (b.estimatedGap || 0) - (a.estimatedGap || 0) ||
      (b.growth_gap || 0) - (a.growth_gap || 0) ||
      (b.total_monthly_current || b.total_current || 0) - (a.total_monthly_current || a.total_current || 0));
}

function visibleActionQueueRows() {
  const rows = actionQueueRows();
  const limit = document.getElementById('action-queue-limit')?.value || '10';
  return limit === 'all' ? rows : rows.slice(0, parseInt(limit, 10));
}

function updateActionQueueMetrics() {
  const rows = actionQueueRows();
  const slMode = hasServiceAttachData();
  const monthlyGap = rows.reduce((sum, r) => sum + (r.estimatedGap || 0), 0);
  const annualOpportunity = rows.reduce((sum, r) => sum + (r.estimatedAnnualOpportunity || 0), 0);
  const accountsWithGap = rows.filter(r => r.hasGap).length;
  const thresholdLabel = fmtThreshold(dfcShareThreshold);
  const annualEl = document.getElementById('action-annual-opportunity');
  const annualNoteEl = document.getElementById('action-annual-opportunity-note');
  const monthlyEl = document.getElementById('action-monthly-gap');
  const monthlyNoteEl = document.getElementById('action-monthly-gap-note');
  const belowEl = document.getElementById('action-below-threshold');
  const belowNoteEl = document.getElementById('action-below-threshold-note');
  if (annualEl) annualEl.textContent = fmt.money2(annualOpportunity);
  if (annualNoteEl) annualNoteEl.textContent = slMode ? 'per-service attach gap, annualized' : `annualized run-rate gap to ${thresholdLabel}`;
  if (monthlyEl) monthlyEl.textContent = fmt.money2(monthlyGap);
  if (monthlyNoteEl) monthlyNoteEl.textContent = slMode ? 'per-service attach gap, latest month' : `monthly gap to ${thresholdLabel}`;
  if (belowEl) belowEl.textContent = accountsWithGap.toLocaleString('en-US');
  if (belowNoteEl) belowNoteEl.textContent = slMode ? 'accounts with a per-service gap' : `below selected ${thresholdLabel} threshold`;
}

function actionQueueText() {
  const slMode = hasServiceAttachData();
  return visibleActionQueueRows().map((r, index) => {
    const topService = r.topServiceLabel ? `${r.topServiceLabel}${r.topServiceGap > 0 ? ` (${fmt.money2(r.topServiceGap)}/mo)` : ''}` : 'n/a';
    const coverageCol = slMode ? `Gap services ${r.gapServiceCount || 0}` : `DfC ${fmt.pctRaw(r.dfc_ratio)}`;
    return `${index + 1}. ${r.customer} | ${r.perServicePriority} | Account ACR/mo ${fmt.money2(r.total_monthly_current || r.total_current)} | ${coverageCol} | Top gap service: ${topService} | Attach gap/mo ${fmt.money2(r.estimatedGap)} | Annualized attach opportunity ${fmt.money2(r.estimatedAnnualOpportunity)} | ${r.recommendedAction} - ${r.conversationAngle}`;
  }).join('\n');
}

function setActionQueueStatus(message) {
  const status = document.getElementById('action-queue-status');
  if (status) status.textContent = message;
}

function copyActionQueue() {
  const text = actionQueueText();
  if (!text) {
    setActionQueueStatus('Nothing to copy');
    return;
  }
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).then(
      () => setActionQueueStatus('Copied'),
      () => setActionQueueStatus('Copy failed')
    );
    return;
  }
  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.style.position = 'fixed';
  textarea.style.left = '-9999px';
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand('copy');
  document.body.removeChild(textarea);
  setActionQueueStatus(copied ? 'Copied' : 'Copy failed');
}

function csvCell(value) {
  return `"${String(value ?? '').replace(/"/g, '""')}"`;
}

function downloadActionQueueCsv() {
  const thresholdLabel = fmtThreshold(dfcShareThreshold);
  const rows = visibleActionQueueRows();
  if (!rows.length) {
    setActionQueueStatus('Nothing to download');
    return;
  }
  const slMode = hasServiceAttachData();
  const headers = ['Customer', 'Priority', 'Account ACR/mo', slMode ? 'Gap services' : 'Defender %', 'Top gap service', 'Top gap service $/mo', 'Attach gap / mo', 'Annualized attach opportunity', 'Recommended action', 'Conversation angle', 'Reason'];
  const lines = [
    headers.map(csvCell).join(','),
    ...rows.map(r => [
      r.customer,
      r.perServicePriority,
      r.total_monthly_current || r.total_current,
      slMode ? (r.gapServiceCount || 0) : r.dfc_ratio,
      r.topServiceLabel || '',
      r.topServiceGap || 0,
      r.estimatedGap,
      r.estimatedAnnualOpportunity,
      r.recommendedAction,
      r.conversationAngle,
      r.actionReason
    ].map(csvCell).join(','))
  ];
  const blob = new Blob([lines.join('\r\n')], {type: 'text/csv;charset=utf-8'});
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `defender-action-queue-${thresholdLabel.replace('%', 'pct')}.csv`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
  setActionQueueStatus('CSV downloaded');
}

function quadrantChart(containerId, allPoints) {
  const W = 900, H = 460;
  const M = {top: 30, right: 30, bottom: 54, left: 78};
  const innerW = W - M.left - M.right, innerH = H - M.top - M.bottom;
  const points = allPoints.filter(p => p.x != null && p.y != null && !isNaN(p.x) && !isNaN(p.y));
  const positiveGaps = points.map(p => Math.max(0, p.x || 0));
  const xMaxRaw = Math.max(...positiveGaps, 1);
  const xMax = Math.max(1000, Math.ceil(xMaxRaw / 1000) * 1000);
  const yMax = 20;
  const xMin = 0, yMin = 0;
  const xScale = v => M.left + ((Math.max(xMin, Math.min(xMax, v)) - xMin) / (xMax - xMin)) * innerW;
  const yScale = v => M.top + innerH - ((Math.max(yMin, Math.min(yMax, v)) - yMin) / (yMax - yMin)) * innerH;
  const sizes = points.map(p => p.size || 1);
  const sMax = Math.max(...sizes, 1);
  const sScale = s => 5 + Math.sqrt(s / sMax) * 24;
  let svg = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">`;
  const lowShareY = yScale(2);
  const medShareY = yScale(5);
  svg += `<rect x="${M.left}" y="${medShareY}" width="${innerW}" height="${H - M.bottom - medShareY}" fill="#fde7e9" opacity="0.45"/>`;
  svg += `<rect x="${M.left}" y="${lowShareY}" width="${innerW}" height="${medShareY - lowShareY}" fill="#fff4ce" opacity="0.48"/>`;
  svg += `<rect x="${M.left}" y="${M.top}" width="${innerW}" height="${lowShareY - M.top}" fill="#dff6dd" opacity="0.42"/>`;
  const xTicks = [0, xMax * 0.25, xMax * 0.5, xMax * 0.75, xMax];
  const yTicks = [0, 2, 5, 10, 15, 20];
  xTicks.forEach(xv => {
    svg += `<line x1="${xScale(xv)}" y1="${M.top}" x2="${xScale(xv)}" y2="${H - M.bottom}" stroke="#edebe9"/>`;
    svg += `<text x="${xScale(xv)}" y="${H - M.bottom + 16}" text-anchor="middle" font-size="10" fill="#605e5c">$${Math.round(xv).toLocaleString('en-US')}</text>`;
  });
  yTicks.forEach(yv => {
    svg += `<line x1="${M.left}" y1="${yScale(yv)}" x2="${W - M.right}" y2="${yScale(yv)}" stroke="#edebe9"/>`;
    svg += `<text x="${M.left - 8}" y="${yScale(yv) + 3}" text-anchor="end" font-size="10" fill="#605e5c">${yv}%</text>`;
  });
  svg += `<line x1="${M.left}" y1="${yScale(2)}" x2="${W - M.right}" y2="${yScale(2)}" stroke="#a19f9d" stroke-dasharray="4 3"/>`;
  svg += `<line x1="${M.left}" y1="${yScale(5)}" x2="${W - M.right}" y2="${yScale(5)}" stroke="#a19f9d" stroke-dasharray="4 3"/>`;
  svg += `<text x="${M.left + innerW/2}" y="${H - 8}" text-anchor="middle" font-size="11" fill="#323130" font-weight="600">3-month monthly ACR growth gap: Other Azure minus DfC</text>`;
  svg += `<text x="18" y="${M.top + innerH/2}" text-anchor="middle" font-size="11" fill="#323130" font-weight="600" transform="rotate(-90 18 ${M.top + innerH/2})">DfC share of total ACR</text>`;
  svg += `<text x="${W - M.right - 8}" y="${H - M.bottom - 8}" text-anchor="end" font-size="11" fill="#a4262c" font-weight="700">HIGH OPPORTUNITY: low DfC share + large growth gap</text>`;
  svg += `<text x="${W - M.right - 8}" y="${M.top + 14}" text-anchor="end" font-size="11" fill="#107c10" font-weight="700">Healthier DfC penetration</text>`;
  const colorMap = {High: '#d13438', Medium: '#ff8c00', Low: '#107c10', 'Too small': '#a19f9d'};
  const opacityMap = {High: 0.82, Medium: 0.72, Low: 0.28, 'Too small': 0.20};
  const oppRank = {High: 3, Medium: 2, Low: 1, 'Too small': 0};
  const orderedPoints = points.slice().sort((a, b) => (oppRank[a.opportunity] || 0) - (oppRank[b.opportunity] || 0));
  const labelCandidates = orderedPoints
    .filter(p => (p.opportunity === 'High' || p.opportunity === 'Medium') && p.x > 0)
    .sort((a, b) => (b.label_score || 0) - (a.label_score || 0))
    .slice(0, 8);
  const labeledSet = new Set(labelCandidates.map(p => p.label));
  const drawnLabels = [];
  orderedPoints.forEach(p => {
    const isClippedX = p.x > xMax;
    const isClippedY = p.y > yMax;
    const cx = xScale(p.x), cy = yScale(p.y);
    const r = sScale(p.size || 1);
    const fill = colorMap[p.opportunity] || '#0078d4';
    const op = opacityMap[p.opportunity] != null ? opacityMap[p.opportunity] : 0.65;
    const stroke = (isClippedX || isClippedY) ? '#201f1e' : 'white';
    const strokeWidth = (isClippedX || isClippedY) ? 2 : 1.5;
    svg += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${fill}" opacity="${op}" stroke="${stroke}" stroke-width="${strokeWidth}" data-customer="${p.label.replace(/"/g, '&quot;')}" data-x="${p.x}" data-y="${p.y}" data-size="${p.size}" data-opp="${p.opportunity}" data-other-delta="${p.other_delta}" data-dfc-delta="${p.dfc_delta}" style="cursor:pointer"/>`;
    if (labeledSet.has(p.label)) {
      const truncated = p.label.length > 22 ? p.label.slice(0, 22) + '...' : p.label;
      const anchors = [
        {x: cx + r + 4, y: cy - r - 2, align: 'start'},
        {x: cx + r + 4, y: cy + r + 10, align: 'start'},
        {x: cx - r - 4, y: cy - r - 2, align: 'end'},
      ];
      const labelW = truncated.length * 5.5, labelH = 12;
      let chosen = null;
      for (const a of anchors) {
        const lx = a.align === 'end' ? a.x - labelW : a.x;
        const ly = a.y - labelH;
        const collides = drawnLabels.some(d => lx < d.x + d.w && lx + labelW > d.x && ly < d.y + d.h && ly + labelH > d.y);
        if (!collides && lx >= M.left && lx + labelW <= W - M.right && ly >= M.top && ly + labelH <= H - M.bottom) {
          chosen = a; drawnLabels.push({x: lx, y: ly, w: labelW, h: labelH}); break;
        }
      }
      if (chosen) svg += `<text x="${chosen.x}" y="${chosen.y}" text-anchor="${chosen.align}" font-size="10" fill="#201f1e" font-weight="600" style="paint-order:stroke; stroke:#ffffff; stroke-width:3px; stroke-linejoin:round;">${truncated}</text>`;
    }
  });
  svg += `</svg>`;
  document.getElementById(containerId).innerHTML = svg;
  const footEl = document.getElementById(containerId + '-foot');
  if (footEl) footEl.innerHTML = 'This view uses absolute monthly ACR change, not percentage growth, to avoid misleading spikes from tiny Defender baselines. X = Other Azure 3M $ change minus DfC 3M $ change. Y is capped at 20% for readability.';
  document.querySelectorAll(`#${containerId} circle`).forEach(c => {
    c.addEventListener('mousemove', e => {
      const html = `<b>${c.getAttribute('data-customer')}</b><br/>
        Priority: ${c.getAttribute('data-opp')}<br/>
        DfC share: ${parseFloat(c.getAttribute('data-y')).toFixed(1)}%<br/>
        Growth gap: $${parseFloat(c.getAttribute('data-x')).toLocaleString('en-US',{maximumFractionDigits:0})}<br/>
        Other Azure 3M delta: $${parseFloat(c.getAttribute('data-other-delta')).toLocaleString('en-US',{maximumFractionDigits:0})}<br/>
        DfC 3M delta: $${parseFloat(c.getAttribute('data-dfc-delta')).toLocaleString('en-US',{maximumFractionDigits:0})}<br/>
        Monthly Total ACR: $${parseFloat(c.getAttribute('data-size')).toLocaleString('en-US',{maximumFractionDigits:0})}`;
      showTooltip(html, e.pageX, e.pageY);
    });
    c.addEventListener('mouseleave', hideTooltip);
    c.addEventListener('click', () => selectCustomer(c.getAttribute('data-customer')));
  });
}

function renderQuadrant() {
  const filter = document.getElementById('quadrant-filter').value;
  let pts = DATA.opportunity
    .filter(r => r.opportunity !== 'Too small')
    .filter(r => r.total_current > 0)
    .map(r => {
      const gap = Math.max(0, r.growth_gap || 0);
      const share = r.dfc_ratio || 0;
      const labelScore = gap * (1 + Math.max(0, 5 - Math.min(share, 5))) * Math.sqrt(Math.max(r.total_current || 0, 1));
      return {
        label: r.customer,
        x: gap,
        y: share,
        size: r.total_monthly_current || r.total_current,
        opportunity: r.opportunity,
        other_delta: r.other_3m_delta || 0,
        dfc_delta: r.dfc_3m_delta || 0,
        label_score: labelScore
      };
    });
  if (filter === 'High') pts = pts.filter(p => p.opportunity === 'High');
  else if (filter === 'Medium') pts = pts.filter(p => p.opportunity === 'Medium');
  else if (filter === 'HighMed') pts = pts.filter(p => p.opportunity === 'High' || p.opportunity === 'Medium');
  quadrantChart('chart-quadrant', pts);
}

function renderOpportunityHeatmap() {
  ensureDfcThresholdControl();
  ensureActionQueueShell();
  ensureMergedQueueControls();
  renderDivergenceStories();
  updateActionQueueMetrics();
  const thresholdLabel = fmtThreshold(dfcShareThreshold);
  const slMode = hasServiceAttachData();
  const thresholdWrap = document.getElementById('dfc-threshold-wrap');
  if (thresholdWrap) thresholdWrap.style.display = slMode ? 'none' : 'flex';
  const allRows = filteredOpportunityRows().map(r => ({...r, ...actionDetails(r)}));
  const gapCount = allRows.filter(r => slMode ? r.hasGap : (r.dfc_ratio || 0) < dfcShareThreshold).length;
  const rows = visibleActionQueueRows();
  const maxGap = Math.max(...rows.map(r => Math.max(0, slMode ? (r.estimatedGap || 0) : (r.growth_gap || 0))), 1);
  const maxTotal = Math.max(...rows.map(r => r.total_monthly_current || r.total_current || 0), 1);
  const heat = (value, maxValue, color) => {
    const intensity = Math.max(0.08, Math.min(0.85, (value || 0) / maxValue));
    return `background: color-mix(in srgb, ${color} ${Math.round(intensity * 75)}%, white);`;
  };
  const shareStyle = value => {
    if (value < Math.min(2, dfcShareThreshold)) return 'background:#fde7e9;color:#a4262c;font-weight:700;';
    if (value < dfcShareThreshold) return 'background:#fff4ce;color:#8e562e;font-weight:700;';
    return 'background:#dff6dd;color:#107c10;font-weight:700;';
  };
  const thresholdValueEl = document.getElementById('dfc-threshold-value');
  if (thresholdValueEl) thresholdValueEl.textContent = thresholdLabel;
  const thresholdCountEl = document.getElementById('dfc-threshold-count');
  if (thresholdCountEl) thresholdCountEl.textContent = slMode ? `${gapCount} with attach gaps` : `${gapCount} below threshold`;
  const emptyRow = rows.length ? '' :
    '<tr><td colspan="9" style="padding:24px;text-align:center;color:#605e5c;">No opportunities match the current filters.</td></tr>';
  document.getElementById('chart-quadrant').innerHTML = `
    <div class="scroll-table" style="max-height:620px;">
      <table>
        <thead>
          <tr>
            <th>Customer</th>
            <th>Priority</th>
            <th class="num">${slMode ? 'Account ACR/mo' : 'Monthly Total ACR'}</th>
            <th class="num">${slMode ? 'Gap services' : 'DfC %'}</th>
            <th>Top gap service</th>
            <th class="num">Attach gap / mo</th>
            <th class="num">Annualized attach opp.</th>
            <th>Recommended action</th>
            <th>Conversation angle</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map(r => `
            <tr class="clickable" data-customer="${r.customer.replace(/"/g, '&quot;')}">
              <td><strong>${r.customer}</strong></td>
              <td>${tagFor(r.perServicePriority)}</td>
              <td class="num" style="${slMode ? '' : heat(r.total_monthly_current || r.total_current, maxTotal, '#0078d4')}">${fmt.money2(r.total_monthly_current || r.total_current)}</td>
              <td class="num" style="${slMode ? '' : shareStyle(r.dfc_ratio || 0)}">${slMode ? `${r.gapServiceCount || 0} ${(r.gapServiceCount === 1) ? 'service' : 'services'}` : fmt.pctRaw(r.dfc_ratio)}</td>
              <td>${r.topServiceLabel ? `${escapeHtml(r.topServiceLabel)}${r.topServiceGap > 0 ? ` <span style="font-size:12px;color:#605e5c;">(${fmt.money2(r.topServiceGap)}/mo)</span>` : ''}` : '<span style="color:#a19f9d;">—</span>'}</td>
              <td class="num" style="${heat(Math.max(0, r.estimatedGap || 0), maxGap, '#d13438')}"><strong>${fmt.money2(r.estimatedGap || 0)}</strong></td>
              <td class="num"><strong>${fmt.money2(r.estimatedAnnualOpportunity || 0)}</strong></td>
              <td>${escapeHtml(r.recommendedAction)}<br><span style="font-size:12px;color:#605e5c;">${escapeHtml(r.actionReason)}</span></td>
              <td>${escapeHtml(r.conversationAngle)}</td>
            </tr>
          `).join('')}${emptyRow}
        </tbody>
      </table>
    </div>`;
  document.querySelectorAll('#chart-quadrant tr.clickable').forEach(tr =>
    tr.addEventListener('click', () => selectCustomer(tr.getAttribute('data-customer'))));
  const footEl = document.getElementById('chart-quadrant-foot');
  if (footEl) {
    footEl.innerHTML = slMode
      ? `Ranked by per-service Defender attach gap — the workloads each account buys but doesn't protect with the matching Defender plan. Top gap service shows the single largest monthly gap; gap services counts how many eligible workloads are unprotected; attach gap and annualized opportunity sum every eligible service for that account. Recommended action and conversation angle give the sales play. Account ACR/mo is shown for sizing context only.`
      : `Ranked heatmap. Rows below the selected ${thresholdLabel} Defender share threshold are lifted and highlighted; priority still also considers total ACR, growth gap, and Defender momentum. Default 6% is the corporate Defender attach baseline (every customer should run at least 6% of total ACR on Defender workloads).`;
  }
}

function renderQuadrant() {
  renderOpportunityHeatmap();
}

// ---- Overview decoration (service-level attach narrative) ----------------
// In SL mode the legacy corp-penetration Overview is rewritten in place to the
// per-service attach story. Guarded so non-SL data renders byte-identically.
function slSetChartText(containerId, title, sub) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const box = el.closest('.chart-box');
  if (!box) return;
  if (title != null) {
    const t = box.querySelector('.title');
    if (t) t.textContent = title;
  }
  if (sub != null) {
    const s = box.querySelector('.sub');
    if (s) s.textContent = sub;
  }
}

function slPlanBars(containerId, rows) {
  const el = document.getElementById(containerId);
  if (!el) return;
  if (!rows.length) {
    el.innerHTML = '<div style="padding:24px;color:#605e5c;font-size:13px;">No quantified per-service attach gaps in this book.</div>';
    return;
  }
  const maxV = Math.max.apply(null, rows.map(r => r.value).concat([1]));
  el.innerHTML = rows.map(r => {
    const w = Math.max(2, (r.value / maxV) * 100);
    return '<div style="display:flex;align-items:center;gap:10px;margin:7px 0;font-size:12px;">'
      + '<div style="flex:0 0 210px;text-align:right;color:#323130;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + escapeHtml(r.label) + '">' + escapeHtml(r.label) + '</div>'
      + '<div style="flex:1;background:#f3f2f1;border-radius:3px;"><div style="width:' + w + '%;height:16px;background:#d83b01;border-radius:3px;"></div></div>'
      + '<div style="flex:0 0 92px;color:#605e5c;font-weight:600;">' + fmt.money(r.value) + '</div>'
      + '</div>';
  }).join('');
}

function slDecorateOverview() {
  if (!hasServiceAttachData()) return;
  const sa = DATA.service_attach || {};
  const dossiers = (Array.isArray(sa.dossiers) ? sa.dossiers : [])
    .filter(d => d && typeof d === 'object' && typeof d.customer === 'string');

  const totalGap = sa.totalGapDollars || 0;
  const annual = totalGap * 12;

  let accountsWithGap = 0;
  let highCount = 0;
  dossiers.forEach(d => {
    const sl = slAttach(d.customer);
    if (!sl) return;
    if (sl.hasGap) accountsWithGap++;
    if (sl.priority === 'High') highCount++;
  });

  // Aggregate dollar gaps by Defender plan -> biggest gap service + chart 1.
  const byPlan = new Map();
  dossiers.forEach(d => {
    (Array.isArray(d.opportunities) ? d.opportunities : []).forEach(o => {
      const g = (o && o.gapDollars) || 0;
      if (g > 0 && o.planLabel) byPlan.set(o.planLabel, (byPlan.get(o.planLabel) || 0) + g);
    });
  });
  let topPlan = null;
  let topPlanGap = 0;
  byPlan.forEach((v, k) => { if (v > topPlanGap) { topPlanGap = v; topPlan = k; } });

  const attachRatio = (sa.bookAttachRatio != null) ? sa.bookAttachRatio : null;

  const setCard = (valId, label, value, delta) => {
    const valEl = document.getElementById(valId);
    if (!valEl) return null;
    valEl.textContent = value;
    const card = valEl.closest('.card');
    if (!card) return null;
    if (label != null) {
      const labelEl = card.querySelector('.label');
      if (labelEl) labelEl.textContent = label;
    }
    if (delta != null) {
      const deltaEl = card.querySelector('.delta');
      if (deltaEl) deltaEl.textContent = delta;
    }
    return card;
  };

  setCard('kpi-high', 'Total attach gap / mo', fmt.money(totalGap), 'unprotected eligible workload spend');
  setCard('kpi-med', 'Annualized opportunity', fmt.money(annual), 'if every per-service gap is closed');
  setCard('kpi-low', 'Accounts with a gap', String(accountsWithGap), 'of ' + dossiers.length + ' accounts in the book');
  setCard('kpi-small', 'High-priority accounts', String(highCount), 'work these first');

  const attachCard = setCard('kpi-dfc-acr', null,
    attachRatio == null ? '\u2013' : (attachRatio * 100).toFixed(1) + '%', null);
  if (attachCard) {
    const labelEl = attachCard.querySelector('.label');
    if (labelEl) {
      const tip = 'Book attach rate = total Defender for Cloud spend divided by the Azure workload spend that is eligible for a matching Defender plan. It excludes non-Azure spend (e.g. Power BI, GitHub) so it is not diluted by workloads Defender cannot protect.';
      labelEl.innerHTML = 'Book attach rate '
        + '<span class="prio-badge-i" tabindex="0" role="img" aria-label="What is book attach rate?" style="cursor:help;" title="'
        + escapeHtml(tip) + '">&#9432;</span>';
    }
    const deltaEl = document.getElementById('kpi-dfc-mom');
    if (deltaEl) deltaEl.textContent = 'Defender \u00f7 eligible workload ACR';
  }

  setCard('kpi-dfc-pct', 'Biggest gap service',
    topPlan ? fmt.money(topPlanGap) : '\u2013',
    topPlan ? topPlan + ' / mo across the book' : 'no quantified service gap');

  const note = document.querySelector('#panel-overview .note');
  if (note) {
    note.innerHTML = '<strong>How to read this:</strong> Each account buys Azure workloads '
      + '(containers, SQL, App Service, storage, and more) without the matching Defender for Cloud plan switched on. '
      + 'The cards size the total monthly and annualized attach gap across the book, how many accounts are affected, '
      + 'and which Defender service carries the largest gap. Use <em>Service Attach Opportunities</em> for workloads customers buy but do not protect, '
      + 'and <em>Defender Coverage Drift</em> when workload trends and mapped Defender trends move apart. To refresh, click <em>Import new Excel</em> and pick your latest export.';
  }

  // Chart 1: attach gap by Defender service (non-clickable plan bars).
  const planRows = Array.from(byPlan.entries())
    .map(([label, value]) => ({label: label, value: value}))
    .sort((a, b) => b.value - a.value)
    .slice(0, 12);
  slPlanBars('chart-dfc-trend', planRows);
  slSetChartText('chart-dfc-trend', 'Attach gap by Defender service', 'Monthly $ gap aggregated across all accounts');

  // Chart: top 15 accounts by attach gap (clickable -> drill-down).
  const topEl = document.getElementById('chart-top-dfc');
  if (topEl) {
    const accRows = dossiers
      .map(d => ({label: d.customer, value: d.totalGapDollars || 0}))
      .filter(r => r.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 15);
    if (accRows.length) {
      barChartHorizontal('chart-top-dfc', accRows);
    } else {
      topEl.innerHTML = '<div style="padding:24px;color:#605e5c;font-size:13px;">No quantified attach gaps to rank yet.</div>';
    }
    slSetChartText('chart-top-dfc', 'Top 15 accounts by attach gap', 'Monthly $ attach gap \u00b7 click a bar to drill down');
  }

  // Product mix chart: reword subtitle only.
  slSetChartText('chart-product-mix', null, 'Where the Azure spend sits \u2014 the workloads that should carry Defender attach');
}

'''
    return template.replace("function renderAll() {", script + "\nfunction renderAll() {", 1)
