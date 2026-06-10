# LCC Domain Meals Report - Technical Documentation

## Overview

The LCC Domain Meals Report is a standalone static HTML dashboard generated from Dataverse data and prepared for GitHub Pages publication.

## Project Paths

- Working folder: `C:\DEV_Workspace\LCC_all\Report extern LCC Domain from Dataverse`
- Source reference: `C:\DEV_Workspace\LCC_all\Report extern LCC Domain from excel`
- Pattern reference: `C:\DEV_Workspace\LCC_all\Report extern SUN Domain`
- System runtime: `C:\DEV_Workspace\LCC_all\Systemfiles`

## Dataverse Source

- Org URL: `https://org1afb89f7.crm4.dynamics.com`
- Participant table: `new_mealparticipants`
- Scan log table: `new_mealscanlogs`

The report no longer reads `Meals_Database_Master1.xlsx`. `dataverse_export_report_data.ps1` reads both Dataverse entity sets through the Dataverse Web API and returns JSON to `gen_meals_report.py`.

## Field Mapping

Participant rows:

| Dataverse column | Report field |
| --- | --- |
| `new_no` | `NO.` |
| `new_firstnameandsurname` | `FirstName_and_Surname` |
| `new_idnumber` | `IDNumber` |
| `new_dateofbirth` | `Date of Birth` |
| `new_ageformula` | `Age` |
| `new_agegroupformula` | `Age Group` |
| `new_gender` | `Gender` |
| `new_race` | `Race` |
| `new_disabled` | `Disabled` |
| `new_specifydisability` | `Specify Disability` |
| `new_dateofadmission` | `Date of Admission` |
| `new_powerappsid` | `__PowerAppsId__` |

Scan log rows:

| Dataverse column | Report field |
| --- | --- |
| `new_firstnameandsurname` | `FirstName_and_Surname` |
| `new_idnumber` | `IDNumber` |
| `new_scantimestamp` | `ScanTimestamp` |
| `new_age` | `Age` |
| `new_gender` | `Gender` |
| `new_race` | `Race` |
| `new_disabled` | `Disabled` |
| `new_newqrcode` | `NewQRCode` |
| `new_powerappsid` | `__PowerAppsId__` |

The exporter probes optional columns before querying. This keeps the report stable when legacy columns such as `new_legacypowerappsid` are absent.

## Runtime Flow

1. `gen_meals_report.py` starts.
2. It calls `dataverse_export_report_data.ps1`.
3. The PowerShell script authenticates through service-principal variables or interactive Microsoft login.
4. Dataverse rows are normalized to the legacy report field names.
5. `Meals_Report_py.html` is generated.
6. `index.html` is updated for GitHub Pages.

## Local Commands

Generate once:

```powershell
python .\gen_meals_report.py --no-serve
Copy-Item .\Meals_Report_py.html .\index.html -Force
```

Generate with offline fallback:

```powershell
python .\gen_meals_report.py --no-serve --offline-fallback
Copy-Item .\Meals_Report_py.html .\index.html -Force
```

Run monitored automation without publishing:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_report_automation.ps1 -NoPublish
```

## Automation

- Monitor server: `monitor_server.py`
- Monitor URL: `http://127.0.0.1:8767/`
- Scheduled task name: `LCC Domain Meals Report Automation`
- Log path: `logs\report-automation.log`
- Status path: `status\last-run.json`

## GitHub Target

- Repository: `https://github.com/MarkusGhighi/lcc-domain-meals-report-dataverse`
- GitHub Pages URL: `https://markusghighi.github.io/lcc-domain-meals-report-dataverse/`

## Security

Secrets are not committed. `.env` is ignored by Git. For unattended automation, configure these local values:

```text
DATAVERSE_TENANT_ID=<tenant-id>
DATAVERSE_CLIENT_ID=<app-registration-client-id>
DATAVERSE_CLIENT_SECRET=<client-secret>
DATAVERSE_ORG_URL=https://org1afb89f7.crm4.dynamics.com
```

## Validation Targets

- Participant count should match Dataverse `new_mealparticipants`.
- Scan log count should match Dataverse `new_mealscanlogs`.
- Generated HTML should contain `LCC Domain Meals Report`.
- `index.html` should be identical to `Meals_Report_py.html` after generation.
