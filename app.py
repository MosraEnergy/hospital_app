import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from analytics import (visit_frame, filter_visits, daily_counts, diagnosis_counts, documentation,
                       week_bounds, period_summary, incident_period, report_csv, local_date, usage_table)
from clinic_data import ClinicStore, ACTIVE, CLOSED, STATUSES, TRIAGE, GENDERS, clean_diagnoses, file_number, make_engine

LOCAL_TZ = ZoneInfo('Africa/Lagos')
ROOT = Path(__file__).resolve().parent
DIAGNOSES = ['Malaria', 'Hypertension (Elevated BP)', 'Peptic Ulcer Disease (PUD)',
             'Typhoid Fever', 'Upper Respiratory Tract Infection (URTI)',
             'Musculoskeletal Pain / Trauma', 'Skin Infection', 'Other Operational/Routine Encounter']
PAGES = ['Overview', 'Patient files', 'Record a visit', 'Observation & active care', 'Workplace incidents', 'Weekly reports', 'Clinic setup']
st.set_page_config(page_title='Company Clinic', page_icon='🏥', layout='wide')
st.markdown('''<style>
.stMainBlockContainer{max-width:1380px;padding-top:2rem;padding-bottom:3rem}
h1{letter-spacing:-.04em} h2{letter-spacing:-.025em}
[data-testid="stMetric"]{background:var(--secondary-background-color);border:1px solid #9aafb524;border-radius:12px;padding:16px 18px}
[data-testid="stMetricValue"]{font-size:1.9rem}
[data-testid="stSidebar"]{border-right:1px solid #9aafb524}
[data-testid="stSidebar"] h1{font-size:1.4rem}
div[data-testid="stForm"]{border-radius:12px}
@media(max-width:700px){.stMainBlockContainer{padding:1rem}.stMetric{padding:10px}}
</style>''', unsafe_allow_html=True)


def setting(key, default=None):
    value = os.environ.get(key)
    if value is not None: return value
    try: return st.secrets.get(key, default)
    except FileNotFoundError: return default


@st.cache_resource
def get_store():
    # Absolute path avoids accidentally opening a second database from another working directory.
    url = setting('DATABASE_URL')
    if not url and setting('CLINIC_ENV', 'local').lower() == 'production':
        raise ValueError('DATABASE_URL is required in production; the app will not fall back to a local database.')
    return ClinicStore(make_engine(url or f'sqlite:///{ROOT / "clinic_operations.db"}'))


def now(): return datetime.now(LOCAL_TZ)


def goto(page, patient_id=None):
    st.session_state['workspace_page'] = page
    if patient_id is not None:
        st.session_state['selected_patient_id'] = patient_id
        for key in ('file_patient', 'intake_patient', 'incident_patient'):
            st.session_state[key] = patient_id


def refresh(message):
    st.session_state['notice'] = message
    st.rerun()


def token(key):
    if key not in st.session_state: st.session_state[key] = str(uuid4())
    return st.session_state[key]


def persist(action, message, reset=()):
    try:
        result = action()
    except ValueError as exc:
        st.error(str(exc)); return
    except IntegrityError:
        st.error('A duplicate reference or concurrent update prevented this save. Refresh and check the existing record before retrying.'); return
    except SQLAlchemyError:
        st.error('The database did not confirm the save. Your entries remain here. Refresh records to check whether it saved before retrying.'); return
    for key in reset: st.session_state.pop(key, None)
    refresh(message(result) if callable(message) else message)


def patient_label(p):
    return f'{p["name"]} · {file_number(p["id"])}' + (f' · {p["employee_id"]}' if p['employee_id'] else '')


def stamp(value):
    if value is None or pd.isna(value): return 'Date not recorded'
    d = pd.Timestamp(value)
    d = d.tz_localize('UTC') if d.tzinfo is None else d
    return d.tz_convert('Africa/Lagos').strftime('%d %b %Y, %H:%M')


def visit_label(v):
    return f'#{v["id"]} · {stamp(v["timestamp"])} · {"; ".join(v["diagnoses"]) or v["chief_complaint"] or "Diagnosis not recorded"}'


def patient_picker(label, key):
    if not patients:
        st.info('Create a patient file first.')
        st.button('Go to patient files', key=f'empty_{key}', on_click=goto, args=('Patient files',))
        return None
    ids = [p['id'] for p in patients]
    if key in st.session_state and st.session_state[key] not in ids: del st.session_state[key]
    if key not in st.session_state:
        selected = st.session_state.get('selected_patient_id')
        st.session_state[key] = selected if selected in ids else ids[0]
    selected = st.selectbox(label, ids, format_func=lambda i: patient_label(patient_by_id[i]), key=key)
    return patient_by_id[selected]


def visit_table(rows, full=False):
    output = []
    for v in rows:
        item = {'Visit': v['id'], 'Patient': v['patient_name'], 'Date / time': stamp(v['timestamp']),
                'Triage': v['triage'], 'Status': v['status']}
        if full:
            item.update({'Department': v['department'] or 'Not recorded',
                         'Diagnoses': '; '.join(v['diagnoses']) or 'Not recorded', 'Bed': v['bed_name'] or '—'})
        else: item['Complaint / diagnosis'] = v['chief_complaint'] or '; '.join(v['diagnoses'])
        output.append(item)
    st.dataframe(pd.DataFrame(output), hide_index=True, width='stretch')


def heading(title, caption):
    st.title(title); st.caption(caption)


