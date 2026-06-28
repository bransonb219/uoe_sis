# University of Edenberg — Student Information System (SIS)

A Streamlit + SQLAlchemy + SQLite Student Information System covering student
records, course management, intake/cohort tracking, registration, results
entry/publication, fee management, reporting, and bulk data import.

---

## 1. Setup

```bash
# 1. Create and activate a virtual environment (recommended)
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the application
streamlit run app.py
```

The app will open at `http://localhost:8501`.

## 2. First Run — Demo Data vs. Real Data

By default `seed_all()` in `app.py` is **disabled** (commented out) — the app
expects a real database already populated with real institution data.

- **For a demo/test instance**: uncomment the `seed_all(db)` call in `app.py`
  and delete `sis_uoe.db` if it exists, then start the app. It seeds
  programmes, courses, students, staff, intakes, sample results, exemptions,
  and payments.
- **For going live with real data**: leave seeding disabled. Run
  `python init_admin.py` once against an empty `sis_uoe.db` to create the
  first Admin account, then build out Programmes/Fee Structures/Courses/
  Students either through the UI or via **Data Import (ETL)**.

### Demo credentials (only valid when seeded)

| Role | Username | Password |
|---|---|---|
| Admin | `admin` | `Admin@2024` |
| Registrar | `registrar` | `Reg@2024` |
| Finance | `finance` | `Fin@2024` |
| Lecturer | `dr.mulenga` / `dr.tembo` | `Lec@2024` |
| Student | lowercase student number, e.g. `bcs2024001` | `Student@2026` |

**Change every default password before going live.** Student accounts share
a default password until they log in and change it — see Settings → Staff
Users for the password-change flow.

## 3. University Logo

`assets/uoelogo.png` ships with a placeholder crest. Replace it with your
own PNG (recommended ~600×160px, transparent background) — picked up
automatically in the sidebar, login page, and result slip header.

## 4. Project Structure

```
sis_uoe/
├── app.py                      # Entry point: login + dashboard
├── models.py                   # SQLAlchemy ORM models
├── requirements.txt
├── init_admin.py                # One-off: create the first Admin on an empty DB
├── assets/
│   └── uoelogo.png               # University logo (replace as needed)
├── data_entry_templates/         # Sample CSV templates for bulk ETL import
├── utils/
│   ├── auth.py                   # Login (three-tier fallback), hashing, role checks, audit log
│   ├── db.py                     # Cached engine/session helpers
│   ├── results_logic.py          # Grading, GPA, payment gates, cohort/enrolment logic
│   ├── seed.py                    # First-run demo data seeding
│   └── ui.py                      # Sidebar, icons, badges, shared components
└── pages/
    ├── 01_students.py             # Student records — add/edit (incl. intake, bio data)
    ├── 02_courses.py              # Course catalogue — add/delete-all/replace-all
    ├── 03_registration.py         # Self-service registration + Registrar controls
    ├── 04_results_entry.py        # Score entry, bulk upload, exemptions
    ├── 05_results_publish.py      # Results publication (batch/individual/history)
    ├── 06_my_results.py           # Student-facing results (payment-gated)
    ├── 07_financials.py           # Fee statements, payment recording, overview
    ├── 08_reports.py              # Performance, enrolment, fee collection reports
    ├── 09_result_slip.py          # Printable HTML result slip with GPA
    ├── 10_etl.py                  # Bulk Excel/CSV import (incl. replace-all-courses)
    └── 11_settings.py             # Admin: users, programmes, fees, intakes, cohorts, audit log
```

## 5. Core Concepts

### Intakes & cohort progression
Students belong to an **Intake** (their cohort — set once, never changes),
distinct from their current `year_of_study`/`current_semester` (which
advance over time). An **IntakeProgress** record maps each cohort-step
(intake, year, semester) to a calendar **AcademicYear** — set once by the
Registrar via **Settings → Intakes & Cohorts → Promote Cohort**, which also
auto-enrols every student in that intake into their matching courses for
the new period. **Backfill Enrolment** (same page) retroactively creates
missing Registration/StudentCourse rows for any student's full progression
history — safe to re-run, only creates what's missing.

### Grading scale (7-band)
A+ (86–100, 5.0/4.0) · A (75–85, 4.0/3.5) · B+ (70–74, 3.0/3.0) ·
B (60–69, 3.0/3.0) · C+ (56–59, 2.0/2.0) · C (50–55, 1.0/1.0) · F (0–49, 0.0)
— two GPA scales (4-pt/5-pt) switchable system-wide in Settings.

