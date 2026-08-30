import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker
import random

# ==========================================
# 1. CLOUD DATABASE CONFIGURATION (SECURE)
# ==========================================
try:
    DATABASE_URL = st.secrets["DATABASE_URL"]
except (KeyError, AttributeError):
    DATABASE_URL = "sqlite:///clinic_operations.db"

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"sslmode": "require"} if "postgresql" in DATABASE_URL else {}
)
Base = declarative_base()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class PatientVisit(Base):
    __tablename__ = "patient_visits"
    
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    patient_name = Column(String(100), nullable=False)
    age = Column(Integer, nullable=False)
    gender = Column(String(20), nullable=False)
    employee_designation = Column(String(100), nullable=True)
    
    systolic_bp = Column(Integer, nullable=True)
    diastolic_bp = Column(Integer, nullable=True)
    temperature_c = Column(Float, nullable=True)
    pulse_rate = Column(Integer, nullable=True)
    
    primary_diagnosis = Column(String(100), nullable=False)
    is_admission = Column(String(50), default="No Entry")
    is_referral = Column(Integer, default=0)
    
    is_incident = Column(Integer, default=0)
    incident_type = Column(String(50), nullable=True)
    clinical_notes = Column(Text, nullable=True)
    
    hours_in_clinic = Column(Float, nullable=True, default=0.0)
    days_admitted = Column(Integer, nullable=True, default=0)


# ==========================================
# 2. DATABASE MIGRATION HELPER
# ==========================================
def add_column_if_not_exists(table_name, column):
    inspector = inspect(engine)
    existing_columns = [col['name'] for col in inspector.get_columns(table_name)]
    if column.name not in existing_columns:
        with engine.connect() as conn:
            col_type = str(column.type)
            alter_stmt = text(f"ALTER TABLE {table_name} ADD COLUMN {column.name} {col_type}")
            conn.execute(alter_stmt)
            conn.commit()

Base.metadata.create_all(bind=engine)
add_column_if_not_exists("patient_visits", PatientVisit.employee_designation)


# ==========================================
# 3. HELPER FUNCTIONS (DATA LAYER)
# ==========================================
def save_visit(data):
    db = SessionLocal()
    try:
        db_visit = PatientVisit(**data)
        db.add(db_visit)
        db.commit()
    finally:
        db.close()

@st.cache_data(ttl=60)
def load_data_dataframe(start_date=None, end_date=None):
    db = SessionLocal()
    try:
        query = db.query(PatientVisit)
        if start_date:
            query = query.filter(PatientVisit.timestamp >= start_date)
        if end_date:
            query = query.filter(PatientVisit.timestamp <= end_date)
        results = query.all()
    finally:
        db.close()
    
    if not results:
        return pd.DataFrame()
        
    data = []
    for item in results:
        data.append({
            "ID": item.id,
            "Timestamp": item.timestamp,
            "Date": item.timestamp.strftime("%Y-%m-%d %H:%M") if item.timestamp else "N/A",
            "Patient Name": item.patient_name,
            "Age": item.age,
            "Gender": item.gender,
            "Designation": item.employee_designation,
            "Systolic": item.systolic_bp,
            "Diastolic": item.diastolic_bp,
            "Temp (°C)": item.temperature_c,
            "Diagnosis": item.primary_diagnosis,
            "Admission Status": item.is_admission,
            "Referral": "Yes" if item.is_referral == 1 else "No",
            "Incident Case": "Yes" if item.is_incident == 1 else "No",
            "Incident Type": item.incident_type if item.is_incident == 1 else "N/A",
            "Hours in Clinic": item.hours_in_clinic,
            "Days Admitted": item.days_admitted,
            "Notes": item.clinical_notes
        })
    df = pd.DataFrame(data)
    if not df.empty and "Timestamp" in df.columns:
        df["Timestamp"] = pd.to_datetime(df["Timestamp"])
    return df


# ==========================================
# 4. STREAMLIT INTERFACE (UI LAYER)
# ==========================================
st.set_page_config(page_title="Clinic Operations System", layout="wide", page_icon="🏥")
st.title("🏥 Site Clinic Intelligence System")
st.markdown("---")

# ------------------------------------------
# SIDEBAR FILTERS
# ------------------------------------------
st.sidebar.header("🔍 Filters")

