import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from analytics import ADMISSIONS, daily_counts, diagnosis_counts, filter_visits, outcomes, visit_frame
from clinic_data import ClinicStore, clean_diagnoses, file_number, make_engine

st.set_page_config(page_title="Company Clinic", page_icon="🏥", layout="wide")
LOCAL_TZ = ZoneInfo("Africa/Lagos")
DIAGNOSES = ["Malaria", "Hypertension (Elevated BP)", "Peptic Ulcer Disease (PUD)",
             "Typhoid Fever", "Upper Respiratory Tract Infection (URTI)",
             "Musculoskeletal Pain / Trauma", "Skin Infection", "Other Operational/Routine Encounter"]
GENDERS = ["Male", "Female", "Other", "Not recorded"]


@st.cache_resource
def get_store():
    url = os.environ.get("DATABASE_URL")
    if not url:
        try:
            url = st.secrets.get("DATABASE_URL")
        except FileNotFoundError:
            url = None
    return ClinicStore(make_engine(url or "sqlite:///clinic_operations.db"))


def refresh(message):
    st.session_state["notice"] = message
    st.rerun()


def patient_label(patient):
    reference = f" · {patient.employee_id}" if patient.employee_id else ""
    return f"{file_number(patient.id)} · {patient.name}{reference}"


def visit_label(visit):
    stamp = visit["timestamp"]
    date = stamp.strftime("%d %b %Y, %H:%M") if pd.notna(stamp) else "Date not recorded"
    return f"Visit #{visit['id']} · {date} · {', '.join(visit['diagnoses'])}"


def display_visit(visit):
    st.write("**Diagnoses:** " + "; ".join(visit["diagnoses"]))
    a, b, c, d = st.columns(4)
    bp = f"{visit['systolic_bp']:g}/{visit['diastolic_bp']:g}" if pd.notna(visit['systolic_bp']) and pd.notna(visit['diastolic_bp']) else "Not recorded"
    a.metric("Blood pressure (mmHg)", bp)
    b.metric("Temperature (°C)", f"{visit['temperature_c']:g}" if pd.notna(visit['temperature_c']) else "Not recorded")
    c.metric("Pulse (bpm)", f"{visit['pulse_rate']:g}" if pd.notna(visit['pulse_rate']) else "Not recorded")
    d.metric("Age at visit", visit["age"])
    st.write(f"**Admission:** {'No admission' if visit['admission'] == 'No Entry' else visit['admission']} · **Referral:** {'Yes' if visit['referral'] else 'No'}")
    if visit["incident"]:
        st.write(f"**Workplace incident:** {visit['incident_type'] or 'Classification not recorded'}")
    st.text(visit["notes"] or "No clinical notes recorded.")
    for note in store.notes(int(visit["id"])):
        stamp = note.timestamp.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ)
        st.caption(f"Follow-up · {stamp:%d %b %Y, %H:%M} · {note.author}")
        st.text(note.text)


