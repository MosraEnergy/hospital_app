# Company Clinic — improved Streamlit edition

An upgrade of your Streamlit application, keeping patient files, repeat visits and follow-up notes while simplifying the dashboard and completing the clinic workflow.

## Start or upgrade

Requires Python 3.11 or later.

1. Stop the old app and back up your existing `clinic_operations.db` (or take a PostgreSQL backup).
2. Extract this package into your project folder and replace the old code files. The package does **not** contain a database or credentials, so it cannot overwrite your existing database file.
3. Keep `clinic_operations.db` beside `app.py` for local use. Without a configured database, a new empty local database is created at that location. No sample patient records are inserted.
4. Install dependencies and launch:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

Startup creates missing companion tables. It does not rewrite old visits or automatically match people by name. Existing tables from your app remain supported. Test the upgrade on a database copy or Neon development branch first.

## What changed

| Area | Updated behaviour |
| --- | --- |
| Overview | Four period totals, live active-care list, recent visits and a compact diagnosis table. Detailed charts are on Weekly reports. |
| Patient profiles | Name, age, gender, unique employee ID, department, contacts and emergency contact. Search by name, employee ID or clinic file number. |
| Longitudinal records | Chronological encounters, notes, treatment, care events, and vital-sign trends. Recent patient history is visible alongside the new-visit form. |
| Assessment | BP, temperature, pulse, respiratory rate, SpO₂, nurse-assigned triage, chief complaint and observations. Unmeasured vitals stay blank. |
| Diagnoses | Standard multi-select and adjacent free-text diagnoses; case-insensitive deduplication. A triage encounter may be saved before diagnosis is recorded. |
| Treatment | Separate treatment field. An open encounter can be completed later using an assessment update. Original assessments and subsequent revisions are retained. |
| Active care | In consultation, Observation, Short-day admission, Discharged or Referred. Actual bed names are configurable; conflicting bed assignments and stale care updates are rejected. |
| Discharge / referral | Formal dated care event, recorded-by attribution, handover notes and referral destination. Closing an encounter releases its bed. |
| Workplace incidents | Separate injury type, department and LTI classification. Repeated visits link to one incident case. Dated safety updates preserve LTI classification history. |
| Weekly reporting | Monday–Sunday or Sunday–Saturday weeks, aggregate CSV export, attendance, diagnoses, departments, outcomes, incidents/LTIs and documentation coverage. |
| Neon | PostgreSQL connection-string support, TLS, connection checks, bounded pool and development-branch setup instructions. |

## Daily clinic workflow

1. **Patient files:** search before registering. Confirm identity, then create a file if necessary. Two people with the same name keep separate file numbers.
2. **Record a visit:** choose the patient, review prior encounters, choose the care status and complete the assessment. Select any applicable diagnoses or leave them blank until assessed. Record the staff name and save.
3. **Observation & active care:** complete or revise an assessment, add care notes, assign a bed, or formally discharge/refer. The app allows only one open encounter per patient.
4. **Workplace incidents:** create one injury case, optionally linking the initial visit. Subsequent visits can link to that incident. LTI is a separate safety classification, not inferred from severity.
5. **Weekly reports:** select a reporting week and download the automatically aggregated summary.

Set up the real bed names in **Clinic setup**. The application does not assume a bed count.

## Neon configuration and development branching

Use either `DATABASE_URL` in the environment or `.streamlit/secrets.toml`. Environment values take precedence. A template is included as `.streamlit/secrets.example.toml`; copy it to `secrets.toml` and enter the credentials privately. `.env` files are not automatically loaded.

For a new deployment:

1. Create a separate Neon development branch. Prefer a **schema-only branch** when production contains patient records; populate it with fictional test data.
2. In Neon's Connect dialog, select that branch and use its pooled connection string. The pooled hostname includes `-pooler`.
3. Set the development `DATABASE_URL`, then launch this app. Run the tests and validate your clinic workflow on that branch.
4. Before production, back up the clinic database, verify recovery, and configure the production connection separately. Set `CLINIC_ENV="production"` to prevent silent fallback to SQLite if the URL is missing.
5. Keep development and production credentials separate. A branch connection does not migrate existing SQLite data into Neon; any data transfer needs a separate, verified migration.

Optional settings: `CLINIC_NAME`, `REPORT_WEEK_START` (`Monday` or `Sunday`), and `CLINIC_ENV` (`local`, `development`, or `production`). All timestamps are stored in UTC and displayed in Africa/Lagos.

The database engine uses `pool_pre_ping=True`, `pool_recycle=300`, a pool size of 5 and up to 5 overflow connections for PostgreSQL. These checks recover stale connections before checkout; they do not guarantee recovery from a disconnection in the middle of a transaction. Failed saves keep the form entries. Visit submissions use a request key to avoid duplicate encounters after retrying an uncertain save.

