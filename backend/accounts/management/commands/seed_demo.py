import os
from datetime import date

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import (
    Course,
    CourseAssignment,
    Department,
    Faculty,
    Level,
    Programme,
    Role,
    Semester,
    Session,
    User,
)
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
    ("CSC 201", "Computer Programming I", 3, Level.L200, "CSC"),
    ("ACC 101", "Principles of Accounting I", 3, Level.L100, "ACC"),
    ("ACC 301", "Financial Accounting", 3, Level.L300, "ACC"),
]

ASSIGNMENTS = [
    ("ada.obi@veritas.edu.ng", "CSC 101"),
    ("emeka.nwosu@veritas.edu.ng", "MTH 101"),
]


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

        n = 0
        for email, full_name, matric, level, dept_code in STUDENTS:
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
            n += was_created
        created["students"] = n

        n = 0
        for lecturer_email, course_code in ASSIGNMENTS:
            _, was_created = CourseAssignment.all_objects.get_or_create(
                institution=institution,
                lecturer=lecturers[lecturer_email],
                course=courses[course_code],
                session=session,
                semester=semesters["First"],
            )
            n += was_created
        created["assignments"] = n

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Seeded: {institution.name} ({institution.code})"))
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("School admin login"))
        self.stdout.write(f"  email:    {ADMIN_EMAIL}")
        self.stdout.write(f"  password: {password}")
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Created this run (0 = already existed)"))
        for key, count in created.items():
            self.stdout.write(f"  {key:<12} {count}")
        self.stdout.write("")