def display_visit(v, compact=False):
    st.write('**Diagnoses:** ' + ('; '.join(v['diagnoses']) or 'Not recorded'))
    st.caption(f'Triage: {v["triage"]} · Current status: {v["status"]}' + (f' · {v["bed_name"]}' if v['bed_name'] else ''))
    def n(key): return f'{v[key]:g}' if pd.notna(v[key]) else '—'
    values = [('BP', f'{n("systolic_bp")}/{n("diastolic_bp")} mmHg'), ('Temperature', f'{n("temperature_c")} °C'),
              ('Pulse', f'{n("pulse_rate")} bpm'), ('Respiratory rate', f'{n("respiratory_rate")} /min'), ('SpO₂', f'{n("spo2")} %')]
    st.dataframe(pd.DataFrame(values, columns=['Vital sign', 'Recorded value']).set_index('Vital sign').T,
                 width='stretch')
    for label, key in [('Chief complaint', 'chief_complaint'), ('Clinical notes', 'observations'), ('Treatment provided', 'treatment')]:
        if v.get(key): st.write(f'**{label}**'); st.text(v[key])
    if v.get('notes'):
        st.write('**Original clinical notes**'); st.text(v['notes'])
    if not v['modern']:
        st.caption(f'Historical record · admission: {v["admission"] or "Not recorded"} · referral: {"Yes" if v["referral"] else "No"}. Current care status is unconfirmed.')
    if not compact:
        revisions = store.assessments(int(v['id']))
        if revisions:
            with st.expander('Assessment changes and original entry'):
                for idx, revision in enumerate(revisions):
                    if idx == 0:
                        st.write('**Original assessment**')
                        assessment_snapshot(revision['previous'])
                    st.caption(f'{stamp(revision["timestamp"])} · {revision["author"]} · {revision["reason"]}')
                    assessment_snapshot(revision['current'])
        for e in store.events(int(v['id'])):
            st.caption(f'{stamp(e["timestamp"])} · {e["status"]} · {e["author"]}' + (f' · {e["bed_name"]}' if e['bed_name'] else ''))
            if e['referral_to']: st.write('Referral destination:', e['referral_to'])
            if e['note']: st.text(e['note'])
        for note in store.notes(int(v['id'])):
            st.caption(f'Follow-up · {stamp(note.timestamp)} · {note.author}'); st.text(note.text)


def assessment_snapshot(s):
    st.write('Diagnoses: ' + ('; '.join(s['diagnoses']) or 'Not recorded'))
    st.caption(f'Triage: {s["triage"]} · BP {s["systolic_bp"]}/{s["diastolic_bp"]} · Temp {s["temperature_c"]} °C · Pulse {s["pulse_rate"]} · RR {s["respiratory_rate"]} · SpO₂ {s["spo2"]}%')
    for label, key in [('Complaint', 'chief_complaint'), ('Observations', 'observations'), ('Treatment', 'treatment')]:
        if s.get(key): st.write(f'**{label}:**'); st.text(s[key])


def assessment_form(v):
    def val(key):
        value = v[key]
        return value if pd.notna(value) else None
    with st.expander('Complete or update the assessment'):
        st.caption('Save further measurements, diagnoses and treatment. The original entry and every assessment revision remain available in the patient file.')
        with st.form(f'assessment_{v["id"]}_{v["version"]}'):
            triage = st.selectbox('Triage category', TRIAGE, index=TRIAGE.index(v['triage']))
            complaint = st.text_input('Chief complaint *', value=v['chief_complaint'])
            a, b, c = st.columns(3)
            systolic = a.number_input('Systolic BP (mmHg)', 1, 350, value=int(val('systolic_bp')) if val('systolic_bp') is not None else None, step=1)
            diastolic = b.number_input('Diastolic BP (mmHg)', 1, 250, value=int(val('diastolic_bp')) if val('diastolic_bp') is not None else None, step=1)
            temp = c.number_input('Temperature (°C)', 20.0, 50.0, value=float(val('temperature_c')) if val('temperature_c') is not None else None, step=0.1)
            pulse = a.number_input('Pulse (bpm)', 0, 350, value=int(val('pulse_rate')) if val('pulse_rate') is not None else None, step=1)
            rr = b.number_input('Respiratory rate (/min)', 0, 100, value=int(val('respiratory_rate')) if val('respiratory_rate') is not None else None, step=1)
            spo2 = c.number_input('SpO₂ (%)', 0.0, 100.0, value=float(val('spo2')) if val('spo2') is not None else None, step=1.0)
            a, b = st.columns(2)
            dx = a.multiselect('Diagnoses', DIAGNOSES, default=[d for d in v['diagnoses'] if d in DIAGNOSES])
            custom = b.text_area('Other diagnoses', value='\n'.join(d for d in v['diagnoses'] if d not in DIAGNOSES))
            observations = st.text_area('Clinical notes', value=v['observations'])
            treatment = st.text_area('Treatment provided', value=v['treatment'])
            reason = st.text_input('Reason for update *', placeholder='e.g. assessment completed, repeat vital signs')
            author = st.text_input('Recorded by *', max_chars=100)
            if st.form_submit_button('Save assessment update', type='primary'):
                def save():
                    values = dict(triage=triage, chief_complaint=complaint, observations=observations, treatment=treatment,
                                  systolic_bp=systolic, diastolic_bp=diastolic, temperature_c=temp, pulse_rate=pulse,
                                  respiratory_rate=rr, spo2=spo2)
                    return store.revise_assessment(int(v['id']), values, clean_diagnoses(dx, custom, required=False),
                                                   author, reason, int(v['version']))
                persist(save, 'Assessment updated. The original entry has been preserved.')