References: [Neon connection pooling](https://neon.com/docs/connect/connection-pooling), [Neon schema-only branches](https://neon.com/docs/guides/branching-schema-only), [SQLAlchemy connection checks](https://docs.sqlalchemy.org/en/21/core/pooling.html).

## Reporting and optional scheduled exports

The report screen calculates totals from the database whenever it is opened. It does not require copying data into a spreadsheet.

For an export that runs without opening the app:

```sh
# Previous complete week, using the configured week start:
.venv/bin/python report_weekly.py

# A particular week:
.venv/bin/python report_weekly.py --date 2026-10-19 --week-start Monday --output-dir reports
```

The CLI reads the same environment or secrets file and writes an aggregate `clinic-weekly-YYYY-MM-DD.csv`. It can be run by the deployment host's scheduler. No scheduler or email delivery has been configured by this update. Regenerating a week replaces that week's local CSV with the latest counts; retain dated copies separately if your process requires frozen reports.

### Counting rules

- Attendance and diagnoses use the visit's date in Lagos. One visit counts once per diagnosis, so diagnosis totals can exceed attendance.
- Care outcomes use the event date. A prior-week encounter can be discharged or referred in the current week. Outcome rows can overlap and are not a partition of attendance.
- Active-care totals and bed occupancy represent **current state**, independently of a reporting date range.
- Incident cases use the injury occurrence date. Follow-up attendances do not create extra incident cases. LTI counts use the latest recorded classification.
- Old incident flags are reported separately as **legacy incident visits**, because their distinct injury cases are unknown. After staff reconcile and link a visit to a case, it contributes through that case.
- Legacy admission/referral flags remain counted by their visit date. A historic admission is not assumed to be a currently occupied bed.
- Department is preserved as recorded at an encounter. Later profile edits do not recategorize old attendance.
- Weekly CSV summaries omit names, employee IDs, contact details and clinical notes. User-entered CSV labels are protected against spreadsheet formula interpretation.

## Data preservation and changes

Original tables are retained: `patient_visits`, `patients`, `visit_patients`, `visit_diagnoses`, `visit_notes`.

New companion tables: `patient_profiles`, `encounter_details`, `clinic_beds`, `care_events`, `assessment_revisions`, `workplace_incidents`, `incident_visits`, `incident_updates`.

There are no automatic DELETE, DROP or ALTER operations, no name-based patient merges, and no default values inserted as measured vital signs. Initial visit data remain available after assessment revisions. A closed encounter accepts appended notes; a new attendance is a new encounter. Older unlinked visits can be attached only after the user confirms identity.

Startup table creation is an additive bootstrap, not a general migration framework. Future changes to columns in these tables should use reviewed, versioned migrations.

## Verification

```sh
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Tests use temporary databases and fictional records. They cover legacy-row preservation, patient history, nullable vitals, duplicate submissions, current-care/bed conflicts, assessment history, discharge/referral, incident deduplication, Lagos reporting dates, aggregate-export privacy and CSV formula handling. Streamlit AppTest exercises actual widgets through the clinic workflows. PostgreSQL table definitions are compiled during tests; a live Neon connection requires your branch credentials and has not been tested here.

## Deployment boundary

This update records staff-entered triage and diagnoses; it does not provide medical recommendations. Staff names are attribution only, not authenticated identity. Individual sign-in, role-based permissions, access auditing, backup/recovery and the clinic's privacy controls must be configured before real patient use. The retained assessment/care history is useful record history, but is not a complete authenticated security audit trail.

Browser/tablet visual layout has not been screenshot-verified in this workspace. Streamlit's responsive layouts are used, and the workflows were exercised through Streamlit's testing interface. Reports use a general clinic format; your official weekly template and clinical terminology can be substituted later.


## Dashboard update — 23 October 2026
Replace app.py, analytics.py and clinic_data.py together, then reboot Streamlit. Keep your existing DATABASE_URL secret and database. No data migration is required.

Overview defaults to the last 30 days. It shows visits, unique linked patients, repeat visitors, diagnoses, dated injury incidents, affected people, repeat injuries and LTI cases. Two charts show common diagnoses and activity over time; tables show injury types/departments and individual usage. Patient references retain existing employee IDs.

Usage statistics refer to the selected dates. Mean visit gap uses consecutive visits. Mean duration uses visit start to first dated discharge/referral, including closures after the selected period. Missing closure times are excluded, and the number of completed durations is displayed. This is recorded elapsed time, not measured hands-on treatment time. Injury-only patients appear with zero visits. Legacy injury visits lacking an incident record are disclosed separately. No workforce-normalized injury rate is calculated without headcounts or hours worked.

New patient gender choices are Male and Female; existing records are preserved. Clinical notes and treatment remain separate fields.
