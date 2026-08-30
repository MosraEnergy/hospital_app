# import streamlit as st
# import pandas as pd
# from datetime import datetime
# from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text
# from sqlalchemy.orm import declarative_base, sessionmaker
# import matplotlib.pyplot as plt

# # ==========================================
# # 1. CLOUD DATABASE CONFIGURATION (SECURE)
# # ==========================================
# # Pulling connection string dynamically from Streamlit secure secrets env
# if "DATABASE_URL" in st.secrets:
#     DATABASE_URL = st.secrets["DATABASE_URL"]
# else:
#     # Fallback to local testing only if cloud secret isn't configured yet
#     DATABASE_URL = "sqlite:///clinic_operations.db"

# # Added pool_pre_ping to automatically reconnect across unstable network drops
# engine = create_engine(
#     DATABASE_URL, 
#     pool_pre_ping=True,
#     connect_args={"sslmode": "require"} if "postgresql" in DATABASE_URL else {}
# )
# Base = declarative_base()
# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# class PatientVisit(Base):
#     __tablename__ = "patient_visits"
    
#     id = Column(Integer, primary_key=True, index=True)
#     timestamp = Column(DateTime, default=datetime.utcnow)
#     patient_name = Column(String(100), nullable=False)
#     age = Column(Integer, nullable=False)
#     gender = Column(String(20), nullable=False)
    
#     # Vitals
#     systolic_bp = Column(Integer, nullable=True)
#     diastolic_bp = Column(Integer, nullable=True)
#     temperature_c = Column(Float, nullable=True)
#     pulse_rate = Column(Integer, nullable=True)
    
#     # Clinical Classifications
#     primary_diagnosis = Column(String(100), nullable=False)
#     is_admission = Column(String(50), default="No Entry")  # No Entry, Short-Day, Standard Admission
#     is_referral = Column(Integer, default=0) # 0 = No, 1 = Yes
    
#     # Incident Tracking
#     is_incident = Column(Integer, default=0) # 0 = No, 1 = Yes
#     incident_type = Column(String(50), nullable=True) # Minor, Major (LTI)
#     clinical_notes = Column(Text, nullable=True)

# # Generate tables if they do not already exist in the database
# Base.metadata.create_all(bind=engine)

# # ==========================================
# # 2. HELPER FUNCTIONS (DATA LAYER)
# # ==========================================
# def save_visit(data):
#     db = SessionLocal()
#     try:
#         db_visit = PatientVisit(**data)
#         db.add(db_visit)
#         db.commit()
#     finally:
#         # Ensures connection returns to the pool even if an error occurs
#         db.close()

# def load_data_dataframe():
#     db = SessionLocal()
#     try:
#         query = db.query(PatientVisit).all()
#     finally:
#         db.close()
    
#     if not query:
#         return pd.DataFrame()
        
#     data = []
#     for item in query:
#         data.append({
#             "ID": item.id,
#             "Date": item.timestamp.strftime("%Y-%m-%d %H:%M") if item.timestamp else "N/A",
#             "Patient Name": item.patient_name,
#             "Age": item.age,
#             "Gender": item.gender,
#             "Blood Pressure": f"{item.systolic_bp}/{item.diastolic_bp}" if item.systolic_bp else "N/A",
#             "Systolic": item.systolic_bp,
#             "Diastolic": item.diastolic_bp,
#             "Temp (°C)": item.temperature_c,
#             "Diagnosis": item.primary_diagnosis,
#             "Admission Status": item.is_admission,
#             "Referral": "Yes" if item.is_referral == 1 else "No",
#             "Incident Case": "Yes" if item.is_incident == 1 else "No",
#             "Incident Type": item.incident_type if item.is_incident == 1 else "N/A",
#             "Notes": item.clinical_notes
#         })
#     return pd.DataFrame(data)

# # ==========================================
# # 3. STREAMLIT INTERFACE (UI LAYER)
# # ==========================================
# st.set_page_config(page_title="Clinic Operations System", layout="wide")

