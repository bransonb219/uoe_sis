"""
Seed the University of Edenberg SIS database with realistic demo data.
Run once on first launch.
"""
from datetime import datetime, date
from models import (
    Programme, FeeStructure, Student, Course, Registration,
    StudentCourse, Result, Payment, User, ResultStatus, PublicationStatus,
    Gender, StudentStatus, EnrolmentStatus, UserRole, PaymentStatus,
    ModeOfStudy, ProgrammeLevel, Intake, AcademicYear, IntakeProgress, Exemption
)
from utils.auth import hash_password
from utils.results_logic import compute_total_score, compute_grade, determine_status
import random


ACADEMIC_YEAR = "2024/2025"
SEMESTER = 1

# Mirrors migrate_intake.py — same cohort definitions, so seed/test data and
# the real migrated data follow the same intake/progress conventions.
INTAKES = [
    ("JAN2025", "Oct 2024 / Jan 2025 / Apr 2025 (merged intake)"),
    ("JUL2025", "Jul 2025 / Oct 2025 (merged intake)"),
    ("JAN2026", "Jan 2026 intake"),
    ("LEGACY", "Legacy / pre-October-2024"),
    ("UNCONFIRMED", "Not yet reconciled to a confirmed intake"),
]
ACADEMIC_YEARS = ["2024/2025", "2025/2026", "2026/2027"]
# (intake_code, year_of_study, semester_of_study, academic_year, is_current)
INTAKE_PROGRESS = [
    ("JAN2025", 1, 1, "2024/2025", False),
    ("JAN2025", 1, 2, "2024/2025", False),
    ("JAN2025", 2, 1, "2025/2026", True),
    ("JUL2025", 1, 1, "2025/2026", False),
    ("JUL2025", 1, 2, "2025/2026", True),
    ("JAN2026", 1, 1, "2025/2026", True),
]