def overview():
    heading('Clinic overview', 'A quick view of attendance and patients who are still in care.')
    controls, action = st.columns([3, 1])
    with controls:
        period = st.radio('Activity period', ['Today', 'This week', 'Last 30 days', 'Custom'], index=2, horizontal=True)
    with action:
        st.button('＋ Record a visit', type='primary', width='stretch', on_click=goto, args=('Record a visit',))
    today = now().date(); start, end = today, today
    if period == 'This week': start = week_bounds(today, week_start_setting())[0]
    elif period == 'Last 30 days': start = today - timedelta(days=29)
    elif period == 'Custom':
        a, b = st.columns(2)
        start = a.date_input('From', today - timedelta(days=6)); end = b.date_input('To', today)
    if start > end:
        st.error('The start date must be on or before the end date.'); return
    selected = filter_visits(frame, start, end)
    summary = period_summary(frame, incidents, care_events, start, end)
    st.caption(f'Activity: {start:%d %b %Y} to {end:%d %b %Y} · Africa/Lagos')
    for col, label in zip(st.columns(4), ['Visits', 'Linked patients seen', 'Referrals', 'Workplace incidents']):
        col.metric(label, summary[label])
    if summary['Unlinked visits']: st.caption(f'{summary["Unlinked visits"]} unlinked visits are excluded from the patient count.')
    if not patients:
        st.info('Ready for your first patient. Register a file, then record the visit.')
        st.button('Register a patient', on_click=goto, args=('Patient files',))
    usage = usage_table(selected, patients, incidents, care_events, start, end)
    repeat = int((usage['Visits'] > 1).sum()) if not usage.empty else 0
    injury_cases = incident_period(incidents, start, end)
    injured = len({i['patient_id'] for i in injury_cases})
    counts = pd.Series([i['patient_id'] for i in injury_cases], dtype='object').value_counts()
    for col, label, value in zip(st.columns(4),
            ['Repeat visitors', 'People injured', 'People with repeat injuries', 'LTI cases'],
            [repeat, injured, int((counts > 1).sum()), summary['LTI cases']]):
        col.metric(label, value)
    st.caption('Repeat means two or more visits or distinct incidents within the selected dates. Injury counts use occurrence dates, not follow-up visits.')
    left, right = st.columns(2)
    with left:
        st.subheader('Most common diagnoses')
        dx = diagnosis_counts(selected).head(10)
        if dx.empty: st.caption('No diagnoses recorded in this period.')
        else:
            fig = px.bar(dx.sort_values('Visits'), x='Visits', y='Diagnosis', orientation='h', text='Visits')
            fig.update_layout(height=350, margin=dict(l=0,r=10,t=10,b=0), yaxis_title=None)
            st.plotly_chart(fig, width='stretch')
            st.caption('Each visit counts once per diagnosis; a visit can have multiple diagnoses.')
    with right:
        st.subheader('Visits and injury incidents over time')
        trend = daily_counts(selected, start, end)
        injury_days = pd.Series([local_date(i['occurred_at']) for i in injury_cases], dtype='object').value_counts()
        trend['Injury incidents'] = trend['Date'].map(injury_days).fillna(0).astype(int)
        if selected.empty and not injury_cases: st.caption('No activity in this period.')
        else:
            if (end-start).days > 60:
                trend['Date'] = pd.to_datetime(trend['Date'])
                trend = trend.set_index('Date').resample('W-MON', label='left', closed='left').sum().reset_index()
                st.caption('Weekly totals; boundary weeks may be partial.')
            st.plotly_chart(px.line(trend, x='Date', y=['Visits','Injury incidents'], markers=True), width='stretch')
    st.subheader('Workplace injury patterns')
    if injury_cases:
        injuries = pd.DataFrame(injury_cases)
        injuries['department'] = injuries.department.replace('', 'Not recorded').fillna('Not recorded')
        a, b = st.columns(2)
        by_dept = injuries.groupby('department').agg(Incidents=('id','nunique'), People=('patient_id','nunique'), LTI=('is_lti','sum')).reset_index().rename(columns={'department':'Department'})
        a.dataframe(by_dept.sort_values('Incidents', ascending=False), hide_index=True, width='stretch')
        types = injuries.groupby('injury_type').agg(Incidents=('id','nunique'), People=('patient_id','nunique')).reset_index().rename(columns={'injury_type':'Injury type'})
        b.dataframe(types.sort_values('Incidents', ascending=False), hide_index=True, width='stretch')
        st.caption('Counts show recorded burden, not departmental risk rates: staff headcounts and hours worked are not available.')
    else: st.caption('No distinct workplace incidents recorded in this period.')
    if summary['Legacy incident visits (not distinct cases)']:
        st.info(f"{summary['Legacy incident visits (not distinct cases)']} older injury-related visits lack incident links and are excluded from distinct injury counts.")
    st.subheader('Patient usage and frequency')
    st.caption('Patient reference displays the existing staff ID where supplied. First/latest visits and repeat counts refer to the selected period. Duration runs from visit start to the first recorded discharge/referral; open or undated outcomes are excluded.')
    if usage.empty: st.caption('No linked patients or injury records in this period.')
    else:
        query = st.text_input('Filter by patient reference, file number or name')
        shown = usage
        if query.strip():
            shown = usage[usage[['Patient reference','File number','Patient']].astype(str).apply(lambda c: c.str.contains(query.strip(), case=False, regex=False)).any(axis=1)]
        st.dataframe(shown, hide_index=True, width='stretch')
    st.divider()
    st.subheader('Active care now')
    live = [v for v in records if v['status'] in ACTIVE]
    used = sum(b['visit_id'] is not None for b in beds)
    st.caption(f'{len(live)} open encounter(s) · {used} of {len(beds)} configured beds occupied. This live view is independent of the activity dates above.')
    if live:
        priority = {'Emergency': 0, 'Urgent': 1, 'Not assessed': 2, 'Routine': 3}
        live.sort(key=lambda v: (priority.get(v['triage'], 4), v['timestamp']))
        urgent = sum(v['triage'] in ('Urgent', 'Emergency') for v in live)
        if urgent: st.warning(f'{urgent} open encounter(s) have a nurse-assigned Urgent or Emergency category.')
        visit_table(live)
        st.button('Manage care, beds and discharge →', on_click=goto, args=('Observation & active care',))
    else: st.info('No open encounters. Historical admissions are not treated as current bed occupancy.')
    st.divider()
    st.subheader('Recent visits')
    if selected.empty: st.caption('No visits in the selected period.')
    else: visit_table(selected.sort_values('timestamp', ascending=False).head(8).to_dict('records'))
    st.button('Weekly report →', on_click=goto, args=('Weekly reports',))