# Date range
default_end = datetime.now()
default_start = default_end - timedelta(days=30)
start_date = st.sidebar.date_input("Start Date", default_start)
end_date = st.sidebar.date_input("End Date", default_end)

start_dt = datetime.combine(start_date, datetime.min.time()) if start_date else None
end_dt = datetime.combine(end_date, datetime.max.time()) if end_date else None

# Load main data
df = load_data_dataframe(start_dt, end_dt)

if df.empty:
    st.sidebar.warning("No records for the selected period.")
else:
    # Additional filters (populated from the dataframe)
    designation_options = ["All"] + sorted(df["Designation"].dropna().unique().tolist())
    diagnosis_options = ["All"] + sorted(df["Diagnosis"].unique().tolist())
    incident_options = ["All", "Yes", "No"]
    
    selected_designation = st.sidebar.selectbox("Designation", designation_options)
    selected_diagnosis = st.sidebar.selectbox("Diagnosis", diagnosis_options)
    selected_incident = st.sidebar.selectbox("Incident Case", incident_options)
    
    # Apply filters
    filtered_df = df.copy()
    if selected_designation != "All":
        filtered_df = filtered_df[filtered_df["Designation"] == selected_designation]
    if selected_diagnosis != "All":
        filtered_df = filtered_df[filtered_df["Diagnosis"] == selected_diagnosis]
    if selected_incident != "All":
        filtered_df = filtered_df[filtered_df["Incident Case"] == selected_incident]
    
    # Reset filters button
    if st.sidebar.button("Reset Filters"):
        st.rerun()
    
    st.sidebar.markdown("---")
    st.sidebar.caption(f"Showing {len(filtered_df)} records")

    # Use filtered_df for dashboard
    df_display = filtered_df

# ------------------------------------------
# TABS
# ------------------------------------------
tab_dashboard, tab_entry = st.tabs(["📊 Real-Time Analytics Dashboard", "📝 Nurse Intake Registry"])

