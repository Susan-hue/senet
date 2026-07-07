import os
from datetime import date, datetime
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import (
    Course,
    CourseAssignment,
    Department,
    Enrolment,
    Faculty,
    Level,
    Programme,
    Role,
    Semester,
    Session,
    User,
)
from assessments.models import AssessmentGrade, AssessmentItem
from tenancy.models import Institution

ADMIN_EMAIL = "admin@veritas.edu.ng"

LECTURERS = [
    ("ada.obi@veritas.edu.ng", "Dr. Ada Obi", "CSC"),
    ("emeka.nwosu@veritas.edu.ng", "Dr. Emeka Nwosu", "MTH"),
    ("bola.adeyemi@veritas.edu.ng", "Prof. Bola Adeyemi", "ACC"),
]

STUDENTS = [
    ("chidi.okafor@student.veritas.edu.ng", "Chidi Okafor", "VUA/CSC/21/0001", 100, "CSC"),
    ("ngozi.eze@student.veritas.edu.ng", "Ngozi Eze", "VUA/CSC/20/0002", 200, "CSC"),
    ("tunde.bakare@student.veritas.edu.ng", "Tunde Bakare", "VUA/MTH/21/0003", 100, "MTH"),
    ("amina.yusuf@student.veritas.edu.ng", "Amina Yusuf", "VUA/ACC/19/0004", 300, "ACC"),
    ("ifeoma.nnaji@student.veritas.edu.ng", "Ifeoma Nnaji", "VUA/ACC/20/0005", 200, "ACC"),
]

COURSES = [
    ("MTH 101", "Elementary Mathematics I", 3, Level.L100, "MTH"),
    ("MTH 201", "Mathematical Methods I", 3, Level.L200, "MTH"),
    ("CSC 101", "Introduction to Computer Science", 2, Level.L100, "CSC"),
    ("CSC 103", "Introduction to Problem Solving", 2, Level.L100, "CSC"),
    ("CSC 201", "Computer Programming I", 3, Level.L200, "CSC"),
    ("ACC 101", "Principles of Accounting I", 3, Level.L100, "ACC"),
    ("ACC 201", "Cost Accounting I", 3, Level.L200, "ACC"),
    ("ACC 301", "Financial Accounting", 3, Level.L300, "ACC"),
    ("ACC 303", "Taxation I", 3, Level.L300, "ACC"),
]

ASSIGNMENTS = [
    ("ada.obi@veritas.edu.ng", "CSC 101"),
    ("ada.obi@veritas.edu.ng", "CSC 103"),
    ("emeka.nwosu@veritas.edu.ng", "MTH 101"),
    ("emeka.nwosu@veritas.edu.ng", "MTH 201"),
    ("bola.adeyemi@veritas.edu.ng", "ACC 201"),
    ("bola.adeyemi@veritas.edu.ng", "ACC 301"),
]

ENROLMENT_PLAN = {
    ("CSC", 100): ["CSC 101", "CSC 103", "MTH 101"],
    ("CSC", 200): ["CSC 201", "MTH 201"],
    ("MTH", 100): ["MTH 101", "CSC 101", "CSC 103"],
    ("MTH", 200): ["MTH 201", "CSC 201"],
    ("ACC", 200): ["ACC 201", "ACC 101"],
    ("ACC", 300): ["ACC 301", "ACC 303"],
}

ROSTER_COURSE = "CSC 101"
ROSTER_LECTURER = "ada.obi@veritas.edu.ng"

ASSESSMENT_ITEMS = [
    ("Assignment 1", AssessmentItem.Kind.ASSIGNMENT, "20", "15", datetime(2024, 10, 25, 23, 59)),
    ("Test 1", AssessmentItem.Kind.TEST, "30", "20", datetime(2024, 11, 22, 10, 0)),
]

FIRST_NAMES = [
    "Adaeze",
    "Bayo",
    "Chiamaka",
    "Damilola",
    "Ebuka",
    "Folake",
    "Gbenga",
    "Halima",
    "Ikenna",
    "Jumoke",
    "Kelechi",
    "Lola",
    "Musa",
    "Nkechi",
    "Obinna",
    "Patience",
]