def patient_files():
    heading('Patient files', 'Search by name, employee ID or file number. Keep all visits together in one patient file.')
    reg_key = token('register_token')
    with st.expander('＋ Register a patient', expanded=not patients):
        with st.form(f'register_{reg_key}'):
            a, b = st.columns(2)
            name = a.text_input('Full name *', max_chars=100)
            reference = b.text_input('Patient reference (optional)', max_chars=80)
            a, b, c = st.columns(3)
            age = a.number_input('Age (years)', 0, 120, value=None, step=1)
            gender = b.selectbox('Gender', GENDERS, index=0)
            dept = c.text_input('Department', max_chars=120)
            a, b = st.columns(2)
            contact = a.text_input('Contact details', max_chars=180)
            emergency = b.text_input('Emergency contact', max_chars=180)
            st.caption('Employee IDs are unique. Patients without an employee ID receive a unique clinic file number.')
            if st.form_submit_button('Create patient file', type='primary'):
                def create():
                    pid = store.register_patient(name, gender, reference, age, dept, contact, emergency)
                    st.session_state['selected_patient_id'] = pid; st.session_state['file_patient'] = pid
                    return pid
                persist(create, lambda i: f'Patient file {file_number(i)} created.', ['register_token'])
    p = patient_picker('Find patient', 'file_patient')
    if not p: return
    history = [v for v in records if v['patient_id'] == p['id']]
    with st.container(border=True):
        a, b = st.columns([3, 1])
        a.subheader(p['name'])
        a.caption(f'{file_number(p["id"])} · {p["employee_id"] or "No employee ID"} · {p["department"] or "Department not recorded"}')
        a.write(f'**Gender:** {p["gender"]} · **Contact:** {p["contact"] or "Not recorded"}')
        if p['age'] is not None: a.caption(f'Reported age: {p["age"]} years · recorded {p["age_recorded_on"]}')
        b.metric('Visits', len(history))
        b.button('＋ New visit', type='primary', on_click=goto, args=('Record a visit', p['id']), width='stretch')
    timeline, trends, profile = st.tabs(['Visit history', 'Vital-sign trends', 'Profile details'])
    with timeline:
        if not history: st.info('No linked visits yet.')
        else:
            known = sorted({d for v in history for d in v['diagnoses']}, key=str.casefold)
            if known: st.caption('Recorded across past visits: ' + '; '.join(known))
            st.caption('Historical diagnoses are encounter records, not a verified current problem list.')
            by_visit = {v['id']: v for v in history}
            visit_id = st.selectbox('Open an encounter', list(by_visit), format_func=lambda i: visit_label(by_visit[i]), key=f'history_{p["id"]}')
            display_visit(by_visit[visit_id])
            with st.expander('Add a follow-up note or correction'):
                nt = token(f'note_token_{visit_id}')
                with st.form(f'note_{visit_id}_{nt}'):
                    author = st.text_input('Recorded by *', max_chars=100)
                    note = st.text_area('Follow-up note *', placeholder='Dated correction, treatment update or subsequent findings')
                    if st.form_submit_button('Append note'):
                        persist(lambda: store.add_note(int(visit_id), author, note), 'Follow-up note appended.', [f'note_token_{visit_id}'])
            if len(history) > 1:
                with st.expander(f'All {len(history)} visits, newest first'): visit_table(history, full=True)
    with trends:
        if not history: st.info('Record a visit to begin tracking vital signs.')
        else:
            hf = pd.DataFrame(history).sort_values('timestamp')
            measure = st.selectbox('Measurement', ['Blood pressure', 'Temperature', 'Pulse', 'Respiratory rate', 'SpO₂'])
            mapping = {'Blood pressure': ('systolic_bp', 'diastolic_bp'), 'Temperature': ('temperature_c',),
                       'Pulse': ('pulse_rate',), 'Respiratory rate': ('respiratory_rate',), 'SpO₂': ('spo2',)}
            cols = list(mapping[measure]); trend = hf[['timestamp', *cols]].dropna(subset=cols, how='all')
            if trend.empty: st.info('No measurements of this type have been recorded.')
            else:
                labels = {'systolic_bp': 'Systolic (mmHg)', 'diastolic_bp': 'Diastolic (mmHg)',
                          'temperature_c': 'Temperature (°C)', 'pulse_rate': 'Pulse (bpm)',
                          'respiratory_rate': 'Respiratory rate (/min)', 'spo2': 'SpO₂ (%)'}
                trend = trend.rename(columns=labels).set_index('timestamp')
                st.line_chart(trend)
                st.dataframe(trend, width='stretch')
                st.caption('Only recorded measurements are shown. Historical default values cannot be distinguished from measured values.')
    with profile:
        with st.form(f'profile_{p["id"]}'):
            a, b = st.columns(2)
            age = a.number_input('Current reported age', 0, 120, value=p['age'], step=1)
            dept = b.text_input('Department', p['department'], max_chars=120)
            contact = a.text_input('Contact details', p['contact'], max_chars=180)
            emergency = b.text_input('Emergency contact', p['emergency_contact'], max_chars=180)
            if st.form_submit_button('Update profile'):
                persist(lambda: store.update_profile(p['id'], age, dept, contact, emergency), 'Profile updated. Historical visit details preserved.')
    unlinked = [v for v in records if pd.isna(v['patient_id'])]
    if unlinked:
        with st.expander(f'Link an older visit ({len(unlinked)} unlinked)'):
            vm = {v['id']: v for v in unlinked}
            vid = st.selectbox('Existing visit', list(vm), format_func=lambda i: f'{vm[i]["patient_name"]} · {visit_label(vm[i])}')
            display_visit(vm[vid], compact=True)
            confirmed = st.checkbox(f'I verified that this visit belongs to {patient_label(p)}', key=f'link_{vid}_{p["id"]}')
            st.caption('Matching names alone are not enough to establish identity. Linking does not alter the original record.')
            if st.button('Link visit', disabled=not confirmed):
                persist(lambda: store.link_visit(int(vid), p['id']), 'Historical visit linked.')


