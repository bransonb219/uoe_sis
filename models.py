"""
University of Edenberg SIS - Database Models
SQLAlchemy ORM definitions for all entities
"""
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean,
    DateTime, ForeignKey, Text, Enum as SAEnum, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
import enum

Base = declarative_base()


# ─────────────────────────── Enums ───────────────────────────

class Gender(str, enum.Enum):
    MALE = "Male"
    FEMALE = "Female"


class StudentStatus(str, enum.Enum):
    ACTIVE = "Active"
    SUSPENDED = "Suspended"
    GRADUATED = "Graduated"
    WITHDRAWN = "Withdrawn"
    DEFERRED = "Deferred"


class EnrolmentStatus(str, enum.Enum):
    ENROLLED = "Enrolled"
    COMPLETED = "Completed"
    WITHDRAWN = "Withdrawn"
    DEFERRED = "Deferred"


class ResultStatus(str, enum.Enum):
    PASS = "Pass"
    FAIL = "Fail"
    SUPPLEMENTARY = "Supplementary"        # Score 40–49: sit supp exam
    PROCEED_REPEAT = "Proceed but Repeat"  # Fail ≥2 courses this semester
    INCOMPLETE = "Incomplete"
    PENDING = "Pending"


class ExamType(str, enum.Enum):
    REGISTRATION = "Registration"       # requires 40% payment
    MID_SEMESTER = "Mid-Semester"       # requires 40% payment
    FINAL = "Final"                     # requires 70% payment
    SUPPLEMENTARY = "Supplementary"     # special sitting


class PaymentStatus(str, enum.Enum):
    PENDING = "Pending"
    COMPLETED = "Completed"
    PARTIAL = "Partial"
    OVERDUE = "Overdue"
    WAIVED = "Waived"


class UserRole(str, enum.Enum):
    STUDENT = "Student"
    LECTURER = "Lecturer"
    REGISTRAR = "Registrar"
    FINANCE = "Finance"
    ADMIN = "Admin"
    # Administrative support staff under the Registrar's office — can view
    # and edit student bio/registration data, but deliberately excluded from
    # cohort promotion, registration period control, and results publication.
    ADMIN_SUPPORT = "Admin Support"


class PublicationStatus(str, enum.Enum):
    DRAFT = "Draft"
    PUBLISHED = "Published"
    WITHHELD = "Withheld"


class ProgrammeLevel(str, enum.Enum):
    """
    Determines which results weighting scheme applies.
      DIPLOMA and UNDERGRADUATE: CA1 10% + CA2 10% + Mid-Sem 20% + Final 60%
      POSTGRADUATE:              CA1 25% + CA2 25% + Final 50% (no Mid-Sem)
    Diploma is tracked as its own level even though it currently uses the
    same weighting as Undergraduate.
    """
    DIPLOMA = "Diploma"
    UNDERGRADUATE = "Undergraduate"
    POSTGRADUATE = "Postgraduate"


class ModeOfStudy(str, enum.Enum):
    FULL_TIME = "Full-Time"
    ODEL = "ODeL"


# ─────────────────────────── Intake / cohort tracking ──────────────────────
# An Intake is the cohort a student first enrolled with — permanent, never
# changes. Separate from year_of_study/current_semester, which move forward
# as the student progresses. IntakeProgress is the canonical (intake,
# year_of_study, semester_of_study) -> academic_year mapping, set once by
# the Registrar per cohort-step via the "Promote Cohort" action — this is
# what lets the system derive the academic year for a cohort's progress
# logically instead of staff retyping/reselecting it per student.