def intake(patients):
    st.header("Record a visit")
    st.caption("Select the patient file first. Leave unmeasured vital signs blank.")
    if not patients:
        st.info("Create a patient file in Patient files before recording a visit.")
        return
    by_id = {p.id: p for p in patients}
    patient_id = st.selectbox("Patient file", list(by_id), format_func=lambda i: patient_label(by_id[i]), key="intake_patient")
    history = [v for v in records if v["patient_id"] == patient_id]
    if history:
        latest = history[0]
        st.info(f"{len(history)} previous visit(s). Latest: {visit_label(latest)}")
        with st.expander("Review previous visits"):
            for visit in history[:5]:
                st.write(visit_label(visit))
            st.caption("Full history and follow-up notes are in Patient files.")
    else:
        st.caption("No previous visits linked to this file.")
    form_key = f"visit_form_{patient_id}_{st.session_state.get('visit_version', 0)}"
    with st.form(form_key):
        left, right = st.columns(2)
        now = datetime.now(LOCAL_TZ)
        with left:
            visit_date = st.date_input("Visit date", value=now.date(), max_value=now.date())
            visit_time = st.time_input("Visit time (Lagos)", value=now.time().replace(second=0, microsecond=0))
            age = st.number_input("Age at this visit (years)", min_value=0, max_value=120, value=None, step=1)
            diagnoses = st.multiselect("Diagnoses / presentations", DIAGNOSES)
            custom = st.text_area("Other diagnoses", placeholder="Enter one diagnosis per line", help="These are saved alongside the selected diagnoses and included in reports.")
        with right:
            st.subheader("Vital signs")
            s, d = st.columns(2)
            sys = s.number_input("Systolic BP (mmHg)", min_value=1, max_value=350, value=None, step=1)
            dia = d.number_input("Diastolic BP (mmHg)", min_value=1, max_value=250, value=None, step=1)
            temp = st.number_input("Temperature (°C)", min_value=20.0, max_value=50.0, value=None, step=0.1)
            pulse = st.number_input("Pulse (bpm)", min_value=1, max_value=350, value=None, step=1)
            admission = st.selectbox("Admission", ["No admission", "Short-Day Admission", "Standard Admission"])
            referral = st.checkbox("Referred to another facility")
            incident = st.selectbox("Workplace incident", ["Not incident-related", "Minor Injury Case", "Major (LTI)"])
        notes = st.text_area("Clinical notes / treatment", placeholder="Complaints, findings, treatment and follow-up plan")
        if st.form_submit_button("Save visit", type="primary"):
            try:
                diagnosis_list = clean_diagnoses(diagnoses, custom)
                stamp = datetime.combine(visit_date, visit_time, tzinfo=LOCAL_TZ)
                if stamp > datetime.now(LOCAL_TZ):
                    raise ValueError("Visit date and time cannot be in the future.")
                visit_id = store.save_visit(patient_id, {
                    "timestamp": stamp.astimezone(timezone.utc).replace(tzinfo=None), "age": age,
                    "systolic_bp": sys, "diastolic_bp": dia, "temperature_c": temp, "pulse_rate": pulse,
                    "is_admission": "No Entry" if admission == "No admission" else admission,
                    "is_referral": int(referral), "is_incident": int(incident != "Not incident-related"),
                    "incident_type": None if incident == "Not incident-related" else incident,
                    "clinical_notes": notes.strip(),
                }, diagnosis_list)
            except ValueError as exc:
                st.error(str(exc))
            except SQLAlchemyError:
                st.error("The visit could not be saved. Your entries are still here; check the database connection and retry.")
            else:
                st.session_state["visit_version"] = st.session_state.get("visit_version", 0) + 1
                refresh(f"Visit #{visit_id} saved to {file_number(patient_id)}.")