def intake():
    heading('Record a visit', 'Select a patient, review their history and record the current encounter.')
    p = patient_picker('Patient file', 'intake_patient')
    if not p: return
    history = [v for v in records if v['patient_id'] == p['id']]
    active = [v for v in history if v['status'] in ACTIVE]
    if active:
        st.warning(f'This patient already has an open encounter: #{active[0]["id"]}. Continue that encounter before creating another attendance.')
        st.button('Continue active care', on_click=goto, args=('Observation & active care', p['id'])); return
    main, prior = st.columns([2, 1])
    with prior:
        with st.container(border=True):
            st.subheader('Patient context')
            st.write(f'**{p["name"]}**'); st.caption(patient_label(p))
            st.write(f'Department: {p["department"] or "Not recorded"}')
            st.caption(f'{len(history)} previous visit(s)')
            if history:
                for idx, v in enumerate(history[:3]):
                    with st.expander(visit_label(v), expanded=idx == 0): display_visit(v, compact=True)
                if len(history) > 3: st.caption('The full chronological record is available in Patient files.')
            else: st.info('First recorded visit.')
    with main:
        st.caption('Unmeasured vitals stay blank. Triage and diagnosis are recorded by clinic staff; the app does not make clinical decisions.')
        # Controls outside the form reveal only the fields relevant to this outcome.
        status = st.selectbox('Encounter status', STATUSES, key=f'intake_status_{p["id"]}')
        bed_id, referral_to, closing_note = None, '', ''
        if status in ('Observation', 'Short-day admission'):
            available = {b['id']: b['name'] for b in beds if b['visit_id'] is None}
            bed_id = st.selectbox('Assign a bed', [None, *available], format_func=lambda i: 'Not assigned' if i is None else available[i])
            if not beds: st.caption('Add the clinic’s actual bed names under Clinic setup.')
        if status == 'Referred': referral_to = st.text_input('Referral destination *', max_chars=180)
        if status in CLOSED: closing_note = st.text_area('Discharge / referral plan', placeholder='Destination, follow-up and handover details')
        key = f'visit_token_{p["id"]}'; request_key = token(key)
        with st.form(f'visit_{p["id"]}_{request_key}'):
            st.subheader('1 · Assessment')
            a, b, c = st.columns(3)
            visit_date = a.date_input('Visit date', now().date(), max_value=now().date())
            visit_time = b.time_input('Visit time', now().time().replace(second=0, microsecond=0))
            default_age = history[0]['age'] if history else p['age']
            age = c.number_input('Age at visit *', 0, 120, value=int(default_age) if default_age is not None else None, step=1)
            triage = st.selectbox('Triage category', TRIAGE)
            complaint = st.text_input('Chief complaint *', placeholder='Reason for this visit')
            st.subheader('2 · Vital signs')
            a, b, c = st.columns(3)
            sys = a.number_input('Systolic BP (mmHg)', 1, 350, value=None, step=1)
            dia = b.number_input('Diastolic BP (mmHg)', 1, 250, value=None, step=1)
            temp = c.number_input('Temperature (°C)', 20.0, 50.0, value=None, step=0.1)
            pulse = a.number_input('Pulse (bpm)', 0, 350, value=None, step=1)
            rr = b.number_input('Respiratory rate (/min)', 0, 100, value=None, step=1)
            spo2 = c.number_input('SpO₂ (%)', 0.0, 100.0, value=None, step=1.0)
            st.subheader('3 · Findings and care')
            a, b = st.columns(2)
            selected = a.multiselect('Diagnoses', DIAGNOSES)
            custom = b.text_area('Other diagnoses', placeholder='One diagnosis per line')
            st.caption('Diagnosis can remain blank while an encounter is being assessed.')
            observations = st.text_area('Clinical notes', placeholder='Findings, relevant history and assessment')
            treatment = st.text_area('Treatment provided', placeholder='Medication and dose, wound care, fluid therapy, advice')
            patient_incidents = {i['id']: i for i in incidents if i['patient_id'] == p['id']}
            incident_id = st.selectbox('Link a workplace incident', [None, *patient_incidents],
                                      format_func=lambda i: 'Not linked' if i is None else f'INC-{i:05d} · {patient_incidents[i]["injury_type"]}')
            st.caption('Record a new injury under Workplace incidents. Additional visits can link to the same injury.')
            author = st.text_input('Recorded by *', max_chars=100)
            if st.form_submit_button('Save visit', type='primary', width='stretch'):
                def save():
                    dx = clean_diagnoses(selected, custom, required=False)
                    data = dict(timestamp=datetime.combine(visit_date, visit_time, tzinfo=LOCAL_TZ), age=age,
                                systolic_bp=sys, diastolic_bp=dia, temperature_c=temp, pulse_rate=pulse)
                    details = dict(status=status, triage=triage, chief_complaint=complaint, respiratory_rate=rr,
                                   spo2=spo2, observations=observations, treatment=treatment, recorded_by=author)
                    return store.save_visit(p['id'], data, dx, details, request_key, bed_id, referral_to, closing_note, incident_id)
                persist(save, lambda i: f'Visit #{i} saved to {file_number(p["id"])}.', [key])