class Intake(Base):
    __tablename__ = "intakes"
    id = Column(Integer, primary_key=True)
    code = Column(String(30), unique=True, nullable=False)
    label = Column(String(200), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AcademicYear(Base):
    """Managed lookup list for academic year dropdowns system-wide."""
    __tablename__ = "academic_years"
    id = Column(Integer, primary_key=True)
    label = Column(String(20), unique=True, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class IntakeProgress(Base):
    """
    One row per (intake, year_of_study, semester_of_study) progression step.
    academic_year_id resolves what calendar academic year that step occurred
    in — set once when the Registrar promotes the cohort into that step.
    """
    __tablename__ = "intake_progress"
    id = Column(Integer, primary_key=True)
    intake_id = Column(Integer, ForeignKey("intakes.id"), nullable=False)
    year_of_study = Column(Integer, nullable=False)
    semester_of_study = Column(Integer, nullable=False)
    academic_year_id = Column(Integer, ForeignKey("academic_years.id"), nullable=False)
    is_current = Column(Boolean, default=False)
    started_at = Column(DateTime, default=datetime.utcnow)

    intake = relationship("Intake")
    academic_year = relationship("AcademicYear")
    __table_args__ = (UniqueConstraint("intake_id", "year_of_study", "semester_of_study"),)


# ─────────────────────────── Models ───────────────────────────

class Programme(Base):
    __tablename__ = "programmes"
    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    department = Column(String(100))
    faculty = Column(String(100))
    level = Column(SAEnum(ProgrammeLevel), default=ProgrammeLevel.UNDERGRADUATE, nullable=False)
    duration_years = Column(Integer, default=3)
    total_credits = Column(Integer, default=360)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    students = relationship("Student", back_populates="programme")
    courses = relationship("Course", back_populates="programme")
    fee_structures = relationship("FeeStructure", back_populates="programme")


class FeeStructure(Base):
    __tablename__ = "fee_structures"
    id = Column(Integer, primary_key=True)
    programme_id = Column(Integer, ForeignKey("programmes.id"), nullable=False)
    academic_year = Column(String(20), nullable=False)
    semester = Column(Integer, nullable=False)
    mode_of_study = Column(SAEnum(ModeOfStudy), default=ModeOfStudy.FULL_TIME, nullable=False)
    total_fee = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    programme = relationship("Programme", back_populates="fee_structures")
    __table_args__ = (UniqueConstraint("programme_id", "academic_year", "semester", "mode_of_study"),)


class Student(Base):
    __tablename__ = "students"
    id = Column(Integer, primary_key=True)
    student_number = Column(String(20), unique=True, nullable=False)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    other_names = Column(String(100))
    gender = Column(SAEnum(Gender))
    date_of_birth = Column(DateTime)
    national_id = Column(String(50))
    nationality = Column(String(50))
    marital_status = Column(String(30))
    next_of_kin_name = Column(String(150))
    next_of_kin_phone = Column(String(30))
    email = Column(String(200))
    phone = Column(String(30))
    address = Column(Text)
    programme_id = Column(Integer, ForeignKey("programmes.id"))
    intake_id = Column(Integer, ForeignKey("intakes.id"), nullable=True)
    year_of_study = Column(Integer, default=1)
    current_semester = Column(Integer, default=1)
    academic_year = Column(String(20))
    mode_of_study = Column(SAEnum(ModeOfStudy), default=ModeOfStudy.FULL_TIME)
    # Net adjustment vs the standard FeeStructure-computed total — covers
    # individual scholarships/discounts or additional charges that don't fit
    # the shared per-programme/year/semester/mode fee structure. Positive =
    # charged more than standard; negative = discount. Defaults to 0 (no
    # adjustment) for students without any special fee arrangement.
    fee_adjustment = Column(Float, default=0.0)
    status = Column(SAEnum(StudentStatus), default=StudentStatus.ACTIVE)
    photo_path = Column(String(300))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    programme = relationship("Programme", back_populates="students")
    intake = relationship("Intake")
    registrations = relationship("Registration", back_populates="student")
    payments = relationship("Payment", back_populates="student")
    user = relationship("User", back_populates="student", uselist=False)

    @property
    def full_name(self):
        parts = [self.first_name]
        if self.other_names:
            parts.append(self.other_names)
        parts.append(self.last_name)
        return " ".join(parts)


class Course(Base):
    __tablename__ = "courses"
    id = Column(Integer, primary_key=True)
    code = Column(String(20), nullable=False)
    name = Column(String(200), nullable=False)
    programme_id = Column(Integer, ForeignKey("programmes.id"))
    # semester: 1 or 2 for a course tied to a single semester.
    # 0 is a sentinel meaning "offered in either semester" — used for
    # electives that don't belong to one fixed semester. Any code that
    # filters/queries Course by a specific semester must also match
    # semester == 0 so these electives surface regardless of which
    # semester is currently selected. See utils/results_logic.py
    # course_matches_semester() for the shared helper that does this.
    semester = Column(Integer, nullable=False)
    year_level = Column(Integer, default=1)
    credits = Column(Integer, default=3)
    is_core = Column(Boolean, default=True)
    lecturer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    programme = relationship("Programme", back_populates="courses")
    lecturer = relationship("User", foreign_keys=[lecturer_id])
    student_courses = relationship("StudentCourse", back_populates="course")
    __table_args__ = (UniqueConstraint("code", "programme_id", "semester"),)


class Registration(Base):
    __tablename__ = "registrations"
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    academic_year = Column(String(20), nullable=False)
    semester = Column(Integer, nullable=False)
    year_of_study = Column(Integer, nullable=False)
    status = Column(SAEnum(EnrolmentStatus), default=EnrolmentStatus.ENROLLED)
    registered_at = Column(DateTime, default=datetime.utcnow)
    registered_by = Column(Integer, ForeignKey("users.id"))

    student = relationship("Student", back_populates="registrations")
    student_courses = relationship("StudentCourse", back_populates="registration")
    __table_args__ = (UniqueConstraint("student_id", "academic_year", "semester"),)


class StudentCourse(Base):
    __tablename__ = "student_courses"
    id = Column(Integer, primary_key=True)
    registration_id = Column(Integer, ForeignKey("registrations.id"), nullable=False)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False)
    is_repeat = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    registration = relationship("Registration", back_populates="student_courses")
    course = relationship("Course", back_populates="student_courses")
    result = relationship("Result", back_populates="student_course", uselist=False)
    exemption = relationship("Exemption", back_populates="student_course", uselist=False)
    __table_args__ = (UniqueConstraint("registration_id", "course_id"),)


class Exemption(Base):
    """
    Marks a StudentCourse as exempted rather than sat. A StudentCourse has
    EITHER a Result (sat the course) OR an Exemption (waived) — never both.
    Exempted courses are excluded from GPA and from total credits required
    (pure waiver, no credit transfer), and are shown distinctly on result
    slips/transcripts.
    """
    __tablename__ = "exemptions"
    id = Column(Integer, primary_key=True)
    student_course_id = Column(Integer, ForeignKey("student_courses.id"), nullable=False, unique=True)
    reason = Column(String(300))
    granted_by = Column(Integer, ForeignKey("users.id"))
    granted_at = Column(DateTime, default=datetime.utcnow)

    student_course = relationship("StudentCourse", back_populates="exemption")
    granter = relationship("User")


class Result(Base):
    __tablename__ = "results"
    id = Column(Integer, primary_key=True)
    student_course_id = Column(Integer, ForeignKey("student_courses.id"), nullable=False, unique=True)
    # Component scores
    ca1_score = Column(Float)  # Continuous Assessment 1
    ca2_score = Column(Float)  # Continuous Assessment 2
    mid_sem_score = Column(Float)  # Mid-Semester (Diploma/Undergrad only)
    final_score = Column(Float)  # Final Exam
    supp_score = Column(Float)  # Supplementary Exam
    # Computed fields
    total_score = Column(Float)        # Weighted total
    grade = Column(String(5))
    grade_point = Column(Float)
    status = Column(SAEnum(ResultStatus), default=ResultStatus.PENDING)
    remarks = Column(String(200))
    # Publication control
    publication_status = Column(SAEnum(PublicationStatus), default=PublicationStatus.DRAFT)
    published_at = Column(DateTime)
    published_by = Column(Integer, ForeignKey("users.id"))
    # Audit
    entered_by = Column(Integer, ForeignKey("users.id"))
    entered_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    student_course = relationship("StudentCourse", back_populates="result")
    publisher = relationship("User", foreign_keys=[published_by])
    enterer = relationship("User", foreign_keys=[entered_by])


class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    academic_year = Column(String(20), nullable=False)
    semester = Column(Integer, nullable=False)
    amount = Column(Float, nullable=False)
    payment_date = Column(DateTime, default=datetime.utcnow)
    reference = Column(String(100))
    method = Column(String(50))       # Cash, Bank Transfer, Mobile Money
    status = Column(SAEnum(PaymentStatus), default=PaymentStatus.COMPLETED)
    received_by = Column(Integer, ForeignKey("users.id"))
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    student = relationship("Student", back_populates="payments")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(200), nullable=False)
    role = Column(SAEnum(UserRole), nullable=False)
    first_name = Column(String(100))
    last_name = Column(String(100))
    email = Column(String(200))
    is_active = Column(Boolean, default=True)
    last_login = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    student_id = Column(Integer, ForeignKey("students.id"), nullable=True)
    student = relationship("Student", back_populates="user", foreign_keys=[student_id])


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    action = Column(String(100), nullable=False)
    entity = Column(String(100))
    entity_id = Column(Integer)
    details = Column(Text)
    ip_address = Column(String(50))
    timestamp = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")