def patient_files(patients):
    st.header("Patient files")
    st.caption("Find a file by name, file number or employee reference. Confirm identity before adding information.")
    with st.expander("Create a patient file", expanded=not patients):
        with st.form(f"register_{st.session_state.get('register_version', 0)}"):
            name = st.text_input("Full name", max_chars=100)
            gender = st.selectbox("Gender", GENDERS, index=3)
            reference = st.text_input("Employee / patient reference (optional)", max_chars=80)
            st.caption("Check existing files before registering. People with the same name keep separate file numbers.")
            if st.form_submit_button("Create file", type="primary"):
                try:
                    patient_id = store.register_patient(name, gender, reference)
                except ValueError as exc:
                    st.error(str(exc))
                except IntegrityError:
                    st.error("That employee / patient reference already has a file. Find and use the existing file.")
                except SQLAlchemyError:
                    st.error("The patient file could not be saved. Please retry.")
                else:
                    st.session_state["register_version"] = st.session_state.get("register_version", 0) + 1
                    st.session_state["file_patient"] = patient_id
                    refresh(f"Patient file {file_number(patient_id)} created.")
    if not patients:
        return
    by_id = {p.id: p for p in patients}
    patient_id = st.selectbox("Find patient", list(by_id), format_func=lambda i: patient_label(by_id[i]), key="file_patient")
    patient = by_id[patient_id]
    st.subheader(patient_label(patient))
    st.caption(f"Gender: {patient.gender}")
    history = [v for v in records if v["patient_id"] == patient_id]
    st.metric("Recorded visits", len(history))
    if history:
        known = sorted({d for v in history for d in v["diagnoses"]}, key=str.casefold)
        st.write("**Previously recorded diagnoses:** " + "; ".join(known))
        st.caption("Historical diagnoses are encounter records, not a current problem list.")
        st.dataframe(pd.DataFrame([{
            "Visit": v["id"],
            "Date (Lagos)": v["timestamp"].strftime("%Y-%m-%d %H:%M") if pd.notna(v["timestamp"]) else "Not recorded",
            "Diagnoses": "; ".join(v["diagnoses"]),
            "Admission": "No admission" if v["admission"] == "No Entry" else v["admission"],
            "Referral": "Yes" if v["referral"] else "No",
        } for v in history]), hide_index=True, use_container_width=True)
        visit_map = {v["id"]: v for v in history}
        visit_id = st.selectbox("Visit details", list(visit_map), format_func=lambda i: visit_label(visit_map[i]), key=f"details_{patient_id}")
        display_visit(visit_map[visit_id])
        st.subheader("Add follow-up information")
        st.caption(f"Adding to visit #{visit_id} above. New notes are dated and appended; the original visit remains available.")
        with st.form(f"follow_up_{patient_id}_{visit_id}_{st.session_state.get('note_version', 0)}"):
            author = st.text_input("Recorded by", max_chars=100)
            note = st.text_area("Follow-up note", placeholder="Subsequent findings, treatment changes, or a correction to the original record")
            if st.form_submit_button("Add follow-up note"):
                try:
                    store.add_note(int(visit_id), author, note)
                except ValueError as exc:
                    st.error(str(exc))
                except SQLAlchemyError:
                    st.error("The note could not be saved. Your text is still here; please retry.")
                else:
                    st.session_state["note_version"] = st.session_state.get("note_version", 0) + 1
                    refresh("Follow-up note added.")
    else:
        st.info("No visits yet. Use Record a visit to add the first encounter.")
    unlinked = [v for v in records if pd.isna(v["patient_id"])]
    if unlinked:
        with st.expander(f"Link an existing visit ({len(unlinked)} unlinked)"):
            st.caption("Older records remain unlinked until staff confirm identity. Matching names alone do not establish identity.")
            visits_by_id = {v["id"]: v for v in unlinked}
            visit_id = st.selectbox("Existing visit", list(visits_by_id), format_func=lambda i: f"{visits_by_id[i]['patient_name']} · {visit_label(visits_by_id[i])}")
            display_visit(visits_by_id[visit_id])
            confirmed = st.checkbox(f"I have confirmed this visit belongs to {patient_label(patient)}", key=f"confirm_{visit_id}_{patient_id}")
            if st.button("Link visit to this file", disabled=not confirmed):
                try:
                    store.link_visit(int(visit_id), patient_id)
                except ValueError as exc:
                    st.error(str(exc))
                except SQLAlchemyError:
                    st.error("The visit could not be linked. Refresh and retry.")
                else:
                    refresh("Existing visit linked. Its original details have been preserved.")


def chart(figure):
    figure.update_layout(template="plotly_white", margin=dict(l=10, r=10, t=20, b=10),
                         font=dict(size=13), showlegend=False, height=330)
    if figure.data and figure.data[0].orientation == "h":
        figure.update_xaxes(rangemode="tozero", dtick=1 if max(figure.data[0].x, default=0) < 10 else None)
    elif figure.data:
        figure.update_yaxes(rangemode="tozero", dtick=1 if max(figure.data[0].y, default=0) < 10 else None)
    st.plotly_chart(figure, use_container_width=True)


