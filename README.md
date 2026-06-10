# LCC Domain Meals Report

Standalone GitHub Pages-ready report for the LCC Domain area.

## Data Source

The report reads directly from Dataverse:

- Meal Participant: `new_mealparticipants`
- Meal Scan Log: `new_mealscanlogs`

The Dataverse export script is `dataverse_export_report_data.ps1`. It uses the existing PAC/MSAL runtime in `..\Systemfiles\pac_nupkg_2.7.4\tools`.

Default Dataverse org:

```text
https://org1afb89f7.crm4.dynamics.com
```

## Generate Locally

```powershell
python .\gen_meals_report.py --no-serve
Copy-Item .\Meals_Report_py.html .\index.html -Force
```

For a local preview without live Dataverse authentication, use the explicit fallback based on the existing Dataverse import files:

```powershell
python .\gen_meals_report.py --no-serve --offline-fallback
Copy-Item .\Meals_Report_py.html .\index.html -Force
```

## Live Automation Monitor

Start the local live dashboard:

```cmd
start_monitor.bat
```

Dashboard URL:

```text
http://127.0.0.1:8767/
```

The automation wrapper writes live status, history, and logs:

```text
run_report_automation.ps1
status\current-run.json
status\last-run.json
status\history.jsonl
logs\report-automation.log
```

Local test run without publishing:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_report_automation.ps1 -NoPublish
```

## Publish

```cmd
Publish_Report.bat
```

`Publish_Report.bat` calls the monitored automation wrapper. It generates the Dataverse report, updates `index.html`, commits only when the report changed, pushes to GitHub, checks GitHub Pages, and writes all results to the monitor dashboard.

## Scheduled Automation

Install a Windows scheduled task that runs every 30 minutes:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_automation_task.ps1
```

For fully unattended runs, Dataverse authentication should use a Service Principal / Dataverse Application User. Interactive user-token fallback can stop when Microsoft requires a fresh login.

## Service Principal Auth

For unattended Dataverse export, set these local environment variables or create a local `.env` file. Do not commit `.env`.

```text
DATAVERSE_TENANT_ID=<tenant-id>
DATAVERSE_CLIENT_ID=<app-registration-client-id>
DATAVERSE_CLIENT_SECRET=<client-secret>
DATAVERSE_ORG_URL=https://org1afb89f7.crm4.dynamics.com
```

## GitHub

Repository:

```text
https://github.com/MarkusGhighi/lcc-domain-meals-report-dataverse
```

Live GitHub Pages report:

```text
https://markusghighi.github.io/lcc-domain-meals-report-dataverse/
```
