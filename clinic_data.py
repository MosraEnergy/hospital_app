"""Patient files extend the original visit table without rewriting old records."""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, event, select
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PatientVisit(Base):
    __tablename__ = "patient_visits"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=utc_now)
    patient_name = Column(String(100), nullable=False)
    age = Column(Integer, nullable=False)
    gender = Column(String(20), nullable=False)
    systolic_bp = Column(Integer)
    diastolic_bp = Column(Integer)
    temperature_c = Column(Float)
    pulse_rate = Column(Integer)
    primary_diagnosis = Column(String(100), nullable=False)
    is_admission = Column(String(50), default="No Entry")
    is_referral = Column(Integer, default=0)
    is_incident = Column(Integer, default=0)
    incident_type = Column(String(50))
    clinical_notes = Column(Text)


class Patient(Base):
    __tablename__ = "patients"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    gender = Column(String(20), nullable=False)
    employee_id = Column(String(80), unique=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class VisitPatient(Base):
    __tablename__ = "visit_patients"
    visit_id = Column(Integer, ForeignKey("patient_visits.id"), primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)


class VisitDiagnosis(Base):
    __tablename__ = "visit_diagnoses"
    visit_id = Column(Integer, ForeignKey("patient_visits.id"), primary_key=True)
    position = Column(Integer, primary_key=True)
    diagnosis = Column(String(100), nullable=False)


class VisitNote(Base):
    __tablename__ = "visit_notes"
    id = Column(Integer, primary_key=True)
    visit_id = Column(Integer, ForeignKey("patient_visits.id"), nullable=False, index=True)
    timestamp = Column(DateTime, default=utc_now, nullable=False)
    author = Column(String(100), nullable=False)
    text = Column(Text, nullable=False)


def make_engine(url):
    options = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
    elif url.startswith("postgresql"):
        options["connect_args"] = {"sslmode": "require"}
    engine = create_engine(url, **options)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
    return engine


def file_number(patient_id):
    return f"CL-{patient_id:06d}"


def clean_diagnoses(selected, custom=""):
    values, seen = [], set()
    for value in [*selected, *custom.splitlines()]:
        value = value.strip()
        if not value:
            continue
        if len(value) > 100:
            raise ValueError("Each diagnosis must be 100 characters or fewer.")
        if value.casefold() not in seen:
            values.append(value)
            seen.add(value.casefold())
    if not values:
        raise ValueError("Select or enter at least one diagnosis or presentation.")
    return values


class ClinicStore:
    def __init__(self, engine):
        Base.metadata.create_all(engine)
        self.sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def patients(self):
        with self.sessions() as db:
            return db.scalars(select(Patient).order_by(Patient.name, Patient.id)).all()

    def register_patient(self, name, gender, employee_id=""):
        name = name.strip()
        employee_id = employee_id.strip() or None
        if not name or len(name) > 100:
            raise ValueError("Enter a patient name of 1–100 characters.")
        if employee_id and len(employee_id) > 80:
            raise ValueError("Employee / patient reference must be 80 characters or fewer.")
        with self.sessions.begin() as db:
            patient = Patient(name=name, gender=gender, employee_id=employee_id)
            db.add(patient)
            db.flush()
            return patient.id

    def save_visit(self, patient_id, data, diagnoses):
        diagnoses = clean_diagnoses(diagnoses)
        age = data.get("age")
        if age is None or not 0 <= age <= 120:
            raise ValueError("Enter the patient's age at this visit (0–120 years).")
        sys, dia = data.get("systolic_bp"), data.get("diastolic_bp")
        if (sys is None) != (dia is None):
            raise ValueError("Enter both blood pressure readings, or leave both blank.")
        if sys is not None and sys <= dia:
            raise ValueError("Check blood pressure: systolic must be greater than diastolic.")
        if data.get("is_incident") and not data.get("incident_type"):
            raise ValueError("Choose an incident classification.")
        with self.sessions.begin() as db:
            patient = db.get(Patient, patient_id)
            if patient is None:
                raise ValueError("Patient file could not be found. Refresh and select it again.")
            visit = PatientVisit(**data, patient_name=patient.name, gender=patient.gender,
                                 primary_diagnosis=diagnoses[0])
            db.add(visit)
            db.flush()
            db.add(VisitPatient(visit_id=visit.id, patient_id=patient.id))
            for position, diagnosis in enumerate(diagnoses):
                db.add(VisitDiagnosis(visit_id=visit.id, position=position, diagnosis=diagnosis))
            return visit.id

    def link_visit(self, visit_id, patient_id):
        with self.sessions.begin() as db:
            if db.get(Patient, patient_id) is None or db.get(PatientVisit, visit_id) is None:
                raise ValueError("Patient or visit no longer exists.")
            if db.get(VisitPatient, visit_id) is not None:
                raise ValueError("This visit is already linked to a patient file.")
            db.add(VisitPatient(visit_id=visit_id, patient_id=patient_id))

    def add_note(self, visit_id, author, text):
        if not author.strip() or not text.strip():
            raise ValueError("Enter your name and a follow-up note.")
        if len(author.strip()) > 100:
            raise ValueError("Author name must be 100 characters or fewer.")
        with self.sessions.begin() as db:
            if db.get(PatientVisit, visit_id) is None:
                raise ValueError("Visit could not be found.")
            db.add(VisitNote(visit_id=visit_id, author=author.strip(), text=text.strip()))

    def notes(self, visit_id):
        with self.sessions() as db:
            return db.scalars(select(VisitNote).where(VisitNote.visit_id == visit_id)
                              .order_by(VisitNote.timestamp, VisitNote.id)).all()

    def visits(self):
        with self.sessions() as db:
            rows = db.execute(select(PatientVisit, VisitPatient.patient_id)
                              .outerjoin(VisitPatient, PatientVisit.id == VisitPatient.visit_id)
                              .order_by(PatientVisit.timestamp.desc(), PatientVisit.id.desc())).all()
            diagnoses = {}
            for item in db.scalars(select(VisitDiagnosis).order_by(VisitDiagnosis.position)):
                diagnoses.setdefault(item.visit_id, []).append(item.diagnosis)
            return [dict(id=v.id, patient_id=patient_id, timestamp=v.timestamp,
                         patient_name=v.patient_name, age=v.age, gender=v.gender,
                         systolic_bp=v.systolic_bp, diastolic_bp=v.diastolic_bp,
                         temperature_c=v.temperature_c, pulse_rate=v.pulse_rate,
                         diagnoses=diagnoses.get(v.id, [v.primary_diagnosis]),
                         admission=v.is_admission, referral=bool(v.is_referral),
                         incident=bool(v.is_incident), incident_type=v.incident_type,
                         notes=v.clinical_notes) for v, patient_id in rows]
