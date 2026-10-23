"""Lagos-local reporting; visit, incident and current-care counts stay distinct."""
from datetime import date, timedelta
import csv
import io
import pandas as pd

ADMISSIONS = ['Short-Day', 'Short-Day Admission', 'Standard Admission']
COLUMNS = ['id', 'patient_id', 'timestamp', 'patient_name', 'age', 'gender', 'systolic_bp',
           'diastolic_bp', 'temperature_c', 'pulse_rate', 'respiratory_rate', 'spo2',
           'diagnoses', 'admission', 'referral', 'incident', 'incident_type', 'incident_id',
           'notes', 'triage', 'chief_complaint', 'observations', 'treatment', 'department',
           'status', 'recorded_by', 'version', 'bed_name', 'modern']


def visit_frame(records):
    frame = pd.DataFrame(records, columns=COLUMNS)
    frame['timestamp'] = pd.to_datetime(frame['timestamp'], utc=True, errors='coerce').dt.tz_convert('Africa/Lagos')
    return frame


def filter_visits(frame, start, end):
    return frame.loc[frame['timestamp'].dt.date.between(start, end)].copy()


def diagnosis_counts(frame):
    if frame.empty: return pd.DataFrame(columns=['Diagnosis', 'Visits'])
    exploded = frame[['id', 'diagnoses']].explode('diagnoses').dropna()
    exploded['key'] = exploded['diagnoses'].str.strip().str.casefold()
    exploded = exploded[~exploded['key'].isin(['', 'not yet recorded'])].drop_duplicates(['id', 'key'])
    counts = exploded.groupby('key').size().sort_values(ascending=False)
    labels = exploded.groupby('key')['diagnoses'].first()
    return pd.DataFrame({'Diagnosis': labels.reindex(counts.index).values, 'Visits': counts.values})


def daily_counts(frame, start, end):
    counts = frame.groupby(frame['timestamp'].dt.date).size()
    days = pd.date_range(start, end, freq='D').date
    return pd.DataFrame({'Date': days, 'Visits': counts.reindex(days, fill_value=0).values})


def week_bounds(day, starts_on=0):
    """Monday=0, Sunday=6. Return complete, inclusive seven-day calendar boundaries."""
    start = day - timedelta(days=(day.weekday() - starts_on) % 7)
    return start, start + timedelta(days=6)


def local_date(value):
    if value is None: return None
    stamp = pd.Timestamp(value)
    if pd.isna(stamp): return None
    if stamp.tzinfo is None: stamp = stamp.tz_localize('UTC')
    return stamp.tz_convert('Africa/Lagos').date()


def in_period(value, start, end):
    day = local_date(value)
    return day is not None and start <= day <= end


def incident_period(incidents, start, end):
    return [i for i in incidents if in_period(i['occurred_at'], start, end)]


def period_summary(frame, incidents, events, start, end):
    visits = filter_visits(frame, start, end)
    injury_cases = incident_period(incidents, start, end)
    period_events = [e for e in events if in_period(e['timestamp'], start, end)]
    legacy = visits[~visits.modern.astype(bool)]
    # New encounters use dated care events; old rows retain their old flags.
    admission_ids = {e['visit_id'] for e in period_events if e['status'] == 'Short-day admission'}
    admission_ids.update(legacy.loc[legacy.admission.isin(ADMISSIONS), 'id'])
    referral_ids = {e['visit_id'] for e in period_events if e['status'] == 'Referred'}
    referral_ids.update(legacy.loc[legacy.referral.astype(bool), 'id'])
    legacy_incident = visits[visits.incident.astype(bool) & visits.incident_id.isna()]
    return {
        'Visits': len(visits),
        'Linked patients seen': int(visits.patient_id.nunique()),
        'Unlinked visits': int(visits.patient_id.isna().sum()),
        'Urgent / emergency visits': int(visits.triage.isin(['Urgent', 'Emergency']).sum()),
        'Observation entries': len({e['visit_id'] for e in period_events if e['status'] == 'Observation'}),
        'Admissions': len(admission_ids),
        'Discharges': len({e['visit_id'] for e in period_events if e['status'] == 'Discharged'}),
        'Referrals': len(referral_ids),
        'Workplace incidents': len(injury_cases),
        'LTI cases': sum(i['is_lti'] for i in injury_cases),
        'Legacy incident visits (not distinct cases)': len(legacy_incident),
        'Legacy LTI-classified visits': int(legacy_incident.incident_type.eq('Major (LTI)').sum()),
    }


