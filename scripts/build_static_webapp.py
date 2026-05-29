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
    html = _harden_csvcell(html)

    closing_body = "</body>"
    extra_scripts = (
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
    _assert_contains(html, "${escapeHtml(r.notes)}", "escaped notes in heatmap")
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
    _assert_contains(html, "function priorityGradingRules()", "priority grading rubric")
    _assert_contains(html, 'class="tag \' + cls + \' prio-badge"', "clickable priority badge")
    _assert_contains(html, "e.target.closest('.prio-badge')", "capture-phase badge click handler")
    _assert_contains(html, './vendor/xlsx.full.min.js', "vendored SheetJS")
    _assert_contains(html, './vendor/pptxgen.bundle.js', "vendored PptxGenJS")
    _assert_contains(html, './js/acr-model.js', "acr-model.js script")
    _assert_contains(html, './js/pptx-acr.js', "pptx-acr.js script")
    _assert_contains(html, "#app-nav .app-menu", "app-nav inline CSS")
    _assert_contains(html, 'id="app-nav"', "app-nav placeholder")
    _assert_contains(html, 'id="splash"', "splash overlay")
    _assert_contains(html, 'id="splash-dropzone"', "splash dropzone")
    _assert_contains(html, "splash.hidden = true", "splash hide-on-load")
    _assert_contains(html, "if (!DATA.customers || DATA.customers.length === 0) return;", "renderAll empty-state guard")
    _assert_contains(html, "ACR_CACHE_KEY", "session-storage persistence")
    _assert_contains(html, "sessionStorage.setItem(ACR_CACHE_KEY", "persistence write on import")
    _assert_contains(html, "DATA.track_products && DATA.track_products.length", "taxonomy-aware trend chart")
    _assert_contains(html, "const colorFor = p =>", "validated trend colour helper")
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
    _assert_contains(html, "const weekly = !!(DATA.weekly_enabled && DATA.product_weekly);", "weekly product series auto-selected")
    _assert_contains(html, "DATA.product_weekly", "weekly product series wired into trend")
    _assert_contains(html, "cd.dfc_weekly", "weekly customer series wired into drill-down")
    _assert_absent(html, "lineChart('chart-dfc-trend', [{label: 'Defender for Cloud', values: DATA.dfc_total_monthly, color: '#0078d4'}]);", "stale month-only DfC overview trend call")
    _assert_absent(html, 'id="product-trend-grain"', "removed monthly/weekly granularity toggle")
    _assert_absent(html, 'id="cust-trend-grain"', "removed customer granularity toggle")
    _assert_absent(html, "function initGrainControls()", "removed granularity control init")

    # Product-mix donut (replaces the product-trend line chart on the overview).
    _assert_contains(html, "function donutChart(", "product-mix donut helper")
    _assert_contains(html, "function renderProductMix()", "product-mix donut renderer")
    _assert_contains(html, 'id="chart-product-mix"', "product-mix donut container")
    _assert_contains(html, 'id="legend-product-mix"', "product-mix donut legend")
    _assert_contains(html, "  renderProductMix();", "renderAll product-mix wiring")
    _assert_contains(html, "donutChart('chart-product-mix', items)", "donut render call")
    _assert_absent(html, "function renderProductTrend()", "removed product-trend line renderer")
    _assert_absent(html, "  renderProductTrend();", "removed product-trend renderAll call")
    _assert_absent(html, 'id="product-trend-mode"', "removed product-trend mode select")
    _assert_absent(html, 'id="chart-product-trend"', "removed product-trend line container")
    _assert_absent(html, 'id="legend-product-trend"', "removed product-trend legend")
    _assert_absent(html, "Product mix — ACR trend by service", "removed product-trend line title")

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
        "const ACR_CACHE_KEY = 'defenderattach:acr:v2';\n"
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

    splash_wire = (
        "<script>\n"
        "(function(){\n"
        "  var btn = document.getElementById('splash-import-btn');\n"
        "  var dz = document.getElementById('splash-dropzone');\n"
        "  var err = document.getElementById('splash-error');\n"
        "  var importBtn = document.getElementById('import-btn');\n"
        "  var fileInput = document.getElementById('file-input');\n"
        "  if (!importBtn || !fileInput) return;\n"
        "\n"
        "  function showError(msg){ if (err) err.textContent = msg || ''; }\n"
        "  function clickBrowse(){ showError(''); importBtn.click(); }\n"
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

    # 3. Customer drill-down: escape product names + collapsible SKU sub-rows.
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
        "    cd.products.map((p, pi) => {\n"
        "      const sparkColor = p.product === 'Defender for Cloud' ? '#0078d4' : '#605e5c';\n"
        "      const nameEsc = escapeHtml(p.product);\n"
        "      const nameHtml = p.product === 'Defender for Cloud' ? '<strong style=\"color:#0078d4\">' + nameEsc + '</strong>' : nameEsc;\n"
        "      const skus = Array.isArray(p.skus) ? p.skus : [];\n"
        "      const sid = 'sku-' + pi;\n"
        "      const caret = skus.length ? `<span class=\"sku-caret\" style=\"cursor:pointer;user-select:none;color:#605e5c;margin-right:6px;\">\\u25b8</span>` : '<span style=\"display:inline-block;width:14px;\"></span>';\n"
        "      const head = `<div class=\"product-row\"${skus.length ? ` data-sku-toggle=\"${sid}\" style=\"cursor:pointer;\"` : ''}>\n"
        "        <div class=\"name\">${caret}${nameHtml}</div>\n"
        "        <div class=\"num\">${fmt.money2(p.current)}</div>\n"
        "        <div class=\"num ${fmt.pctClass(p.mom)}\">${fmt.pct(p.mom)}</div>\n"
        "        <div class=\"num ${fmt.pctClass(p.three_m)}\">${fmt.pct(p.three_m)}</div>\n"
        "        <div>${sparkline(p.series, 140, 26, sparkColor)}</div>\n"
        "      </div>`;\n"
        "      const subs = skus.map(s => `<div class=\"product-row sku-row ${sid}\" hidden style=\"background:#faf9f8;\">\n"
        "        <div class=\"name\" style=\"padding-left:22px;color:#605e5c;\">${escapeHtml(s.sku)}</div>\n"
        "        <div class=\"num\">${fmt.money2(s.current)}</div>\n"
        "        <div class=\"num ${fmt.pctClass(s.mom)}\">${fmt.pct(s.mom)}</div>\n"
        "        <div class=\"num ${fmt.pctClass(s.three_m)}\">${fmt.pct(s.three_m)}</div>\n"
        "        <div>${sparkline(s.series, 140, 26, '#a19f9d')}</div>\n"
        "      </div>`).join('');\n"
        "      return head + subs;\n"
        "    }).join('');",
        "SKU drill-down rows in customer table",
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

    # 5. Customer drill-down charts: prefer weekly series + labels.
    html = _replace_once(
        html,
        "  lineChart('chart-cust-dfc', [\n"
        "    {label: 'Defender for Cloud', values: cd.dfc_series, color: '#0078d4'},\n"
        "    {label: 'Other Azure', values: cd.other_series, color: '#605e5c', dash: '4 3'},\n"
        "  ]);\n"
        "  const pctSeries = cd.dfc_series.map((v, i) => {\n"
        "    const t = cd.total_series[i];\n"
        "    return t > 0 ? (v / t) * 100 : 0;\n"
        "  });\n"
        "  lineChart('chart-cust-pct', [{label: 'DfC % of total', values: pctSeries, color: '#8764b8'}]);",
        "  const cWeekly = !!(DATA.weekly_enabled && Array.isArray(cd.dfc_weekly) && Array.isArray(cd.other_weekly) && Array.isArray(cd.total_weekly));\n"
        "  const dfcSeries = cWeekly ? cd.dfc_weekly : cd.dfc_series;\n"
        "  const otherSeries = cWeekly ? cd.other_weekly : cd.other_series;\n"
        "  const totalSeries = cWeekly ? cd.total_weekly : cd.total_series;\n"
        "  const cLabels = cWeekly ? DATA.week_labels : DATA.month_labels;\n"
        "  lineChart('chart-cust-dfc', [\n"
        "    {label: 'Defender for Cloud', values: dfcSeries, color: '#0078d4'},\n"
        "    {label: 'Other Azure', values: otherSeries, color: '#605e5c', dash: '4 3'},\n"
        "  ], {labels: cLabels, partialIdx: cWeekly ? -1 : DATA.partial_month_idx});\n"
        "  const pctSeries = dfcSeries.map((v, i) => {\n"
        "    const t = totalSeries[i];\n"
        "    return t > 0 ? (v / t) * 100 : 0;\n"
        "  });\n"
        "  lineChart('chart-cust-pct', [{label: 'DfC % of total', values: pctSeries, color: '#8764b8'}], {labels: cLabels, partialIdx: cWeekly ? -1 : DATA.partial_month_idx});",
        "weekly customer drill-down charts",
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
    html = _replace_once(
        html,
        '      <div class="sub">Monthly ACR — does DfC track with the rest of the footprint?</div>',
        '      <div class="sub">ACR trend — does DfC track with the rest of the footprint?</div>',
        "customer dfc trend sub relabel",
    )
    html = _replace_once(
        html,
        '      <div class="sub">DfC as % of total monthly ACR for this customer</div>',
        '      <div class="sub">DfC as % of total ACR for this customer</div>',
        "customer pct trend sub relabel",
    )

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
            "function renderProductMix() {\n"
            "  const weekly = !!(DATA.weekly_enabled && DATA.product_weekly);\n"
            "  const src = weekly ? DATA.product_weekly : DATA.product_monthly;\n"
            "  const tracks = (DATA.track_products && DATA.track_products.length ? DATA.track_products : TRACK_PRODUCTS)\n"
            "    .filter(p => src[p]);\n"
            "  const colorFor = p => { const c = (DATA.product_colors && DATA.product_colors[p]) || PRODUCT_COLORS[p] || '#605e5c'; return /^#[0-9a-fA-F]{6}$/.test(c) ? c : '#605e5c'; };\n"
            "  const sumOf = a => (Array.isArray(a) ? a : []).reduce((s, v) => s + (Number(v) || 0), 0);\n"
            "  const items = tracks.map(p => ({label: p, value: sumOf(src[p]), color: colorFor(p)}))\n"
            "    .filter(d => d.value > 0)\n"
            "    .sort((a, b) => b.value - a.value);\n"
            "  donutChart('chart-product-mix', items);\n"
            "  document.getElementById('legend-product-mix').innerHTML = items.map(d =>\n"
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
            "  const totalLbl = total >= 1000 ? '$' + (total / 1000).toFixed(1) + 'k' : '$' + total.toFixed(0);\n"
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
            "  svg += `<text x=\"${cx}\" y=\"${cy + 15}\" text-anchor=\"middle\" font-size=\"10\" fill=\"#605e5c\">total ACR</text>`;\n"
            "  svg += `</svg>`;\n"
            "  el.innerHTML = svg;\n"
            "  el.querySelectorAll('[data-label]').forEach(seg => {\n"
            "    seg.addEventListener('mousemove', e => {\n"
            "      const label = seg.getAttribute('data-label');\n"
            "      const val = parseFloat(seg.getAttribute('data-val'));\n"
            "      const pct = seg.getAttribute('data-pct');\n"
            "      showTooltip(`<b>${escapeHtml(label)}</b><br/>$${val.toLocaleString('en-US', {maximumFractionDigits: 0})} · ${pct}%`, e.pageX, e.pageY);\n"
            "    });\n"
            "    seg.addEventListener('mouseleave', hideTooltip);\n"
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

    Covers the injected opportunity heatmap as well as the original
    Opportunity Map and All Customers Table from the upstream template,
    all of which originally interpolated raw workbook strings.
    """

    html = _replace_exact(
        html,
        '<tr class="clickable" data-customer="${r.customer.replace(/"/g, \'&quot;\')}">',
        '<tr class="clickable" data-customer="${escapeHtml(r.customer)}">',
        "row data-customer attribute",
        3,
    )
    html = _replace_exact(
        html,
        "<td><strong>${r.customer}</strong></td>",
        "<td><strong>${escapeHtml(r.customer)}</strong></td>",
        "heatmap customer cell",
        1,
    )
    html = _replace_exact(
        html,
        "<td>${r.customer}</td>",
        "<td>${escapeHtml(r.customer)}</td>",
        "original table customer cell",
        2,
    )
    html = _replace_exact(
        html,
        "<td>${r.notes}</td>",
        "<td>${escapeHtml(r.notes)}</td>",
        "original table notes cell",
        2,
    )
    html = _replace_exact(
        html,
        "}${r.notes}</td>",
        "}${escapeHtml(r.notes)}</td>",
        "heatmap notes cell",
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

// Threshold-aware rubric mirroring AcrModel.classifyOpportunity. The highest
// tier whose conditions are met wins.
function priorityGradingRules() {
  const t = (typeof dfcShareThreshold === 'number') ? dfcShareThreshold : 6;
  const tl = (typeof fmtThreshold === 'function') ? fmtThreshold(t) : (t + '%');
  return [
    { tier: 'Too small', text: 'Total Azure ACR under $1,500 / month — sales priority is low regardless of Defender share.' },
    { tier: 'High',   text: 'No Defender for Cloud spend at all (under $15 / month) while the customer spends over $3,000 / month on Azure — 0% against the ' + tl + ' attach baseline.' },
    { tier: 'High',   text: 'Other Azure workloads grew over the last 3 months while Defender for Cloud is shrinking (declining more than 5%).' },
    { tier: 'High',   text: 'Other Azure is growing, Defender is flat (under 2% growth) AND Defender is under 2% of total ACR.' },
    { tier: 'High',   text: 'Break of trend: core workloads (Compute, Databases, Developer Tools, Integration, AI + Machine Learning, Containers) grew over 5% over 3 months, Defender did not keep pace (more than 5 points behind), and the customer is below the ' + tl + ' baseline.' },
    { tier: 'Medium', text: 'Defender penetration under 1.5% of total ACR while other Azure is growing — undersold.' },
    { tier: 'Medium', text: 'Defender for Cloud is growing more than 5 points slower than the rest of Azure.' },
    { tier: 'Medium', text: 'Very low Defender penetration (under 0.5%) on a sizeable account (total ACR over $6,000 / month).' },
    { tier: 'Medium', text: 'Break of trend on core workloads while already at or above the ' + tl + ' baseline.' },
    { tier: 'Medium', text: 'Defender attach baseline: Defender share is below the ' + tl + ' corporate baseline — every customer should run at least ' + tl + ' of total ACR on Defender workloads.' },
    { tier: 'Low',    text: 'None of the above triggers fire — Defender attach looks healthy for this customer at the current ' + tl + ' baseline.' },
  ];
}

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
    '.prio-section{margin-bottom:18px}' +
    '.prio-section h3{font-size:14px;margin:0 0 8px;color:#201f1e}' +
    '.prio-signals{margin:0;padding-left:18px}' +
    '.prio-signals li{margin-bottom:6px;color:#323130}' +
    '.prio-none{color:#107c10;margin:0}' +
    '.prio-metrics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px 18px}' +
    '.prio-metric{display:flex;justify-content:space-between;gap:12px;border-bottom:1px solid #eef1f5;padding:5px 0;font-size:13px}' +
    '.prio-metric .k{color:#605e5c}.prio-metric .v{font-weight:600;color:#201f1e;text-align:right}' +
    '.prio-rubric-intro{font-size:12px;color:#605e5c;margin:0 0 8px}' +
    '.prio-rubric{list-style:none;margin:0;padding:0}' +
    '.prio-rule{display:flex;gap:10px;align-items:flex-start;padding:7px 8px;border-radius:6px;font-size:13px}' +
    '.prio-rule.current{background:#f5f7fb}' +
    '.prio-pill{flex:0 0 auto;font-size:11px;font-weight:700;padding:2px 8px;border-radius:999px;border:1px solid}' +
    '.prio-rule-text{color:#323130}' +
    '@media(max-width:560px){.prio-metrics{grid-template-columns:1fr}}';
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

function openPriorityExplainer(customer) {
  if (!DATA || !Array.isArray(DATA.opportunity)) return;
  const row = DATA.opportunity.find(r => r.customer === customer);
  if (!row) return;
  const overlay = _ensurePrioOverlay();
  const meta = PRIORITY_META[row.opportunity] || PRIORITY_META.Low;
  const t = (typeof dfcShareThreshold === 'number') ? dfcShareThreshold : 6;
  const tl = (typeof fmtThreshold === 'function') ? fmtThreshold(t) : (t + '%');

  const signals = (row.notes && row.notes !== '-')
    ? row.notes.split('; ').map(s => s.trim()).filter(Boolean) : [];
  const signalsHtml = signals.length
    ? '<ul class="prio-signals">' + signals.map(s => '<li>' + escapeHtml(s) + '</li>').join('') + '</ul>'
    : '<p class="prio-none">No attach gaps detected at the current ' + escapeHtml(tl) +
      ' baseline — Defender coverage looks healthy for this customer.</p>';

  const catNames = (Array.isArray(row.growth_cat_names) && row.growth_cat_names.length)
    ? row.growth_cat_names.join(', ') : '—';
  const metrics = [
    ['Total monthly ACR', fmt.money2(row.total_current)],
    ['Defender for Cloud monthly ACR', fmt.money2(row.dfc_current)],
    ['Defender share of total', fmt.pctRaw(row.dfc_ratio)],
    ['Attach baseline', escapeHtml(tl)],
    ['Defender 3-month trend', fmt.pct(row.dfc_3m)],
    ['Other Azure 3-month trend', fmt.pct(row.other_3m)],
    ['Core workloads 3-month trend', row.growth_cat_3m == null ? '—' : fmt.pct(row.growth_cat_3m)],
    ['Growing core workloads', escapeHtml(catNames)],
  ];
  const metricsHtml = metrics.map(m =>
    '<div class="prio-metric"><span class="k">' + m[0] + '</span><span class="v">' + m[1] + '</span></div>'
  ).join('');

  const rubricHtml = priorityGradingRules().map(rule => {
    const rm = PRIORITY_META[rule.tier] || PRIORITY_META.Low;
    const current = rule.tier === row.opportunity ? ' current' : '';
    return '<li class="prio-rule' + current + '">' +
      '<span class="prio-pill" style="background:' + rm.bg + ';color:' + rm.color + ';border-color:' + rm.color + ';">' +
      escapeHtml(rule.tier) + '</span>' +
      '<span class="prio-rule-text">' + escapeHtml(rule.text) + '</span></li>';
  }).join('');

  document.getElementById('prio-body').innerHTML =
    '<div class="prio-head" style="border-left:6px solid ' + meta.color + ';background:' + meta.bg + ';">' +
      '<div class="prio-head-tier" style="color:' + meta.color + ';">' + escapeHtml(meta.label) + '</div>' +
      '<h2 id="prio-title">Why is ' + escapeHtml(customer) + ' rated &ldquo;' + escapeHtml(row.opportunity) + '&rdquo;?</h2>' +
    '</div>' +
    '<section class="prio-section"><h3>Signals for this customer</h3>' + signalsHtml + '</section>' +
    '<section class="prio-section"><h3>Key numbers</h3><div class="prio-metrics">' + metricsHtml + '</div></section>' +
    '<section class="prio-section"><h3>How priorities are graded</h3>' +
      '<p class="prio-rubric-intro">The highest tier whose conditions are met wins. The tier this customer landed in is highlighted.</p>' +
      '<ul class="prio-rubric">' + rubricHtml + '</ul></section>';
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