# ==========================================
# TAB 1: DASHBOARD (OVERHAULED)
# ==========================================
with tab_dashboard:
    if df_display.empty:
        st.info("No records match the current filters. Adjust your filters or add new data.")
    else:
        df = df_display  # for brevity
        
        # ----------------------------
        # 1. COMPUTE KPIs & TRENDS
        # ----------------------------
        total_visits = len(df)
        admissions = len(df[df["Admission Status"].isin(["Standard Admission", "Short-Day Admission"])])
        referrals = len(df[df["Referral"] == "Yes"])
        incidents = len(df[df["Incident Case"] == "Yes"])
        lti_cases = len(df[df["Incident Type"] == "Major (LTI)"])
        avg_hours = df["Hours in Clinic"].mean() if not df["Hours in Clinic"].isna().all() else 0
        avg_days = df[df["Days Admitted"] > 0]["Days Admitted"].mean() if not df[df["Days Admitted"] > 0].empty else 0

        # Compare with previous period (e.g., same length, previous 30 days)
        if start_dt and end_dt:
            period_length = (end_dt - start_dt).days
            prev_start = start_dt - timedelta(days=period_length)
            prev_end = start_dt - timedelta(days=1)
            df_prev = load_data_dataframe(prev_start, prev_end)
            if not df_prev.empty:
                prev_total = len(df_prev)
                trend_total = (total_visits - prev_total) / prev_total * 100 if prev_total > 0 else 0
            else:
                trend_total = 0
        else:
            trend_total = 0

        # Display KPI cards with trend arrows
        col1, col2, col3, col4, col5, col6, col7 = st.columns(7)
        col1.metric("Total Visits", total_visits, delta=f"{trend_total:.1f}%")
        col2.metric("Admissions", admissions)
        col3.metric("Referrals", referrals)
        col4.metric("Incidents", incidents, delta=f"{incidents/total_visits*100:.1f}% of visits")
        col5.metric("LTI (Major)", lti_cases)
        col6.metric("Avg Hours/Visit", f"{avg_hours:.1f}h")
        col7.metric("Avg Days Admitted", f"{avg_days:.1f}d" if avg_days > 0 else "N/A")
        st.markdown("---")

        # ----------------------------
        # 2. ROW 1: TOP DIAGNOSES & VISITS BY DESIGNATION
        # ----------------------------
        chart_col1, chart_col2 = st.columns(2)
        with chart_col1:
            dx_counts = df["Diagnosis"].value_counts().reset_index()
            dx_counts.columns = ["Diagnosis", "Count"]
            # Add incident flag for colour
            dx_incident = df[df["Incident Case"] == "Yes"]["Diagnosis"].value_counts().reset_index()
            dx_incident.columns = ["Diagnosis", "Incident_Count"]
            dx_counts = dx_counts.merge(dx_incident, on="Diagnosis", how="left").fillna(0)
            dx_counts["Incident_Count"] = dx_counts["Incident_Count"].astype(int)
            
            fig_dx = px.bar(dx_counts, x="Count", y="Diagnosis", orientation='h',
                            title="Leading Causes of Clinic Attendance",
                            color="Incident_Count", color_continuous_scale="Reds",
                            hover_data={"Incident_Count": True})
            fig_dx.update_layout(yaxis={'categoryorder':'total ascending'}, showlegend=False)
            st.plotly_chart(fig_dx, use_container_width=True)

        with chart_col2:
            # Visits by Designation, split by incident
            des_counts = df.groupby(["Designation", "Incident Case"]).size().reset_index(name="Count")
            fig_des = px.bar(des_counts, x="Designation", y="Count", color="Incident Case",
                             title="Visits by Designation (Incident vs Non‑Incident)",
                             barmode="stack", color_discrete_map={"Yes": "#d62728", "No": "#2ca02c"})
            st.plotly_chart(fig_des, use_container_width=True)

        st.markdown("---")

        # ----------------------------
        # 3. ROW 2: TIME-SERIES WITH ROLLING AVERAGES
        # ----------------------------
        time_col1, time_col2 = st.columns(2)
        with time_col1:
            # Daily visit trend with 7-day rolling average
            daily = df.groupby(df["Timestamp"].dt.date).size().reset_index(name="Visits")
            daily.columns = ["Date", "Visits"]
            daily = daily.sort_values("Date")
            daily["7-day MA"] = daily["Visits"].rolling(window=7, min_periods=1).mean()
            fig_daily = px.line(daily, x="Date", y=["Visits", "7-day MA"],
                                title="Daily Visits & 7‑Day Rolling Average",
                                markers=True, color_discrete_map={"Visits": "#1f77b4", "7-day MA": "#ff7f0e"})
            st.plotly_chart(fig_daily, use_container_width=True)

        with time_col2:
            # Daily incident trend with rolling average
            incident_daily = df[df["Incident Case"] == "Yes"].groupby(df["Timestamp"].dt.date).size().reset_index(name="Incidents")
            incident_daily.columns = ["Date", "Incidents"]
            if not incident_daily.empty:
                incident_daily = incident_daily.sort_values("Date")
                incident_daily["7-day MA"] = incident_daily["Incidents"].rolling(window=7, min_periods=1).mean()
                fig_inc = px.line(incident_daily, x="Date", y=["Incidents", "7-day MA"],
                                  title="Daily Incident Cases & 7‑Day MA",
                                  markers=True, color_discrete_map={"Incidents": "#d62728", "7-day MA": "#9467bd"})
                # Add threshold line (e.g., 2 incidents/day)
                fig_inc.add_hline(y=2, line_dash="dash", line_color="red", opacity=0.5, annotation_text="Alert threshold")
                st.plotly_chart(fig_inc, use_container_width=True)
            else:
                st.info("No incidents in this period.")

        # ----------------------------
        # 3b. NEW: Bar chart of incidents per day (clearer view)
        # ----------------------------
        st.markdown("#### 📅 Incidents by Date (Bar Chart)")
        if not incident_daily.empty:
            fig_inc_bar = px.bar(incident_daily, x="Date", y="Incidents",
                                 title="Incident Count per Day",
                                 color="Incidents", color_continuous_scale="Reds",
                                 hover_data={"Incidents": True})
            fig_inc_bar.update_layout(showlegend=False)
            st.plotly_chart(fig_inc_bar, use_container_width=True)
        else:
            st.info("No incidents to display in this bar chart.")

        st.markdown("---")

        # ----------------------------
        # 4. ROW 3: LENGTH OF STAY & WATCHLIST
        # ----------------------------
        stay_col1, stay_col2 = st.columns(2)
        with stay_col1:
            # Boxplot of Hours in Clinic by Diagnosis with jitter and admission colour
            df_hours = df[df["Hours in Clinic"].notna()].copy()
            if not df_hours.empty:
                fig_box = px.box(df_hours, x="Diagnosis", y="Hours in Clinic", points="all",
                                 color="Admission Status", hover_data=["Patient Name"],
                                 title="Consultation Duration by Diagnosis")
                fig_box.update_layout(showlegend=True)
                st.plotly_chart(fig_box, use_container_width=True)
            else:
                st.write("No hours data available.")

        with stay_col2:
            # Top 10 prolonged admissions
            admitted = df[df["Days Admitted"] > 0].copy()
            if not admitted.empty:
                top_admitted = admitted.nlargest(10, "Days Admitted")[["Patient Name", "Days Admitted", "Diagnosis"]]
                fig_stay = px.bar(top_admitted, x="Days Admitted", y="Patient Name", orientation='h',
                                  color="Diagnosis", title="Top 10 Longest Admissions",
                                  hover_data={"Days Admitted": True}, text_auto=True)
                fig_stay.update_layout(yaxis={'categoryorder':'total ascending'})
                st.plotly_chart(fig_stay, use_container_width=True)
                # Watchlist: show patients admitted >3 days
                watchlist = df[df["Days Admitted"] > 3][["Patient Name", "Days Admitted", "Diagnosis", "Admission Status"]]
                if not watchlist.empty:
                    st.markdown("#### ⚠️ Prolonged Stay Watchlist (>3 days)")
                    st.dataframe(watchlist, use_container_width=True)
            else:
                st.success("No prolonged admissions (>0 days) in this period.")

        st.markdown("---")

        # ----------------------------
        # 5. ROW 4: INCIDENT DEEP-DIVE
        # ----------------------------
        inc_col1, inc_col2 = st.columns(2)
        with inc_col1:
            # Incident severity pie
            incident_df = df[df["Incident Case"] == "Yes"]
            if not incident_df.empty:
                severity_counts = incident_df["Incident Type"].value_counts().reset_index()
                severity_counts.columns = ["Severity", "Count"]
                fig_pie = px.pie(severity_counts, values="Count", names="Severity",
                                 title="Incident Severity Distribution",
                                 color_discrete_map={"Minor Injury Case": "#ffa600", "Major (LTI)": "#d62728"})
                st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.info("No incidents to display.")

        with inc_col2:
            # Incident rate by designation (incidents / total visits per role)
            des_total = df.groupby("Designation").size().reset_index(name="Total")
            des_incident = df[df["Incident Case"] == "Yes"].groupby("Designation").size().reset_index(name="Incidents")
            des_rate = des_total.merge(des_incident, on="Designation", how="left").fillna(0)
            des_rate["Rate (%)"] = (des_rate["Incidents"] / des_rate["Total"]) * 100
            des_rate = des_rate.sort_values("Rate (%)", ascending=False)
            fig_rate = px.bar(des_rate, x="Rate (%)", y="Designation", orientation='h',
                              title="Incident Rate by Designation (% of visits)",
                              color="Rate (%)", color_continuous_scale="Reds")
            fig_rate.update_layout(yaxis={'categoryorder':'total ascending'})
            st.plotly_chart(fig_rate, use_container_width=True)

        st.markdown("---")

        # ----------------------------
        # 6. ROW 5: HEATMAP – Day vs Hour
        # ----------------------------
        if not df.empty and "Timestamp" in df.columns:
            df["Hour"] = df["Timestamp"].dt.hour
            df["DayOfWeek"] = df["Timestamp"].dt.day_name()
            # Order days
            day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            df["DayOfWeek"] = pd.Categorical(df["DayOfWeek"], categories=day_order, ordered=True)
            # Aggregate counts per hour and day
            heatmap_data = df.groupby(["DayOfWeek", "Hour"], observed=True).size().reset_index(name="Visits")
            # Pivot for heatmap
            pivot = heatmap_data.pivot(index="DayOfWeek", columns="Hour", values="Visits").fillna(0)
            fig_heat = px.imshow(pivot, text_auto=True, aspect="auto",
                                 color_continuous_scale="Blues",
                                 title="Visit Volume Heatmap (Day of Week vs Hour of Day)")
            fig_heat.update_xaxes(title="Hour of Day")
            fig_heat.update_yaxes(title="Day of Week")
            st.plotly_chart(fig_heat, use_container_width=True)

        st.markdown("---")

        # ----------------------------
        # 7. FILTERABLE PATIENT REGISTRY
        # ----------------------------
        st.subheader("📋 Patient Registry (Filtered View)")
        # Search box
        search = st.text_input("Search by Patient Name", "")
        registry_df = df[["Date", "Patient Name", "Designation", "Diagnosis", "Incident Case", "Hours in Clinic", "Days Admitted", "Notes"]]
        if search:
            registry_df = registry_df[registry_df["Patient Name"].str.contains(search, case=False)]
        st.dataframe(registry_df, use_container_width=True)