def active_care():
    heading('Observation & active care', 'Manage current encounters, assign beds and record formal discharge or referral.')
    live = [v for v in records if v['status'] in ACTIVE]
    c1, c2, c3 = st.columns(3)
    c1.metric('In consultation', sum(v['status'] == 'In consultation' for v in live))
    c2.metric('Observation / short-day', sum(v['status'] in ('Observation', 'Short-day admission') for v in live))
    c3.metric('Beds occupied', f'{sum(b["visit_id"] is not None for b in beds)} / {len(beds)}')
    if beds:
        st.caption('Configured beds')
        names = {v['id']: v['patient_name'] for v in live}
        st.dataframe(pd.DataFrame([{'Bed': b['name'], 'Status': 'Occupied' if b['visit_id'] else 'Available',
                                   'Patient': names.get(b['visit_id'], '—')} for b in beds]), hide_index=True, width='stretch')
    if not live:
        st.info('No active encounters. Patients in historical admission records need review; they are not assumed to be in a bed now.'); return
    visit_table(live, full=True)
    vm = {v['id']: v for v in live}
    ids = list(vm); pid = st.session_state.get('selected_patient_id')
    default = next((i for i, vid in enumerate(ids) if vm[vid]['patient_id'] == pid), 0)
    vid = st.selectbox('Manage encounter', ids, index=default, format_func=lambda i: f'{vm[i]["patient_name"]} · Visit #{i} · {vm[i]["status"]}')
    v = vm[vid]
    with st.expander('Review assessment and care history'): display_visit(v)
    assessment_form(v)
    status = st.selectbox('Update status', STATUSES, index=STATUSES.index(v['status']), key=f'care_status_{vid}')
    bed_id = None
    if status in ('Observation', 'Short-day admission'):
        available = {b['id']: b['name'] for b in beds if b['visit_id'] in (None, vid)}
        current = next((b['id'] for b in beds if b['visit_id'] == vid), None)
        options = [None, *available]
        bed_id = st.selectbox('Bed assignment', options, index=options.index(current), format_func=lambda i: 'Not assigned' if i is None else available[i])
    with st.form(f'care_{vid}_{v["version"]}'):
        referral_to = st.text_input('Referral destination *' if status == 'Referred' else 'Referral destination (only used for referral)', max_chars=180)
        note = st.text_area('Care update / discharge or referral note *', placeholder='Record the care provided and follow-up plan')
        author = st.text_input('Recorded by *', max_chars=100)
        if status in CLOSED: st.caption('Saving closes this encounter and releases its bed. The full care history remains in the patient file.')
        label = 'Confirm discharge' if status == 'Discharged' else 'Confirm referral' if status == 'Referred' else 'Save care update'
        if st.form_submit_button(label, type='primary'):
            persist(lambda: store.transition(vid, status, author, note, int(v['version']), bed_id, referral_to), 'Care status updated.')
    with st.expander('Append a clinical note without changing status'):
        with st.form(f'active_note_{vid}_{token(f"active_note_token_{vid}")}'):
            author = st.text_input('Recorded by *', max_chars=100)
            note = st.text_area('Clinical note *')
            if st.form_submit_button('Append note'):
                persist(lambda: store.add_note(vid, author, note), 'Clinical note appended.', [f'active_note_token_{vid}'])