def documentation(frame):
    total = len(frame)
    measures = [('Blood pressure', frame.systolic_bp.notna() & frame.diastolic_bp.notna()),
                ('Temperature', frame.temperature_c.notna()), ('Pulse', frame.pulse_rate.notna()),
                ('Respiratory rate', frame.respiratory_rate.notna()), ('SpO₂', frame.spo2.notna()),
                ('Triage category', frame.triage.isin(['Routine', 'Urgent', 'Emergency'])),
                ('Diagnosis', frame.diagnoses.map(bool))]
    return pd.DataFrame([{'Field': label, 'Visits recorded': int(mask.sum()),
                          'Coverage (%)': round(mask.sum()/total*100, 1) if total else 0}
                         for label, mask in measures])


def safe_csv_cell(value):
    """Neutralize spreadsheet formulas in user-entered labels."""
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


def csv_bytes(rows):
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    for row in rows: writer.writerow([safe_csv_cell(c) for c in row])
    return output.getvalue().encode('utf-8-sig')


def report_csv(frame, incidents, events, start, end):
    visits = filter_visits(frame, start, end)
    summary = period_summary(frame, incidents, events, start, end)
    rows = [['Company clinic weekly report'], ['Period start', start.isoformat()],
            ['Period end', end.isoformat()], ['Timezone', 'Africa/Lagos'], [], ['Metric', 'Count']]
    rows += list(summary.items())
    rows += [[], ['Date', 'Visits']] + daily_counts(visits, start, end).values.tolist()
    rows += [[], ['Diagnosis', 'Visits']] + diagnosis_counts(visits).values.tolist()
    dept = visits.department.replace('', 'Not recorded').fillna('Not recorded').value_counts()
    rows += [[], ['Department (at visit)', 'Visits']] + list(dept.items())
    rows += [[], ['Documentation field', 'Visits recorded', 'Coverage (%)']] + documentation(visits).values.tolist()
    rows += [[], ['Counting notes'],
             ['Visits use visit date; care outcomes use event date. A prior-week visit can be discharged this week.'],
             ['Incident cases use incident occurrence date. Follow-up visits do not create additional cases.'],
             ['LTI reflects the latest recorded classification, including later updates.'],
             ['Legacy incident visits are shown separately because distinct cases are unknown.'],
             ['Multi-diagnosis visits count once per diagnosis; category totals can exceed visits.'],
             ['No patient names, employee IDs, contacts or clinical notes are included.']]
    return csv_bytes(rows)


def usage_table(visits, patients, incidents, events, start, end):
    """Period usage by stable patient ID; duration requires a dated closure."""
    columns = ['Patient reference', 'File number', 'Patient', 'Visits', 'First visit', 'Latest visit',
               'Mean gap (days)', 'Completed durations', 'Mean duration (hours)', 'Injury incidents', 'LTI cases']
    people = {p['id']: p for p in patients}
    cases = incident_period(incidents, start, end)
    ids = set(visits.patient_id.dropna()) | {i['patient_id'] for i in cases}
    closures = {}
    for e in events:
        if e['status'] in ('Discharged', 'Referred'):
            t = pd.to_datetime(e['timestamp'], utc=True, errors='coerce')
            if not pd.isna(t): closures[e['visit_id']] = min(t, closures.get(e['visit_id'], t))
    rows = []
    for pid in ids:
        p = people.get(pid, {})
        v = visits[visits.patient_id == pid].sort_values('timestamp')
        stamps = v.timestamp.dropna()
        durations = []
        for _, visit in v.iterrows():
            close = closures.get(visit.id)
            if close is not None and pd.notna(visit.timestamp) and close >= visit.timestamp:
                durations.append((close - visit.timestamp).total_seconds()/3600)
        injuries = [i for i in cases if i['patient_id'] == pid]
        rows.append([p.get('employee_id') or 'Not recorded', f'CL-{int(pid):06d}', p.get('name','Unknown'),
                     len(v), stamps.iloc[0].strftime('%d %b %Y %H:%M') if len(stamps) else None,
                     stamps.iloc[-1].strftime('%d %b %Y %H:%M') if len(stamps) else None,
                     round(stamps.diff().dt.total_seconds().mean()/86400, 1) if len(stamps)>1 else None,
                     len(durations), round(sum(durations)/len(durations), 2) if durations else None,
                     len(injuries), sum(bool(i['is_lti']) for i in injuries)])
    return pd.DataFrame(rows, columns=columns).sort_values(['Visits','Injury incidents','File number'], ascending=[False,False,True]).reset_index(drop=True)
