# Company Clinic

Streamlit app for patient files, repeat visits, follow-up notes and clinic reporting.

## Run

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

Set `DATABASE_URL` in the environment or Streamlit secrets to use PostgreSQL.
Environment configuration takes precedence. Without either, the app uses
`clinic_operations.db` in the working directory. PostgreSQL connections require SSL.

## Nurse workflow

1. In **Patient files**, search the patient selector by name, file number or employee reference. Create a file if needed.
2. In **Record a visit**, select that file and enter the encounter. Select multiple diagnoses and enter any additional diagnoses one per line. Leave unmeasured vital signs blank.
3. In **Patient files**, review previous visits and add dated follow-up notes to an encounter. A new attendance should be saved as a new visit.
4. In **Clinic overview**, choose a date range to see attendance, diagnoses, admissions, referrals, incident classifications and documentation completeness.

## Existing records

Startup creates four companion tables: `patients`, `visit_patients`,
`visit_diagnoses` and `visit_notes`. The original `patient_visits` table and
its records are preserved. Back up the database before upgrading.

Older visits appear in reporting immediately. In a patient file, use **Link an
existing visit** after checking identity to attach each old visit to the correct
file. No automatic name-based merging occurs. The linked encounter retains its
original name, demographics, diagnosis and notes.

New visits retain their first diagnosis in the original `primary_diagnosis`
column for compatibility; all diagnoses are saved separately. Follow-up notes
are appended and do not overwrite the original clinical notes. The entered
author name is a staff attribution, not authenticated identity.

Times are stored as UTC and displayed in Africa/Lagos. Existing timestamps are
interpreted as UTC, matching the previous app. Patient counts include linked
files only. Incident charts count visits, not unique injuries; admissions are
encounter counts, not bed occupancy. Historical default vitals cannot be
distinguished from measured readings.

This change does not add sign-in or roles. Continue using the company's existing
access controls for the app and database.

## Tests

```sh
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

Tests use temporary SQLite databases, including a legacy-schema upgrade test and
Streamlit form interactions. They do not connect to the company's database.