def seed_all(session):
    if session.query(User).count() > 0:
        return  # Already seeded

    # ── Programmes ──────────────────────────────────────────
    programmes = [
        Programme(code="BCS", name="Bachelor of Computer Science", department="Computing",
                  faculty="Science & Technology", level=ProgrammeLevel.UNDERGRADUATE,
                  duration_years=3, total_credits=360),
        Programme(code="BBA", name="Bachelor of Business Administration", department="Business",
                  faculty="Commerce", level=ProgrammeLevel.UNDERGRADUATE,
                  duration_years=3, total_credits=360),
        Programme(code="BED", name="Bachelor of Education", department="Education",
                  faculty="Humanities", level=ProgrammeLevel.UNDERGRADUATE,
                  duration_years=4, total_credits=480),
        Programme(code="BNS", name="Bachelor of Nursing Science", department="Health",
                  faculty="Health Sciences", level=ProgrammeLevel.UNDERGRADUATE,
                  duration_years=4, total_credits=480),
        Programme(code="MBA", name="Master of Business Administration", department="Business",
                  faculty="Commerce", level=ProgrammeLevel.POSTGRADUATE,
                  duration_years=2, total_credits=120),
    ]
    session.add_all(programmes)
    session.flush()

    # ── Intakes / AcademicYears / IntakeProgress ─────────────
    intakes_by_code = {}
    for code, label in INTAKES:
        i = Intake(code=code, label=label)
        session.add(i)
        intakes_by_code[code] = i
    session.flush()

    ay_by_label = {}
    for label in ACADEMIC_YEARS:
        ay = AcademicYear(label=label)
        session.add(ay)
        ay_by_label[label] = ay
    session.flush()

    current_progress_by_intake = {}
    for code, yos, sos, ay_label, is_current in INTAKE_PROGRESS:
        ip = IntakeProgress(
            intake_id=intakes_by_code[code].id,
            year_of_study=yos,
            semester_of_study=sos,
            academic_year_id=ay_by_label[ay_label].id,
            is_current=is_current,
        )
        session.add(ip)
        if is_current:
            current_progress_by_intake[code] = (yos, sos, ay_label)
    session.flush()

    # ── Fee Structures — both FT and ODeL per programme/semester/year ───────
    # Covers 2024/2025 and 2025/2026 since cohorts' current steps span both.
    ft_fees = {"BCS": 8500, "BBA": 7800, "BED": 7200, "BNS": 9500, "MBA": 12500}
    odel_fees = {"BCS": 6000, "BBA": 5500, "BED": 5000, "BNS": 7000, "MBA": 9000}
    for prog in programmes:
        for ay_label in ("2024/2025", "2025/2026"):
            for sem in [1, 2]:
                session.add(FeeStructure(
                    programme_id=prog.id, academic_year=ay_label, semester=sem,
                    mode_of_study=ModeOfStudy.FULL_TIME, total_fee=ft_fees[prog.code]
                ))
                session.add(FeeStructure(
                    programme_id=prog.id, academic_year=ay_label, semester=sem,
                    mode_of_study=ModeOfStudy.ODEL, total_fee=odel_fees[prog.code]
                ))
    session.flush()

    # ── Staff Users ──────────────────────────────────────────
    staff = [
        User(username="admin", password_hash=hash_password("Admin@2024"),
             role=UserRole.ADMIN, first_name="System", last_name="Administrator",
             email="admin@edenberg.ac.zm", is_active=True),
        User(username="registrar", password_hash=hash_password("Reg@2024"),
             role=UserRole.REGISTRAR, first_name="Grace", last_name="Mwale",
             email="registrar@edenberg.ac.zm", is_active=True),
        User(username="finance", password_hash=hash_password("Fin@2024"),
             role=UserRole.FINANCE, first_name="Peter", last_name="Banda",
             email="finance@edenberg.ac.zm", is_active=True),
        User(username="dr.mulenga", password_hash=hash_password("Lec@2024"),
             role=UserRole.LECTURER, first_name="Charles", last_name="Mulenga",
             email="c.mulenga@edenberg.ac.zm", is_active=True),
        User(username="dr.tembo", password_hash=hash_password("Lec@2024"),
             role=UserRole.LECTURER, first_name="Ruth", last_name="Tembo",
             email="r.tembo@edenberg.ac.zm", is_active=True),
    ]
    session.add_all(staff)
    session.flush()

    lec1_id = staff[3].id
    lec2_id = staff[4].id

    # ── Courses (5 core per semester per programme, plus electives) ──────
    # Tuple shape: (code, name, semester, year_level, credits, is_core)
    # semester=0 is the "offered in either semester" sentinel for electives.
    course_templates = {
        "BCS": [
            ("BCS101", "Introduction to Programming", 1, 1, 4, True),
            ("BCS102", "Mathematics for Computing", 1, 1, 3, True),
            ("BCS103", "Computer Organisation", 1, 1, 3, True),
            ("BCS104", "Introduction to Databases", 1, 1, 3, True),
            ("BCS105", "Communication Skills", 1, 1, 2, True),
            ("BCS201", "Data Structures & Algorithms", 2, 1, 4, True),
            ("BCS202", "Operating Systems", 2, 1, 3, True),
            ("BCS203", "Web Technologies", 2, 1, 3, True),
            ("BCS204", "Statistics for Computing", 2, 1, 3, True),
            ("BCS205", "Technical Writing", 2, 1, 2, True),
            ("BCS210", "Mobile App Development", 0, 1, 3, False),
            ("BCS211", "Introduction to Cybersecurity", 1, 1, 3, False),
            ("BCS212", "Cloud Computing Fundamentals", 2, 1, 3, False),
            # Year 2 — exists to exercise the JAN2025 cohort (currently Year 2 Sem 1)
            ("BCS301", "Software Engineering", 1, 2, 4, True),
            ("BCS302", "Database Systems II", 1, 2, 3, True),
            ("BCS303", "Computer Networks", 1, 2, 3, True),
        ],
        "BBA": [
            ("BBA101", "Principles of Management", 1, 1, 3, True),
            ("BBA102", "Financial Accounting", 1, 1, 4, True),
            ("BBA103", "Business Communication", 1, 1, 3, True),
            ("BBA104", "Introduction to Economics", 1, 1, 3, True),
            ("BBA105", "Business Mathematics", 1, 1, 2, True),
            ("BBA201", "Marketing Management", 2, 1, 3, True),
            ("BBA202", "Cost Accounting", 2, 1, 4, True),
            ("BBA203", "Human Resource Management", 2, 1, 3, True),
            ("BBA204", "Business Law", 2, 1, 3, True),
            ("BBA205", "Entrepreneurship", 2, 1, 2, True),
            ("BBA210", "Digital Marketing", 0, 1, 3, False),
            ("BBA211", "Supply Chain Management", 1, 1, 3, False),
        ],
        "BED": [
            ("BED101", "Foundations of Education", 1, 1, 3, True),
            ("BED102", "Child Psychology", 1, 1, 3, True),
            ("BED103", "Curriculum Development", 1, 1, 3, True),
            ("BED104", "Teaching Methods", 1, 1, 4, True),
            ("BED105", "Educational Research", 1, 1, 2, True),
            ("BED210", "Special Needs Education", 0, 1, 3, False),
        ],
        "BNS": [
            ("BNS101", "Anatomy & Physiology", 1, 1, 4, True),
            ("BNS102", "Fundamentals of Nursing", 1, 1, 4, True),
            ("BNS103", "Medical Biochemistry", 1, 1, 3, True),
            ("BNS104", "Psychology in Healthcare", 1, 1, 3, True),
            ("BNS105", "Health Communication", 1, 1, 2, True),
            ("BNS210", "Community Health Nursing", 0, 1, 3, False),
        ],
        "MBA": [
            ("MBA101", "Managerial Economics", 1, 1, 3, True),
            ("MBA102", "Organisational Behaviour", 1, 1, 3, True),
            ("MBA103", "Financial Management", 1, 1, 3, True),
            ("MBA104", "Strategic Management", 1, 1, 3, True),
            ("MBA105", "Research Methods", 1, 1, 2, True),
            ("MBA201", "International Business", 2, 1, 3, True),
            ("MBA202", "Operations Management", 2, 1, 3, True),
            ("MBA203", "Corporate Governance", 2, 1, 3, True),
            ("MBA204", "Project Management", 2, 1, 3, True),
            ("MBA205", "Business Ethics", 2, 1, 2, True),
            ("MBA210", "Entrepreneurial Finance", 0, 2, 3, False),
        ],
    }

    prog_map = {p.code: p for p in programmes}
    all_courses = {}
    for code, templates in course_templates.items():
        prog = prog_map[code]
        for c_code, c_name, sem, yr, credits, is_core in templates:
            c = Course(code=c_code, name=c_name, programme_id=prog.id,
                       semester=sem, year_level=yr, credits=credits, is_core=is_core,
                       lecturer_id=lec1_id if sem in (0, 1) else lec2_id)
            session.add(c)
            all_courses[c_code] = c
    session.flush()

    # ── Students (10 per programme) ──────────────────────────
    first_names = ["Alice", "Bob", "Clara", "David", "Esther", "Frank", "Grace", "Henry",
                   "Irene", "James", "Karen", "Luka", "Mary", "Nathan", "Olivia", "Paul",
                   "Queen", "Robert", "Sarah", "Thomas"]
    last_names = ["Banda", "Chanda", "Daka", "Mwale", "Phiri", "Soko", "Tembo",
                  "Zulu", "Mulenga", "Lungu", "Nkonde", "Mwanza", "Kasonde", "Mumba"]

    random.seed(42)
    student_users = []
    all_students = []

    # Round-robin students across the 3 confirmed cohorts so all three
    # progression states (Y2S1, Y1S2, Y1S1) get exercised by test data.
    cohort_cycle = ["JAN2025", "JUL2025", "JAN2026"]

    for prog in programmes:
        for i in range(10):
            fn = random.choice(first_names)
            ln = random.choice(last_names)
            yr = random.randint(2000, 2004)
            snum = f"{prog.code}{2024:04d}{i+1:03d}"
            mode = ModeOfStudy.ODEL if i % 3 == 0 else ModeOfStudy.FULL_TIME
            cohort_code = cohort_cycle[i % len(cohort_cycle)]
            cohort_yos, cohort_sos, cohort_ay = current_progress_by_intake[cohort_code]
            s = Student(
                student_number=snum,
                first_name=fn, last_name=ln,
                gender=random.choice([Gender.MALE, Gender.FEMALE]),
                date_of_birth=datetime(yr, random.randint(1, 12), random.randint(1, 28)),
                email=f"{fn.lower()}.{ln.lower()}{i}@student.edenberg.ac.zm",
                phone=f"+2609{random.randint(10000000, 99999999)}",
                programme_id=prog.id,
                intake_id=intakes_by_code[cohort_code].id,
                year_of_study=cohort_yos,
                current_semester=cohort_sos,
                academic_year=cohort_ay,
                mode_of_study=mode,
                status=StudentStatus.ACTIVE,
            )
            session.add(s)
            session.flush()

            u = User(
                username=snum.lower(),
                password_hash=hash_password("Student@2026"),
                role=UserRole.STUDENT,
                first_name=fn, last_name=ln,
                email=s.email,
                is_active=True,
                student_id=s.id
            )
            session.add(u)
            student_users.append(u)
            all_students.append(s)

    session.flush()

    # ── Registrations, Payments, Results ────────────────────
    from utils.results_logic import course_matches_semester

    for idx, student in enumerate(all_students):
        prog_code = next(p.code for p in programmes if p.id == student.programme_id)
        sem = student.current_semester or 1
        ay = student.academic_year or ACADEMIC_YEAR

        # Use course_matches_semester so electives marked semester=0
        # ("both semesters") are correctly included alongside core courses,
        # instead of being silently excluded by a raw equality check.
        # Courses are also matched to the student's OWN year_of_study, since
        # cohorts now sit at different years (e.g. JAN2025 is Year 2).
        eligible_courses = [c for c in all_courses.values()
                            if c.programme_id == student.programme_id
                            and c.year_level == student.year_of_study
                            and course_matches_semester(c.semester, sem)]

        if not eligible_courses:
            continue

        # Registration
        reg = Registration(
            student_id=student.id,
            academic_year=ay,
            semester=sem,
            year_of_study=student.year_of_study,
            status=EnrolmentStatus.ENROLLED,
            registered_by=staff[1].id
        )
        session.add(reg)
        session.flush()

        # Payment — vary amounts
        pct_paid = random.choice([0.30, 0.45, 0.60, 0.75, 0.85, 1.0, 1.0, 1.0])
        fs = session.query(FeeStructure).filter_by(
            programme_id=student.programme_id,
            academic_year=ay, semester=sem,
            mode_of_study=student.mode_of_study,
        ).first()
        if fs:
            amount = fs.total_fee * pct_paid
            session.add(Payment(
                student_id=student.id,
                academic_year=ay,
                semester=sem,
                amount=amount,
                reference=f"PAY{random.randint(100000, 999999)}",
                method=random.choice(["Bank Transfer", "Mobile Money", "Cash"]),
                status=PaymentStatus.COMPLETED,
                received_by=staff[2].id
            ))

        prog = prog_map[prog_code]
        prog_level = prog.level.value if prog.level else ProgrammeLevel.UNDERGRADUATE.value

        for course_idx, course in enumerate(eligible_courses):
            sc = StudentCourse(registration_id=reg.id, course_id=course.id)
            session.add(sc)
            session.flush()

            # Every 25th student is exempted from their first eligible
            # course, to exercise the Exemption pathway end-to-end.
            if idx % 25 == 0 and course_idx == 0:
                session.add(Exemption(
                    student_course_id=sc.id,
                    reason="Credit transfer from prior qualification",
                    granted_by=staff[1].id,
                ))
                continue

            # Generate scores — some fail, some supp
            outcome = random.choices(
                ["pass", "supp", "fail"], weights=[70, 15, 15]
            )[0]

            if outcome == "pass":
                ca1 = round(random.uniform(50, 90), 1)
                ca2 = round(random.uniform(50, 90), 1)
                mid = round(random.uniform(50, 90), 1)
                final = round(random.uniform(50, 90), 1)
                supp = None
            elif outcome == "supp":
                ca1 = round(random.uniform(30, 50), 1)
                ca2 = round(random.uniform(30, 50), 1)
                mid = round(random.uniform(30, 50), 1)
                final = round(random.uniform(30, 50), 1)
                supp = round(random.uniform(45, 70), 1)
            else:
                ca1 = round(random.uniform(10, 38), 1)
                ca2 = round(random.uniform(10, 38), 1)
                mid = round(random.uniform(10, 38), 1)
                final = round(random.uniform(10, 38), 1)
                supp = None

            total = compute_total_score(ca1, ca2, mid, final, prog_level, supp)
            grade, gp = compute_grade(total)
            status = determine_status(total, supp)

            r = Result(
                student_course_id=sc.id,
                ca1_score=ca1,
                ca2_score=ca2,
                mid_sem_score=mid,
                final_score=final,
                supp_score=supp,
                total_score=total,
                grade=grade,
                grade_point=gp,
                status=status,
                publication_status=PublicationStatus.PUBLISHED if random.random() > 0.2 else PublicationStatus.DRAFT,
                published_at=datetime.utcnow() if random.random() > 0.2 else None,
                published_by=staff[1].id,
                entered_by=staff[3].id,
            )
            session.add(r)

    session.commit()
    print("✅ Seed data created successfully.")