# st.title("🏥 Site Clinic Intelligence System")
# st.markdown("---")

# # Navigation Tabs
# tab_dashboard, tab_entry = st.tabs(["📊 Real-Time Analytics Dashboard", "📝 Nurse Intake Registry"])

# # ------------------------------------------
# # TAB 1: REAL-TIME ANALYTICS DASHBOARD
# # ------------------------------------------
# with tab_dashboard:
#     df = load_data_dataframe()
    
#     if df.empty:
#         st.info("The system database is currently empty. Switch to the Intake Registry tab to seed data.")
#     else:
#         # High-Level Metrics Calculations
#         total_visits = len(df)
#         admissions = len(df[df["Admission Status"].isin(["Standard Admission", "Short-Day Admission"])])
#         referrals = len(df[df["Referral"] == "Yes"])
#         incidents = len(df[df["Incident Case"] == "Yes"])
#         lti_cases = len(df[df["Incident Type"] == "Major (LTI)"])

#         # Display Top KPI Block Cards
#         col1, col2, col3, col4, col5 = st.columns(5)
#         col1.metric("Total Patient Visits", total_visits)
#         col2.metric("Admissions", admissions)
#         col3.metric("Referral Cases", referrals)
#         col4.metric("Incident Cases", incidents)
#         col5.metric("Loss Time Injuries (LTI)", lti_cases)
        
#         st.markdown("---")
        
#         # Visual Analytics Zone
#         chart_col1, chart_col2 = st.columns(2)
        
#         with chart_col1:
#             st.subheader("Leading Causes of Clinic Attendance")
#             diagnosis_counts = df["Diagnosis"].value_counts()
            
#             fig, ax = plt.subplots(figsize=(8, 4.5))
#             diagnosis_counts.plot(kind="barh", ax=ax, color="#1f77b4", edgecolor="none")
#             ax.spines['top'].set_visible(False)
#             ax.spines['right'].set_visible(False)
#             ax.invert_yaxis()  # Top down representation
#             plt.tight_layout()
#             st.pyplot(fig)
            
#         with chart_col2:
#             st.subheader("Hypertension & Cardiovascular Monitoring")
#             # Filter rows with valid BP entries
#             valid_bp = df[df["Systolic"].notna()]
            
#             if not valid_bp.empty:
#                 fig2, ax2 = plt.subplots(figsize=(8, 4.5))
#                 colors = valid_bp["Systolic"].apply(lambda x: '#d62728' if x >= 140 else '#2ca02c')
#                 ax2.scatter(valid_bp["Systolic"], valid_bp["Diastolic"], c=colors, s=100, alpha=0.7, edgecolors='none')
#                 ax2.axvline(x=140, color='#d62728', linestyle='--', alpha=0.5, label='Hypertensive Threshold')
#                 ax2.set_xlabel("Systolic Blood Pressure (mmHg)")
#                 ax2.set_ylabel("Diastolic Blood Pressure (mmHg)")
#                 ax2.spines['top'].set_visible(False)
#                 ax2.spines['right'].set_visible(False)
#                 st.pyplot(fig2)
#             else:
#                 st.write("No vital signs records available for hypertension tracking.")
                
#         st.markdown("---")
#         st.subheader("Master Patient Registry Log")
#         st.dataframe(df, use_container_width=True)

# # ------------------------------------------
# # TAB 2: NURSE INTAKE REGISTRY FORM
# # ------------------------------------------
# with tab_entry:
#     st.subheader("New Patient Clinical Record Entry")
    
#     with st.form("patient_intake_form", clear_on_submit=True):
#         form_col1, form_col2, form_col3 = st.columns(3)
        
#         with form_col1:
#             st.markdown("##### **Demographic Info**")
#             p_name = st.text_input("Patient Full Name", placeholder="Surname first")
#             p_age = st.number_input("Age", min_value=0, max_value=120, step=1, value=25)
#             p_gender = st.selectbox("Gender", ["Male", "Female", "Other"])
            