def workplace_incidents():
    heading('Workplace incidents', 'One record per injury. Link repeat clinic visits to the existing incident.')
    log_tab, new_tab = st.tabs(['Incident register', '＋ Record an incident'])
    with log_tab:
        query = st.text_input('Search incidents', placeholder='Name, department, injury type or incident number')
        chosen = [i for i in incidents if query.casefold() in f'INC-{i["id"]:05d} {i["patient_name"]} {i["department"]} {i["injury_type"]}'.casefold()]
        a, b, c = st.columns(3)
        a.metric('Recorded cases', len(chosen)); b.metric('LTI cases', sum(i['is_lti'] for i in chosen)); c.metric('Linked clinic visits', sum(len(i['visits']) for i in chosen))
        st.caption('Register totals follow the search. Weekly reports use incident occurrence dates.')
        if chosen:
            st.dataframe(pd.DataFrame([{'Incident': f'INC-{i["id"]:05d}', 'Patient': i['patient_name'], 'Occurred': stamp(i['occurred_at']),
                                      'Injury type': i['injury_type'], 'Department': i['department'], 'LTI': 'Yes' if i['is_lti'] else 'No',
                                      'Clinic visits': len(i['visits'])} for i in chosen]), hide_index=True, width='stretch')
            im = {i['id']: i for i in chosen}
            iid = st.selectbox('Review incident', list(im), format_func=lambda i: f'INC-{i:05d} · {im[i]["patient_name"]} · {im[i]["injury_type"]}')
            item = im[iid]; st.text(item['description'] or 'No description recorded.')
            st.caption(f'Recorded by {item["author"]} · Linked visits: ' + (', '.join(map(str, item['visits'])) or 'None'))
            for u in item['updates']:
                st.caption(f'{stamp(u["timestamp"])} · {u["author"]} · LTI: {"Yes" if u["is_lti"] else "No"}'); st.text(u['note'])
            with st.expander('Add a safety update / change LTI classification'):
                with st.form(f'incident_update_{iid}_{token(f"incident_update_token_{iid}")}'):
                    lti = st.checkbox('Loss time injury (LTI)', value=item['is_lti'])
                    note = st.text_area('Reason / safety follow-up *')
                    author = st.text_input('Recorded by *', max_chars=100)
                    if st.form_submit_button('Save incident update'):
                        persist(lambda: store.update_incident(iid, lti, author, note), 'Incident update recorded.', [f'incident_update_token_{iid}'])
        else: st.info('No incident records match. Use Record an incident to add a case.')
        legacy = [v for v in records if v['incident'] and pd.isna(v['incident_id'])]
        if legacy:
            with st.expander(f'Older incident-related visits to reconcile ({len(legacy)})'):
                st.caption('These are visit classifications, not confirmed distinct injury cases. Record and link a case after reviewing identity and occurrence details.')
                visit_table(legacy, full=True)
    with new_tab:
        p = patient_picker('Patient involved', 'incident_patient')
        if p:
            available = {v['id']: v for v in records if v['patient_id'] == p['id'] and pd.isna(v['incident_id'])}
            key = f'incident_token_{p["id"]}'; tk = token(key)
            with st.form(f'incident_{p["id"]}_{tk}'):
                a, b = st.columns(2)
                day = a.date_input('Incident date', now().date(), max_value=now().date())
                time = b.time_input('Incident time', now().time().replace(second=0, microsecond=0))
                injury = a.text_input('Injury type *', placeholder='e.g. cut, burn, strain', max_chars=120)
                dept = b.text_input('Incident department *', value=p['department'], max_chars=120)
                lti = st.checkbox('Loss time injury (LTI)')
                st.caption('LTI is recorded separately from injury type or severity, using the company’s safety classification.')
                description = st.text_area('Incident description')
                vid = st.selectbox('Link an existing clinic visit (optional)', [None, *available],
                                   format_func=lambda i: 'No visit linked yet' if i is None else visit_label(available[i]))
                author = st.text_input('Recorded by *', max_chars=100)
                if st.form_submit_button('Save incident', type='primary'):
                    persist(lambda: store.record_incident(p['id'], datetime.combine(day, time, tzinfo=LOCAL_TZ),
                                injury, dept, lti, description, author, tk, vid), lambda i: f'Incident INC-{i:05d} recorded.', [key])


def week_start_setting():
    return 6 if setting('REPORT_WEEK_START', 'Monday').casefold() == 'sunday' else 0


def chart(fig):
    fig.update_layout(template='plotly_white', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                      margin=dict(l=10, r=10, t=15, b=10), font=dict(size=13), showlegend=False, height=280)
    st.plotly_chart(fig, width='stretch', config={'displayModeBar': False})