# ==========================================
# TAB 2: NURSE INTAKE REGISTRY FORM
# ==========================================
with tab_entry:
    st.subheader("New Patient Clinical Record Entry")
    
    with st.form("patient_intake_form", clear_on_submit=True):
        form_col1, form_col2, form_col3 = st.columns(3)
        
        with form_col1:
            st.markdown("##### **Demographic Info**")
            p_name = st.text_input("Patient Full Name", placeholder="Surname first")
            p_age = st.number_input("Age", min_value=0, max_value=120, step=1, value=25)
            p_gender = st.selectbox("Gender", ["Male", "Female", "Other"])
            p_designation = st.text_input("Employee Designation (Role/Department)", placeholder="e.g., Nurse, Engineer, Admin")
            
        with form_col2:
            st.markdown("##### **Clinical Vitals**")
            sys_bp = st.number_input("Systolic BP (mmHg)", min_value=50, max_value=250, value=120)
            dia_bp = st.number_input("Diastolic BP (mmHg)", min_value=30, max_value=150, value=80)
            temp_c = st.number_input("Temperature (°C)", min_value=30.0, max_value=45.0, step=0.1, value=36.5)
            pulse = st.number_input("Pulse Rate (bpm)", min_value=30, max_value=200, value=75)
            
        with form_col3:
            st.markdown("##### **Diagnosis & Classifications**")
            dx = st.selectbox("Primary Diagnosis/Presentation", [
                "Malaria", 
                "Hypertension (Elevated BP)", 
                "Peptic Ulcer Disease (PUD)", 
                "Typhoid Fever", 
                "Upper Respiratory Tract Infection (URTI)", 
                "Musculoskeletal Pain / Trauma", 
                "Skin Infection", 
                "Other Operational/Routine Encounter"
            ])
            admission_status = st.selectbox("Admission Strategy", ["No Entry", "Short-Day Admission", "Standard Admission"])
            is_ref = st.checkbox("Escalate as a Referral Outward Case")
            
        st.markdown("---")
        
        # Duration and Incident Tracking
        dur_col1, dur_col2 = st.columns(2)
        
        with dur_col1:
            st.markdown("##### **Time Tracking**")
            hrs_spent = st.number_input("Hours Spent in Clinic (Outpatient/Consultation)", min_value=0.0, max_value=24.0, step=0.5, value=0.5)
            days_spent = st.number_input("Days Admitted (Leave at 0 if not admitted)", min_value=0, max_value=30, step=1, value=0)
            
        with dur_col2:
            st.markdown("##### **Workplace Incident Logging**")
            has_incident = st.checkbox("Is this visit related to a workplace incident/injury?")
            inc_type = st.selectbox("Incident Severity Classification", ["Minor Injury Case", "Major (LTI)"]) if has_incident else None
            
        notes = st.text_area("Clinical Notes & Observation Assessments", placeholder="Type out detailed patient complaints, treatment plans, or ongoing observation adjustments.")
        
        submit_btn = st.form_submit_button("Commit Entry to Ledger Database")
        
        if submit_btn:
            if not p_name.strip():
                st.error("Submission blocked: Patient Name cannot be left completely blank.")
            else:
                payload = {
                    "patient_name": p_name,
                    "age": p_age,
                    "gender": p_gender,
                    "employee_designation": p_designation if p_designation.strip() else None,
                    "systolic_bp": sys_bp,
                    "diastolic_bp": dia_bp,
                    "temperature_c": temp_c,
                    "pulse_rate": pulse,
                    "primary_diagnosis": dx,
                    "is_admission": admission_status,
                    "is_referral": 1 if is_ref else 0,
                    "is_incident": 1 if has_incident else 0,
                    "incident_type": inc_type,
                    "hours_in_clinic": hrs_spent,
                    "days_admitted": days_spent,
                    "clinical_notes": notes
                }
                save_visit(payload)
                st.success(f"Log Successfully Generated for {p_name}. Database updated instantly.")
                st.rerun()