#         with form_col2:
#             st.markdown("##### **Clinical Vitals**")
#             sys_bp = st.number_input("Systolic BP (mmHg)", min_value=50, max_value=250, value=120)
#             dia_bp = st.number_input("Diastolic BP (mmHg)", min_value=30, max_value=150, value=80)
#             temp_c = st.number_input("Temperature (°C)", min_value=30.0, max_value=45.0, step=0.1, value=36.5)
#             pulse = st.number_input("Pulse Rate (bpm)", min_value=30, max_value=200, value=75)
            
#         with form_col3:
#             st.markdown("##### **Diagnosis & Classifications**")
#             dx = st.selectbox("Primary Diagnosis/Presentation", [
#                 "Malaria", 
#                 "Hypertension (Elevated BP)", 
#                 "Peptic Ulcer Disease (PUD)", 
#                 "Typhoid Fever", 
#                 "Upper Respiratory Tract Infection (URTI)", 
#                 "Musculoskeletal Pain / Trauma", 
#                 "Skin Infection", 
#                 "Other Operational/Routine Encounter"
#             ])
#             admission_status = st.selectbox("Admission Strategy", ["No Entry", "Short-Day Admission", "Standard Admission"])
#             is_ref = st.checkbox("Escalate as a Referral Outward Case")
            
#         st.markdown("---")
#         st.markdown("##### **Workplace Incident & Safety Logging**")
#         inc_col1, inc_col2 = st.columns(2)
        
#         with inc_col1:
#             has_incident = st.checkbox("Is this visit related to a workplace incident/injury?")
#         with inc_col2:
#             inc_type = st.selectbox("Incident Severity Classification", ["Minor Injury Case", "Major (LTI)"]) if has_incident else None
            
#         notes = st.text_area("Clinical Notes & Observation Assessments", placeholder="Type out detailed patient complaints, treatment plans, or ongoing observation adjustments.")
        
#         submit_btn = st.form_submit_button("Commit Entry to Ledger Database")
        
#         if submit_btn:
#             if not p_name.strip():
#                 st.error("Submission blocked: Patient Name cannot be left completely blank.")
#             else:
#                 payload = {
#                     "patient_name": p_name,
#                     "age": p_age,
#                     "gender": p_gender,
#                     "systolic_bp": sys_bp,
#                     "diastolic_bp": dia_bp,
#                     "temperature_c": temp_c,
#                     "pulse_rate": pulse,
#                     "primary_diagnosis": dx,
#                     "is_admission": admission_status,
#                     "is_referral": 1 if is_ref else 0,
#                     "is_incident": 1 if has_incident else 0,
#                     "incident_type": inc_type,
#                     "clinical_notes": notes
#                 }
#                 save_visit(payload)
#                 st.success(f"Log Successfully Generated for {p_name}. Database updated instantly.")
#                 st.rerun()

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, inspect
from sqlalchemy.orm import declarative_base, sessionmaker
import plotly.express as px
import random

# ==========================================
# 1. CLOUD DATABASE CONFIGURATION (SECURE)
# ==========================================
if "DATABASE_URL" in st.secrets:
    DATABASE_URL = st.secrets["DATABASE_URL"]
else:
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
    employee_designation = Column(String(100), nullable=True)  # NEW: job title / department
    
    # Vitals
    systolic_bp = Column(Integer, nullable=True)
    diastolic_bp = Column(Integer, nullable=True)
    temperature_c = Column(Float, nullable=True)
    pulse_rate = Column(Integer, nullable=True)
    
    # Clinical Classifications
    primary_diagnosis = Column(String(100), nullable=False)
    is_admission = Column(String(50), default="No Entry") 
    is_referral = Column(Integer, default=0) 
    
    # Incident Tracking
    is_incident = Column(Integer, default=0) 
    incident_type = Column(String(50), nullable=True) 
    clinical_notes = Column(Text, nullable=True)
    
    # Duration & Length of Stay Tracking
    hours_in_clinic = Column(Float, nullable=True, default=0.0)
    days_admitted = Column(Integer, nullable=True, default=0)

