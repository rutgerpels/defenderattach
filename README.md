# Defender ACR dashboard

Local dashboard for comparing total customer ACR against Defender for Cloud ACR and identifying growth opportunities.

The app now includes two separate views:

- **ACR dashboard** compares total customer ACR with Defender for Cloud ACR.
- **Milestone attach gaps** compares Migration milestones with Defender for Cloud milestones.

## Two ways to run

### ⭐ Static web app (recommended for colleagues — no install)

Open [`web-app/index.html`](./web-app/index.html) by **double-clicking** it in Microsoft Edge or Google Chrome, then choose the ACR dashboard or the milestone dashboard. No Python, no Docker, no `npm install` — Excel parsing happens entirely in the browser and your data never leaves your machine.

Read [`web-app/README.md`](./web-app/README.md) for the full colleague-friendly guide, browser support matrix, and feature list.

### Flask + Docker (power users / shared deployments)

The original Python stack is still here for anyone who wants `inputfolder/` auto-loading or plans to deploy to a server. See the **Run locally** section below.

## Stack

- Flask-served HTML dashboard based on the executive opportunity dashboard in `docs`
- pandas and openpyxl for Excel ingestion
- Native SVG charts in the browser for fast drill-downs
- python-pptx for Flask/Docker PowerPoint export

## Data assumptions

The app loads the newest Excel workbook from `inputfolder` and expects the `Export` sheet to use the two-row structure from the Azure Service Level Subscription Details extract. The browser dashboard uses monthly `$ ACR`:

- `TPAccountName` identifies the customer.
- `ServiceCompGrouping` identifies the product/service group.
- `ServiceCompGrouping = "Total"` is the customer total ACR.
- `ServiceCompGrouping = "Defender for Cloud"` is Defender for Cloud ACR.
- Monthly `$ ACR` columns are grouped under fiscal month headers like `FY26-Jul`.

The milestone attach view loads the newest Migration and Defender workbooks from `inputfolder_opty`. The file names must contain `Migration` and `Defender`, and each workbook must have an `Export` sheet with these fields:

- `Translated Account Name`
- `Opportunity ID`
- `Milestone ID`
- `Milestone Name`
- `Milestone Workload`
- `Workload`
- `ACR Pipeline $`
- `Status`
- `Commitment`
- `Due Date`
- `Category`
- `Owner Role`
- `Owner`

## Run locally on Windows

The easiest local option is:

```cmd
start-dashboard.cmd
```

The script creates `.venv` if needed, installs dependencies, opens your browser, and starts the local dashboard at `http://127.0.0.1:8050`.

Use the top navigation to switch between the ACR dashboard and the milestone attach gap view. The navigation stays fixed while each dashboard loads inside the main frame.

To run the optional Streamlit service-attach helper instead, use:

```cmd
start-service-attach.cmd
```

That script installs `requirements-streamlit.txt` into the same local `.venv`.

## Run with Docker Compose

If you prefer not to manage Python locally, run:

```powershell
docker compose up --build
```

Then open `http://localhost:8050`.

Docker Desktop must be running before you run the command. The container mounts `inputfolder` and `inputfolder_opty` as read-only and writes PowerPoint exports to `output`.

## Manual local run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -e . --no-deps
$env:PYTHONPATH = ".\src"
python app.py
```

Open the local dashboard URL printed in the terminal.

## Export

The Flask/Docker app still includes PowerPoint export endpoints that generate decks in `output` and download them from the browser.

- The ACR dashboard deck includes the ranked customer opportunity table and charts for the top flagged customers.
- The milestone attach deck includes summary metrics, priority mix, top 10 highest-priority gaps, and methodology notes.

In the zero-install static web app, the ACR page currently shows a **Build sales plan** placeholder instead of the retired browser PowerPoint export. The milestone attach view still includes **Export to PowerPoint** and **Download CSV** actions.

## Opportunity defaults

Customers are flagged when:

- Defender for Cloud share is below the selected threshold. The default dashboard threshold is 6%.
- Non-Defender ACR is growing more than 10% MoM.

The Opportunity Matrix includes a Defender share slider so you can tune the view during analysis. The slider changes the heatmap highlighting and the sales action queue without reloading the page.

## Dashboard workflow

The main dashboard uses four tabs:

- **Overview** for portfolio KPIs, attach gaps by Defender service, product mix, and top accounts.
- **Service Attach Opportunities** for workloads customers buy but do not protect with the matching Defender plan.
- **Defender Coverage Drift** for accounts where workload growth and Defender growth are moving apart.
- **Customer Drill-Down** for customer-specific DfC penetration and product breakdown.

The Excel import button from the original HTML example is disabled in this local app. To refresh data, replace the workbook in `inputfolder` and refresh the browser or restart the container.

## Milestone attach gap workflow

Open **Milestone Attach Gaps** from the top navigation or browse to `http://127.0.0.1:8050/milestones`. The standalone dashboard content is served inside the app frame from `/embed/milestones`.

The view compares Migration milestones against Defender for Cloud milestones in two steps:

- **Account-level gap**: the account has Migration milestones but no Defender milestones.
- **Attached account**: the account has both Migration and Defender milestones.
- **Opportunity-level gap**: for attached accounts, a Migration `Opportunity ID` has no Defender milestone with the same account and `Opportunity ID`.

Priority is assigned as:

- **HIGH** when at least one migration milestone is committed or has an estimated date within the near-term window.
- **MEDIUM** when the milestone is uncommitted but has a recognized workload.
- **LOW** when the workload is unclear or edge-case.

The near-term window defaults to 90 days. To change it, add `near_term_days` to the URL, for example:

```text
http://127.0.0.1:8050/milestones?near_term_days=120
```

Strict `Opportunity ID` matching can overstate gaps if Migration and Defender work are tracked under separate CRM opportunities. Use the detail panel and exports as a prioritization aid before account follow-up.

## Sales action queue

The Opportunity Matrix tab includes a sales action queue under the heatmap. It shows both FYTD ACR and latest monthly ACR for Total and Defender for Cloud. The threshold and gap calculations use latest monthly ACR as the run-rate basis:

```text
max(0, total monthly ACR * selected Defender share threshold - Defender monthly ACR)
```

The tab also annualizes that monthly gap:

```text
estimated monthly gap * 12
```

This is shown as **Annualized DfC ACR Opportunity**. The gap is directional sizing only. It is not a forecast, pipeline number, or revenue commitment.

Use the queue to:

- Review the top 10, top 25, or all visible actions.
- Click a customer row to open the existing customer drill-down.
- Copy the current action list for email or Teams.
- Download the current action list as CSV for follow-up tracking.