# ==========================================
# 5. SEED DATA BUTTON (with random timestamps)
# ==========================================
if st.button("Seed Database with 20 Sample Records (random dates)"):
    names = [
        "Chuka Obi", "Amina Bello", "Emeka Uba", "Sarah Johnson", "Michael Eze", 
        "Fatima Aliyu", "David Smith", "Ngozi Okafor", "Tunde Bakare", "John Doe", 
        "Jane Smith", "Musa Ibrahim", "Grace Nwachukwu", "Peter Ojo", "Aisha Yusuf", 
        "Samuel Kalu", "Chidinma Nwosu", "Oluwaseun Adeyemi", "Kabir Danladi", "Victoria Coker"
    ]
    designations = ["Nurse", "Doctor", "Engineer", "Admin", "Technician", "Manager", "Operator"]
    diagnoses = [
        "Malaria", "Hypertension (Elevated BP)", "Peptic Ulcer Disease (PUD)", 
        "Typhoid Fever", "Upper Respiratory Tract Infection (URTI)", 
        "Musculoskeletal Pain / Trauma", "Skin Infection", "Other Operational/Routine Encounter"
    ]
    
    # Define date range: July 30, 2026 to August 30, 2026
    start_seed = datetime(2026, 7, 30, 0, 0, 0)
    end_seed = datetime(2026, 8, 30, 23, 59, 59)
    delta_days = (end_seed - start_seed).days

    for name in names:
        # Random timestamp within the range
        rand_days = random.randint(0, delta_days)
        rand_seconds = random.randint(0, 86400)  # seconds in a day
        random_timestamp = start_seed + timedelta(days=rand_days, seconds=rand_seconds)
        
        is_incident = 1 if random.random() < 0.2 else 0
        inc_type = random.choice(["Minor Injury Case", "Major (LTI)"]) if is_incident else None
        dx = "Musculoskeletal Pain / Trauma" if is_incident else random.choice(diagnoses)
        
        if dx == "Hypertension (Elevated BP)":
            sys_bp = random.randint(140, 185)
            dia_bp = random.randint(90, 115)
        else:
            sys_bp = random.randint(100, 135)
            dia_bp = random.randint(60, 85)
            
        temp = round(random.uniform(38.0, 39.8), 1) if dx in ["Malaria", "Typhoid Fever"] else round(random.uniform(36.1, 37.3), 1)
        
        if random.random() < 0.25:
            admission = random.choice(["Short-Day Admission", "Standard Admission"])
            days = random.randint(1, 5) if admission == "Standard Admission" else 0
        else:
            admission = "No Entry"
            days = 0
            
        payload = {
            "timestamp": random_timestamp,  # <-- added random timestamp
            "patient_name": name,
            "age": random.randint(22, 60),
            "gender": random.choice(["Male", "Female"]),
            "employee_designation": random.choice(designations),
            "systolic_bp": sys_bp,
            "diastolic_bp": dia_bp,
            "temperature_c": temp,
            "pulse_rate": random.randint(65, 110),
            "primary_diagnosis": dx,
            "is_admission": admission,
            "is_referral": 1 if random.random() < 0.1 else 0,
            "is_incident": is_incident,
            "incident_type": inc_type,
            "hours_in_clinic": round(random.uniform(0.5, 5.0), 1),
            "days_admitted": days,
            "clinical_notes": f"Sample generated record for {dx}." if not is_incident else f"Incident report: {inc_type}. Monitoring applied."
        }
        
        save_visit(payload)
        
    st.success("20 sample records with random dates (July 30 – Aug 30, 2026) successfully injected! Please refresh the page to see your dashboard light up.")