# ==========================================
# 2. DATABASE MIGRATION HELPER
# ==========================================
from sqlalchemy import text  # add this import at the top

def add_column_if_not_exists(table_name, column):
    inspector = inspect(engine)
    existing_columns = [col['name'] for col in inspector.get_columns(table_name)]
    if column.name not in existing_columns:
        with engine.connect() as conn:
            # Get the SQL type name as a string (e.g., VARCHAR(100))
            col_type = str(column.type)
            alter_stmt = text(f"ALTER TABLE {table_name} ADD COLUMN {column.name} {col_type}")
            conn.execute(alter_stmt)
            conn.commit()

# Create tables (existing ones are left untouched)
Base.metadata.create_all(bind=engine)
# Add new column if missing
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
            "Timestamp": item.timestamp,  # keep as datetime for filtering/plotting
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

tab_dashboard, tab_entry = st.tabs(["📊 Real-Time Analytics Dashboard", "📝 Nurse Intake Registry"])

# ------------------------------------------
# TAB 1: REAL-TIME ANALYTICS DASHBOARD
# ------------------------------------------
with tab_dashboard:
    # Date filter
    st.sidebar.header("Filter by Date")
    default_end = datetime.now()
    default_start = default_end - timedelta(days=30)
    start_date = st.sidebar.date_input("Start Date", default_start)
    end_date = st.sidebar.date_input("End Date", default_end)
    
    # Convert to datetime for query
    start_dt = datetime.combine(start_date, datetime.min.time()) if start_date else None
    end_dt = datetime.combine(end_date, datetime.max.time()) if end_date else None
    
    df = load_data_dataframe(start_dt, end_dt)
    
    if df.empty:
        st.info("No records found for the selected date range. Switch to the Intake Registry tab to add data.")
    else:
        # High-Level Metrics Calculations
        total_visits = len(df)
        admissions = len(df[df["Admission Status"].isin(["Standard Admission", "Short-Day Admission"])])
        referrals = len(df[df["Referral"] == "Yes"])
        incidents = len(df[df["Incident Case"] == "Yes"])
        lti_cases = len(df[df["Incident Type"] == "Major (LTI)"])

        # Display Top KPI Block Cards
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Total Patient Visits", total_visits)
        col2.metric("Admissions", admissions)
        col3.metric("Referral Cases", referrals)
        col4.metric("Incident Cases", incidents)
        col5.metric("Loss Time Injuries (LTI)", lti_cases)
        
        st.markdown("---")
        
        # ROW 1: Diagnoses & Hypertension (Plotly)
        chart_col1, chart_col2 = st.columns(2)
        
        with chart_col1:
            dx_counts = df["Diagnosis"].value_counts().reset_index()
            dx_counts.columns = ["Diagnosis", "Count"]
            fig_dx = px.bar(dx_counts, x="Count", y="Diagnosis", orientation='h', 
                            title="Leading Causes of Clinic Attendance",
                            color="Count", color_continuous_scale="Blues")
            fig_dx.update_layout(yaxis={'categoryorder':'total ascending'}, showlegend=False)
            st.plotly_chart(fig_dx, use_container_width=True)
            
        with chart_col2:
            valid_bp = df[df["Systolic"].notna()].copy()
            if not valid_bp.empty:
                valid_bp["Risk Level"] = valid_bp["Systolic"].apply(lambda x: "High Risk (≥140)" if x >= 140 else "Normal")
                fig_bp = px.scatter(valid_bp, x="Systolic", y="Diastolic", color="Risk Level",
                                    color_discrete_map={"High Risk (≥140)": "#d62728", "Normal": "#2ca02c"},
                                    hover_data=["Patient Name", "Diagnosis"],
                                    title="Hypertension & Cardiovascular Monitoring")
                fig_bp.add_vline(x=140, line_dash="dash", line_color="red", opacity=0.5)
                st.plotly_chart(fig_bp, use_container_width=True)
            else:
                st.write("No vital signs records available for hypertension tracking.")
                
        st.markdown("---")
        
        # ROW 2: Length of Stay & Time Tracking (Plotly)
        time_col1, time_col2 = st.columns(2)
        
        with time_col1:
            st.markdown("##### **⏱️ Outpatient Time Spent in Clinic (Hours)**")
            fig_time = px.box(df, x="Diagnosis", y="Hours in Clinic", points="all",
                              color="Diagnosis", title="Average Duration per Consultation/Treatment",
                              hover_data=["Patient Name"])
            fig_time.update_layout(showlegend=False)
            st.plotly_chart(fig_time, use_container_width=True)
            
        with time_col2:
            st.markdown("##### **🛏️ Prolonged Admissions Watchlist**")
            admitted_df = df[df["Days Admitted"] > 0].copy()
            if not admitted_df.empty:
                fig_stay = px.bar(admitted_df.sort_values("Days Admitted", ascending=False), 
                                  x="Patient Name", y="Days Admitted", color="Diagnosis",
                                  title="Total Days Admitted per Patient", text_auto=True)
                st.plotly_chart(fig_stay, use_container_width=True)
            else:
                st.success("No active or prolonged admissions recorded.")
        
        st.markdown("---")
        
        # ========== NEW TIME-SERIES VISUALS ==========
        st.subheader("📈 Time‑Based Activity Trends")
        
        # Ensure Timestamp is datetime
        df["Timestamp"] = pd.to_datetime(df["Timestamp"])
        df["DateOnly"] = df["Timestamp"].dt.date
        
        # 1. Daily visit trend
        daily_visits = df.groupby("DateOnly").size().reset_index(name="Visits")
        fig_daily = px.line(daily_visits, x="DateOnly", y="Visits", 
                            title="Daily Patient Visits", markers=True)
        fig_daily.update_xaxes(title="Date")
        fig_daily.update_yaxes(title="Number of Visits")
        st.plotly_chart(fig_daily, use_container_width=True)
        
        # 2. Incident trend (daily)
        incident_df = df[df["Incident Case"] == "Yes"].copy()
        if not incident_df.empty:
            daily_incidents = incident_df.groupby("DateOnly").size().reset_index(name="Incidents")
            fig_inc = px.line(daily_incidents, x="DateOnly", y="Incidents",
                              title="Daily Incident Cases", markers=True, color_discrete_sequence=["red"])
            fig_inc.update_xaxes(title="Date")
            fig_inc.update_yaxes(title="Number of Incidents")
            st.plotly_chart(fig_inc, use_container_width=True)
        else:
            st.info("No incident records in the selected period.")
        
        # 3. Weekly pattern (day of week)
        df["DayOfWeek"] = df["Timestamp"].dt.day_name()
        # Order days correctly
        day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        df["DayOfWeek"] = pd.Categorical(df["DayOfWeek"], categories=day_order, ordered=True)
        weekly_counts = df.groupby("DayOfWeek", observed=True).size().reset_index(name="Visits")
        fig_week = px.bar(weekly_counts, x="DayOfWeek", y="Visits",
                          title="Visits by Day of Week", color="Visits", color_continuous_scale="Viridis")
        st.plotly_chart(fig_week, use_container_width=True)
        
        st.markdown("---")
        st.subheader("Master Patient Registry Log (Filtered)")
        st.dataframe(df[["Date", "Patient Name", "Designation", "Diagnosis", "Incident Case", "Hours in Clinic", "Days Admitted"]], 
                     use_container_width=True)

# ------------------------------------------
# TAB 2: NURSE INTAKE REGISTRY FORM
# ------------------------------------------
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
# 5. SEED DATA BUTTON (with Designation)
# ==========================================
if st.button("Seed Database with 20 Sample Records"):
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
    
    for name in names:
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
        
    st.success("20 robust sample records successfully injected! Please refresh the page to see your dashboard light up.")