def dashboard(frame):
    st.header("Clinic overview")
    st.caption("Attendance, care outcomes and workplace incidents. All figures use the selected visit dates (Lagos time).")
    if frame.empty:
        st.info("No visits recorded yet. Create a patient file, then record a visit to start reporting.")
        return
    today = datetime.now(LOCAL_TZ).date()
    undated = int(frame.timestamp.isna().sum())
    if undated:
        st.warning(f"{undated} visit(s) have no recorded date and cannot be included in date-based reports. They remain available in patient files.")
    c1, c2 = st.columns(2)
    start = c1.date_input("From", value=today - timedelta(days=29))
    end = c2.date_input("To", value=today)
    if start > end:
        st.error("The start date must be on or before the end date.")
        return
    filtered = filter_visits(frame, start, end)
    if filtered.empty:
        st.info("No visits in this date range. Choose a wider range to see older records.")
        return
    total = len(filtered)
    cards = st.columns(5)
    for col, label, value in zip(cards, ["Visits", "Linked patients seen", "Admissions", "Referrals", "Workplace incidents"],
                                  [total, filtered.patient_id.nunique(), filtered.admission.isin(ADMISSIONS).sum(), filtered.referral.sum(), filtered.incident.sum()]):
        col.metric(label, int(value))
    missing = int(filtered.patient_id.isna().sum())
    st.caption(f"{missing} unlinked visit(s) excluded from the patient count. Admissions and referrals count encounters, not current bed occupancy.")
    left, right = st.columns(2)
    with left:
        st.subheader("Clinic attendance over time")
        daily = daily_counts(filtered, start, end)
        if len(daily) > 90:
            daily["Date"] = pd.to_datetime(daily["Date"])
            daily = daily.set_index("Date").resample("W-MON", label="left", closed="left").sum().reset_index()
            st.caption("Weekly totals; first and last weeks may be partial.")
        else:
            st.caption("Daily visits, including days with zero attendance.")
        chart(px.bar(daily, x="Date", y="Visits", color_discrete_sequence=["#157f83"]))
    with right:
        st.subheader("Most frequent diagnoses")
        counts = diagnosis_counts(filtered)
        top = counts.head(10).sort_values("Visits")
        st.caption("Top 10 by visits. A visit with multiple diagnoses contributes to each diagnosis.")
        chart(px.bar(top, x="Visits", y="Diagnosis", orientation="h", text="Visits", color_discrete_sequence=["#2864b4"]))
        with st.expander("All diagnoses and visit percentages"):
            counts["% of visits"] = (counts.Visits / total * 100).round(1)
            st.dataframe(counts, hide_index=True, use_container_width=True)
    left, right = st.columns(2)
    with left:
        st.subheader("Admission outcomes")
        chart(px.bar(outcomes(filtered), x="Outcome", y="Visits", text="Visits", color_discrete_sequence=["#157f83"]))
        st.caption(f"Referred onward: {int(filtered.referral.sum())} of {total} visits ({filtered.referral.mean():.0%}). Referrals can also involve admission.")
    with right:
        st.subheader("Workplace incident classifications")
        incidents = filtered[filtered.incident]
        if incidents.empty:
            st.info("No workplace incidents recorded in this period.")
        else:
            severity = incidents.incident_type.fillna("Not classified").value_counts().rename_axis("Classification").reset_index(name="Visits")
            chart(px.bar(severity, x="Classification", y="Visits", text="Visits", color_discrete_sequence=["#b87524"]))
        st.caption("Counts reflect incident-related visits. Repeat visits may relate to the same incident; LTI is the recorded classification.")
    with st.expander("Vital sign documentation"):
        st.caption("Documentation coverage for this period. This measures recording completeness, not clinical risk.")
        coverage = pd.DataFrame({"Measurement": ["Blood pressure (both readings)", "Temperature", "Pulse"],
                                 "Visits recorded": [int((filtered.systolic_bp.notna() & filtered.diastolic_bp.notna()).sum()),
                                                    int(filtered.temperature_c.notna().sum()), int(filtered.pulse_rate.notna().sum())]})
        coverage["% of visits"] = (coverage["Visits recorded"] / total * 100).round(1)
        st.dataframe(coverage, hide_index=True, use_container_width=True)
        st.caption("Older entries may contain default vital signs from the previous form.")
    with st.expander("Visit register for this period"):
        view = filtered.copy()
        view["Patient file"] = view.patient_id.map(lambda i: file_number(int(i)) if pd.notna(i) else "Unlinked")
        view["Diagnoses"] = view.diagnoses.map("; ".join)
        view["Date (Lagos)"] = view.timestamp.dt.strftime("%Y-%m-%d %H:%M")
        view = view.rename(columns={"id": "Visit", "patient_name": "Patient", "admission": "Admission", "referral": "Referral", "incident": "Incident"})
        st.dataframe(view[["Visit", "Patient file", "Date (Lagos)", "Patient", "Diagnoses", "Admission", "Referral", "Incident"]], hide_index=True, use_container_width=True)


st.title("🏥 Company Clinic")
st.caption("Patient care • Visit history • Clinic reporting")
if "notice" in st.session_state:
    st.success(st.session_state.pop("notice"))
try:
    store = get_store()
    patients = store.patients()
    frame = visit_frame(store.visits())
    records = frame.to_dict("records") if not frame.empty else []
except SQLAlchemyError:
    st.error("The clinic database is unavailable. Check the database connection and reload.")
    st.stop()

page = st.sidebar.radio("Workspace", ["Clinic overview", "Record a visit", "Patient files"])
st.sidebar.caption("All displayed dates and times use Africa/Lagos.")
if st.sidebar.button("Refresh records"):
    st.rerun()
try:
    if page == "Clinic overview":
        dashboard(frame)
    elif page == "Record a visit":
        intake(patients)
    else:
        patient_files(patients)
except SQLAlchemyError:
    st.error("Records could not be loaded. Check the database connection and refresh.")