class ResultPublicationBatch(Base):
    """Tracks batch publication events for audit trail"""
    __tablename__ = "result_publication_batches"
    id = Column(Integer, primary_key=True)
    academic_year = Column(String(20), nullable=False)
    semester = Column(Integer, nullable=False)
    programme_id = Column(Integer, ForeignKey("programmes.id"), nullable=True)
    exam_type = Column(SAEnum(ExamType))
    total_published = Column(Integer, default=0)
    published_by = Column(Integer, ForeignKey("users.id"))
    published_at = Column(DateTime, default=datetime.utcnow)
    notes = Column(Text)

    programme = relationship("Programme")
    publisher = relationship("User")


class RegistrationPeriod(Base):
    """
    Controls whether self-service student registration is open, globally,
    for a given academic year + semester. Opened/closed by the Registrar
    or Admin. Students cannot self-register outside an open period,
    regardless of their payment status.
    """
    __tablename__ = "registration_periods"
    id = Column(Integer, primary_key=True)
    academic_year = Column(String(20), nullable=False)
    semester = Column(Integer, nullable=False)
    is_open = Column(Boolean, default=False)
    deadline_at = Column(DateTime, nullable=True)
    opened_at = Column(DateTime)
    closed_at = Column(DateTime)
    opened_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    opener = relationship("User")
    __table_args__ = (UniqueConstraint("academic_year", "semester"),)


class SystemSetting(Base):
    """Key-value store for institution-wide configuration."""
    __tablename__ = "system_settings"
    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(String(500), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    updater = relationship("User")

# ─────────────────────────── Engine / Session ───────────────────────────

def get_engine(db_path="sis_uoe.db", database_url=None):
    """
    Returns a SQLAlchemy engine. If database_url is given (e.g. a Postgres
    connection string from Streamlit secrets/env), connects to that instead
    of local SQLite — this is what makes the database persist across
    Streamlit Cloud restarts/redeploys, since the local filesystem there is
    ephemeral. db_path is only used for the SQLite fallback (local dev).
    """
    if database_url:
        return create_engine(database_url, echo=False, pool_pre_ping=True)
    return create_engine(f"sqlite:///{db_path}", echo=False, connect_args={"check_same_thread": False})


def get_session(engine):
    session = sessionmaker(bind=engine)
    return session()


def init_db(engine):
    Base.metadata.create_all(engine)