def reports():
    heading('Weekly reports', 'Clinic totals are calculated from saved records. Export a report without copying figures by hand.')
    a, b = st.columns([2, 1])
    day = a.date_input('Choose a date in the reporting week', value=now().date())
    starts = b.selectbox('Week starts on', ['Monday', 'Sunday'], index=int(week_start_setting() == 6))
    start, end = week_bounds(day, 0 if starts == 'Monday' else 6)
    st.subheader(f'{start:%d %b} – {end:%d %b %Y}')
    if end >= now().date(): st.caption('In-progress week: figures may change as visits and care updates are entered.')
    summary = period_summary(frame, incidents, care_events, start, end)
    selected = filter_visits(frame, start, end)
    st.download_button('↓ Download weekly summary (CSV)', report_csv(frame, incidents, care_events, start, end),
                       file_name=f'clinic-weekly-{start}.csv', mime='text/csv', type='primary')
    st.caption('The summary contains aggregate figures only. Patient names, employee IDs, contacts and clinical notes are excluded.')
    for c, label in zip(st.columns(4), ['Visits', 'Linked patients seen', 'Workplace incidents', 'LTI cases']): c.metric(label, summary[label])
    summary_tab, detail_tab, quality_tab, register_tab = st.tabs(['Activity & outcomes', 'Departments & diagnoses', 'Documentation', 'Visit register'])
    with summary_tab:
        left, right = st.columns([2, 1])
        with left:
            st.subheader('Attendance')
            chart(px.bar(daily_counts(selected, start, end), x='Date', y='Visits', color_discrete_sequence=['#147d72']))
        with right:
            st.subheader('Care outcomes')
            labels = ['Urgent / emergency visits', 'Observation entries', 'Admissions', 'Discharges', 'Referrals']
            st.dataframe(pd.DataFrame([{'Measure': k, 'Count': summary[k]} for k in labels]), hide_index=True, width='stretch')
            st.caption('Care outcomes use the date of the care event. A visit from an earlier week can be discharged or referred this week.')
    with detail_tab:
        left, right = st.columns(2)
        with left:
            st.subheader('Diagnoses')
            counts = diagnosis_counts(selected)
            if counts.empty: st.info('No diagnoses in this week.')
            else:
                top = counts.head(8).sort_values('Visits')
                chart(px.bar(top, x='Visits', y='Diagnosis', orientation='h', color_discrete_sequence=['#147d72']))
                st.dataframe(counts, hide_index=True, width='stretch')
            st.caption('A visit with several diagnoses contributes once to each diagnosis.')
        with right:
            st.subheader('Attendance by department')
            dep = selected.department.replace('', 'Not recorded').fillna('Not recorded').value_counts().rename_axis('Department').reset_index(name='Visits')
            st.dataframe(dep, hide_index=True, width='stretch')
            st.caption('Department is preserved as recorded at the visit.')
            st.subheader('Incident cases by department')
            injury = incident_period(incidents, start, end)
            if injury:
                st.dataframe(pd.DataFrame(injury).groupby('department').agg(Cases=('id', 'size'), LTIs=('is_lti', 'sum')),
                             width='stretch')
            else: st.caption('No incident cases occurred in this week.')
    with quality_tab:
        st.dataframe(documentation(selected), hide_index=True, width='stretch')
        st.caption('Coverage measures documentation, not clinical risk. Old default readings may not represent measured vitals.')
        st.write(f'Unlinked visits: **{summary["Unlinked visits"]}**')
        undated = int(frame.timestamp.isna().sum())
        if undated: st.warning(f'{undated} undated records are excluded from all date-based reports.')
        if summary['Legacy incident visits (not distinct cases)']:
            st.warning(f'{summary["Legacy incident visits (not distinct cases)"]} legacy incident-related visits are listed separately from distinct incident cases, including {summary["Legacy LTI-classified visits"]} marked Major (LTI).')
        st.caption('LTI case counts reflect the latest classification. Reports can change after a later safety update.')
    with register_tab:
        if selected.empty: st.info('No visits in this week.')
        else: visit_table(selected.to_dict('records'), full=True)


def setup():
    heading('Clinic setup', 'Use the actual bed names in your clinic. No bed capacity is assumed.')
    if beds: st.dataframe(pd.DataFrame([{'Bed': b['name'], 'Status': 'Occupied' if b['visit_id'] else 'Available'} for b in beds]), hide_index=True, width='stretch')
    with st.form(f'add_bed_{token("bed_token")}'):
        bed_name = st.text_input('New bed name', placeholder='e.g. Observation 1', max_chars=60)
        if st.form_submit_button('Add bed'): persist(lambda: store.add_bed(bed_name), 'Bed added.', ['bed_token'])
    st.subheader('Connection and reporting')
    st.write('Database: **PostgreSQL / Neon**' if store.engine.dialect.name == 'postgresql' else 'Database: **Local SQLite**')
    st.caption('Dates and times: Africa/Lagos. The weekly report screen supports Monday or Sunday week starts.')
    st.info('Staff names on entries are attribution only; they do not authenticate the user. Keep the app behind your company’s access controls. See README for Neon development branches and deployment steps.')


try:
    store = get_store()
    patients = store.patients(); patient_by_id = {p['id']: p for p in patients}
    frame = visit_frame(store.visits()); records = frame.to_dict('records')
    beds = store.beds(); incidents = store.incidents(); care_events = store.events()
except (SQLAlchemyError, ValueError):
    st.error('The clinic database is unavailable or its configuration is invalid. Check the configured connection without sharing credentials in chat.'); st.stop()

with st.sidebar:
    st.title(setting('CLINIC_NAME', 'Company Clinic'))
    st.caption('PATIENT CARE & CLINIC RECORDS')
    page = st.radio('Workspace', PAGES, key='workspace_page', label_visibility='collapsed')
    st.divider()
    st.caption(f'{now():%A, %d %B %Y} · Lagos')
    st.caption('PostgreSQL connected' if store.engine.dialect.name == 'postgresql' else 'Local database')
    if st.button('Refresh records', width='stretch'): st.rerun()
if 'notice' in st.session_state: st.success(st.session_state.pop('notice'))
try:
    {'Overview': overview, 'Patient files': patient_files, 'Record a visit': intake,
     'Observation & active care': active_care, 'Workplace incidents': workplace_incidents,
     'Weekly reports': reports, 'Clinic setup': setup}[page]()
except SQLAlchemyError:
    st.error('Records could not be loaded. Refresh after checking the database connection.')
