"""Clinic persistence. Existing tables and historical rows are never rewritten by startup."""
from datetime import datetime, timezone, date
import json
from sqlalchemy import (Boolean, Column, Date, DateTime, Float, ForeignKey, Integer,
                        String, Text, create_engine, event, select, update)
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()
ACTIVE = ('In consultation', 'Observation', 'Short-day admission')
CLOSED = ('Discharged', 'Referred')
STATUSES = ACTIVE + CLOSED
TRIAGE = ('Not assessed', 'Routine', 'Urgent', 'Emergency')
GENDERS = ('Male', 'Female')


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def as_utc(value):
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


class PatientVisit(Base):
    __tablename__ = 'patient_visits'
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
    is_admission = Column(String(50), default='No Entry')
    is_referral = Column(Integer, default=0)
    is_incident = Column(Integer, default=0)
    incident_type = Column(String(50))
    clinical_notes = Column(Text)


class Patient(Base):
    __tablename__ = 'patients'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    gender = Column(String(20), nullable=False)
    employee_id = Column(String(80), unique=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class VisitPatient(Base):
    __tablename__ = 'visit_patients'
    visit_id = Column(Integer, ForeignKey('patient_visits.id'), primary_key=True)
    patient_id = Column(Integer, ForeignKey('patients.id'), nullable=False, index=True)


class VisitDiagnosis(Base):
    __tablename__ = 'visit_diagnoses'
    visit_id = Column(Integer, ForeignKey('patient_visits.id'), primary_key=True)
    position = Column(Integer, primary_key=True)
    diagnosis = Column(String(100), nullable=False)


class VisitNote(Base):
    __tablename__ = 'visit_notes'
    id = Column(Integer, primary_key=True)
    visit_id = Column(Integer, ForeignKey('patient_visits.id'), nullable=False, index=True)
    timestamp = Column(DateTime, default=utc_now, nullable=False)
    author = Column(String(100), nullable=False)
    text = Column(Text, nullable=False)


# Version 2 companion tables. No ALTER/DROP or automatic patient matching.
class PatientProfile(Base):
    __tablename__ = 'patient_profiles'
    patient_id = Column(Integer, ForeignKey('patients.id'), primary_key=True)
    age = Column(Integer)
    age_recorded_on = Column(Date)
    department = Column(String(120), nullable=False, default='')
    contact = Column(String(180), nullable=False, default='')
    emergency_contact = Column(String(180), nullable=False, default='')
    updated_at = Column(DateTime, default=utc_now, nullable=False)


class EncounterDetails(Base):
    __tablename__ = 'encounter_details'
    visit_id = Column(Integer, ForeignKey('patient_visits.id'), primary_key=True)
    # At most one currently open encounter per patient; null for closed encounters.
    active_patient_id = Column(Integer, ForeignKey('patients.id'), nullable=True, unique=True)
    triage = Column(String(30), nullable=False)
    respiratory_rate = Column(Integer)
    spo2 = Column(Float)
    chief_complaint = Column(Text, nullable=False)
    observations = Column(Text, nullable=False, default='')
    treatment = Column(Text, nullable=False, default='')
    department = Column(String(120), nullable=False, default='')
    status = Column(String(30), nullable=False)
    recorded_by = Column(String(100), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    request_key = Column(String(36), nullable=False, unique=True)


class Bed(Base):
    __tablename__ = 'clinic_beds'
    id = Column(Integer, primary_key=True)
    name = Column(String(60), nullable=False, unique=True)
    occupied_visit_id = Column(Integer, ForeignKey('patient_visits.id'), unique=True, nullable=True)


class CareEvent(Base):
    __tablename__ = 'care_events'
    id = Column(Integer, primary_key=True)
    visit_id = Column(Integer, ForeignKey('patient_visits.id'), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, default=utc_now)
    status = Column(String(30), nullable=False)
    bed_name = Column(String(60), nullable=False, default='')
    referral_to = Column(String(180), nullable=False, default='')
    note = Column(Text, nullable=False, default='')
    author = Column(String(100), nullable=False)


class AssessmentRevision(Base):
    __tablename__ = 'assessment_revisions'
    id = Column(Integer, primary_key=True)
    visit_id = Column(Integer, ForeignKey('patient_visits.id'), nullable=False, index=True)
    timestamp = Column(DateTime, default=utc_now, nullable=False)
    author = Column(String(100), nullable=False)
    reason = Column(Text, nullable=False)
    previous_json = Column(Text, nullable=False)
    snapshot_json = Column(Text, nullable=False)


class WorkplaceIncident(Base):
    __tablename__ = 'workplace_incidents'
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey('patients.id'), nullable=False, index=True)
    occurred_at = Column(DateTime, nullable=False)
    recorded_at = Column(DateTime, default=utc_now, nullable=False)
    injury_type = Column(String(120), nullable=False)
    department = Column(String(120), nullable=False)
    is_lti = Column(Boolean, nullable=False, default=False)
    description = Column(Text, nullable=False, default='')
    author = Column(String(100), nullable=False)
    request_key = Column(String(36), nullable=False, unique=True)


class IncidentVisit(Base):
    __tablename__ = 'incident_visits'
    visit_id = Column(Integer, ForeignKey('patient_visits.id'), primary_key=True)
    incident_id = Column(Integer, ForeignKey('workplace_incidents.id'), nullable=False, index=True)


class IncidentUpdate(Base):
    __tablename__ = 'incident_updates'
    id = Column(Integer, primary_key=True)
    incident_id = Column(Integer, ForeignKey('workplace_incidents.id'), nullable=False)
    timestamp = Column(DateTime, default=utc_now, nullable=False)
    is_lti = Column(Boolean, nullable=False)
    author = Column(String(100), nullable=False)
    note = Column(Text, nullable=False)


def make_engine(url):
    if url.startswith('postgres://'):
        url = 'postgresql+psycopg2://' + url[len('postgres://'):]
    elif url.startswith('postgresql://'):
        url = 'postgresql+psycopg2://' + url[len('postgresql://'):]
    parsed = make_url(url)
    options = dict(pool_pre_ping=True, pool_recycle=300)
    if parsed.get_backend_name() == 'sqlite':
        options['connect_args'] = {'check_same_thread': False, 'timeout': 20}
    elif parsed.get_backend_name() == 'postgresql':
        # Retain stricter SSL preferences, but never disable TLS.
        sslmode = parsed.query.get('sslmode', 'require')
        if sslmode not in ('require', 'verify-ca', 'verify-full'):
            raise ValueError('PostgreSQL must use sslmode=require or stricter.')
        options.update(pool_size=5, max_overflow=5, pool_timeout=30,
                       connect_args={'sslmode': sslmode, 'connect_timeout': 15})
    else:
        raise ValueError('Use PostgreSQL / Neon or SQLite.')
    engine = create_engine(url, **options)
    if parsed.get_backend_name() == 'sqlite':
        @event.listens_for(engine, 'connect')
        def foreign_keys(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
    return engine


def file_number(patient_id):
    return f'CL-{patient_id:06d}'


def text_value(value, label, limit=None, required=False):
    value = str(value or '').strip()
    if required and not value:
        raise ValueError(f'Enter {label}.')
    if limit and len(value) > limit:
        raise ValueError(f'{label.capitalize()} must be {limit} characters or fewer.')
    return value


def clean_diagnoses(selected, custom='', required=True):
    values, seen = [], set()
    for value in [*selected, *custom.splitlines()]:
        value = text_value(value, 'diagnosis', 100)
        if value and value.casefold() not in seen:
            values.append(value); seen.add(value.casefold())
    if required and not values:
        raise ValueError('Select or enter at least one diagnosis or presentation.')
    return values


def validate_vitals(data):
    ranges = {'systolic_bp': (1, 350), 'diastolic_bp': (1, 250),
              'temperature_c': (20, 50), 'pulse_rate': (0, 350),
              'respiratory_rate': (0, 100), 'spo2': (0, 100)}
    for key, (low, high) in ranges.items():
        value = data.get(key)
        if value is not None and not low <= value <= high:
            raise ValueError(f'Check {key.replace("_", " ")}: accepted entry range is {low}–{high}.')
    sys, dia = data.get('systolic_bp'), data.get('diastolic_bp')
    if (sys is None) != (dia is None):
        raise ValueError('Enter both blood pressure readings, or leave both blank.')
    if sys is not None and sys <= dia:
        raise ValueError('Check blood pressure: systolic must be greater than diastolic.')


class ClinicStore:
    def __init__(self, engine):
        Base.metadata.create_all(engine)
        self.engine = engine
        self.sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def patients(self):
        with self.sessions() as db:
            rows = db.execute(select(Patient, PatientProfile).outerjoin(
                PatientProfile, Patient.id == PatientProfile.patient_id).order_by(Patient.name, Patient.id))
            return [dict(id=p.id, name=p.name, gender=p.gender, employee_id=p.employee_id,
                         age=x.age if x else None, age_recorded_on=x.age_recorded_on if x else None,
                         department=x.department if x else '', contact=x.contact if x else '',
                         emergency_contact=x.emergency_contact if x else '') for p, x in rows]

    def register_patient(self, name, gender, employee_id='', age=None, department='', contact='', emergency_contact=''):
        name = text_value(name, 'patient name', 100, True)
        reference = text_value(employee_id, 'employee ID', 80).upper() or None
        if gender not in GENDERS: raise ValueError('Choose a valid gender entry.')
        if age is not None and not 0 <= age <= 120: raise ValueError('Age must be 0–120.')
        with self.sessions.begin() as db:
            # Check case-insensitively while preserving historical reference spelling.
            from sqlalchemy import func
            if reference and db.scalar(select(Patient.id).where(func.lower(Patient.employee_id) == reference.lower())):
                raise ValueError('That employee ID already has a patient file.')
            p = Patient(name=name, gender=gender, employee_id=reference)
            db.add(p); db.flush()
            db.add(PatientProfile(patient_id=p.id, age=age, age_recorded_on=date.today() if age is not None else None,
                                  department=text_value(department, 'department', 120),
                                  contact=text_value(contact, 'contact details', 180),
                                  emergency_contact=text_value(emergency_contact, 'emergency contact', 180)))
            return p.id

    def update_profile(self, patient_id, age, department, contact, emergency_contact=''):
        if age is not None and not 0 <= age <= 120: raise ValueError('Age must be 0–120.')
        with self.sessions.begin() as db:
            if not db.get(Patient, patient_id): raise ValueError('Patient file not found.')
            profile = db.get(PatientProfile, patient_id)
            if profile is None:
                profile = PatientProfile(patient_id=patient_id); db.add(profile)
            profile.age = age
            profile.age_recorded_on = date.today() if age is not None else None
            profile.department = text_value(department, 'department', 120)
            profile.contact = text_value(contact, 'contact details', 180)
            profile.emergency_contact = text_value(emergency_contact, 'emergency contact', 180)
            profile.updated_at = utc_now()

    def _claim_bed(self, db, visit_id, bed_id, status):
        if bed_id is not None and status not in ('Observation', 'Short-day admission'):
            raise ValueError('Beds can be assigned only to observation or short-day admission.')
        current = db.scalar(select(Bed).where(Bed.occupied_visit_id == visit_id))
        if bed_id is not None:
            target = db.get(Bed, bed_id)
            if target is None: raise ValueError('Selected bed no longer exists.')
            if not current or current.id != bed_id:
                changed = db.execute(update(Bed).where(Bed.id == bed_id, Bed.occupied_visit_id.is_(None))
                                     .values(occupied_visit_id=visit_id)).rowcount
                if not changed: raise ValueError('That bed is occupied. Refresh and choose another bed.')
        if current and current.id != bed_id:
            current.occupied_visit_id = None
        return db.get(Bed, bed_id).name if bed_id is not None else ''

    def save_visit(self, patient_id, data, diagnoses, details, request_key, bed_id=None,
                   referral_to='', discharge_note='', incident_id=None):
        diagnoses = clean_diagnoses(diagnoses, required=False)
        validate_vitals({**data, **details})
        age = data.get('age')
        if age is None or not 0 <= age <= 120: raise ValueError('Enter age at this visit (0–120 years).')
        stamp = as_utc(data.get('timestamp') or utc_now())
        if stamp > utc_now(): raise ValueError('Visit date and time cannot be in the future.')
        status, triage = details.get('status'), details.get('triage')
        if status not in STATUSES or triage not in TRIAGE: raise ValueError('Choose valid triage and visit status.')
        author = text_value(details.get('recorded_by'), 'recorded by', 100, True)
        complaint = text_value(details.get('chief_complaint'), 'chief complaint', required=True)
        referral_to = text_value(referral_to, 'referral destination', 180, status == 'Referred')
        try:
            with self.sessions.begin() as db:
                existing = db.scalar(select(EncounterDetails).where(EncounterDetails.request_key == request_key))
                if existing: return existing.visit_id
                p = db.get(Patient, patient_id)
                if not p: raise ValueError('Patient file not found.')
                if db.scalar(select(EncounterDetails.visit_id).where(EncounterDetails.active_patient_id == patient_id)):
                    raise ValueError('This patient already has an open encounter. Complete it in Observation & active care.')
                profile = db.get(PatientProfile, patient_id)
                incident = db.get(WorkplaceIncident, incident_id) if incident_id else None
                if incident_id and (not incident or incident.patient_id != patient_id):
                    raise ValueError('Choose an incident belonging to this patient.')
                v = PatientVisit(timestamp=stamp, patient_name=p.name, gender=p.gender, age=age,
                                 **{k: data.get(k) for k in ('systolic_bp', 'diastolic_bp', 'temperature_c', 'pulse_rate')},
                                 primary_diagnosis=diagnoses[0] if diagnoses else 'Not yet recorded',
                                 is_admission='Short-Day Admission' if status == 'Short-day admission' else 'No Entry',
                                 is_referral=int(status == 'Referred'), is_incident=int(bool(incident)),
                                 incident_type=('Major (LTI)' if incident.is_lti else 'Minor Injury Case') if incident else None,
                                 clinical_notes='')
                db.add(v); db.flush()
                db.add(VisitPatient(visit_id=v.id, patient_id=p.id))
                db.add_all([VisitDiagnosis(visit_id=v.id, position=i, diagnosis=d) for i, d in enumerate(diagnoses)])
                db.add(EncounterDetails(visit_id=v.id, active_patient_id=p.id if status in ACTIVE else None,
                                        triage=triage, chief_complaint=complaint,
                                        respiratory_rate=details.get('respiratory_rate'), spo2=details.get('spo2'),
                                        observations=text_value(details.get('observations'), 'observations'),
                                        treatment=text_value(details.get('treatment'), 'treatment'),
                                        department=profile.department if profile else '', status=status,
                                        recorded_by=author, request_key=request_key))
                if incident: db.add(IncidentVisit(visit_id=v.id, incident_id=incident.id))
                bed_name = self._claim_bed(db, v.id, bed_id, status)
                db.add(CareEvent(visit_id=v.id, timestamp=stamp, status=status, bed_name=bed_name,
                                 referral_to=referral_to if status == 'Referred' else '',
                                 note=discharge_note.strip(), author=author))
                return v.id
        except IntegrityError:
            # A retry with the same request key is safe even after an uncertain commit.
            with self.sessions() as db:
                existing = db.scalar(select(EncounterDetails.visit_id).where(EncounterDetails.request_key == request_key))
                if existing: return existing
            raise ValueError('Another save changed this patient or bed. Refresh records before retrying.') from None

    def transition(self, visit_id, status, author, note, expected_version, bed_id=None, referral_to=''):
        if status not in STATUSES: raise ValueError('Choose a valid status.')
        author = text_value(author, 'recorded by', 100, True)
        note = text_value(note, 'care update or discharge/referral note', required=True)
        referral_to = text_value(referral_to, 'referral destination', 180, status == 'Referred')
        with self.sessions.begin() as db:
            detail = db.get(EncounterDetails, visit_id)
            if not detail or detail.status in CLOSED: raise ValueError('This encounter is already closed or is historical. Add a follow-up note instead.')
            # Compare-and-swap prevents stale forms silently overwriting another nurse's update.
            changed = db.execute(update(EncounterDetails).where(EncounterDetails.visit_id == visit_id,
                         EncounterDetails.version == expected_version, EncounterDetails.status.in_(ACTIVE))
                         .values(status=status, version=expected_version+1,
                                 active_patient_id=detail.active_patient_id if status in ACTIVE else None)).rowcount
            if not changed: raise ValueError('Another staff member updated this encounter. Refresh and review the latest status.')
            bed_name = self._claim_bed(db, visit_id, bed_id, status)
            db.add(CareEvent(visit_id=visit_id, status=status, author=author, note=note,
                             bed_name=bed_name, referral_to=referral_to if status == 'Referred' else ''))

    def add_bed(self, name):
        name = text_value(name, 'bed name', 60, True)
        with self.sessions.begin() as db:
            if db.scalar(select(Bed.id).where(Bed.name == name)): raise ValueError('That bed name already exists.')
            db.add(Bed(name=name))

    def revise_assessment(self, visit_id, values, diagnoses, author, reason, expected_version):
        author = text_value(author, 'recorded by', 100, True)
        reason = text_value(reason, 'assessment update reason', required=True)
        validate_vitals(values)
        if values.get('triage') not in TRIAGE: raise ValueError('Choose a valid triage category.')
        values = {**values, 'chief_complaint': text_value(values.get('chief_complaint'), 'chief complaint', required=True),
                  'diagnoses': clean_diagnoses(diagnoses, required=False)}
        fields = ('systolic_bp', 'diastolic_bp', 'temperature_c', 'pulse_rate', 'respiratory_rate',
                  'spo2', 'triage', 'chief_complaint', 'observations', 'treatment', 'diagnoses')
        latest = next((v for v in self.visits() if v['id'] == visit_id), None)
        if latest is None: raise ValueError('Encounter not found.')
        previous = {k: latest[k] for k in fields}
        current = {k: values.get(k) for k in fields}
        with self.sessions.begin() as db:
            changed = db.execute(update(EncounterDetails).where(EncounterDetails.visit_id == visit_id,
                EncounterDetails.version == expected_version, EncounterDetails.status.in_(ACTIVE))
                .values(version=expected_version+1)).rowcount
            if not changed: raise ValueError('The encounter changed or is closed. Refresh before updating it.')
            db.add(AssessmentRevision(visit_id=visit_id, author=author, reason=reason,
                   previous_json=json.dumps(previous, allow_nan=False), snapshot_json=json.dumps(current, allow_nan=False)))

    def assessments(self, visit_id):
        with self.sessions() as db:
            return [dict(timestamp=r.timestamp, author=r.author, reason=r.reason,
                         previous=json.loads(r.previous_json), current=json.loads(r.snapshot_json))
                    for r in db.scalars(select(AssessmentRevision).where(AssessmentRevision.visit_id == visit_id)
                                        .order_by(AssessmentRevision.timestamp, AssessmentRevision.id))]

    def beds(self):
        with self.sessions() as db:
            return [dict(id=b.id, name=b.name, visit_id=b.occupied_visit_id) for b in db.scalars(select(Bed).order_by(Bed.name))]

    def link_visit(self, visit_id, patient_id):
        with self.sessions.begin() as db:
            if not db.get(Patient, patient_id) or not db.get(PatientVisit, visit_id): raise ValueError('Patient or visit not found.')
            if db.get(VisitPatient, visit_id): raise ValueError('This visit is already linked.')
            db.add(VisitPatient(visit_id=visit_id, patient_id=patient_id))

    def add_note(self, visit_id, author, text):
        author = text_value(author, 'recorded by', 100, True)
        text = text_value(text, 'follow-up note', required=True)
        with self.sessions.begin() as db:
            if not db.get(PatientVisit, visit_id): raise ValueError('Visit not found.')
            db.add(VisitNote(visit_id=visit_id, author=author, text=text))

    def notes(self, visit_id):
        with self.sessions() as db:
            return db.scalars(select(VisitNote).where(VisitNote.visit_id == visit_id)
                              .order_by(VisitNote.timestamp, VisitNote.id)).all()

    def events(self, visit_id=None):
        with self.sessions() as db:
            q = select(CareEvent).order_by(CareEvent.timestamp, CareEvent.id)
            if visit_id is not None: q = q.where(CareEvent.visit_id == visit_id)
            return [dict(id=e.id, visit_id=e.visit_id, timestamp=e.timestamp, status=e.status,
                         bed_name=e.bed_name, referral_to=e.referral_to, note=e.note, author=e.author)
                    for e in db.scalars(q)]

    def visits(self):
        with self.sessions() as db:
            rows = db.execute(select(PatientVisit, VisitPatient.patient_id, EncounterDetails, Bed.name, IncidentVisit.incident_id)
                              .outerjoin(VisitPatient, PatientVisit.id == VisitPatient.visit_id)
                              .outerjoin(EncounterDetails, PatientVisit.id == EncounterDetails.visit_id)
                              .outerjoin(Bed, PatientVisit.id == Bed.occupied_visit_id)
                              .outerjoin(IncidentVisit, PatientVisit.id == IncidentVisit.visit_id)
                              .order_by(PatientVisit.timestamp.desc(), PatientVisit.id.desc())).all()
            dx = {}
            for d in db.scalars(select(VisitDiagnosis).order_by(VisitDiagnosis.position)):
                dx.setdefault(d.visit_id, []).append(d.diagnosis)
            revisions = {}
            for revision in db.scalars(select(AssessmentRevision).order_by(AssessmentRevision.timestamp, AssessmentRevision.id)):
                revisions[revision.visit_id] = json.loads(revision.snapshot_json)
            result = []
            for v, patient_id, x, bed_name, incident_id in rows:
                result.append(dict(id=v.id, patient_id=patient_id, timestamp=v.timestamp, patient_name=v.patient_name,
                    age=v.age, gender=v.gender, systolic_bp=v.systolic_bp, diastolic_bp=v.diastolic_bp,
                    temperature_c=v.temperature_c, pulse_rate=v.pulse_rate,
                    diagnoses=dx.get(v.id, [] if x or not v.primary_diagnosis else [v.primary_diagnosis]),
                    admission=v.is_admission, referral=bool(v.is_referral), incident=bool(v.is_incident) or bool(incident_id),
                    incident_type=v.incident_type, incident_id=incident_id, notes=v.clinical_notes,
                    respiratory_rate=x.respiratory_rate if x else None, spo2=x.spo2 if x else None,
                    triage=x.triage if x else 'Not recorded', chief_complaint=x.chief_complaint if x else '',
                    observations=x.observations if x else '', treatment=x.treatment if x else '',
                    department=x.department if x else '', status=x.status if x else 'Historical / outcome unconfirmed',
                    recorded_by=x.recorded_by if x else '', version=x.version if x else None,
                    bed_name=bed_name or '', modern=bool(x)))
                if v.id in revisions: result[-1].update(revisions[v.id])
            return result

    def record_incident(self, patient_id, occurred_at, injury_type, department, is_lti,
                        description, author, request_key, visit_id=None):
        occurred_at = as_utc(occurred_at)
        if occurred_at > utc_now(): raise ValueError('Incident time cannot be in the future.')
        injury_type = text_value(injury_type, 'injury type', 120, True)
        department = text_value(department, 'incident department', 120, True)
        author = text_value(author, 'recorded by', 100, True)
        with self.sessions.begin() as db:
            existing = db.scalar(select(WorkplaceIncident.id).where(WorkplaceIncident.request_key == request_key))
            if existing: return existing
            if not db.get(Patient, patient_id): raise ValueError('Patient file not found.')
            if visit_id:
                link = db.get(VisitPatient, visit_id)
                if not link or link.patient_id != patient_id: raise ValueError('Choose a visit linked to this patient.')
                if db.get(IncidentVisit, visit_id): raise ValueError('That visit is already linked to an incident.')
            item = WorkplaceIncident(patient_id=patient_id, occurred_at=occurred_at, injury_type=injury_type,
                     department=department, is_lti=bool(is_lti), description=description.strip(), author=author, request_key=request_key)
            db.add(item); db.flush()
            if visit_id: db.add(IncidentVisit(visit_id=visit_id, incident_id=item.id))
            return item.id

    def update_incident(self, incident_id, is_lti, author, note):
        author = text_value(author, 'recorded by', 100, True)
        note = text_value(note, 'reason or safety follow-up note', required=True)
        with self.sessions.begin() as db:
            item = db.get(WorkplaceIncident, incident_id)
            if not item: raise ValueError('Incident not found.')
            item.is_lti = bool(is_lti)
            db.add(IncidentUpdate(incident_id=incident_id, is_lti=bool(is_lti), author=author, note=note))

    def incidents(self):
        with self.sessions() as db:
            links, updates = {}, {}
            for x in db.scalars(select(IncidentVisit)):
                links.setdefault(x.incident_id, []).append(x.visit_id)
            for x in db.scalars(select(IncidentUpdate).order_by(IncidentUpdate.timestamp, IncidentUpdate.id)):
                updates.setdefault(x.incident_id, []).append(dict(timestamp=x.timestamp, is_lti=x.is_lti, author=x.author, note=x.note))
            return [dict(id=i.id, patient_id=i.patient_id, patient_name=p.name, occurred_at=i.occurred_at,
                         injury_type=i.injury_type, department=i.department, is_lti=i.is_lti,
                         description=i.description, author=i.author, visits=links.get(i.id, []), updates=updates.get(i.id, []))
                    for i, p in db.execute(select(WorkplaceIncident, Patient).join(Patient)
                                          .order_by(WorkplaceIncident.occurred_at.desc(), WorkplaceIncident.id.desc()))]