**Score weighting:** Diploma/Undergraduate — CA1 10% + CA2 10% +
Mid-Semester 20% + Final 60%. Postgraduate — CA1 25% + CA2 25% + Final 50%
(no Mid-Semester component).

### Payment gates
- **Course registration**: past semesters (backdating) — no gate. Current/
  future semesters — 25% of that semester's fee paid, AND no outstanding
  balance from earlier semesters.
- **Results viewing**: 100% of all outstanding balances (across every
  period the student has progressed through) must be cleared.
- Balances are bounded to each student's actual intake-derived progression
  window — never before their initial enrolment, never beyond their
  programme's standard duration (Diploma 3yrs / Bachelor's 4yrs / Masters
  2yrs). A `Student.fee_adjustment` field captures individual
  scholarships/discounts that don't fit the shared fee structure.

### Exemptions
A `StudentCourse` has either a `Result` (sat the course) or an `Exemption`
(waived) — never both. Exempted courses are excluded from GPA and credit
totals, and shown distinctly on result slips/transcripts.

### Roles
Student · Lecturer · Registrar · Finance · Admin · **Admin Support**
(administrative staff under the Registrar's office — can view/edit student
records, but excluded from cohort promotion, registration period control,
and results publication).

## 6. Results Publication Workflow

1. Lecturer/Registrar enters scores on **Results Entry** — saved as `Draft`.
2. Registrar/Admin publishes via **Publish Results**, batch or individual.
   Every batch publish is logged in `ResultPublicationBatch`.
3. Once `Published`, results become visible on **My Results** and
   **Result Slip** — only if the 100% payment gate is cleared.
4. Results can be **Withheld** or reverted to `Draft` at any time, with
   full audit logging.

## 7. Bulk Data Import / Catalogue Management

**Data Import (ETL)** supports Programmes, Fee Structures, Staff Users,
Students, Courses, and Payments via CSV/XLSX, with downloadable templates.

**Course catalogue replacement** (Courses page / ETL Courses tab):
- **Upload** — additive, skips existing duplicates.
- **Replace All Courses** (Admin only, requires typing `REPLACE`) — wipes
  the entire catalogue (and dependent enrolments/results/exemptions,
  preserving Registrations) then loads the uploaded file fresh.
- **Delete All Courses** (Admin only, requires typing `DELETE`) — wipes
  the catalogue with no replacement.

## 8. Deploying to Streamlit Cloud

Streamlit Community Cloud's filesystem is **ephemeral** — it resets on every
restart/redeploy. SQLite (`sis_uoe.db`) cannot be used for real data there;
you need a real persistent database (Postgres).

1. **Provision a hosted Postgres database** — any provider works (Supabase,
   Neon, Railway, etc.); you just need a standard
   `postgresql://user:pass@host:port/dbname` connection string.
2. **Migrate existing local data** (skip if starting fresh):
   ```bash
   export TARGET_DATABASE_URL="postgresql://...your-connection-string..."
   python migrate_sqlite_to_postgres.py
   ```
   Copies every table from local `sis_uoe.db` into the target, preserving
   IDs/relationships, and resets Postgres's auto-increment sequences.
   Refuses to run against a non-empty target (won't duplicate data).
3. **Configure the secret** — locally, copy `.streamlit/secrets.toml.example`
   to `.streamlit/secrets.toml` (gitignored) and fill in `DATABASE_URL`. On
   Streamlit Cloud, paste the same `DATABASE_URL = "..."` line into the
   app's **Settings → Secrets**.
4. **Deploy** — connect this GitHub repo in Streamlit Cloud, set the main
   file to `app.py`, and deploy. With `DATABASE_URL` configured it connects
   to Postgres automatically (`utils/db.py` falls back to local SQLite only
   when no secret is present).

## 9. Security Notes Before Going Live

- Change every default password (see §2) — especially the shared student
  default if real student accounts were bulk-imported.
- `sis_uoe.db` and anything under `migration_exports/` or `data_uploads/`
  contain real student PII once populated — never commit them (already
  excluded via `.gitignore`).
- Review Settings → Audit Log periodically; every significant action
  (publish, promote cohort, replace courses, grant exemption, etc.) is
  logged with the acting user.

---
*University of Edenberg SIS — built iteratively across multiple development sprints.*
