# Web app — double-click flow

This folder is a self-contained, zero-install version of the Defender for Cloud ACR dashboard. No Python. No Docker. No build step.

## Quick start (colleagues)

1. Clone or download this repository.
2. Open `web-app/index.html` in **Microsoft Edge** or **Google Chrome** by double-clicking it.
3. Click **Pick an Excel file** (or drag and drop) and choose your `ACR Details by … Month` export. It stays on your machine.
4. Use the **Milestones** link in the top nav to switch to the milestone attach-gap view. There you pick **two** workbooks — one Migration export, one Defender export.

That's it. Both pages have **Export to PowerPoint** and the milestone page also has **Download CSV**.

## Why a static app

- **No install** — opens with a double-click. Ideal for sharing with colleagues who don't have Python or Docker.
- **Private by design** — Excel parsing happens entirely in your browser. No network requests are made when you open the page or process a file. Verify in DevTools → Network.
- **Portable** — works from a USB stick, a OneDrive folder, or anywhere the repo is cloned. Same files can later be hosted on private GitHub Pages or Azure Static Web Apps with zero code changes.

## What works

| Capability | How it's done |
|---|---|
| ACR opportunity dashboard (Sales Action Queue, Opportunity Heatmap, KPI cards, threshold slider, All Customers table) | `index.html` is generated from `docs/defender_for_cloud_dashboard (2).html` by `scripts/build_static_webapp.py`, with the Python model swapped for the JS port (`js/acr-model.js`). |
| Milestone attach-gap analysis | Two file pickers, same model as `milestone_analysis.py`. |
| PowerPoint export (both pages) | [PptxGenJS](https://gitbrent.github.io/PptxGenJS/) (vendored under `vendor/`). |
| CSV export (milestone gaps) | Browser `Blob` download with UTF-8 BOM. |
| Theme | Light + dark via `?theme=dark` or system preference. |
| "Re-open last file" (milestones page) | Chrome / Edge File System Access API. Falls back to a one-click file picker on Firefox / Safari. |

## What's different from the Flask/Docker app

- Browsers can't auto-scan a local folder without a user gesture, so there is no `inputfolder/` auto-pick. On Chrome / Edge the app remembers the last file you picked and offers a one-click **Re-open last file** button. On Firefox / Safari you re-pick once per session.
- PowerPoint slide layout may differ slightly from the Python deck (different rendering engine). Data and content are identical.
- The Flask + Docker path still works for anyone who prefers it — see the top-level [README.md](../README.md).

## Browser support

| Browser | Status |
|---|---|
| **Microsoft Edge 121+** | ✅ Recommended. Full feature set including re-open last file. |
| **Google Chrome 121+** | ✅ Recommended. Full feature set. |
| **Firefox 124+** | ✅ Works. Re-open last file unavailable (browser limitation) — re-pick per session. |
| **Safari 17+** | ⚠️ Works for parsing + rendering + exports. Re-open last file unavailable. |

## File layout

```
web-app/
  index.html              # ACR dashboard (GENERATED — do not hand-edit)
  milestones.html         # milestone gaps
  css/
    theme.css             # Clawpilot light/dark tokens
    app.css               # shell, nav, dropzone, empty state
    dashboard.css         # ACR charts and tables
    milestone.css         # milestone page
  js/
    theme.js              # apply theme from URL / system
    app-nav.js            # top nav between pages
    excel-loader.js       # SheetJS wrapper (milestones)
    csv-export.js         # CSV Blob download
    acr-model.js          # port of dashboard_model.py (consumed by index.html)
    milestone-model.js    # port of milestone_analysis.py
    milestone-view.js     # milestone page renderers
    milestone-app.js      # milestone page bootstrap
    pptx-acr.js           # ACR PowerPoint export
    pptx-milestones.js    # milestone PowerPoint export
  vendor/
    xlsx.full.min.js      # SheetJS 0.20.2 (MIT)
    pptxgen.bundle.js     # PptxGenJS 3.12.0 (MIT)
  tests/
    regression.cjs        # Node-based regression suite
```

No bundler, no `npm install`. Each `.js` file is loaded as a classic script, which avoids `file://` module-loading restrictions.

## Maintainer build step

`web-app/index.html` is generated from the dashboard template at
`docs/defender_for_cloud_dashboard (2).html`. Regenerate it after any change
to the template, the JS model (`web-app/js/acr-model.js`), or the Python
helpers it reuses (`src/defender_acr_dashboard/static_dashboard.py`):

```cmd
python scripts\build_static_webapp.py
```

CI / pre-commit can verify the file is up to date without writing:

```cmd
python scripts\build_static_webapp.py --check
```

The script asserts an expected occurrence count for every patch it applies,
so upstream drift fails loud and fast.

## Troubleshooting

- **"Import failed: missing $ ACR column"** — make sure you exported with the right view. The header row containing `$ ACR` must sit directly under the `FY##-Mon` row in the `Export` sheet.
- **PowerPoint export takes a few seconds for large workbooks** — that's expected, the deck is built fully client-side.
- **Charts look blank after import** — open DevTools → Console and check for parsing errors. Most issues are caused by an unusual export schema (renamed columns, hidden rows).
- **"Browser blocked the file picker on this page"** — some Chromium builds disable the modern file picker on `file://`. The app automatically falls back to the basic picker, so you can still load a workbook.

## Running the regression tests

The web app ships with a small Node-based regression suite that covers the
CSV-injection escaping, the milestone near-term timezone boundary, and the
chart-tooltip XSS-escape path. From the repo root:

```cmd
node web-app\tests\regression.cjs
```

Exits with a non-zero status if any check fails. No `npm install` required.

