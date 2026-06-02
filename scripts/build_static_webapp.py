"""Build the no-install static web app from the canonical Docker template.

This script re-uses the Flask-time string transformations from
``defender_acr_dashboard.static_dashboard`` (so the static page tracks the
Docker dashboard 1:1) and then layers on a small number of static-only
patches:

* swap CDN SheetJS for the vendored copy
* add a vendored PptxGenJS + ``js/acr-model.js`` + ``js/pptx-acr.js`` +
  ``js/app-nav.js`` (so the page is fully usable offline)
* replace the template's home-grown ``parseAndScore`` call with
  ``AcrModel.build`` (the existing JS port of ``dashboard_model.py``) so the
  Sales Action Queue / heatmap / KPI cards get all the fields they expect
* escape ``r.customer`` / ``r.notes`` in the injected heatmap (XSS hardening
  on Excel-derived values)
* prefix risky leading characters in ``csvCell`` (CSV formula injection)
* clear the bundled DATA so the static distribution ships with no customer
  rows; the dashboard shows an empty state until a file is picked
* add an Export to PowerPoint button wired to ``PptxAcr.exportDeck``
* insert the shared ``<div id="app-nav" ...>`` placeholder

Usage:
    python scripts/build_static_webapp.py            # write web-app/index.html
    python scripts/build_static_webapp.py --check    # exit 1 if output drifted

Every string replacement asserts an expected count, so accidental drift in
the upstream template fails fast.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from defender_acr_dashboard.static_dashboard import (  # noqa: E402
    _inject_opportunity_map,
    _monthly_acr_labels,
    _opportunity_map_labels,
)

TEMPLATE_PATH = REPO_ROOT / "docs" / "defender_for_cloud_dashboard (2).html"
OUTPUT_PATH = REPO_ROOT / "web-app" / "index.html"


def _replace_once(haystack: str, needle: str, replacement: str, label: str) -> str:
    return _replace_exact(haystack, needle, replacement, label, 1)


def _replace_exact(haystack: str, needle: str, replacement: str, label: str, expected: int) -> str:
    count = haystack.count(needle)
    if count != expected:
        raise SystemExit(
            f"build_static_webapp: expected exactly {expected} occurrence(s) of "
            f"{label!r}, found {count}. Upstream template likely changed."
        )
    return haystack.replace(needle, replacement)


def _assert_contains(html: str, needle: str, label: str) -> None:
    if needle not in html:
        raise SystemExit(
            f"build_static_webapp: post-build assertion failed — missing {label!r}."
        )


def _assert_absent(html: str, needle: str, label: str) -> None:
    if needle in html:
        raise SystemExit(
            f"build_static_webapp: post-build assertion failed — {label!r} "
            "should not be present in static output."
        )


def build_html() -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    html = _monthly_acr_labels(template)
    html = _opportunity_map_labels(html)
    html = _inject_opportunity_map(html)

    html = _replace_once(
        html,
        "  barChartHorizontal('chart-top-dfc', top15);\n",
        "  barChartHorizontal('chart-top-dfc', top15);\n  slDecorateOverview();\n",
        "renderAll chart-top-dfc anchor (Overview decorator wire-up)",
    )

    html = html.replace(
        "<title>Defender for Cloud — Opportunity Dashboard</title>",
        "<title>Defender for Cloud — ACR Opportunity Dashboard</title>",
        1,
    )

    html = _replace_once(
        html,
        '<script src="https://cdn.sheetjs.com/xlsx-0.20.2/package/dist/xlsx.full.min.js"></script>',
        '<script src="./vendor/xlsx.full.min.js"></script>',
        "CDN SheetJS tag",
    )

    nav_block = (
        "<body>\n"
        '<div id="app-nav" data-active="acr"></div>\n'
    )
    html = _replace_once(html, "<body>\n", nav_block, "opening body tag")

    export_button = (
        '    <button class="import-btn" id="import-btn">📂 Import new Excel</button>\n'
        '    <button class="import-btn" id="export-pptx-btn" style="margin-left:8px">📑 Export to PowerPoint</button>'
    )
    html = _replace_once(
        html,
        '    <button class="import-btn" id="import-btn">📂 Import new Excel</button>',
        export_button,
        "import button",
    )

    html = _replace_once(
        html,
        '    <div class="import-status" id="import-status">Showing data from initial export</div>',
        '    <div class="import-status" id="import-status">Pick an Excel export to load the dashboard. Your data stays on this machine.</div>',
        "import status message",
    )

    html = _strip_bundled_data(html)
    html = _inject_app_nav_css(html)
    html = _inject_splash(html)
    html = _inject_persistence(html)

    html = _replace_once(
        html,
        "    const newData = parseAndScore(rows);",
        "    const newData = AcrModel.build(rows, file.name);",
        "parseAndScore call",
    )

    html = _harden_heatmap(html)
    html = _harden_charts(html)
    html = _taxonomy_and_skus(html)
    html = _weekly_views(html)
    html = _product_mix_donut(html)
    html = _threshold_priority(html)
    html = _inject_priority_explainer(html)
    html = _inject_customer_modal(html)
    html = _inject_service_attach(html)
    html = _inject_category_modal(html)
    html = _harden_csvcell(html)

    closing_body = "</body>"
    extra_scripts = (
        '<script src="./js/sl-mapping.js"></script>\n'
        '<script src="./js/sl-parser.js"></script>\n'
        '<script src="./js/sl-engine.js"></script>\n'
        '<script src="./js/acr-model.js"></script>\n'
        '<script src="./vendor/pptxgen.bundle.js"></script>\n'
        '<script src="./js/pptx-acr.js"></script>\n'
        '<script src="./js/app-nav.js"></script>\n'
        f"{_export_handler_script()}\n"
        f"{closing_body}"
    )
    html = _replace_once(html, closing_body, extra_scripts, "closing body tag")

    _assert_absent(html, "cdn.sheetjs.com", "CDN SheetJS URL")
    _assert_absent(html, "= parseAndScore(", "stale parseAndScore call")
    _assert_contains(html, "AcrModel.build(rows, file.name)", "AcrModel.build wiring")
    _assert_contains(html, 'id="export-pptx-btn"', "export PPT button")
    _assert_contains(html, "PptxAcr.exportDeck", "export PPT handler")
    _assert_contains(html, "function renderOpportunityHeatmap()", "heatmap function")
    _assert_contains(html, "${escapeHtml(r.customer)}", "escaped customer in heatmap")
    _assert_contains(html, "${escapeHtml(d.label", "escaped label in bar chart")
    _assert_contains(html, "${escapeHtml(p.label)}", "escaped label in quadrant chart")
    _assert_contains(html, "${escapeHtml(truncated)}", "escaped truncated label in quadrant chart")
    _assert_contains(html, "${escapeHtml(r.getAttribute('data-customer'))}", "escaped bar chart tooltip customer")
    _assert_contains(html, "${escapeHtml(c.getAttribute('data-customer'))}", "escaped quadrant tooltip customer")
    _assert_absent(html, ".label.replace(/\"/g, '&quot;')", "stale quote-only label escape (should use escapeHtml)")
    _assert_contains(html, "CSV_FORMULA_LEADERS", "CSV formula-injection guard")
    _assert_contains(html, "function reclassifyOpportunities(", "reclassify function")
    _assert_contains(html, "reclassifyOpportunities(dfcShareThreshold);\n  renderKpis();", "renderAll reclassify wiring")
    _assert_contains(html, "const DEFAULT_DFC_SHARE_THRESHOLD = 6;", "default 6% attach baseline")
    _assert_contains(html, "attach baseline", "attach baseline footer copy")
    _assert_contains(html, "function openPriorityExplainer(", "priority explainer modal")
    _assert_contains(html, 'class="tag \' + cls + \' prio-badge"', "clickable priority badge")
    _assert_contains(html, "e.target.closest('.prio-badge')", "capture-phase badge click handler")

    # Customer breakdown modal (opens from the Opportunity Matrix instead of navigating).
    _assert_contains(html, "function renderCustomerDetail(name, idp)", "renderCustomerDetail idp refactor")
    _assert_contains(html, "function openCustomerModal(", "customer modal opener")
    _assert_contains(html, "function _ensureCustOverlay(", "customer modal overlay factory")
    _assert_contains(html, 'id="m-cust-title"', "customer modal title node")
    _assert_contains(html, 'id="m-cust-products"', "customer modal product table")
    _assert_contains(html, "#chart-quadrant [data-customer], #chart-top-dfc [data-customer], #action-queue tr[data-customer]", "opportunity matrix click interceptor")
    _assert_contains(html, "function _enhanceCustomerTargetsA11y()", "customer target a11y enhancer")
    _assert_contains(html, "n.setAttribute('tabindex', '0')", "customer targets made focusable")
    _assert_contains(html, "if (e.key !== 'Enter' && e.key !== ' ' && e.key !== 'Spacebar') return;", "customer target keydown activation")
    _assert_contains(html, "renderCustomerDetail(name, 'm-')", "modal renders breakdown via idp")
    _assert_contains(html, "${escapeHtml(opp.notes)}", "escaped drill-down signal note")
    _assert_absent(html, "<strong>Signal:</strong> ${opp.notes}", "unescaped drill-down signal note")
    _assert_absent(html, "lineChart('chart-cust-dfc', [", "stale unprefixed cust dfc chart call")
    _assert_absent(html, "lineChart('chart-cust-pct', [", "stale unprefixed cust pct chart call")

    # Per-service Defender attach (AE talk-track) drill-down.
    _assert_contains(html, "function renderServiceAttach(idp, name)", "service attach renderer")
    _assert_contains(html, 'id="cust-attach"', "inline service attach anchor")
    _assert_contains(html, 'id="m-cust-attach"', "modal service attach anchor")
    _assert_contains(html, "renderServiceAttach(idp, name);", "service attach render call")
    _assert_contains(html, "escapeHtml(o.opener)", "escaped attach opener (XSS)")
    _assert_contains(html, "escapeHtml(c.planLabel)", "escaped attach plan label (XSS)")
    _assert_contains(html, "escapeHtml(f.planLabel)", "escaped foundational plan label (XSS)")
    # New per-service narrative + all-plans scorecard surfaces.
    _assert_contains(html, "function _saSentence(", "service attach narrative sentence helper")
    _assert_contains(html, "function _saScorecard(", "service attach all-plans scorecard helper")
    _assert_contains(html, "function _saOppDetail(", "service attach expanded opportunity detail helper")
    _assert_contains(html, "data-sa-toggle", "service attach scorecard accordion toggle")
    _assert_contains(html, 'class="sa-detail"', "service attach scorecard accordion panel")
    _assert_contains(html, "window.__saAccordionWired", "service attach accordion delegated handler")
    _assert_contains(html, "Defender coverage scorecard", "service attach scorecard title")
    _assert_contains(html, "attach gap.", "service attach narrative gap phrasing")
    _assert_contains(html, "Total ACR gap per month", "service attach $ opportunity banner (month)")
    _assert_contains(html, "Total ACR gap per year", "service attach $ opportunity banner (year)")
    _assert_absent(html, "on the table", "removed 'on the table' wording")
    _assert_absent(html, "function _saGapChart(", "removed service attach SVG gap chart helper")
    _assert_absent(html, "Workload vs Defender ACR by service", "removed service attach chart title")
    _assert_contains(html, "function _prioServiceEvidence(", "priority modal per-service evidence")
    _assert_contains(html, "Service-level summary", "priority modal service summary")
    _assert_contains(html, "Suggested seller conversation", "priority modal seller prompt")
    _assert_contains(html, './vendor/xlsx.full.min.js', "vendored SheetJS")
    _assert_contains(html, './vendor/pptxgen.bundle.js', "vendored PptxGenJS")
    _assert_contains(html, './js/acr-model.js', "acr-model.js script")
    _assert_contains(html, './js/sl-mapping.js', "sl-mapping.js script")
    _assert_contains(html, './js/sl-parser.js', "sl-parser.js script")
    _assert_contains(html, './js/sl-engine.js', "sl-engine.js script")
    _assert_contains(html, './js/pptx-acr.js', "pptx-acr.js script")
    _assert_contains(html, "#app-nav .app-menu", "app-nav inline CSS")
    _assert_contains(html, 'id="app-nav"', "app-nav placeholder")
    _assert_contains(html, 'id="splash"', "splash overlay")
    _assert_contains(html, 'id="splash-dropzone"', "splash dropzone")
    _assert_contains(html, 'id="splash-progress"', "splash loading bar")
    _assert_contains(html, "splash.hidden = true", "splash hide-on-load")
    _assert_contains(html, "if (!DATA.customers || DATA.customers.length === 0) return;", "renderAll empty-state guard")
    _assert_contains(html, "  __slDossierMap = null;\n  reclassifyOpportunities(dfcShareThreshold);", "renderAll dossier-cache reset (stale-data guard)")
    _assert_contains(html, "ACR_CACHE_KEY = 'defenderattach:acr:v3'", "session-storage persistence (v3 cache key)")
    _assert_contains(html, "sessionStorage.setItem(ACR_CACHE_KEY", "persistence write on import")
    _assert_contains(html, "const colorFor = (label, rank) =>", "validated donut colour helper")
    _assert_contains(html, "${escapeHtml(d.label)}</span>", "escaped product mix donut legend label")
    _assert_contains(html, "const nameEsc = escapeHtml(p.product);", "escaped customer product name")
    _assert_contains(html, "${escapeHtml(s.sku)}", "escaped SKU name in drill-down")
    _assert_contains(html, "data-sku-toggle", "SKU drill-down toggle markup")
    _assert_contains(html, "Math.max(0, DATA.months.length - 2) : DATA.months.length - 1", "partial-month KPI guard")
    _assert_contains(html, "data-label=\"${escapeHtml(s.label)}\"", "escaped line chart data-label")
    _assert_contains(html, "showTooltip(`<b>${escapeHtml(label)}</b>", "escaped line chart tooltip label")
    _assert_absent(html, "data-label=\"${s.label}\"", "unescaped line chart data-label")
    _assert_absent(html, "color: PRODUCT_COLORS[p]}));", "stale hardcoded trend colours")

    _assert_contains(html, "function renderDfcTrend()", "weekly-preferring DfC overview trend")
    _assert_contains(html, "const weekly = !!(DATA.weekly_enabled && DATA.dfc_total_weekly);", "weekly DfC series auto-selected")
    _assert_absent(html, "lineChart('chart-dfc-trend', [{label: 'Defender for Cloud', values: DATA.dfc_total_monthly, color: '#0078d4'}]);", "stale month-only DfC overview trend call")
    _assert_absent(html, 'id="product-trend-grain"', "removed monthly/weekly granularity toggle")
    _assert_absent(html, 'id="cust-trend-grain"', "removed customer granularity toggle")
    _assert_absent(html, "function initGrainControls()", "removed granularity control init")

    # Product-mix donut (replaces the product-trend line chart on the overview).
    _assert_contains(html, "function donutChart(", "product-mix donut helper")
    _assert_contains(html, "function renderProductMix()", "product-mix donut renderer")
    _assert_contains(html, "function computeDonutSlices(src, partial)", "donut pure slice-builder")
    _assert_contains(html, 'id="chart-product-mix"', "product-mix donut container")
    _assert_contains(html, 'id="legend-product-mix"', "product-mix donut legend")
    _assert_contains(html, "  renderProductMix();", "renderAll product-mix wiring")
    _assert_contains(html, "donutChart('chart-product-mix', r.items)", "donut render call")
    _assert_absent(html, "function renderProductTrend()", "removed product-trend line renderer")
    _assert_absent(html, "  renderProductTrend();", "removed product-trend renderAll call")
    _assert_absent(html, 'id="product-trend-mode"', "removed product-trend mode select")
    _assert_absent(html, 'id="chart-product-trend"', "removed product-trend line container")
    _assert_absent(html, 'id="legend-product-trend"', "removed product-trend legend")
    _assert_absent(html, "Product mix — ACR trend by service", "removed product-trend line title")

    # Donut drill-down: top-12 categories from product_monthly + category breakdown modal.
    _assert_contains(html, "const MAX_SLICES = 12;", "donut top-12 cap")
    _assert_contains(html, "Object.keys(src).filter(k => k !== 'Total')", "donut sources all product_monthly categories")
    _assert_contains(html, "window._donutOtherCats", "donut Other-slice category stash")
    _assert_contains(html, "function openCategoryBreakdown(", "category breakdown drill-down")
    _assert_contains(html, "function _ensureCatOverlay(", "category modal overlay builder")
    _assert_contains(html, "DATA.product_skus", "category modal sources SKU leaves")
    _assert_absent(html, ": TRACK_PRODUCTS)\n    .filter(p => src[p]);", "donut no longer reuses the 8-cap track_products taxonomy")

    _assert_contains(html, "function slDecorateOverview()", "Overview attach decorator function")
    _assert_contains(html, "function slPlanBars(", "Overview plan-gap bars helper")
    _assert_contains(html, "function slSetChartText(", "Overview runtime chart-text helper")
    _assert_contains(html, "  slDecorateOverview();\n", "renderAll Overview decorator wiring")

    return html


def _inject_persistence(html: str) -> str:
    """Cache parsed DATA in sessionStorage so tab-internal navigation keeps it.

    Each browser tab gets its own sessionStorage; closing the tab clears it
    (privacy default). We:

    * persist DATA after a successful import,
    * try to restore on page load (before the initial empty render),
    * clear the cache when the user clicks "Load other file" in the top nav,
    * wire the nav reload button to the existing import button so both entry
      points behave identically.

    The persistence is wrapped in DOMContentLoaded so ``window.AppNav`` (loaded
    after the inline script) is available when we touch the source pill.
    """

    persist_after_import = (
        "    DATA = newData;\n"
        "    const splash = document.getElementById('splash');\n"
        "    if (splash) splash.hidden = true;\n"
        "    renderAll();\n"
        "    try {\n"
        "      const json = JSON.stringify(DATA);\n"
        "      // 4.5 MB ceiling — leaves headroom under the 5 MB sessionStorage quota.\n"
        "      if (json.length < 4500000) sessionStorage.setItem(ACR_CACHE_KEY, json);\n"
        "    } catch (cacheErr) { console.warn('Could not cache data:', cacheErr); }\n"
        "    if (window.AppNav) AppNav.setSource(file.name);\n"
    )
    html = _replace_once(
        html,
        (
            "    DATA = newData;\n"
            "    const splash = document.getElementById('splash');\n"
            "    if (splash) splash.hidden = true;\n"
            "    renderAll();\n"
        ),
        persist_after_import,
        "persist-on-import block",
    )

    # Add the cache key constant + restore-on-load block, replacing the bare
    # ``renderAll();`` bootstrapper near the bottom of the inline script.
    boot_block = (
        # v3: bump invalidates pre-product_skus cached models so the donut
        # category drill-down (added in a93a603) gets fresh, complete DATA.
        "const ACR_CACHE_KEY = 'defenderattach:acr:v3';\n"
        "renderAll();\n"
        "document.addEventListener('DOMContentLoaded', function() {\n"
        "  // Restore from a previous tab-internal navigation if available.\n"
        "  try {\n"
        "    const cached = sessionStorage.getItem(ACR_CACHE_KEY);\n"
        "    if (cached) {\n"
        "      const parsed = JSON.parse(cached);\n"
        "      if (parsed && parsed.customers && parsed.customers.length) {\n"
        "        DATA = parsed;\n"
        "        const splash = document.getElementById('splash');\n"
        "        if (splash) splash.hidden = true;\n"
        "        renderAll();\n"
        "        if (window.AppNav) AppNav.setSource(DATA.source_name || 'Restored from session');\n"
        "        setStatus('Restored \"' + (DATA.source_name || 'previous file') + '\" from this session.', 'success');\n"
        "      }\n"
        "    }\n"
        "  } catch (restoreErr) {\n"
        "    console.warn('Could not restore cached data:', restoreErr);\n"
        "    try { sessionStorage.removeItem(ACR_CACHE_KEY); } catch (_) {}\n"
        "  }\n"
        "  // Wire the shared nav's \"Load other file\" button to the existing\n"
        "  // import flow + clear the cache so the splash returns next reload.\n"
        "  if (window.AppNav && AppNav.onReload) {\n"
        "    AppNav.onReload(function(){\n"
        "      try { sessionStorage.removeItem(ACR_CACHE_KEY); } catch (_) {}\n"
        "      const btn = document.getElementById('import-btn');\n"
        "      if (btn) btn.click();\n"
        "    });\n"
        "  }\n"
        "});\n"
    )
    return _replace_once(html, "\nrenderAll();\n", "\n" + boot_block, "initial renderAll bootstrap")


def _inject_splash(html: str) -> str:
    """Add an empty-state splash overlay shown until the first import.

    The static distribution ships with no data (see ``_strip_bundled_data``).
    Without a splash the page renders empty KPI cards and blank charts, which
    looks broken. This injects:

    * CSS for ``#splash`` (full-viewport modal-style overlay)
    * the splash markup right after ``<body>``
    * a guard at the top of ``renderAll()`` that bails out when DATA is empty
    * a hide call after a successful import, plus a wire-up so the splash's
      "Choose Excel file" button re-uses the existing ``#file-input``.
    """

    splash_css = (
        "\n/* empty-state splash (visible until first import) */\n"
        "#splash {\n"
        "  position: fixed; inset: 0; z-index: 9999;\n"
        "  background: rgba(243, 242, 241, 0.96);\n"
        "  display: flex; align-items: center; justify-content: center;\n"
        "  font-family: 'Segoe UI', system-ui, sans-serif;\n"
        "}\n"
        "#splash[hidden] { display: none; }\n"
        "#splash .splash-card {\n"
        "  background: #ffffff; border: 1px solid #edebe9;\n"
        "  border-radius: 8px; padding: 36px 44px; max-width: 520px;\n"
        "  box-shadow: 0 8px 32px rgba(0,0,0,0.12); text-align: center;\n"
        "}\n"
        "#splash h2 { margin: 0 0 8px; color: #0078d4; font-size: 22px; }\n"
        "#splash p { margin: 0 0 20px; color: #605e5c; font-size: 14px; line-height: 1.5; }\n"
        "#splash-dropzone {\n"
        "  border: 2px dashed #c8c6c4; border-radius: 6px;\n"
        "  padding: 28px 20px; margin-bottom: 16px;\n"
        "  background: #faf9f8; transition: all 0.15s ease;\n"
        "  cursor: pointer;\n"
        "}\n"
        "#splash-dropzone:hover { border-color: #0078d4; background: #f3f9fd; }\n"
        "#splash-dropzone.dragover {\n"
        "  border-color: #0078d4; background: #deecf9;\n"
        "  border-style: solid;\n"
        "}\n"
        "#splash-dropzone .dz-icon { font-size: 32px; line-height: 1; margin-bottom: 8px; }\n"
        "#splash-dropzone .dz-main { color: #323130; font-weight: 600; font-size: 14px; margin-bottom: 4px; }\n"
        "#splash-dropzone .dz-sub { color: #605e5c; font-size: 12px; }\n"
        "#splash button {\n"
        "  background: #0078d4; color: #ffffff; border: 0;\n"
        "  padding: 12px 28px; border-radius: 4px; font-size: 15px;\n"
        "  font-weight: 600; cursor: pointer;\n"
        "}\n"
        "#splash button:hover { background: #106ebe; }\n"
        "#splash .splash-hint { margin-top: 16px; font-size: 12px; color: #8a8886; }\n"
        "#splash .splash-error { margin-top: 12px; font-size: 13px; color: #a4262c; min-height: 18px; }\n"
        "#splash .splash-progress {\n"
        "  margin-top: 16px; height: 6px; border-radius: 999px;\n"
        "  background: #e6e9ef; overflow: hidden; display: none;\n"
        "}\n"
        "#splash .splash-progress.active { display: block; }\n"
        "#splash .splash-progress .bar {\n"
        "  height: 100%; width: 0%; border-radius: 999px;\n"
        "  background: linear-gradient(90deg, #0078d4, #4aa3e8);\n"
        "  transition: width 0.28s ease;\n"
        "}\n"
        "#splash .splash-progress-label {\n"
        "  margin-top: 8px; font-size: 12px; color: #605e5c; min-height: 16px;\n"
        "}\n"
    )
    html = _replace_once(html, "</style>\n</head>", splash_css + "</style>\n</head>", "closing style/head tags (splash)")

    splash_markup = (
        '<div id="splash">\n'
        '  <div class="splash-card">\n'
        '    <h2>Welcome — load your ACR export</h2>\n'
        '    <p>Pick an "ACR Details by … Month" Excel export to populate the dashboard. '
        'Your data stays on this machine — nothing is uploaded.</p>\n'
        '    <div id="splash-dropzone" role="button" tabindex="0" aria-label="Drop an Excel file here or click to browse">\n'
        '      <div class="dz-icon" aria-hidden="true">📥</div>\n'
        '      <div class="dz-main">Drop your Excel file here</div>\n'
        '      <div class="dz-sub">or click to browse</div>\n'
        '    </div>\n'
        '    <button type="button" id="splash-import-btn">📂 Choose Excel file</button>\n'
        '    <div class="splash-progress" id="splash-progress" role="progressbar" aria-label="Loading file" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><div class="bar"></div></div>\n'
        '    <div class="splash-progress-label" id="splash-progress-label" aria-live="polite"></div>\n'
        '    <div class="splash-error" id="splash-error" role="alert"></div>\n'
        '    <div class="splash-hint">You can swap files later from the top menu.</div>\n'
        '  </div>\n'
        '</div>\n'
    )
    html = _replace_once(
        html,
        '<div id="app-nav" data-active="acr"></div>',
        splash_markup + '<div id="app-nav" data-active="acr"></div>',
        "splash markup before app-nav",
    )

    html = _replace_once(
        html,
        "function renderAll() {",
        "function renderAll() {\n  if (!DATA.customers || DATA.customers.length === 0) return;",
        "renderAll empty-state guard",
    )

    html = _replace_once(
        html,
        "    DATA = newData;\n    renderAll();",
        (
            "    DATA = newData;\n"
            "    const splash = document.getElementById('splash');\n"
            "    if (splash) splash.hidden = true;\n"
            "    renderAll();"
        ),
        "splash hide-on-import hook",
    )

    html = _replace_once(
        html,
        "    if (!newData) { setStatus('Could not parse — check the sheet structure.', 'error'); return; }",
        "    if (!newData || !newData.customers || newData.customers.length === 0) { setStatus('Could not read this workbook — no customers found. Make sure it is the ACR Details Excel export with the expected columns.', 'error'); return; }",
        "import empty-workbook guard",
    )

    splash_wire = (
        "<script>\n"
        "(function(){\n"
        "  var btn = document.getElementById('splash-import-btn');\n"
        "  var dz = document.getElementById('splash-dropzone');\n"
        "  var err = document.getElementById('splash-error');\n"
        "  var prog = document.getElementById('splash-progress');\n"
        "  var plabel = document.getElementById('splash-progress-label');\n"
        "  var importBtn = document.getElementById('import-btn');\n"
        "  var fileInput = document.getElementById('file-input');\n"
        "  if (!importBtn || !fileInput) return;\n"
        "\n"
        "  function showError(msg){ if (err) err.textContent = msg || ''; if (msg && prog) prog.classList.remove('active'); if (msg && plabel) plabel.textContent = ''; }\n"
        "  function clickBrowse(){ showError(''); importBtn.click(); }\n"
        "\n"
        "  // Determinate progress driver used by the import handler. Each import\n"
        "  // stage (read -> parse -> score -> render) sets a percentage so the bar\n"
        "  // visibly fills, repainting between the synchronous parse/build steps.\n"
        "  window.__attachProgress = function(pct, label){\n"
        "    var splashEl = document.getElementById('splash');\n"
        "    if (!prog || (splashEl && splashEl.hidden)) return;\n"
        "    prog.classList.add('active');\n"
        "    var bar = prog.querySelector('.bar');\n"
        "    var p = Math.max(0, Math.min(100, Number(pct) || 0));\n"
        "    if (bar) bar.style.width = p + '%';\n"
        "    prog.setAttribute('aria-valuenow', String(Math.round(p)));\n"
        "    if (plabel && typeof label === 'string') plabel.textContent = label;\n"
        "    if (err) { err.textContent = ''; err.className = 'splash-error'; }\n"
        "  };\n"
        "\n"
        "  if (btn) btn.addEventListener('click', clickBrowse);\n"
        "\n"
        "  if (dz) {\n"
        "    dz.addEventListener('click', clickBrowse);\n"
        "    dz.addEventListener('keydown', function(e){\n"
        "      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); clickBrowse(); }\n"
        "    });\n"
        "\n"
        "    ['dragenter','dragover'].forEach(function(evt){\n"
        "      dz.addEventListener(evt, function(e){\n"
        "        e.preventDefault(); e.stopPropagation();\n"
        "        if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';\n"
        "        dz.classList.add('dragover');\n"
        "      });\n"
        "    });\n"
        "    ['dragleave','dragend'].forEach(function(evt){\n"
        "      dz.addEventListener(evt, function(e){\n"
        "        e.preventDefault(); e.stopPropagation();\n"
        "        dz.classList.remove('dragover');\n"
        "      });\n"
        "    });\n"
        "    dz.addEventListener('drop', function(e){\n"
        "      e.preventDefault(); e.stopPropagation();\n"
        "      dz.classList.remove('dragover');\n"
        "      showError('');\n"
        "      var files = e.dataTransfer && e.dataTransfer.files;\n"
        "      if (!files || !files.length) return;\n"
        "      var file = files[0];\n"
        "      if (!/\\.(xlsx|xls)$/i.test(file.name)) {\n"
        "        showError('Please drop a .xlsx or .xls file.');\n"
        "        return;\n"
        "      }\n"
        "      try {\n"
        "        var dt = new DataTransfer();\n"
        "        dt.items.add(file);\n"
        "        fileInput.files = dt.files;\n"
        "        fileInput.dispatchEvent(new Event('change', { bubbles: true }));\n"
        "      } catch (ex) {\n"
        "        showError('Could not read dropped file — use the Choose Excel file button instead.');\n"
        "      }\n"
        "    });\n"
        "  }\n"
        "\n"
        "  // Block accidental drops outside the dropzone (default browser behavior\n"
        "  // would navigate away from the dashboard).\n"
        "  window.addEventListener('dragover', function(e){ e.preventDefault(); });\n"
        "  window.addEventListener('drop', function(e){\n"
        "    var splash = document.getElementById('splash');\n"
        "    if (splash && !splash.hidden) e.preventDefault();\n"
        "  });\n"
        "\n"
        "  // Mirror import status onto the splash overlay. The top-menu status\n"
        "  // element is hidden behind the splash, so a failed or empty import\n"
        "  // would otherwise look like 'nothing happened'. Errors show red text;\n"
        "  // in-progress messages reveal the determinate bar (filled via\n"
        "  // window.__attachProgress from the import handler).\n"
        "  if (typeof window.setStatus === 'function') {\n"
        "    var _origSetStatus = window.setStatus;\n"
        "    window.setStatus = function(msg, kind){\n"
        "      try { _origSetStatus(msg, kind); } catch (_) {}\n"
        "      var splashEl = document.getElementById('splash');\n"
        "      if (!(err && splashEl && !splashEl.hidden)) return;\n"
        "      if (kind === 'error') {\n"
        "        if (prog) prog.classList.remove('active');\n"
        "        if (plabel) plabel.textContent = '';\n"
        "        err.textContent = msg || '';\n"
        "        err.className = 'splash-error error';\n"
        "      } else if (kind) {\n"
        "        if (prog) prog.classList.remove('active');\n"
        "        if (plabel) plabel.textContent = '';\n"
        "        err.textContent = '';\n"
        "        err.className = 'splash-error';\n"
        "      } else {\n"
        "        err.textContent = '';\n"
        "        err.className = 'splash-error';\n"
        "        if (prog) prog.classList.add('active');\n"
        "        if (plabel) plabel.textContent = msg || 'Loading…';\n"
        "      }\n"
        "    };\n"
        "  }\n"
        "})();\n"
        "</script>\n"
    )
    html = _replace_once(html, "</body>", splash_wire + "</body>", "splash wire-up before body close")

    return html


def _inject_app_nav_css(html: str) -> str:
    """Inject `.app-menu` styles into the template's <style> block.

    The Docker template scopes its own CSS variables; ``web-app/css/app.css``
    references different ones (``--cp-link``, ``--cp-dashboard-muted``…) that
    are not defined in the template. We therefore inline the nav-only rules
    with concrete colors so the menu renders identically to the milestones
    page without dragging in the rest of ``app.css`` (which would clobber the
    template's body / shell styles).
    """

    nav_css = (
        "\n/* shared app nav (matches web-app/css/app.css .app-menu rules) */\n"
        "#app-nav .app-menu {\n"
        "  display: flex; gap: 12px; align-items: center;\n"
        "  padding: 10px 18px 0;\n"
        "  background: #f3f2f1;\n"
        "  border-bottom: 1px solid #edebe9;\n"
        "}\n"
        "#app-nav .app-menu a {\n"
        "  color: #605e5c; text-decoration: none; font-weight: 700;\n"
        "  padding: 12px 14px 10px; border-bottom: 4px solid transparent;\n"
        "  font-size: 14px;\n"
        "}\n"
        "#app-nav .app-menu a.active {\n"
        "  color: #0078d4; border-bottom-color: #0078d4;\n"
        "}\n"
        "#app-nav .app-menu a:not(.active):hover {\n"
        "  color: #0078d4; border-bottom-color: #0078d4;\n"
        "}\n"
        "#app-nav .app-menu .spacer { flex: 1; }\n"
        "#app-nav .app-menu .source-pill {\n"
        "  font-size: 11px; color: #605e5c;\n"
        "  padding: 4px 10px; background: #ffffff;\n"
        "  border: 1px solid #edebe9; border-radius: 12px;\n"
        "  max-width: 320px; overflow: hidden; text-overflow: ellipsis;\n"
        "  white-space: nowrap; font-weight: 400;\n"
        "}\n"
        "#app-nav .app-menu button.menu-action {\n"
        "  font-size: 12px; padding: 6px 12px;\n"
        "  background: #ffffff; border: 1px solid #edebe9;\n"
        "  border-radius: 4px; color: #0078d4;\n"
        "  cursor: pointer; font-weight: 600;\n"
        "}\n"
        "#app-nav .app-menu button.menu-action:hover { background: #faf9f8; }\n"
    )
    return _replace_once(html, "</style>\n</head>", nav_css + "</style>\n</head>", "closing style/head tags")


def _strip_bundled_data(html: str) -> str:
    """Replace the template's pre-baked DATA blob with an empty shell.

    The static distribution must ship with no customer rows (privacy + the
    colleague experience should start from "pick a file"). The template
    embeds a `let DATA = {...big JSON...};` literal whose JSON span is hard
    to delimit with a single string match, so we slice between known anchors.
    """

    start_marker = "let DATA = "
    end_marker = "// ============ Helpers ============"
    start = html.find(start_marker)
    end = html.find(end_marker)
    if start == -1 or end == -1 or end <= start:
        raise SystemExit("build_static_webapp: could not locate DATA literal block.")

    replacement = (
        "let DATA = {\n"
        '  months: [], month_labels: [], partial_month_idx: -1,\n'
        '  last_full_month: "", prior_month: "",\n'
        '  customers: [], products: [], opportunity: [],\n'
        '  generated_at: "", source_name: ""\n'
        "};\n\n"
    )
    return html[:start] + replacement + html[end:]


def _taxonomy_and_skus(html: str) -> str:
    """Make the product views taxonomy-aware and add SKU drill-down.

    The new-format model emits Excel-derived product/SKU names, a per-dataset
    ``track_products`` list and a ``product_colors`` map. Three changes:

    * KPI "current month" derives from the last FULL month when the latest
      month is partial (``partial_month_idx``), so a half-finished month does
      not distort headline ACR / MoM / share figures.
    * The product-trend chart prefers ``DATA.track_products`` /
      ``DATA.product_colors`` (falling back to the hardcoded template lists),
      escapes every legend label, and validates colours against a hex
      allowlist before injecting them into inline styles.
    * The customer drill-down escapes product names (now user-controlled) and
      renders collapsible SKU sub-rows under each product, also escaped.
    """

    # 1. KPI: score on the last full month when the latest month is partial.
    html = _replace_once(
        html,
        "  const lastIdx = DATA.months.length - 1;",
        "  const lastIdx = (DATA.partial_month_idx >= 0 && DATA.partial_month_idx === DATA.months.length - 1)\n"
        "    ? Math.max(0, DATA.months.length - 2) : DATA.months.length - 1;",
        "KPI last-full-month index",
    )

    # 2a. Product trend: taxonomy-aware series with validated colours.
    html = _replace_once(
        html,
        "  const series = TRACK_PRODUCTS\n"
        "    .filter(p => DATA.product_monthly[p])\n"
        "    .map(p => ({label: p, values: DATA.product_monthly[p], color: PRODUCT_COLORS[p]}));",
        "  const tracks = (DATA.track_products && DATA.track_products.length ? DATA.track_products : TRACK_PRODUCTS)\n"
        "    .filter(p => DATA.product_monthly[p]);\n"
        "  const colorFor = p => { const c = (DATA.product_colors && DATA.product_colors[p]) || PRODUCT_COLORS[p] || '#605e5c'; return /^#[0-9a-fA-F]{6}$/.test(c) ? c : '#605e5c'; };\n"
        "  const series = tracks.map(p => ({label: p, values: DATA.product_monthly[p], color: colorFor(p)}));",
        "taxonomy-aware product trend series",
    )

    # 2b. Product trend legend: escape labels, validated colour swatches.
    html = _replace_once(
        html,
        "  document.getElementById('legend-product-trend').innerHTML = TRACK_PRODUCTS.filter(p => DATA.product_monthly[p]).map(p =>\n"
        "    `<span class=\"legend-item\"><span class=\"legend-swatch\" style=\"background:${PRODUCT_COLORS[p]}\"></span>${p}</span>`).join('');",
        "  document.getElementById('legend-product-trend').innerHTML = tracks.map(p =>\n"
        "    `<span class=\"legend-item\"><span class=\"legend-swatch\" style=\"background:${colorFor(p)}\"></span>${escapeHtml(p)}</span>`).join('');",
        "escaped product trend legend",
    )

    # 3. Customer drill-down: escape product names + collapsible SL4 detail rows.
    html = _replace_once(
        html,
        "    cd.products.map(p => {\n"
        "      const sparkColor = p.product === 'Defender for Cloud' ? '#0078d4' : '#605e5c';\n"
        "      return `<div class=\"product-row\">\n"
        "        <div class=\"name\">${p.product === 'Defender for Cloud' ? '<strong style=\"color:#0078d4\">' + p.product + '</strong>' : p.product}</div>\n"
        "        <div class=\"num\">${fmt.money2(p.current)}</div>\n"
        "        <div class=\"num ${fmt.pctClass(p.mom)}\">${fmt.pct(p.mom)}</div>\n"
        "        <div class=\"num ${fmt.pctClass(p.three_m)}\">${fmt.pct(p.three_m)}</div>\n"
        "        <div>${sparkline(p.series, 140, 26, sparkColor)}</div>\n"
        "      </div>`;\n"
        "    }).join('');",
        "    `<div class=\"product-row product-header\">\n"
        "      <div>Azure service category / Service Level 4 detail</div>\n"
        "      <div class=\"num\">Monthly ACR</div>\n"
        "      <div class=\"num\">MoM</div>\n"
        "      <div class=\"num\">3M</div>\n"
        "      <div>Trend</div>\n"
        "    </div>` + cd.products.map((p, pi) => {\n"
        "      const sparkColor = p.product === 'Defender for Cloud' ? '#0078d4' : '#605e5c';\n"
        "      const nameEsc = escapeHtml(p.product);\n"
        "      const nameHtml = p.product === 'Defender for Cloud' ? '<strong style=\"color:#0078d4\">' + nameEsc + '</strong>' : nameEsc;\n"
        "      const skus = Array.isArray(p.skus) ? p.skus : [];\n"
        "      const sid = 'sku-' + pi;\n"
        "      const caret = skus.length ? `<span class=\"sku-caret\">\\u25b8</span>` : '<span class=\"sku-caret\"></span>';\n"
        "      const detailLabel = skus.length ? `<span class=\"sku-meta\">Click to show ${skus.length} service detail${skus.length === 1 ? '' : 's'}</span>` : '<span class=\"sku-meta\">No active Service Level 4 detail in this category</span>';\n"
        "      const toggleAttrs = skus.length ? ` data-sku-toggle=\"${sid}\" aria-expanded=\"false\" role=\"button\" tabindex=\"0\"` : '';\n"
        "      const head = `<div class=\"product-row category-row\"${toggleAttrs}>\n"
        "        <div class=\"name\">${caret}${nameHtml}${detailLabel}</div>\n"
        "        <div class=\"num\">${fmt.money2(p.current)}</div>\n"
        "        <div class=\"num ${fmt.pctClass(p.mom)}\">${fmt.pct(p.mom)}</div>\n"
        "        <div class=\"num ${fmt.pctClass(p.three_m)}\">${fmt.pct(p.three_m)}</div>\n"
        "        <div>${sparkline(p.series, 140, 26, sparkColor)}</div>\n"
        "      </div>`;\n"
        "      const subs = skus.map(s => `<div class=\"product-row sku-row ${sid}\" hidden>\n"
        "        <div class=\"name\">${escapeHtml(s.sku)}</div>\n"
        "        <div class=\"num\">${fmt.money2(s.current)}</div>\n"
        "        <div class=\"num ${fmt.pctClass(s.mom)}\">${fmt.pct(s.mom)}</div>\n"
        "        <div class=\"num ${fmt.pctClass(s.three_m)}\">${fmt.pct(s.three_m)}</div>\n"
        "        <div>${sparkline(s.series, 140, 26, '#a19f9d')}</div>\n"
        "      </div>`).join('');\n"
        "      return head + subs;\n"
        "    }).join('');",
        "SL4 service detail drill-down rows in customer table",
    )

    # 4. Delegated click handler that expands/collapses the SKU sub-rows.
    sku_toggle = (
        "document.getElementById('product-trend-mode').addEventListener('change', renderProductTrend);\n"
        "document.getElementById('cust-products').addEventListener('click', (e) => {\n"
        "  const head = e.target.closest('[data-sku-toggle]');\n"
        "  if (!head) return;\n"
        "  const sid = head.getAttribute('data-sku-toggle');\n"
        "  const rows = document.querySelectorAll('#cust-products .' + sid);\n"
        "  let target = null;\n"
        "  rows.forEach(r => { if (target === null) target = !r.hidden; r.hidden = target; });\n"
        "  const caret = head.querySelector('.sku-caret');\n"
        "  if (caret) caret.textContent = target ? '\\u25b8' : '\\u25be';\n"
        "  head.setAttribute('aria-expanded', target ? 'false' : 'true');\n"
        "});\n"
        "document.getElementById('cust-products').addEventListener('keydown', (e) => {\n"
        "  if (e.key !== 'Enter' && e.key !== ' ') return;\n"
        "  const head = e.target.closest('[data-sku-toggle]');\n"
        "  if (!head) return;\n"
        "  e.preventDefault();\n"
        "  head.click();\n"
        "});"
    )
    html = _replace_once(
        html,
        "document.getElementById('product-trend-mode').addEventListener('change', renderProductTrend);",
        sku_toggle,
        "SKU drill-down toggle handler",
    )

    return html


def _weekly_views(html: str) -> str:
    """Render the trend visuals on weekly granularity (monthly view removed).

    The new-format model emits a continuous weekly series (``weekly_enabled``,
    ``week_labels``, ``product_weekly``, ``dfc_total_weekly`` and per-customer
    ``dfc_weekly``/``other_weekly``/``total_weekly``). The three monthly points
    are too coarse — and the most recent month is partial — so the trend line
    charts now render weekly whenever that data is present. There is no
    user-facing monthly/weekly toggle.

    The legacy format omits the weekly series; those exports silently fall back
    to the monthly series rather than rendering blank charts. Runs after
    ``_taxonomy_and_skus`` so it can target that pass's rewritten
    ``renderProductTrend`` body.
    """

    # 1. Relabel the indexed/absolute mode options so they no longer say "month".
    html = _replace_once(
        html,
        '      <select id="product-trend-mode">\n'
        '        <option value="indexed">Indexed to first month (=100)</option>\n'
        '        <option value="absolute" selected>Absolute monthly ACR</option>\n'
        "      </select>",
        '      <select id="product-trend-mode">\n'
        '        <option value="indexed">Indexed to first point (=100)</option>\n'
        '        <option value="absolute" selected>Absolute ACR</option>\n'
        "      </select>",
        "trend mode option relabel",
    )

    # 2. Product trend: prefer the weekly series + week x-axis labels.
    html = _replace_once(
        html,
        "  const tracks = (DATA.track_products && DATA.track_products.length ? DATA.track_products : TRACK_PRODUCTS)\n"
        "    .filter(p => DATA.product_monthly[p]);\n"
        "  const colorFor = p => { const c = (DATA.product_colors && DATA.product_colors[p]) || PRODUCT_COLORS[p] || '#605e5c'; return /^#[0-9a-fA-F]{6}$/.test(c) ? c : '#605e5c'; };\n"
        "  const series = tracks.map(p => ({label: p, values: DATA.product_monthly[p], color: colorFor(p)}));\n"
        "  lineChart('chart-product-trend', series, {indexed: mode === 'indexed', width: 1600, height: 300});",
        "  const weekly = !!(DATA.weekly_enabled && DATA.product_weekly);\n"
        "  const src = weekly ? DATA.product_weekly : DATA.product_monthly;\n"
        "  const labels = weekly ? DATA.week_labels : DATA.month_labels;\n"
        "  const tracks = (DATA.track_products && DATA.track_products.length ? DATA.track_products : TRACK_PRODUCTS)\n"
        "    .filter(p => src[p]);\n"
        "  const colorFor = p => { const c = (DATA.product_colors && DATA.product_colors[p]) || PRODUCT_COLORS[p] || '#605e5c'; return /^#[0-9a-fA-F]{6}$/.test(c) ? c : '#605e5c'; };\n"
        "  const series = tracks.map(p => ({label: p, values: src[p], color: colorFor(p)}));\n"
        "  lineChart('chart-product-trend', series, {indexed: mode === 'indexed', width: 1600, height: 300, labels, partialIdx: weekly ? -1 : DATA.partial_month_idx});",
        "weekly product trend series",
    )

    # 3. Inject a weekly-preferring overview DfC trend helper.
    html = _replace_once(
        html,
        "function renderProductTrend() {",
        "function renderDfcTrend() {\n"
        "  const weekly = !!(DATA.weekly_enabled && DATA.dfc_total_weekly);\n"
        "  const values = weekly ? DATA.dfc_total_weekly : DATA.dfc_total_monthly;\n"
        "  const labels = weekly ? DATA.week_labels : DATA.month_labels;\n"
        "  lineChart('chart-dfc-trend', [{label: 'Defender for Cloud', values, color: '#0078d4'}], {labels, partialIdx: weekly ? -1 : DATA.partial_month_idx});\n"
        "}\n\n"
        "function renderProductTrend() {",
        "weekly-preferring overview DfC trend",
    )

    # 4. renderAll: route the DfC overview trend through the helper.
    html = _replace_once(
        html,
        "  renderKpis();\n"
        "  lineChart('chart-dfc-trend', [{label: 'Defender for Cloud', values: DATA.dfc_total_monthly, color: '#0078d4'}]);",
        "  renderKpis();\n"
        "  renderDfcTrend();",
        "renderAll DfC trend routing",
    )

    # 6. lineChart partial-month marker: honour an explicit opts.partialIdx so
    #    weekly charts (which pass -1) don't stamp the red "*" onto an arbitrary
    #    week. Monthly fallback callers omit it and keep DATA.partial_month_idx.
    html = _replace_once(
        html,
        "  labels.forEach((l, i) => {\n"
        "    const isPartial = i === DATA.partial_month_idx;",
        "  const partialIdx = (opts.partialIdx != null) ? opts.partialIdx : DATA.partial_month_idx;\n"
        "  labels.forEach((l, i) => {\n"
        "    const isPartial = i === partialIdx;",
        "lineChart opts.partialIdx",
    )

    # 7. Relabel chart titles/subtitles that hard-code "monthly"; these trend
    #    charts now render weekly points (with a silent monthly fallback for
    #    legacy exports), so neutral wording avoids a misleading label.
    html = _replace_once(
        html,
        '      <div class="title">Defender for Cloud — Monthly ACR across all customers</div>\n'
        '      <div class="sub">Sum of monthly ACR by month</div>',
        '      <div class="title">Defender for Cloud — ACR across all customers</div>\n'
        '      <div class="sub">ACR trend (weekly where available)</div>',
        "dfc trend title relabel",
    )
    html = _replace_once(
        html,
        '    <div class="title">Product mix — monthly ACR trend by service</div>',
        '    <div class="title">Product mix — ACR trend by service</div>',
        "product trend title relabel",
    )

    # 8. DfC penetration chart removed: the percent-format lineChart transforms
    #    that supported it are gone, so the base lineChart stays dollar-only.

    return html


def _product_mix_donut(html: str) -> str:
    """Overview GUI change: replace the product-mix line chart with a donut.

    Runs AFTER ``_weekly_views`` so every needle byte-matches the
    post-weekly-views text. Three structural moves on the overview page:

    1. The ``grid-2`` row keeps the weekly total-ACR line chart on the left
       and gains a product-mix **donut** on the right (replacing Top 15).
    2. The standalone product-trend *line* box below becomes the full-width
       **Top 15** box.
    3. ``renderProductTrend`` (a line chart over time) is replaced by
       ``renderProductMix`` (share-of-ACR donut), a ``donutChart`` SVG helper
       is injected, ``renderAll`` calls the new renderer, and the now-dead
       ``product-trend-mode`` change listener is removed.
    """
    # 1) grid-2 right cell: Top 15 box -> product-mix donut box.
    html = _replace_once(
        html,
        (
            '    <div class="chart-box">\n'
            '      <div class="title">Top 15 customers by Defender for Cloud monthly ACR</div>\n'
            '      <div class="sub">Click a bar to drill down</div>\n'
            '      <div class="svg-container" id="chart-top-dfc"></div>\n'
            "    </div>"
        ),
        (
            '    <div class="chart-box">\n'
            '      <div class="title">Product mix — share of ACR by service</div>\n'
            '      <div class="sub">ACR split across tracked workloads (weekly where available)</div>\n'
            '      <div class="svg-container" id="chart-product-mix"></div>\n'
            '      <div class="legend" id="legend-product-mix"></div>\n'
            "    </div>"
        ),
        "overview grid-2 donut swap",
    )

    # 2) standalone product-trend line box -> full-width Top 15 box.
    html = _replace_once(
        html,
        (
            '  <div class="chart-box">\n'
            '    <div class="title">Product mix — ACR trend by service</div>\n'
            '    <div class="sub">Compare DfC against Azure Virtual Desktop, General Purpose Compute, and other workloads</div>\n'
            '    <div class="controls">\n'
            "      <label>Show: </label>\n"
            '      <select id="product-trend-mode">\n'
            '        <option value="indexed">Indexed to first point (=100)</option>\n'
            '        <option value="absolute" selected>Absolute ACR</option>\n'
            "      </select>\n"
            "    </div>\n"
            '    <div class="svg-container" id="chart-product-trend"></div>\n'
            '    <div class="legend" id="legend-product-trend"></div>\n'
            "  </div>"
        ),
        (
            '  <div class="chart-box">\n'
            '    <div class="title">Top 15 customers by Defender for Cloud monthly ACR</div>\n'
            '    <div class="sub">Click a bar to drill down</div>\n'
            '    <div class="svg-container" id="chart-top-dfc"></div>\n'
            "  </div>"
        ),
        "overview product-trend box -> top15",
    )

    # 3a) Replace renderProductTrend (line-over-time) with renderProductMix (donut).
    html = _replace_once(
        html,
        (
            "function renderProductTrend() {\n"
            "  const mode = document.getElementById('product-trend-mode').value;\n"
            "  const weekly = !!(DATA.weekly_enabled && DATA.product_weekly);\n"
            "  const src = weekly ? DATA.product_weekly : DATA.product_monthly;\n"
            "  const labels = weekly ? DATA.week_labels : DATA.month_labels;\n"
            "  const tracks = (DATA.track_products && DATA.track_products.length ? DATA.track_products : TRACK_PRODUCTS)\n"
            "    .filter(p => src[p]);\n"
            "  const colorFor = p => { const c = (DATA.product_colors && DATA.product_colors[p]) || PRODUCT_COLORS[p] || '#605e5c'; return /^#[0-9a-fA-F]{6}$/.test(c) ? c : '#605e5c'; };\n"
            "  const series = tracks.map(p => ({label: p, values: src[p], color: colorFor(p)}));\n"
            "  lineChart('chart-product-trend', series, {indexed: mode === 'indexed', width: 1600, height: 300, labels, partialIdx: weekly ? -1 : DATA.partial_month_idx});\n"
            "  document.getElementById('legend-product-trend').innerHTML = tracks.map(p =>\n"
            "    `<span class=\"legend-item\"><span class=\"legend-swatch\" style=\"background:${colorFor(p)}\"></span>${escapeHtml(p)}</span>`).join('');\n"
            "}"
        ),
        (
            "// Pure selection + reconciliation math for the product-mix donut. Kept separate from\n"
            "// the DOM rendering so it can be unit-tested in isolation. Takes the monthly category\n"
            "// series (DATA.product_monthly) + the partial/accumulating month index; returns the\n"
            "// drillable slices (`items`), the categories folded into 'Other' (`otherCats`), and the\n"
            "// reconciliation totals. Donut shows AVERAGE MONTHLY ACR share across COMPLETE months\n"
            "// only (the partial last month is excluded), so the centre equals a representative\n"
            "// monthly ACR, not a cumulative period total. Slices = top categories by avg monthly\n"
            "// ACR (Defender for Cloud is always pinned in) up to a cap; everything below the cap\n"
            "// rolls into an 'Other services' slice so the slices sum to the true total. Decoupled\n"
            "// from DATA.track_products (the 8-cap used by the taxonomy trend / SKU drill-down) so\n"
            "// large real categories (Storage, Networking, ...) surface here instead of hiding.\n"
            "function computeDonutSlices(src, partial) {\n"
            "  src = src || {};\n"
            "  const DFC = 'Defender for Cloud';\n"
            "  const MAX_SLICES = 12;\n"
            "  const p = (typeof partial === 'number') ? partial : -1;\n"
            "  const avgOf = a => { const arr = Array.isArray(a) ? a : []; const vals = arr.filter((_, i) => i !== p); if (!vals.length) return 0; return vals.reduce((s, v) => s + (Number(v) || 0), 0) / vals.length; };\n"
            "  const isHex = c => /^#[0-9a-fA-F]{6}$/.test(c);\n"
            "  // Deterministic palette by rank; DfC (#0078d4) and Sentinel (#005a9e) keep their\n"
            "  // brand colours and are intentionally excluded from the rotation to avoid collisions.\n"
            "  const PALETTE = ['#107c10','#5c2d91','#d83b01','#008272','#a4262c','#c19c00','#004e8c','#874800','#5d5a58','#018574','#8764b8','#e3008c'];\n"
            "  const colorFor = (label, rank) => { if (label === DFC) return '#0078d4'; if (label === 'Sentinel') return '#005a9e'; const c = PALETTE[rank % PALETTE.length]; return isHex(c) ? c : '#605e5c'; };\n"
            "  const all = Object.keys(src).filter(k => k !== 'Total')\n"
            "    .map(k => ({label: k, value: avgOf(src[k])}))\n"
            "    .filter(d => d.value > 0)\n"
            "    .sort((a, b) => b.value - a.value);\n"
            "  const named = all.slice(0, MAX_SLICES);\n"
            "  // Pin Defender for Cloud: if it ranks below the cap, swap it in for the lowest named.\n"
            "  const dfc = all.find(d => d.label === DFC);\n"
            "  if (dfc && named.indexOf(dfc) === -1 && named.length) { named[named.length - 1] = dfc; named.sort((a, b) => b.value - a.value); }\n"
            "  const namedLabels = new Set(named.map(d => d.label));\n"
            "  const items = named.map((d, i) => ({label: d.label, value: d.value, color: colorFor(d.label, i)}));\n"
            "  const totalAvg = avgOf(src['Total']);\n"
            "  const namedSum = items.reduce((s, d) => s + d.value, 0);\n"
            "  const otherVal = Math.max(0, totalAvg - namedSum);\n"
            "  // Stash the categories that fold into 'Other' (plus any total-vs-leaf residual) so the\n"
            "  // Other slice's drill-down reconciles to the slice value.\n"
            "  const tail = all.filter(d => !namedLabels.has(d.label));\n"
            "  const tailSum = tail.reduce((s, d) => s + d.value, 0);\n"
            "  const otherCats = tail.map(d => ({label: d.label, value: d.value}));\n"
            "  if (otherVal - tailSum > 1) otherCats.push({label: 'Unmapped / residual', value: otherVal - tailSum});\n"
            "  if (otherVal > 1) items.push({label: 'Other services', value: otherVal, color: '#c8c6c4'});\n"
            "  return {items: items, otherCats: otherCats, totalAvg: totalAvg, otherVal: otherVal};\n"
            "}\n"
            "function renderProductMix() {\n"
            "  // Each slice is drillable into its underlying services (see donutChart + the\n"
            "  // category modal). All selection/reconciliation math lives in computeDonutSlices.\n"
            "  const r = computeDonutSlices(DATA.product_monthly, DATA.partial_month_idx);\n"
            "  window._donutOtherCats = r.otherCats;\n"
            "  donutChart('chart-product-mix', r.items);\n"
            "  document.getElementById('legend-product-mix').innerHTML = r.items.map(d =>\n"
            "    `<span class=\"legend-item\"><span class=\"legend-swatch\" style=\"background:${d.color}\"></span>${escapeHtml(d.label)}</span>`).join('');\n"
            "}"
        ),
        "renderProductTrend -> renderProductMix",
    )

    # 3b) Inject the donutChart SVG helper just before lineChart.
    html = _replace_once(
        html,
        "function lineChart(containerId, series, opts = {}) {",
        (
            "function donutChart(containerId, items, opts = {}) {\n"
            "  const el = document.getElementById(containerId);\n"
            "  if (!el) return;\n"
            "  const W = opts.width || 600, H = opts.height || 260;\n"
            "  const cx = W / 2, cy = H / 2;\n"
            "  const rOuter = Math.min(W, H) / 2 - 14, rInner = rOuter * 0.6;\n"
            "  const total = items.reduce((a, d) => a + (Number(d.value) || 0), 0);\n"
            "  if (!(total > 0)) {\n"
            "    el.innerHTML = '<div style=\"padding:40px;text-align:center;color:#a19f9d;font-size:12px;\">No service ACR to display</div>';\n"
            "    return;\n"
            "  }\n"
            "  const totalLbl = total >= 1e6 ? '$' + (total / 1e6).toFixed(2) + 'M' : total >= 1000 ? '$' + (total / 1000).toFixed(1) + 'k' : '$' + total.toFixed(0);\n"
            "  let svg = `<svg viewBox=\"0 0 ${W} ${H}\" xmlns=\"http://www.w3.org/2000/svg\">`;\n"
            "  if (items.length === 1) {\n"
            "    const d = items[0];\n"
            "    svg += `<circle cx=\"${cx}\" cy=\"${cy}\" r=\"${rOuter}\" fill=\"${d.color}\" data-label=\"${escapeHtml(d.label)}\" data-val=\"${(Number(d.value) || 0).toFixed(2)}\" data-pct=\"100.0\" style=\"cursor:pointer\"/>`;\n"
            "    svg += `<circle cx=\"${cx}\" cy=\"${cy}\" r=\"${rInner}\" fill=\"#ffffff\"/>`;\n"
            "  } else {\n"
            "    let a0 = -Math.PI / 2;\n"
            "    items.forEach(d => {\n"
            "      const frac = (Number(d.value) || 0) / total;\n"
            "      const a1 = a0 + frac * Math.PI * 2;\n"
            "      const large = (a1 - a0) > Math.PI ? 1 : 0;\n"
            "      const xo0 = cx + rOuter * Math.cos(a0), yo0 = cy + rOuter * Math.sin(a0);\n"
            "      const xo1 = cx + rOuter * Math.cos(a1), yo1 = cy + rOuter * Math.sin(a1);\n"
            "      const xi1 = cx + rInner * Math.cos(a1), yi1 = cy + rInner * Math.sin(a1);\n"
            "      const xi0 = cx + rInner * Math.cos(a0), yi0 = cy + rInner * Math.sin(a0);\n"
            "      const dPath = `M${xo0.toFixed(2)},${yo0.toFixed(2)} A${rOuter},${rOuter} 0 ${large} 1 ${xo1.toFixed(2)},${yo1.toFixed(2)} L${xi1.toFixed(2)},${yi1.toFixed(2)} A${rInner},${rInner} 0 ${large} 0 ${xi0.toFixed(2)},${yi0.toFixed(2)} Z`;\n"
            "      svg += `<path d=\"${dPath}\" fill=\"${d.color}\" stroke=\"#ffffff\" stroke-width=\"1.5\" data-label=\"${escapeHtml(d.label)}\" data-val=\"${(Number(d.value) || 0).toFixed(2)}\" data-pct=\"${(frac * 100).toFixed(1)}\" style=\"cursor:pointer\"/>`;\n"
            "      a0 = a1;\n"
            "    });\n"
            "  }\n"
            "  svg += `<text x=\"${cx}\" y=\"${cy - 2}\" text-anchor=\"middle\" font-size=\"15\" font-weight=\"700\" fill=\"#323130\">${totalLbl}</text>`;\n"
            "  svg += `<text x=\"${cx}\" y=\"${cy + 15}\" text-anchor=\"middle\" font-size=\"10\" fill=\"#605e5c\">avg monthly ACR</text>`;\n"
            "  svg += `</svg>`;\n"
            "  el.innerHTML = svg;\n"
            "  el.querySelectorAll('[data-label]').forEach(seg => {\n"
            "    seg.addEventListener('mousemove', e => {\n"
            "      const label = seg.getAttribute('data-label');\n"
            "      const val = parseFloat(seg.getAttribute('data-val'));\n"
            "      const pct = seg.getAttribute('data-pct');\n"
            "      showTooltip(`<b>${escapeHtml(label)}</b><br/>$${val.toLocaleString('en-US', {maximumFractionDigits: 0})} avg/mo · ${pct}%`, e.pageX, e.pageY);\n"
            "    });\n"
            "    seg.addEventListener('mouseleave', hideTooltip);\n"
            "    // Drill-down: each slice opens its underlying services. Keyboard-accessible.\n"
            "    const lbl = seg.getAttribute('data-label');\n"
            "    seg.setAttribute('tabindex', '0');\n"
            "    seg.setAttribute('role', 'button');\n"
            "    seg.setAttribute('aria-label', 'Show services in ' + lbl);\n"
            "    seg.addEventListener('click', () => { if (typeof openCategoryBreakdown === 'function') openCategoryBreakdown(seg.getAttribute('data-label')); });\n"
            "    seg.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') { e.preventDefault(); if (typeof openCategoryBreakdown === 'function') openCategoryBreakdown(seg.getAttribute('data-label')); } });\n"
            "  });\n"
            "}\n\n"
            "function lineChart(containerId, series, opts = {}) {"
        ),
        "inject donutChart helper",
    )

    # 3c) renderAll: call renderProductMix instead of renderProductTrend.
    html = _replace_once(
        html,
        "  renderProductTrend();",
        "  renderProductMix();",
        "renderAll product-mix call",
    )

    # 3d) Remove the now-dead product-trend-mode change listener.
    html = _replace_once(
        html,
        "document.getElementById('product-trend-mode').addEventListener('change', renderProductTrend);\n",
        "",
        "remove product-trend-mode listener",
    )

    return html


def _harden_charts(html: str) -> str:
    """Escape Excel-derived customer labels in the SVG chart helpers.

    Three chart functions (``barChartHorizontal`` and the two ``quadrantChart``
    definitions) interpolate the customer name into:

    * an SVG ``<text>`` body that is written via ``element.innerHTML = svg``
    * a ``data-customer="…"`` attribute (originally escaped only ``"``)
    * a tooltip body read back with ``getAttribute('data-customer')`` and
      handed to ``showTooltip(html)`` which does ``innerHTML = html``

    A workbook with a label like ``<img src=x onerror=alert(1)>`` would
    execute in all three sinks. We funnel every interpolation through the
    shared ``escapeHtml`` helper.
    """

    # 1. Bar chart: SVG <text> body with the (optionally truncated) label.
    html = _replace_exact(
        html,
        ">${d.label.length > 28 ? d.label.slice(0, 28) + '…' : d.label}</text>",
        ">${escapeHtml(d.label.length > 28 ? d.label.slice(0, 28) + '…' : d.label)}</text>",
        "bar chart label text",
        1,
    )

    # 2. Bar chart: data-customer attribute (was escaping only ").
    html = _replace_exact(
        html,
        'data-customer="${d.label.replace(/"/g, \'&quot;\')}"',
        'data-customer="${escapeHtml(d.label)}"',
        "bar chart data-customer attribute",
        1,
    )

    # 3. Quadrant charts (both): data-customer attribute on the bubble circle.
    html = _replace_exact(
        html,
        'data-customer="${p.label.replace(/"/g, \'&quot;\')}"',
        'data-customer="${escapeHtml(p.label)}"',
        "quadrant chart data-customer attribute",
        2,
    )

    # 4. Quadrant charts (both): direct SVG <text> label for the top N bubbles.
    html = _replace_exact(
        html,
        ">${truncated}</text>",
        ">${escapeHtml(truncated)}</text>",
        "quadrant chart direct label",
        2,
    )

    # 5. Bar chart tooltip: <b>${r.getAttribute('data-customer')}</b>
    html = _replace_exact(
        html,
        "<b>${r.getAttribute('data-customer')}</b>",
        "<b>${escapeHtml(r.getAttribute('data-customer'))}</b>",
        "bar chart tooltip customer",
        1,
    )

    # 6. Quadrant chart tooltips (both): <b>${c.getAttribute('data-customer')}</b>
    html = _replace_exact(
        html,
        "<b>${c.getAttribute('data-customer')}</b>",
        "<b>${escapeHtml(c.getAttribute('data-customer'))}</b>",
        "quadrant chart tooltip customer",
        2,
    )

    # 7. Line chart: data-label attribute on each point (Excel-derived product/SKU
    #    names in the new format flow in here via renderProductTrend's series labels).
    html = _replace_exact(
        html,
        'data-label="${s.label}"',
        'data-label="${escapeHtml(s.label)}"',
        "line chart data-label attribute",
        1,
    )

    # 8. Line chart tooltip: <b>${label}</b> read back from data-label.
    html = _replace_exact(
        html,
        "showTooltip(`<b>${label}</b>",
        "showTooltip(`<b>${escapeHtml(label)}</b>",
        "line chart tooltip label",
        1,
    )

    return html


def _harden_heatmap(html: str) -> str:
    """Escape Excel-derived values rendered into table markup.

    Covers the injected opportunity heatmap, which originally interpolated
    raw workbook strings.
    """

    html = _replace_exact(
        html,
        '<tr class="clickable" data-customer="${r.customer.replace(/"/g, \'&quot;\')}">',
        '<tr class="clickable" data-customer="${escapeHtml(r.customer)}">',
        "row data-customer attribute",
        1,
    )
    html = _replace_exact(
        html,
        "<td><strong>${r.customer}</strong></td>",
        "<td><strong>${escapeHtml(r.customer)}</strong></td>",
        "heatmap customer cell",
        1,
    )
    return html


def _harden_csvcell(html: str) -> str:
    """Add CSV formula-injection protection to the injected csvCell helper."""

    original = (
        "function csvCell(value) {\n"
        "  return `\"${String(value ?? '').replace(/\"/g, '\"\"')}\"`;\n"
        "}"
    )
    hardened = (
        "const CSV_FORMULA_LEADERS = ['=', '+', '-', '@', '\\t', '\\r'];\n"
        "function csvCell(value) {\n"
        "  let s = String(value ?? '');\n"
        "  if (s.length && CSV_FORMULA_LEADERS.includes(s.charAt(0))) {\n"
        "    s = \"'\" + s;\n"
        "  }\n"
        "  return `\"${s.replace(/\"/g, '\"\"')}\"`;\n"
        "}"
    )
    return _replace_once(html, original, hardened, "csvCell helper")


def _threshold_priority(html: str) -> str:
    """Reclassify opportunities at the default attach baseline before first render.

    The model bakes a classification at its 6% default, but renderAll is the
    single source of truth for the live page: it reclassifies against the
    current slider value so KPI counts, tables, and the heatmap all agree on
    load. Slider changes call reclassifyOpportunities again client-side.
    """
    return _replace_once(
        html,
        "function renderAll() {\n"
        "  if (!DATA.customers || DATA.customers.length === 0) return;\n"
        "  renderKpis();",
        "function renderAll() {\n"
        "  if (!DATA.customers || DATA.customers.length === 0) return;\n"
        "  __slDossierMap = null;\n"
        "  reclassifyOpportunities(dfcShareThreshold);\n"
        "  renderKpis();",
        "renderAll baseline reclassify",
    )


def _inject_priority_explainer(html: str) -> str:
    """Make every High/Medium/Low/Too small badge a clickable explainer.

    Clicking a priority badge opens a modal that (a) lists the exact signals
    that produced this customer's rating (parsed from row.notes), (b) shows the
    key numbers behind it, and (c) documents the full grading rubric so a user
    can always audit why a customer is rated the way it is. The grading text is
    threshold-aware (reads the live slider value).

    Implementation notes:
    * ``tagFor`` is reassigned (late-bound by every render fn) to emit an
      accessible, focusable badge. The original is defined earlier in the same
      top-level <script>, so this reassignment wins at runtime.
    * A capture-phase click listener intercepts badge clicks BEFORE the row's
      bubbling ``selectCustomer`` handler, so opening the explainer does not also
      navigate to the drill-down.
    """
    script = r'''
// ---- Priority grading explainer -------------------------------------------
const PRIORITY_META = {
  High:        { color: '#d13438', bg: '#fdf3f4', label: 'High priority' },
  Medium:      { color: '#ff8c00', bg: '#fffaf0', label: 'Medium priority' },
  Low:         { color: '#107c10', bg: '#f3f9ef', label: 'Low priority' },
  'Too small': { color: '#605e5c', bg: '#f3f2f1', label: 'Too small to prioritize' },
};

// Clickable, accessible replacement for the template's tagFor. Late-bound, so
// every render path (tables, heatmap, action queue, drill-down) picks it up.
tagFor = function (opp) {
  const cls = opp === 'High' ? 'high' : opp === 'Medium' ? 'medium' : opp === 'Low' ? 'low' : 'small-tag';
  const safe = escapeHtml(opp);
  return '<span class="tag ' + cls + ' prio-badge" role="button" tabindex="0" ' +
    'title="Why is the priority ' + safe + '? Click for the grading.">' +
    safe + ' <span class="prio-badge-i" aria-hidden="true">&#9432;</span></span>';
};

let _prioOverlay = null;
let _prioLastFocus = null;
function _ensurePrioOverlay() {
  if (_prioOverlay) return _prioOverlay;
  const style = document.createElement('style');
  style.textContent =
    '.prio-badge{cursor:pointer;user-select:none}' +
    '.prio-badge:hover{filter:brightness(.96);box-shadow:0 0 0 1px rgba(0,0,0,.15)}' +
    '.prio-badge:focus-visible{outline:2px solid #0078d4;outline-offset:1px}' +
    '.prio-badge-i{font-size:11px;opacity:.7}' +
    '.prio-overlay{position:fixed;inset:0;background:rgba(15,23,42,.55);display:flex;' +
    'align-items:flex-start;justify-content:center;z-index:4000;padding:40px 16px;overflow:auto}' +
    '.prio-overlay[hidden]{display:none}' +
    '.prio-dialog{position:relative;background:#fff;border-radius:10px;max-width:720px;width:100%;' +
    'box-shadow:0 20px 60px rgba(0,0,0,.3)}' +
    '.prio-close{position:absolute;top:8px;right:12px;border:none;background:transparent;font-size:26px;' +
    'line-height:1;cursor:pointer;color:#605e5c}' +
    '.prio-close:hover{color:#201f1e}' +
    '#prio-body{padding:22px 26px 28px}' +
    '.prio-head{padding:14px 16px;border-radius:6px;margin:6px 0 18px}' +
    '.prio-head-tier{font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.05em}' +
    '.prio-head h2{margin:4px 0 0;font-size:19px;color:#201f1e}' +
    '.prio-head p{margin:6px 0 0;font-size:13px;color:#605e5c;line-height:1.4}' +
    '.prio-section{margin-bottom:18px}' +
    '.prio-section h3{font-size:14px;margin:0 0 8px;color:#201f1e}' +
    '.prio-signals{margin:0;padding-left:18px}' +
    '.prio-signals li{margin-bottom:6px;color:#323130}' +
    '.prio-none{color:#107c10;margin:0}' +
    '.prio-gap-banner{display:flex;flex-wrap:wrap;gap:16px;align-items:baseline;background:#fbf6ff;border:1px solid #e3d3f5;border-radius:8px;padding:12px 14px;margin:0 0 12px}' +
    '.prio-gap-banner .big{font-size:22px;font-weight:700;color:#5c2d91}' +
    '.prio-gap-banner .lbl{font-size:12px;color:#605e5c}' +
    '.prio-gap-banner .sub{font-size:12px;color:#605e5c;flex:1 1 200px}' +
    '.prio-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:0 0 14px}' +
    '.prio-kpi{border:1px solid #eef1f5;border-radius:8px;padding:10px;background:#fff}' +
    '.prio-kpi .big{font-size:19px;font-weight:700;color:#201f1e}.prio-kpi .lbl{font-size:11px;color:#605e5c;margin-top:3px}' +
    '.prio-svc-list{display:flex;flex-direction:column;gap:8px}' +
    '.prio-svc-row{display:flex;justify-content:space-between;gap:10px;align-items:center;border:1px solid #eef1f5;border-radius:6px;padding:8px 10px;flex-wrap:wrap}' +
    '.prio-svc-row .svc{font-weight:600;color:#201f1e}' +
    '.prio-svc-row .nums{font-size:12px;color:#605e5c;margin-top:3px}' +
    '.prio-svc-row .gapv{font-weight:600;white-space:nowrap;font-size:13px}' +
    '.prio-metrics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px 18px}' +
    '.prio-metric{display:flex;justify-content:space-between;gap:12px;border-bottom:1px solid #eef1f5;padding:5px 0;font-size:13px}' +
    '.prio-metric .k{color:#605e5c}.prio-metric .v{font-weight:600;color:#201f1e;text-align:right}' +
    '.prio-rubric-intro{font-size:12px;color:#605e5c;margin:0 0 8px}' +
    '.prio-rubric{list-style:none;margin:0;padding:0}' +
    '.prio-rule{display:flex;gap:10px;align-items:flex-start;padding:7px 8px;border-radius:6px;font-size:13px}' +
    '.prio-rule.current{background:#f5f7fb}' +
    '.prio-pill{flex:0 0 auto;font-size:11px;font-weight:700;padding:2px 8px;border-radius:999px;border:1px solid}' +
    '.prio-rule-text{color:#323130}' +
    '.prio-talktrack{border-left:3px solid #0078d4;background:#f3f9fd;border-radius:6px;padding:10px 12px;color:#323130;font-size:13px;line-height:1.45}' +
    '@media(max-width:720px){.prio-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}' +
    '@media(max-width:560px){.prio-metrics,.prio-kpis{grid-template-columns:1fr}}';
  document.head.appendChild(style);

  const overlay = document.createElement('div');
  overlay.id = 'prio-explainer';
  overlay.className = 'prio-overlay';
  overlay.setAttribute('hidden', '');
  overlay.innerHTML =
    '<div class="prio-dialog" role="dialog" aria-modal="true" aria-labelledby="prio-title">' +
    '<button class="prio-close" type="button" aria-label="Close">&times;</button>' +
    '<div id="prio-body"></div></div>';
  overlay.addEventListener('click', (e) => { if (e.target === overlay) closePriorityExplainer(); });
  overlay.querySelector('.prio-close').addEventListener('click', closePriorityExplainer);
  document.body.appendChild(overlay);
  _prioOverlay = overlay;
  return overlay;
}

function _prioDossier(customer) {
  const sa = (typeof DATA !== 'undefined' && DATA) ? DATA.service_attach : null;
  if (!sa || !Array.isArray(sa.dossiers)) return null;
  return sa.dossiers.find(function (x) { return x.customer === customer; }) || null;
}

function _prioSignalLabel(o) {
  if (!o || !o.hasDollarGap) return 'Needs validation';
  if ((o.defenderActual || 0) <= 0) return 'No attach';
  return 'Under-attached';
}

// Per-service evidence for the priority modal: leads with the concrete
// "you buy X but don't protect X" gaps plus the $ opportunity, so the rating
// is justified by service-level facts rather than the corp total-vs-DfC ratio.
function _prioServiceEvidence(customer) {
  const d = _prioDossier(customer);
  if (!d) return '';
  const opps = (Array.isArray(d.opportunities) ? d.opportunities.slice() : []).sort(function (a, b) {
    return ((a.priorityRank == null ? 9 : a.priorityRank) - (b.priorityRank == null ? 9 : b.priorityRank)) ||
      ((b.blendedScore || 0) - (a.blendedScore || 0));
  });
  if (!opps.length) {
    return '<section class="prio-section"><h3>Service-level evidence</h3>' +
      '<p class="prio-none">No specific per-service Defender gaps \u2014 this customer protects the Azure services they run. ' +
      'Use the customer breakdown for supporting service details.</p></section>';
  }
  const monthly = d.totalGapDollars || 0;
  const annual = monthly * 12;
  const covSignals = opps.filter(function (o) { return !o.hasDollarGap; }).length;
  const measurable = opps.filter(function (o) { return o.hasDollarGap && (o.gapDollars || 0) > 0; }).length;
  const kpis =
    '<div class="prio-kpis">' +
      '<div class="prio-kpi"><div class="big">' + fmt.money(d.eligibleWorkloadAcr || 0) + '</div><div class="lbl">Eligible Azure workload ACR / mo</div></div>' +
      '<div class="prio-kpi"><div class="big">' + fmt.money(d.dfcAcr || 0) + '</div><div class="lbl">Mapped Defender ACR / mo</div></div>' +
      '<div class="prio-kpi"><div class="big">' + fmt.money(monthly) + '</div><div class="lbl">Estimated service gap / mo' + (annual > 0 ? ' \u00b7 ' + fmt.money(annual) + '/yr' : '') + '</div></div>' +
      '<div class="prio-kpi"><div class="big">' + opps.length + '</div><div class="lbl">Services to discuss</div></div>' +
    '</div>';
  const rows = opps.slice(0, 6).map(function (o) {
    const pr = (o.priority || '').toLowerCase();
    const prClass = pr === 'high' ? 'high' : (pr === 'medium' ? 'medium' : 'low');
    const gapStr = o.hasDollarGap ? fmt.money(o.gapDollars) + ' / mo gap' : 'needs validation';
    return '<div class="prio-svc-row">' +
      '<div><span class="tag ' + prClass + '">' + escapeHtml(o.priority || '') + '</span> ' +
        '<span class="svc">' + escapeHtml(o.planLabel) + '</span>' +
        '<div class="nums">' + escapeHtml(_prioSignalLabel(o)) + ' \u00b7 Azure service ' + fmt.money(o.workloadAcr) + ' / mo (' + fmt.pct(o.workloadGrowth) + ' 3M) \u2192 Defender ' + fmt.money(o.defenderActual) + ' / mo</div>' +
      '</div>' +
      '<div class="gapv">' + escapeHtml(gapStr) + '</div>' +
    '</div>';
  }).join('');
  const bullets = opps.slice(0, 4).map(function (o) {
    const signal = _prioSignalLabel(o).toLowerCase();
    const gap = o.hasDollarGap && (o.gapDollars || 0) > 0 ? ' with an estimated ' + fmt.money(o.gapDollars) + '/mo gap' : ' and should be validated for active coverage';
    return '<li>' + escapeHtml(o.planLabel) + ': ' + escapeHtml(signal) + ' on ' + fmt.money(o.workloadAcr) + '/mo Azure service consumption' + escapeHtml(gap) + '.</li>';
  }).join('');
  const lead = opps[0];
  const leadWorkload = lead ? escapeHtml(lead.workloadLabel || lead.planLabel) : 'priority services';
  const talkTrack = '<section class="prio-section"><h3>Suggested seller conversation</h3>' +
    '<div class="prio-talktrack">&ldquo;We noticed material Azure consumption in ' + leadWorkload +
    ', but Defender consumption does not appear to match that usage. Can we review whether these workloads are already protected and where Defender-for-X attach makes sense?&rdquo;</div></section>';
  return '<section class="prio-section"><h3>Service-level summary</h3>' + kpis +
    '<p class="prio-rubric-intro">' + measurable + ' quantified gap' + (measurable === 1 ? '' : 's') +
      (covSignals > 0 ? ' plus ' + covSignals + ' usage-priced service' + (covSignals === 1 ? '' : 's') + ' where coverage should be validated.' : '.') +
    '</p></section>' +
    '<section class="prio-section"><h3>Top service attach gaps</h3><div class="prio-svc-list">' + rows + '</div></section>' +
    '<section class="prio-section"><h3>Why this is a priority</h3><ul class="prio-signals">' + bullets + '</ul></section>' +
    talkTrack;
}

function openPriorityExplainer(customer) {
  if (!DATA || !Array.isArray(DATA.opportunity)) return;
  const row = DATA.opportunity.find(r => r.customer === customer);
  if (!row) return;
  const overlay = _ensurePrioOverlay();
  // In SL2/SL4 mode the headline rating is the per-service Defender priority
  // (the same value the opportunity-map row pill shows), NOT the legacy
  // corp-level row.opportunity. This keeps the modal header consistent with
  // the matrix; the corp rating is still explained below as a separate signal.
  const sl = (typeof slAttach === 'function') ? slAttach(customer) : null;
  const ratingTier = sl ? sl.priority : row.opportunity;
  const meta = PRIORITY_META[ratingTier] || PRIORITY_META.Low;
  const dossier = _prioDossier(customer);
  const svcEvidenceHtml = _prioServiceEvidence(customer);
  const headline = dossier
    ? escapeHtml(customer) + ' has material Azure service consumption with low or missing matching Defender-for-X consumption.'
    : 'Use this explanation to review why the customer is prioritized.';

  document.getElementById('prio-body').innerHTML =
    '<div class="prio-head" style="border-left:6px solid ' + meta.color + ';background:' + meta.bg + ';">' +
      '<div class="prio-head-tier" style="color:' + meta.color + ';">' + escapeHtml(meta.label) + '</div>' +
      '<h2 id="prio-title">Why ' + escapeHtml(customer) + ' is a ' + escapeHtml(ratingTier) + ' service attach opportunity</h2>' +
      '<p>' + headline + '</p>' +
    '</div>' +
    (svcEvidenceHtml || '<section class="prio-section"><h3>Priority notes</h3><p class="prio-rubric-intro">' + escapeHtml(row.notes || 'No service-level dossier is available for this import.') + '</p></section>');
  overlay.removeAttribute('hidden');
  const closeBtn = overlay.querySelector('.prio-close');
  if (closeBtn) closeBtn.focus();
}

function closePriorityExplainer() {
  if (_prioOverlay) _prioOverlay.setAttribute('hidden', '');
  // Restore focus to the badge that opened the modal so keyboard users are not stranded.
  if (_prioLastFocus && typeof _prioLastFocus.focus === 'function') {
    try { _prioLastFocus.focus(); } catch (_) {}
  }
  _prioLastFocus = null;
}

function _prioBadgeCustomer(el) {
  const rowEl = el.closest('[data-customer]');
  if (rowEl) return rowEl.getAttribute('data-customer');
  const sel = document.getElementById('customer-select');
  return (sel && sel.value) ? sel.value : null;
}

// Capture phase: intercept before the row's bubbling selectCustomer handler so
// a badge click opens the explainer instead of navigating to the drill-down.
document.addEventListener('click', function (e) {
  const badge = e.target.closest ? e.target.closest('.prio-badge') : null;
  if (!badge) return;
  e.stopPropagation();
  e.preventDefault();
  _prioLastFocus = badge;
  const customer = _prioBadgeCustomer(badge);
  if (customer) openPriorityExplainer(customer);
}, true);

document.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') { closePriorityExplainer(); return; }
  const isBadge = e.target.classList && e.target.classList.contains('prio-badge');
  if (isBadge && (e.key === 'Enter' || e.key === ' ')) {
    e.preventDefault();
    e.stopPropagation();
    _prioLastFocus = e.target;
    const customer = _prioBadgeCustomer(e.target);
    if (customer) openPriorityExplainer(customer);
  }
}, true);

'''
    return _replace_once(
        html,
        "function renderAll() {",
        script + "\nfunction renderAll() {",
        "priority explainer injection point",
    )


def _inject_customer_modal(html: str) -> str:
    """Open a customer-breakdown splash modal from the Opportunity Matrix.

    On the Opportunity Matrix page, clicking a customer (heatmap row or action
    queue row) used to navigate to the Customer Drill-Down tab. Instead we now
    pop a modal that reuses the drill-down renderer to show that customer's full
    breakdown in place.

    Implementation notes:
    * ``renderCustomerDetail`` is refactored to accept an id-prefix (``idp``) so
      it can target either the drill-down panel (no prefix) or the modal's
      ``m-``-prefixed clones. The same refactor escapes ``opp.notes`` (a
      DOM-XSS sink that previously interpolated Excel-derived text raw).
    * A single capture-phase click listener on ``document`` intercepts customer
      clicks within the Opportunity Matrix before the target's
      bubbling ``selectCustomer`` handler runs, so no navigation happens. It
      early-returns on ``.prio-badge`` so the priority explainer still wins.
    * This pass runs AFTER ``_inject_priority_explainer`` so its document
      listeners register after the explainer's; in the capture phase that means
      both fire and each skips the other's targets. A window-capture sentinel
      disambiguates a single Escape press when both modals are stacked.
    """
    # --- Refactor renderCustomerDetail to accept an id-prefix + escape notes. --
    html = _replace_once(
        html,
        "function renderCustomerDetail(name) {",
        "function renderCustomerDetail(name, idp) {\n  idp = idp || '';",
        "renderCustomerDetail idp signature",
    )
    html = _replace_once(
        html,
        "document.getElementById('cust-priority').innerHTML = tagFor(opp.opportunity);",
        "var _slPrio = (typeof slAttach === 'function') ? slAttach(name) : null;\n"
        "  document.getElementById(idp + 'cust-priority').innerHTML = tagFor(_slPrio ? _slPrio.priority : opp.opportunity);",
        "cust-priority id prefix",
    )
    html = _replace_once(
        html,
        "document.getElementById('cust-cards').innerHTML = `",
        "document.getElementById(idp + 'cust-cards').innerHTML = `",
        "cust-cards id prefix",
    )
    html = _replace_once(
        html,
        "const note = document.getElementById('cust-signal');",
        "const note = document.getElementById(idp + 'cust-signal');",
        "cust-signal id prefix",
    )
    html = _replace_once(
        html,
        "note.innerHTML = `<strong>Signal:</strong> ${opp.notes}`;",
        "note.innerHTML = `<strong>Signal:</strong> ${escapeHtml(opp.notes)}`;",
        "escape drill-down signal note (XSS)",
    )
    html = _replace_once(
        html,
        "const ph = document.getElementById('cust-products');",
        "const ph = document.getElementById(idp + 'cust-products');",
        "cust-products id prefix",
    )

    script = r'''
// ---- Customer breakdown modal (Opportunity Matrix) ------------------------
let _custOverlay = null;
let _custLastFocus = null;
let _custPrioWasOpenOnEscape = false;

function _ensureCustOverlay() {
  if (_custOverlay) return _custOverlay;
  const style = document.createElement('style');
  style.textContent =
    '.cust-overlay{position:fixed;inset:0;background:rgba(15,23,42,.55);display:flex;' +
    'align-items:flex-start;justify-content:center;z-index:3900;padding:40px 16px;overflow:auto}' +
    '.cust-overlay[hidden]{display:none}' +
    '.cust-dialog{position:relative;background:#faf9f8;border-radius:10px;max-width:1040px;width:100%;' +
    'box-shadow:0 20px 60px rgba(0,0,0,.3)}' +
    '.cust-close{position:absolute;top:8px;right:14px;border:none;background:transparent;font-size:28px;' +
    'line-height:1;cursor:pointer;color:#605e5c;z-index:1}' +
    '.cust-close:hover{color:#201f1e}' +
    '.cust-close:focus-visible{outline:2px solid #0078d4;outline-offset:1px}' +
    '.cust-body{padding:22px 26px 28px}' +
    '.cust-body h2{margin:0 0 16px;font-size:20px;color:#201f1e;padding-right:32px}';
  document.head.appendChild(style);

  const overlay = document.createElement('div');
  overlay.id = 'cust-modal';
  overlay.className = 'cust-overlay';
  overlay.setAttribute('hidden', '');
  overlay.innerHTML =
    '<div class="cust-dialog" role="dialog" aria-modal="true" aria-labelledby="m-cust-title" data-customer="">' +
    '<button class="cust-close" type="button" aria-label="Close">&times;</button>' +
    '<div class="cust-body">' +
      '<h2 id="m-cust-title"></h2>' +
      '<div class="controls" style="margin-bottom:14px;"><span id="m-cust-priority"></span></div>' +
      '<div class="cards" id="m-cust-cards"></div>' +
      '<div class="note" id="m-cust-signal"></div>' +
      '<div class="chart-box">' +
        '<div class="title">Product breakdown</div>' +
        '<div class="sub">Azure service categories ranked by current monthly ACR. Click a category to reveal the Service Level 4 details from the workbook.</div>' +
        '<div id="m-cust-products"></div>' +
      '</div>' +
    '</div></div>';
  overlay.addEventListener('click', (e) => { if (e.target === overlay) closeCustomerModal(); });
  overlay.querySelector('.cust-close').addEventListener('click', closeCustomerModal);

  // SKU drill-down toggle scoped to the modal's product table (mirrors the
  // drill-down panel listener but rooted at #m-cust-products).
  const mprod = overlay.querySelector('#m-cust-products');
  mprod.addEventListener('click', (e) => {
    const head = e.target.closest('[data-sku-toggle]');
    if (!head || !mprod.contains(head)) return;
    const sid = head.getAttribute('data-sku-toggle');
    const rows = mprod.querySelectorAll('.' + sid);
    let target = null;
    rows.forEach(r => { if (target === null) target = !r.hidden; r.hidden = target; });
    const caret = head.querySelector('.sku-caret');
    if (caret) caret.textContent = target ? '\u25b8' : '\u25be';
    head.setAttribute('aria-expanded', target ? 'false' : 'true');
  });
  mprod.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const head = e.target.closest('[data-sku-toggle]');
    if (!head || !mprod.contains(head)) return;
    e.preventDefault();
    head.click();
  });

  // Lightweight focus trap so keyboard users stay within the dialog.
  overlay.addEventListener('keydown', (e) => {
    if (e.key !== 'Tab') return;
    const nodes = overlay.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
    const focusable = Array.prototype.filter.call(nodes, el => !el.disabled && el.offsetParent !== null);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });

  document.body.appendChild(overlay);
  _custOverlay = overlay;
  return overlay;
}

function openCustomerModal(name) {
  if (!DATA || !Array.isArray(DATA.opportunity) || !DATA.customer_data) return;
  const opp = DATA.opportunity.find(r => r.customer === name);
  const cd = DATA.customer_data[name];
  if (!opp || !cd) return;
  const overlay = _ensureCustOverlay();
  // Stamp the customer on the dialog so the priority badge's data-customer
  // lookup (el.closest('[data-customer]')) resolves inside the modal.
  overlay.querySelector('.cust-dialog').setAttribute('data-customer', name);
  const title = document.getElementById('m-cust-title');
  if (title) title.textContent = name;
  renderCustomerDetail(name, 'm-');
  overlay.removeAttribute('hidden');
  const closeBtn = overlay.querySelector('.cust-close');
  if (closeBtn) closeBtn.focus();
}

function closeCustomerModal() {
  if (_custOverlay) _custOverlay.setAttribute('hidden', '');
  if (_custLastFocus && typeof _custLastFocus.focus === 'function') {
    try { _custLastFocus.focus(); } catch (_) {}
  }
  _custLastFocus = null;
}

// Capture phase: intercept a customer click in the Opportunity Matrix (heatmap/
// scatter + action queue) or the Overview top-customers chart before the
// element's own selectCustomer handler so the breakdown opens in a modal instead of
// navigating to the drill-down tab. Priority badges are skipped so the priority
// explainer still wins.
document.addEventListener('click', function (e) {
  if (!e.target.closest) return;
  if (e.target.closest('.prio-badge')) return;
  const el = e.target.closest('#chart-quadrant [data-customer], #chart-top-dfc [data-customer], #action-queue tr[data-customer]');
  if (!el) return;
  const name = el.getAttribute('data-customer');
  if (!name) return;
  e.stopPropagation();
  e.preventDefault();
  _custLastFocus = (typeof el.focus === 'function') ? el : null;
  openCustomerModal(name);
}, true);

// Keyboard access for the same customer targets. SVG <rect>/<circle> bubbles and
// table <tr> rows are not natively focusable, so a tabindex + button role +
// aria-label is added after every render. MutationObservers scoped to the three
// host containers re-apply this whenever their contents are re-rendered (tab
// switch, data reload), and an initial pass covers anything already drawn.
function _enhanceCustomerTargetsA11y() {
  const nodes = document.querySelectorAll('#chart-quadrant [data-customer], #chart-top-dfc [data-customer], #action-queue tr[data-customer]');
  for (let i = 0; i < nodes.length; i++) {
    const n = nodes[i];
    if (n.getAttribute('tabindex') === null) n.setAttribute('tabindex', '0');
    // Bubbles/bars (SVG shapes) become buttons; table rows keep their row/cell
    // semantics (a "button" role would hide the per-column data from AT) and are
    // simply made focusable + labelled.
    if (n.tagName !== 'TR' && !n.getAttribute('role')) n.setAttribute('role', 'button');
    const nm = n.getAttribute('data-customer');
    if (nm && !n.getAttribute('aria-label')) n.setAttribute('aria-label', 'Open breakdown for ' + nm);
  }
}
['chart-quadrant', 'chart-top-dfc', 'action-queue'].forEach(function (id) {
  const host = document.getElementById(id);
  if (!host || typeof MutationObserver !== 'function') return;
  new MutationObserver(_enhanceCustomerTargetsA11y).observe(host, { childList: true, subtree: true });
});
_enhanceCustomerTargetsA11y();

// Enter/Space on a focused customer target opens the modal (mirrors the click
// interceptor). Priority badges keep their own keyboard handling, so they are
// skipped here too.
document.addEventListener('keydown', function (e) {
  if (e.key !== 'Enter' && e.key !== ' ' && e.key !== 'Spacebar') return;
  if (!e.target.closest) return;
  if (e.target.closest('.prio-badge')) return;
  const el = e.target.closest('#chart-quadrant [data-customer], #chart-top-dfc [data-customer], #action-queue tr[data-customer]');
  if (!el) return;
  const name = el.getAttribute('data-customer');
  if (!name) return;
  e.stopPropagation();
  e.preventDefault();
  _custLastFocus = (typeof el.focus === 'function') ? el : null;
  openCustomerModal(name);
}, true);

// Escape closes the customer modal. A window-capture sentinel (fires before any
// document-capture handler) records whether the priority explainer was the
// modal being dismissed by this same key press, so a stacked Escape does not
// also close the customer modal underneath it.
window.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') {
    _custPrioWasOpenOnEscape = (typeof _prioOverlay !== 'undefined') && !!(_prioOverlay && !_prioOverlay.hasAttribute('hidden'));
  }
}, true);
document.addEventListener('keydown', function (e) {
  if (e.key !== 'Escape') return;
  if (!_custOverlay || _custOverlay.hasAttribute('hidden')) return;
  if (_custPrioWasOpenOnEscape) { _custPrioWasOpenOnEscape = false; return; }
  closeCustomerModal();
}, true);

'''
    return _replace_once(
        html,
        "function renderAll() {",
        script + "\nfunction renderAll() {",
        "customer modal injection point",
    )


def _inject_service_attach(html: str) -> str:
    """Per-service Defender attach (AE talk-track) drill-down.

    Adds a `renderServiceAttach(idp, name)` renderer and mounts it inside the
    per-customer detail view (inline and modal). For customers in an SL2/SL4
    import it surfaces the "you buy service X but don't protect it with the
    matching Defender plan" motion: a KPI strip (true attach ratio on the mapped
    eligible-workload denominator, eligible workload ACR, DfC ACR, open gap),
    ranked per-service opportunities with auto-generated AE openers, and a
    foundational-coverage pill panel. Hides itself gracefully when the active
    import has no `DATA.service_attach` (non-SL2/SL4 workbooks), and shows the
    engine error when `DATA.service_attach_error` is present.

    All customer-derived strings are escapeHtml-wrapped (XSS / A05). Must run
    AFTER _inject_customer_modal so the idp-refactored renderCustomerDetail
    signature and the m-cust-signal modal anchor already exist.
    """
    # 1) Inline mount point, directly under the existing signal note.
    html = _replace_once(
        html,
        '<div class="note" id="cust-signal"></div>',
        '<div class="note" id="cust-signal"></div>\n  <div id="cust-attach"></div>',
        "inline service attach mount",
    )

    # 2) Modal mount point, directly under the modal signal note (built in JS).
    html = _replace_once(
        html,
        "'<div class=\"note\" id=\"m-cust-signal\"></div>' +",
        "'<div class=\"note\" id=\"m-cust-signal\"></div>' +\n      '<div id=\"m-cust-attach\"></div>' +",
        "modal service attach mount",
    )

    # 3) Invoke the renderer at the end of the (idp-aware) detail render. The
    #    note.style.color line is unique to renderCustomerDetail.
    color_anchor = (
        "note.style.color = opp.opportunity === 'High' ? '#5d1014' : "
        "opp.opportunity === 'Medium' ? '#5d3a00' : '#0e3a0e';"
    )
    html = _replace_once(
        html,
        color_anchor,
        color_anchor + "\n  renderServiceAttach(idp, name);",
        "service attach render call",
    )

    # 4) Define renderServiceAttach just before renderCustomerDetail.
    renderer = r'''// ---- Per-service Defender attach (AE talk-track) ------------------------
function _saPct1(v) {
  return (v == null || isNaN(v)) ? '\u2013' : (v * 100).toFixed(1) + '%';
}

// Plain-language attach sentence for one catalog/opportunity entry.
// Dollar-gap plans get the "spends $X on workload but only $Y on Defender ..." line;
// usage-priced plans get a coverage signal with no fabricated dollar figure.
function _saSentence(customer, c) {
  const who = escapeHtml(customer || 'This customer');
  const wname = escapeHtml(c.workloadName || 'this workload');
  const plan = escapeHtml(c.planLabel || 'the matching Defender plan');
  if (c.hasDollarGap) {
    return who + ' spends <strong>' + fmt.money(c.workloadAcr) + '/mo</strong> on ' + wname +
      ' but only <strong>' + fmt.money(c.defenderActual) + '/mo</strong> on ' + plan +
      ' \u2014 roughly a <strong>' + fmt.money(c.gapDollars) + '/mo</strong> attach gap.';
  }
  return who + ' spends <strong>' + fmt.money(c.workloadAcr) + '/mo</strong> on ' + wname +
    ' but has <strong>no ' + plan + '</strong> coverage \u2014 usage-priced, so the upside is not yet quantified.';
}

// Rich detail for an open (below-threshold) opportunity, shown inside an
// expanded scorecard row. Mirrors the former standalone opportunity card,
// minus the plan label (the row head already shows it).
function _saOppDetail(o) {
  const isAttach = o.signal === 'attach';
  const pr = (o.priority || '').toLowerCase();
  const prClass = pr === 'high' ? 'high' : (pr === 'medium' ? 'medium' : 'low');
  const prTag = o.priority
    ? '<span class="tag ' + prClass + '">' + escapeHtml(o.priority) + ' priority</span>'
    : '';
  const badge = isAttach
    ? '<span class="tag high">Not protected</span>'
    : '<span class="tag medium">Under-protected</span>';
  const covTip = 'This Defender plan is billed by usage \u2014 per resource, machine, or transaction \u2014 not as a share of spend. '
    + 'So we flag the unprotected workload but do not guess a dollar gap, which would be too speculative. '
    + 'Confirm the resource count with the customer to size the real upside.';
  const gapStr = o.hasDollarGap
    ? fmt.money(o.gapDollars) + ' / mo gap'
    : 'usage-priced \u00b7 coverage signal '
      + '<span class="prio-badge-i" tabindex="0" role="img" '
      + 'aria-label="What does usage-priced coverage signal mean?" '
      + 'style="cursor:help;" title="' + covTip + '">&#9432;</span>';
  const cov = (o.hasDollarGap && o.coveragePct != null)
    ? ' \u00b7 ' + (o.coveragePct * 100).toFixed(0) + '% of benchmark'
    : '';
  const reason = o.priorityReason
    ? '<div style="font-size:11px;color:#605e5c;margin-top:4px;">Why: ' + escapeHtml(o.priorityReason) + '</div>'
    : '';
  return '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">' +
      '<div>' + prTag + ' ' + badge + '</div>' +
      '<div style="font-weight:600;white-space:nowrap;">' + gapStr + '</div>' +
    '</div>' +
    reason +
    '<div class="note" style="margin:8px 0 0;border-left-color:#0078d4;background:#f0f6fc;color:#243a5e;">' +
      escapeHtml(o.opener) + '</div>' +
    '<div style="font-size:12px;color:#605e5c;margin-top:8px;">' +
      'Workload ' + fmt.money(o.workloadAcr) + ' / mo (' + fmt.pct(o.workloadGrowth) + ' 3M) \u00b7 ' +
      'Defender ' + fmt.money(o.defenderActual) + ' / mo (' + fmt.pct(o.defenderGrowth) + ' 3M)' + cov +
    '</div>';
}

// Detail for an on-track plan (already protecting its workload to benchmark).
function _saOnTrackDetail(c) {
  const covTxt = (c.coveragePct != null) ? ' \u00b7 ' + (c.coveragePct * 100).toFixed(0) + '% of benchmark' : '';
  return '<div style="font-size:12px;color:#323130;">Defender <strong>' + fmt.money(c.defenderActual) +
    '/mo</strong> protecting <strong>' + fmt.money(c.workloadAcr) + '/mo</strong> of ' +
    escapeHtml(c.workloadName || 'this workload') + covTxt + '</div>';
}

// Minimal fallback when a below-threshold plan has no matching opportunity record.
function _saPlainDetail(c) {
  return '<div style="font-size:12px;color:#323130;">' + _saSentence(null, c) + '</div>';
}

// All-services scorecard: every Defender plan for the customer, clearly marked
// below-threshold (open opportunity) / on-track / not-in-use. Below-threshold
// and on-track rows are click-to-expand accordions revealing the recommended
// play; not-in-use rows are static. Returns an HTML string.
function _saScorecard(d) {
  const cat = Array.isArray(d.catalog) ? d.catalog : [];
  if (!cat.length) return '';
  const oppByPlan = {};
  (Array.isArray(d.opportunities) ? d.opportunities : []).forEach(function (o) {
    if (o && o.planLabel != null) oppByPlan[o.planLabel] = o;
  });
  const order = { below_threshold: 0, on_track: 1, not_deployed: 2 };
  const sorted = cat.slice().sort(function (a, b) {
    return ((order[a.status] == null ? 9 : order[a.status]) - (order[b.status] == null ? 9 : order[b.status])) ||
      ((b.gapDollars || 0) - (a.gapDollars || 0)) ||
      (a.planLabel < b.planLabel ? -1 : a.planLabel > b.planLabel ? 1 : 0);
  });
  const rows = sorted.map(function (c) {
    let color, bg, dot, label, detail, expandable, panelInner;
    if (c.status === 'below_threshold') {
      color = '#a4262c'; bg = '#fdf3f4'; dot = '\u25cf';
      label = (c.signal === 'expand') ? 'Under-attached' : 'Below threshold';
      detail = c.hasDollarGap
        ? fmt.money(c.workloadAcr) + '/mo ' + escapeHtml(c.workloadName) + ' vs ' + fmt.money(c.defenderActual) +
          '/mo Defender \u00b7 ~' + fmt.money(c.gapDollars) + '/mo gap'
        : fmt.money(c.workloadAcr) + '/mo ' + escapeHtml(c.workloadName) + ' \u00b7 no coverage (usage-priced)';
      expandable = true;
      panelInner = oppByPlan[c.planLabel] ? _saOppDetail(oppByPlan[c.planLabel]) : _saPlainDetail(c);
    } else if (c.status === 'on_track') {
      color = '#107c10'; bg = '#f3f9ef'; dot = '\u2713'; label = 'On track';
      detail = fmt.money(c.defenderActual) + '/mo Defender on ' + fmt.money(c.workloadAcr) + '/mo workload';
      expandable = true;
      panelInner = _saOnTrackDetail(c);
    } else {
      color = '#8a8886'; bg = '#f3f2f1'; dot = '\u25cb'; label = 'Not in use';
      detail = 'Customer does not run this workload yet';
      expandable = false;
      panelInner = '';
    }
    const caret = expandable
      ? '<span class="sa-caret" style="color:' + color + ';width:12px;display:inline-block;text-align:center;">\u25b8</span>'
      : '<span style="width:12px;display:inline-block;"></span>';
    const headOpen = expandable
      ? '<div data-sa-toggle role="button" tabindex="0" aria-expanded="false" style="cursor:pointer;'
      : '<div style="';
    const head = headOpen +
        'display:flex;align-items:center;gap:8px;padding:8px 12px;border-left:3px solid ' + color +
        ';background:' + bg + ';border-radius:4px;">' +
      caret +
      '<span style="color:' + color + ';font-weight:700;width:14px;text-align:center;">' + dot + '</span>' +
      '<div style="flex:1 1 auto;min-width:0;">' +
        '<div style="font-weight:600;color:#323130;">' + escapeHtml(c.planLabel) + '</div>' +
        '<div style="font-size:11px;color:#605e5c;">' + detail + '</div>' +
      '</div>' +
      '<span style="font-size:11px;font-weight:700;color:' + color + ';white-space:nowrap;">' + label + '</span>' +
    '</div>';
    const panel = expandable
      ? '<div class="sa-detail" hidden style="padding:10px 12px 12px 34px;background:#ffffff;' +
          'border:1px solid #edebe9;border-top:none;border-radius:0 0 4px 4px;margin:-2px 0 2px;">' +
          panelInner + '</div>'
      : '';
    return '<div>' + head + panel + '</div>';
  }).join('');
  return '<div style="margin-top:14px;font-size:13px;color:#323130;font-weight:600;">Defender coverage scorecard</div>' +
    '<div style="font-size:11px;color:#605e5c;margin-bottom:6px;">Every Defender for Cloud plan for this customer. ' +
      'Plans marked <strong style="color:#a4262c;">below threshold</strong> are the open attach opportunities. ' +
      'Click an open or on-track plan to reveal the recommended play.</div>' +
    '<div style="display:flex;flex-direction:column;gap:4px;">' + rows + '</div>';
}

function renderServiceAttach(idp, name) {
  idp = idp || '';
  if (!window.__saAccordionWired) {
    window.__saAccordionWired = true;
    const _saToggle = function (head) {
      const panel = head.nextElementSibling;
      if (!panel || panel.className !== 'sa-detail') return;
      const opening = panel.hasAttribute('hidden');
      if (opening) { panel.removeAttribute('hidden'); } else { panel.setAttribute('hidden', ''); }
      head.setAttribute('aria-expanded', opening ? 'true' : 'false');
      const caret = head.querySelector('.sa-caret');
      if (caret) caret.textContent = opening ? '\u25be' : '\u25b8';
    };
    document.addEventListener('click', function (e) {
      const head = e.target.closest('[data-sa-toggle]');
      if (head) _saToggle(head);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' && e.key !== ' ' && e.key !== 'Spacebar') return;
      const head = e.target.closest('[data-sa-toggle]');
      if (!head) return;
      e.preventDefault();
      _saToggle(head);
    });
  }
  const host = document.getElementById(idp + 'cust-attach');
  if (!host) return;
  const sa = (typeof DATA !== 'undefined' && DATA) ? DATA.service_attach : null;
  const saErr = (typeof DATA !== 'undefined' && DATA) ? DATA.service_attach_error : null;

  if (!sa || !Array.isArray(sa.dossiers)) {
    if (saErr) {
      host.style.display = '';
      host.innerHTML =
        '<div class="note" style="margin-top:18px;border-left-color:#ff8c00;background:#fffaf0;color:#5d3a00;">' +
        '<strong>Service-level attach unavailable:</strong> ' + escapeHtml(String(saErr)) + '</div>';
    } else {
      host.innerHTML = '';
      host.style.display = 'none';
    }
    return;
  }

  const d = sa.dossiers.find(function (x) { return x.customer === name; });
  if (!d) { host.innerHTML = ''; host.style.display = 'none'; return; }
  host.style.display = '';

  const kpis =
    '<div class="cards" style="margin-top:6px;">' +
      '<div class="card"><div class="label">Defender Attach Rate</div><div class="val">' + _saPct1(d.attachRatio) + '</div><div class="delta">DfC \u00f7 eligible workload</div></div>' +
      '<div class="card"><div class="label">Eligible Workload ACR</div><div class="val">' + fmt.money(d.eligibleWorkloadAcr) + '</div><div class="delta">mapped services / mo</div></div>' +
      '<div class="card"><div class="label">Defender for Cloud ACR</div><div class="val">' + fmt.money(d.dfcAcr) + '</div><div class="delta">per month</div></div>' +
      '<div class="card"><div class="label">Open Attach Gap</div><div class="val">' + fmt.money(d.totalGapDollars) + '</div><div class="delta">' + d.uncoveredEligibleCount + ' of ' + d.presentEligibleCount + ' services unprotected</div></div>' +
    '</div>';

  const opps = Array.isArray(d.opportunities)
    ? d.opportunities.slice().sort(function (a, b) {
        return ((a.priorityRank == null ? 9 : a.priorityRank) - (b.priorityRank == null ? 9 : b.priorityRank)) ||
          ((b.blendedScore || 0) - (a.blendedScore || 0));
      })
    : [];
  const emptyNote = opps.length ? '' :
    '<div class="note" style="border-left-color:#107c10;background:#f3f9ef;color:#0e3a0e;">' +
    'No open per-service attach gaps \u2014 this customer protects the Azure services they run.</div>';

  const tierLegend = opps.length
    ? '<div style="font-size:11px;color:#605e5c;margin-top:10px;line-height:1.6;">' +
        '<span class="tag high">High</span> workload growing faster than Defender attach \u00b7 ' +
        '<span class="tag medium">Medium</span> active workload materially under-protected \u00b7 ' +
        '<span class="tag low">Low</span> roughly tracking the benchmark \u2014 minor top-up' +
      '</div>'
    : '';

  const found = Array.isArray(d.foundational) ? d.foundational : [];
  let foundHtml = '';
  if (found.length) {
    foundHtml =
      '<div style="margin-top:14px;font-size:13px;color:#323130;font-weight:600;">Foundational coverage</div>' +
      '<div style="font-size:11px;color:#605e5c;margin-bottom:6px;">Posture plans (CSPM, Resource Manager, DNS, EASM) \u2014 not workload-priced.</div>' +
      '<div style="display:flex;flex-wrap:wrap;gap:6px;">' +
      found.map(function (f) {
        const on = !!f.present;
        const c = on ? '#107c10' : '#a19f9d';
        const bg = on ? '#f3f9ef' : '#f3f2f1';
        const mark = on ? '\u2713' : '\u25cb';
        return '<span style="border:1px solid ' + c + ';background:' + bg + ';color:' + c +
          ';border-radius:12px;padding:2px 10px;font-size:12px;">' + mark + ' ' + escapeHtml(f.planLabel) + '</span>';
      }).join('') +
      '</div>';
  }

  let reconHtml = '';
  if (d.reconciliationOk === false) {
    reconHtml = '<div class="note" style="margin-top:10px;border-left-color:#ff8c00;background:#fffaf0;color:#5d3a00;font-size:12px;">' +
      'Heads-up: provided totals did not fully reconcile against summed service rows for this customer \u2014 treat figures as directional.</div>';
  }

  // Headline open attach gap: quantified monthly gap (sum of dollar-gap plans)
  // annualized x12, plus a count of usage-priced coverage-signal services as
  // separate unquantified upside (never fabricate a $ for those).
  const monthlyGap = d.totalGapDollars || 0;
  const annualGap = monthlyGap * 12;
  const covSignals = opps.filter(function (o) { return !o.hasDollarGap; }).length;
  const gapBanner = (monthlyGap > 0 || covSignals > 0)
    ? '<div style="margin-top:12px;border:1px solid #e3d3f5;background:#fbf6ff;border-radius:8px;padding:14px 16px;display:flex;flex-wrap:wrap;gap:18px;align-items:baseline;">' +
        '<div><div style="font-size:24px;font-weight:700;color:#5c2d91;">' + fmt.money(monthlyGap) + '</div>' +
          '<div style="font-size:12px;color:#605e5c;">Total ACR gap per month</div></div>' +
        '<div><div style="font-size:24px;font-weight:700;color:#5c2d91;">' + fmt.money(annualGap) + '</div>' +
          '<div style="font-size:12px;color:#605e5c;">Total ACR gap per year</div></div>' +
        '<div style="flex:1 1 220px;font-size:12px;color:#605e5c;">Estimated additional Defender for Cloud ACR if these per-service gaps are closed to benchmark.' +
          (covSignals > 0 ? ' Plus ' + covSignals + ' usage-priced service' + (covSignals === 1 ? '' : 's') + ' with coverage gaps (upside not yet quantified).' : '') +
        '</div>' +
      '</div>'
    : '';

  // Plain-language lead: the single biggest below-threshold gap, stated as a sentence.
  const leadEntry = (Array.isArray(d.catalog) ? d.catalog : [])
    .filter(function (c) { return c.status === 'below_threshold'; })
    .sort(function (a, b) {
      return (Number(b.hasDollarGap) - Number(a.hasDollarGap)) || ((b.gapDollars || 0) - (a.gapDollars || 0));
    })[0];
  const leadBox = leadEntry
    ? '<div class="note" style="margin-top:14px;border-left-color:#a4262c;background:#fdf3f4;color:#5d1a1d;font-size:14px;line-height:1.5;">' +
        _saSentence(d.customer, leadEntry) + '</div>'
    : '';
  const scorecard = _saScorecard(d);

  host.innerHTML =
    '<div class="chart-box" style="margin-top:18px;">' +
      '<div class="title">Per-Service Defender Attach</div>' +
      '<div class="sub">Where this customer buys an Azure service but is not protecting it with the matching Defender plan. Ranked by opportunity score.</div>' +
      kpis +
      gapBanner +
      leadBox +
      reconHtml +
      scorecard +
      emptyNote +
      tierLegend +
      foundHtml +
    '</div>';
}

'''
    html = _replace_once(
        html,
        "function renderCustomerDetail(name, idp) {",
        renderer + "function renderCustomerDetail(name, idp) {",
        "service attach renderer definition",
    )
    return html


def _inject_category_modal(html: str) -> str:
    """Drill-down splash for the overview product-mix donut.

    Clicking (or Enter/Space on) a donut slice opens a modal listing the services
    (SKU rows for a real category, or the folded categories for the 'Other services'
    slice) that make up that slice, with each row's avg monthly ACR and share. Runs
    AFTER ``_inject_customer_modal``; its own document-capture Escape handler only
    acts when the category overlay is visible, and the two overlays are mutually
    exclusive (the donut cannot be clicked while the customer modal covers it), so
    no Escape-stacking disambiguation is needed here.
    """
    script = r'''
// ---- Category breakdown modal (Overview product-mix donut) ----------------
let _catOverlay = null;
let _catLastFocus = null;

function _ensureCatOverlay() {
  if (_catOverlay) return _catOverlay;
  const style = document.createElement('style');
  style.textContent =
    '.cat-overlay{position:fixed;inset:0;background:rgba(15,23,42,.55);display:flex;' +
    'align-items:flex-start;justify-content:center;z-index:3950;padding:48px 16px;overflow:auto}' +
    '.cat-overlay[hidden]{display:none}' +
    '.cat-dialog{position:relative;background:#faf9f8;border-radius:10px;max-width:560px;width:100%;' +
    'box-shadow:0 20px 60px rgba(0,0,0,.3)}' +
    '.cat-close{position:absolute;top:8px;right:14px;border:none;background:transparent;font-size:28px;' +
    'line-height:1;cursor:pointer;color:#605e5c;z-index:1}' +
    '.cat-close:hover{color:#201f1e}' +
    '.cat-close:focus-visible{outline:2px solid #0078d4;outline-offset:1px}' +
    '.cat-body{padding:22px 26px 26px}' +
    '.cat-body h2{margin:0 0 4px;font-size:18px;color:#201f1e;padding-right:32px}' +
    '.cat-body .cat-sub{margin:0 0 14px;font-size:12px;color:#605e5c}' +
    '.cat-table{width:100%;border-collapse:collapse;font-size:13px}' +
    '.cat-table th,.cat-table td{padding:6px 8px;text-align:left;border-bottom:1px solid #edebe9}' +
    '.cat-table td.num,.cat-table th.num{text-align:right;font-variant-numeric:tabular-nums}' +
    '.cat-empty{padding:18px 0;color:#a19f9d;font-size:13px}';
  document.head.appendChild(style);

  const overlay = document.createElement('div');
  overlay.id = 'cat-modal';
  overlay.className = 'cat-overlay';
  overlay.setAttribute('hidden', '');
  overlay.innerHTML =
    '<div class="cat-dialog" role="dialog" aria-modal="true" aria-labelledby="cat-title">' +
    '<button class="cat-close" type="button" aria-label="Close">&times;</button>' +
    '<div class="cat-body"><h2 id="cat-title"></h2>' +
    '<p class="cat-sub" id="cat-sub"></p><div id="cat-content"></div></div></div>';
  overlay.addEventListener('click', e => { if (e.target === overlay) closeCategoryModal(); });
  overlay.querySelector('.cat-close').addEventListener('click', closeCategoryModal);
  overlay.addEventListener('keydown', e => {
    if (e.key !== 'Tab') return;
    const nodes = overlay.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
    const f = Array.prototype.filter.call(nodes, el => !el.disabled && el.offsetParent !== null);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
  document.body.appendChild(overlay);
  _catOverlay = overlay;
  return overlay;
}

function openCategoryBreakdown(label) {
  if (!label || typeof DATA === 'undefined' || !DATA) return;
  const partial = (typeof DATA.partial_month_idx === 'number') ? DATA.partial_month_idx : -1;
  const avgOf = a => { const arr = Array.isArray(a) ? a : []; const vals = arr.filter((_, i) => i !== partial); if (!vals.length) return 0; return vals.reduce((s, v) => s + (Number(v) || 0), 0) / vals.length; };
  const fmt = v => '$' + (Number(v) || 0).toLocaleString('en-US', {maximumFractionDigits: 0});
  let rows = [], sub = '';
  if (label === 'Other services') {
    rows = (Array.isArray(window._donutOtherCats) ? window._donutOtherCats : [])
      .map(c => ({name: c.label, val: Number(c.value) || 0}))
      .filter(r => r.val > 0).sort((a, b) => b.val - a.val);
    sub = 'Categories grouped into the Other slice';
  } else {
    const skus = (DATA.product_skus && DATA.product_skus[label]) || null;
    if (skus && skus.length) {
      rows = skus.map(s => ({name: s.sku, val: avgOf(s.monthly)})).filter(r => r.val > 0).sort((a, b) => b.val - a.val);
      sub = 'Services in this category';
    } else {
      sub = 'Service-level breakdown is not available for this data source';
    }
  }
  const sum = rows.reduce((s, r) => s + r.val, 0);
  const overlay = _ensureCatOverlay();
  const titleEl = overlay.querySelector('#cat-title');
  const subEl = overlay.querySelector('#cat-sub');
  const contentEl = overlay.querySelector('#cat-content');
  if (titleEl) titleEl.textContent = label;
  if (subEl) subEl.textContent = sub + (sum > 0 ? ' \u00b7 ' + fmt(sum) + ' avg monthly ACR' : '');
  if (contentEl) {
    if (!rows.length) {
      contentEl.innerHTML = '<div class="cat-empty">No service-level breakdown to display.</div>';
    } else {
      const body = rows.map(r => {
        const pct = sum > 0 ? (r.val / sum * 100).toFixed(1) : '0.0';
        return '<tr><td>' + escapeHtml(r.name) + '</td><td class="num">' + escapeHtml(fmt(r.val)) +
          '</td><td class="num">' + pct + '%</td></tr>';
      }).join('');
      contentEl.innerHTML = '<table class="cat-table"><thead><tr><th>Service</th>' +
        '<th class="num">Avg monthly ACR</th><th class="num">Share</th></tr></thead><tbody>' +
        body + '</tbody></table>';
    }
  }
  _catLastFocus = (document.activeElement && typeof document.activeElement.focus === 'function') ? document.activeElement : null;
  overlay.removeAttribute('hidden');
  const closeBtn = overlay.querySelector('.cat-close');
  if (closeBtn) closeBtn.focus();
}

function closeCategoryModal() {
  if (_catOverlay) _catOverlay.setAttribute('hidden', '');
  if (_catLastFocus && typeof _catLastFocus.focus === 'function') { try { _catLastFocus.focus(); } catch (_) {} }
  _catLastFocus = null;
}

document.addEventListener('keydown', function (e) {
  if (e.key !== 'Escape') return;
  if (!_catOverlay || _catOverlay.hasAttribute('hidden')) return;
  closeCategoryModal();
}, true);

'''
    return _replace_once(
        html,
        "function renderAll() {",
        script + "\nfunction renderAll() {",
        "category modal injection point",
    )


def _export_handler_script() -> str:
    return (
        "<script>\n"
        "(function () {\n"
        "  const btn = document.getElementById('export-pptx-btn');\n"
        "  if (!btn) return;\n"
        "  btn.addEventListener('click', async () => {\n"
        "    if (!window.PptxAcr || typeof window.PptxAcr.exportDeck !== 'function') {\n"
        "      setStatus('PowerPoint export module is not loaded.', 'error');\n"
        "      return;\n"
        "    }\n"
        "    if (!DATA || !Array.isArray(DATA.opportunity) || DATA.opportunity.length === 0) {\n"
        "      setStatus('Load an Excel export before exporting to PowerPoint.', 'error');\n"
        "      return;\n"
        "    }\n"
        "    btn.disabled = true;\n"
        "    const originalLabel = btn.textContent;\n"
        "    btn.textContent = 'Building deck…';\n"
        "    try {\n"
        "      const threshold = (typeof dfcShareThreshold === 'number') ? dfcShareThreshold : 6;\n"
        "      if (typeof reclassifyOpportunities === 'function') reclassifyOpportunities(threshold);\n"
        "      const sourceName = DATA.source_name || 'Imported workbook';\n"
        "      await window.PptxAcr.exportDeck(DATA, sourceName, threshold);\n"
        "      setStatus('PowerPoint deck downloaded.', 'success');\n"
        "    } catch (err) {\n"
        "      console.error('PPTX export failed', err);\n"
        "      setStatus('PowerPoint export failed: ' + (err && err.message ? err.message : err), 'error');\n"
        "    } finally {\n"
        "      btn.disabled = false;\n"
        "      btn.textContent = originalLabel;\n"
        "    }\n"
        "  });\n"
        "})();\n"
        "</script>"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build web-app/index.html from the canonical template.")
    parser.add_argument("--check", action="store_true",
                        help="Do not write; exit 1 if the on-disk output differs from the freshly built HTML.")
    args = parser.parse_args()

    generated = build_html()

    if args.check:
        current = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.exists() else ""
        if current != generated:
            print(
                f"build_static_webapp --check: {OUTPUT_PATH.relative_to(REPO_ROOT)} is "
                "out of date. Run `python scripts/build_static_webapp.py`.",
                file=sys.stderr,
            )
            return 1
        print("build_static_webapp --check: up to date.")
        return 0

    OUTPUT_PATH.write_text(generated, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH.relative_to(REPO_ROOT)} ({len(generated):,} chars).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