LAST_NAMES = [
    "Abubakar",
    "Balogun",
    "Chukwu",
    "Danjuma",
    "Egwu",
    "Falana",
    "Garba",
    "Ibe",
    "Johnson",
    "Kalu",
    "Lawal",
    "Mohammed",
    "Nwachukwu",
    "Okeke",
    "Peters",
    "Sanni",
]


def extra_students():
    rows = []
    for i, first in enumerate(FIRST_NAMES):
        for r in range(2):
            last = LAST_NAMES[(i + 5 * r) % len(LAST_NAMES)]
            serial = 101 + i * 2 + r
            rows.append(
                (
                    f"{first.lower()}.{last.lower()}@student.veritas.edu.ng",
                    f"{first} {last}",
                    f"VUA/CSC/24/{serial:04d}",
                    100,
                    "CSC",
                )
            )
    return rows


class Command(BaseCommand):
    help = "Seed a demo institution, school admin, academic structure and users for local dev."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Allow running with DEBUG=False. Never use against production.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            raise CommandError(
                "Refusing to seed demo data with DEBUG=False. "
                "This command is for local/dev databases only (pass --force to override)."
            )

        password = os.environ.get("SEED_DEMO_PASSWORD", "VeritasDemo123!")
        created = {}

        institution, was_created = Institution.objects.get_or_create(
            code="veritas",
            defaults={"name": "Veritas University, Abuja"},
        )
        created["institutions"] = int(was_created)

        admin, was_created = User.objects.get_or_create(
            email=ADMIN_EMAIL,
            defaults={
                "full_name": "Veritas Admin",
                "role": Role.SCHOOL_ADMIN,
                "institution": institution,
                "is_verified": True,
            },
        )
        if was_created:
            admin.set_password(password)
            admin.save(update_fields=["password"])
        created["admins"] = int(was_created)

        faculties = {}
        n = 0
        for name, code in [
            ("Faculty of Natural and Applied Sciences", "NAS"),
            ("Faculty of Management Sciences", "MGS"),
        ]:
            faculties[code], was_created = Faculty.all_objects.get_or_create(
                institution=institution, code=code, defaults={"name": name}
            )
            n += was_created
        created["faculties"] = n

        departments = {}
        n = 0
        for name, code, faculty_code in [
            ("Computer Science", "CSC", "NAS"),
            ("Mathematics", "MTH", "NAS"),
            ("Accounting", "ACC", "MGS"),
        ]:
            departments[code], was_created = Department.all_objects.get_or_create(
                institution=institution,
                code=code,
                defaults={"name": name, "faculty": faculties[faculty_code]},
            )
            n += was_created
        created["departments"] = n

        n = 0
        for name, code, degree, dept_code in [
            ("B.Sc Computer Science", "BSC-CSC", "B.Sc", "CSC"),
            ("B.Sc Accounting", "BSC-ACC", "B.Sc", "ACC"),
        ]:
            _, was_created = Programme.all_objects.get_or_create(
                institution=institution,
                code=code,
                defaults={
                    "name": name,
                    "degree_type": degree,
                    "department": departments[dept_code],
                },
            )
            n += was_created
        created["programmes"] = n

        session, was_created = Session.all_objects.get_or_create(
            institution=institution,
            name="2024/2025",
            defaults={
                "start_date": date(2024, 9, 16),
                "end_date": date(2025, 7, 31),
                "is_current": True,
            },
        )
        created["sessions"] = int(was_created)

        semesters = {}
        n = 0
        for name, start, end in [
            ("First", date(2024, 9, 16), date(2025, 1, 31)),
            ("Second", date(2025, 2, 10), date(2025, 6, 27)),
        ]:
            semesters[name], was_created = Semester.all_objects.get_or_create(
                institution=institution,
                session=session,
                name=name,
                defaults={"start_date": start, "end_date": end},
            )
            n += was_created
        created["semesters"] = n

        courses = {}
        n = 0
        for code, title, units, level, dept_code in COURSES:
            courses[code], was_created = Course.all_objects.get_or_create(
                institution=institution,
                code=code,
                defaults={
                    "title": title,
                    "credit_units": units,
                    "level": level,
                    "department": departments[dept_code],
                },
            )
            n += was_created
        created["courses"] = n

        lecturers = {}
        n = 0
        for email, full_name, dept_code in LECTURERS:
            department = departments[dept_code]
            lecturers[email], was_created = User.objects.get_or_create(
                email=email,
                defaults={
                    "full_name": full_name,
                    "role": Role.LECTURER,
                    "institution": institution,
                    "faculty": department.faculty,
                    "department": department,
                    "is_verified": True,
                },
            )
            if was_created:
                lecturers[email].set_password(password)
                lecturers[email].save(update_fields=["password"])
            n += was_created
        created["lecturers"] = n

        students = []
        n = 0
        for email, full_name, matric, level, dept_code in STUDENTS + extra_students():
            department = departments[dept_code]
            student, was_created = User.objects.get_or_create(
                email=email,
                defaults={
                    "full_name": full_name,
                    "role": Role.STUDENT,
                    "institution": institution,
                    "faculty": department.faculty,
                    "department": department,
                    "identifier": matric,
                    "current_level": level,
                    "is_verified": True,
                },
            )
            if was_created:
                student.set_password(password)
                student.save(update_fields=["password"])
            students.append((student, dept_code, level))
            n += was_created
        created["students"] = n

        semester = semesters["First"]

        n = 0
        for lecturer_email, course_code in ASSIGNMENTS:
            _, was_created = CourseAssignment.all_objects.get_or_create(
                institution=institution,
                lecturer=lecturers[lecturer_email],
                course=courses[course_code],
                session=session,
                semester=semester,
            )
            n += was_created
        created["assignments"] = n

        n = 0
        for student, dept_code, level in students:
            for course_code in ENROLMENT_PLAN.get((dept_code, level), []):
                _, was_created = Enrolment.all_objects.get_or_create(
                    institution=institution,
                    student=student,
                    course=courses[course_code],
                    session=session,
                    semester=semester,
                )
                n += was_created
        created["enrolments"] = n

        roster_course = courses[ROSTER_COURSE]
        roster_lecturer = lecturers[ROSTER_LECTURER]

        items = {}
        n = 0
        for title, kind, max_score, weight, due in ASSESSMENT_ITEMS:
            items[title], was_created = AssessmentItem.all_objects.get_or_create(
                institution=institution,
                course=roster_course,
                session=session,
                semester=semester,
                title=title,
                defaults={
                    "kind": kind,
                    "created_by": roster_lecturer,
                    "max_score": Decimal(max_score),
                    "weight": Decimal(weight),
                    "due_date": timezone.make_aware(due),
                },
            )
            n += was_created
        created["assessment_items"] = n

        roster = [
            student
            for student, dept_code, level in students
            if ROSTER_COURSE in ENROLMENT_PLAN.get((dept_code, level), [])
        ]
        n = 0
        for i, student in enumerate(roster[:12]):
            _, was_created = AssessmentGrade.all_objects.get_or_create(
                institution=institution,
                item=items["Test 1"],
                student=student,
                defaults={
                    "score": Decimal(12 + (i * 5) % 19),
                    "graded_by": roster_lecturer,
                    "is_released": True,
                },
            )
            n += was_created
        created["assessment_grades"] = n

        roster_size = Enrolment.all_objects.filter(
            institution=institution,
            course=roster_course,
            session=session,
            semester=semester,
        ).count()

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Seeded: {institution.name} ({institution.code})"))
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("School admin login"))
        self.stdout.write(f"  email:    {ADMIN_EMAIL}")
        self.stdout.write(f"  password: {password}")
        self.stdout.write("")
        self.stdout.write(
            self.style.MIGRATE_HEADING("Lecturer with a populated roster (score entry)")
        )
        self.stdout.write(f"  email:    {ROSTER_LECTURER}")
        self.stdout.write(f"  password: {password}")
        self.stdout.write(
            f"  course:   {roster_course.code} — {roster_course.title} "
            f"({semester.name} semester, {session.name})"
        )
        self.stdout.write(f"  roster:   {roster_size} enrolled students")
        self.stdout.write(
            f"  CA items: {', '.join(items)} (Test 1 has {min(len(roster), 12)} released grades)"
        )
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Sample student login"))
        self.stdout.write(f"  email:    {STUDENTS[0][0]}")
        self.stdout.write(f"  password: {password}")
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Created this run (0 = already existed)"))
        for key, count in created.items():
            self.stdout.write(f"  {key:<18} {count}")
        self.stdout.write("")
