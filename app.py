import streamlit as st
import pandas as pd
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker
import matplotlib.pyplot as plt

# ==========================================
# 1. CLOUD DATABASE CONFIGURATION (SECURE)
# ==========================================
# Pulling connection string dynamically from Streamlit secure secrets env
if "DATABASE_URL" in st.secrets:
    DATABASE_URL = st.secrets["DATABASE_URL"]
else:
    # Fallback to local testing only if cloud secret isn't configured yet
    DATABASE_URL = "sqlite:///clinic_operations.db"

# Added pool_pre_ping to automatically reconnect across unstable network drops
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
    
    # Vitals
    systolic_bp = Column(Integer, nullable=True)
    diastolic_bp = Column(Integer, nullable=True)
    temperature_c = Column(Float, nullable=True)
    pulse_rate = Column(Integer, nullable=True)
    
    # Clinical Classifications
    primary_diagnosis = Column(String(100), nullable=False)
    is_admission = Column(String(50), default="No Entry")  # No Entry, Short-Day, Standard Admission
    is_referral = Column(Integer, default=0) # 0 = No, 1 = Yes
    
    # Incident Tracking
    is_incident = Column(Integer, default=0) # 0 = No, 1 = Yes
    incident_type = Column(String(50), nullable=True) # Minor, Major (LTI)
    clinical_notes = Column(Text, nullable=True)

# Generate tables if they do not already exist in the database
Base.metadata.create_all(bind=engine)

# ==========================================
# 2. HELPER FUNCTIONS (DATA LAYER)
# ==========================================
def save_visit(data):
    db = SessionLocal()
    try:
        db_visit = PatientVisit(**data)
        db.add(db_visit)
        db.commit()
    finally:
        # Ensures connection returns to the pool even if an error occurs
        db.close()

def load_data_dataframe():
    db = SessionLocal()
    try:
        query = db.query(PatientVisit).all()
    finally:
        db.close()
    
    if not query:
        return pd.DataFrame()
        
    data = []
    for item in query:
        data.append({
            "ID": item.id,
            "Date": item.timestamp.strftime("%Y-%m-%d %H:%M") if item.timestamp else "N/A",
            "Patient Name": item.patient_name,
            "Age": item.age,
            "Gender": item.gender,
            "Blood Pressure": f"{item.systolic_bp}/{item.diastolic_bp}" if item.systolic_bp else "N/A",
            "Systolic": item.systolic_bp,
            "Diastolic": item.diastolic_bp,
            "Temp (°C)": item.temperature_c,
            "Diagnosis": item.primary_diagnosis,
            "Admission Status": item.is_admission,
            "Referral": "Yes" if item.is_referral == 1 else "No",
            "Incident Case": "Yes" if item.is_incident == 1 else "No",
            "Incident Type": item.incident_type if item.is_incident == 1 else "N/A",
            "Notes": item.clinical_notes
        })
    return pd.DataFrame(data)

# ==========================================
# 3. STREAMLIT INTERFACE (UI LAYER)
# ==========================================
st.set_page_config(page_title="Clinic Operations System", layout="wide")

st.title("🏥 Site Clinic Intelligence System")
st.markdown("---")

# Navigation Tabs
tab_dashboard, tab_entry = st.tabs(["📊 Real-Time Analytics Dashboard", "📝 Nurse Intake Registry"])

# ------------------------------------------
# TAB 1: REAL-TIME ANALYTICS DASHBOARD
# ------------------------------------------
with tab_dashboard:
    df = load_data_dataframe()
    
    if df.empty:
        st.info("The system database is currently empty. Switch to the Intake Registry tab to seed data.")
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
        
        # Visual Analytics Zone
        chart_col1, chart_col2 = st.columns(2)
        
        with chart_col1:
            st.subheader("Leading Causes of Clinic Attendance")
            diagnosis_counts = df["Diagnosis"].value_counts()
            
            fig, ax = plt.subplots(figsize=(8, 4.5))
            diagnosis_counts.plot(kind="barh", ax=ax, color="#1f77b4", edgecolor="none")
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.invert_yaxis()  # Top down representation
            plt.tight_layout()
            st.pyplot(fig)
            
        with chart_col2:
            st.subheader("Hypertension & Cardiovascular Monitoring")
            # Filter rows with valid BP entries
            valid_bp = df[df["Systolic"].notna()]
            
            if not valid_bp.empty:
                fig2, ax2 = plt.subplots(figsize=(8, 4.5))
                colors = valid_bp["Systolic"].apply(lambda x: '#d62728' if x >= 140 else '#2ca02c')
                ax2.scatter(valid_bp["Systolic"], valid_bp["Diastolic"], c=colors, s=100, alpha=0.7, edgecolors='none')
                ax2.axvline(x=140, color='#d62728', linestyle='--', alpha=0.5, label='Hypertensive Threshold')
                ax2.set_xlabel("Systolic Blood Pressure (mmHg)")
                ax2.set_ylabel("Diastolic Blood Pressure (mmHg)")
                ax2.spines['top'].set_visible(False)
                ax2.spines['right'].set_visible(False)
                st.pyplot(fig2)
            else:
                st.write("No vital signs records available for hypertension tracking.")
                
        st.markdown("---")
        st.subheader("Master Patient Registry Log")
        st.dataframe(df, use_container_width=True)

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
        st.markdown("##### **Workplace Incident & Safety Logging**")
        inc_col1, inc_col2 = st.columns(2)
        
        with inc_col1:
            has_incident = st.checkbox("Is this visit related to a workplace incident/injury?")
        with inc_col2:
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
                    "systolic_bp": sys_bp,
                    "diastolic_bp": dia_bp,
                    "temperature_c": temp_c,
                    "pulse_rate": pulse,
                    "primary_diagnosis": dx,
                    "is_admission": admission_status,
                    "is_referral": 1 if is_ref else 0,
                    "is_incident": 1 if has_incident else 0,
                    "incident_type": inc_type,
                    "clinical_notes": notes
                }
                save_visit(payload)
                st.success(f"Log Successfully Generated for {p_name}. Database updated instantly.")
                st.rerun()
