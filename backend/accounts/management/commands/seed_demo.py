import os
import random
from datetime import date, datetime
from decimal import Decimal

from django.conf import settings
from django.core.files.base import ContentFile
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

STUDENT_EMAIL = "chidi.okafor@student.veritas.edu.ng"
COURSE_REP_EMAIL = "uche.mba@student.veritas.edu.ng"

# (email, name, matric, level, department, role). The course rep is a student
# who happens to hold the rep role, so it is seeded here rather than with the
# staff — it needs the same enrolments as everyone else in its year.
STUDENTS = [
    (STUDENT_EMAIL, "Chidi Okafor", "VUA/CSC/21/0001", 100, "CSC", Role.STUDENT),
    (COURSE_REP_EMAIL, "Uche Mba", "VUA/CSC/21/0006", 100, "CSC", Role.COURSE_REP),
    ("ngozi.eze@student.veritas.edu.ng", "Ngozi Eze", "VUA/CSC/20/0002", 200, "CSC", Role.STUDENT),
    (
        "tunde.bakare@student.veritas.edu.ng",
        "Tunde Bakare",
        "VUA/MTH/21/0003",
        100,
        "MTH",
        Role.STUDENT,
    ),
    (
        "amina.yusuf@student.veritas.edu.ng",
        "Amina Yusuf",
        "VUA/ACC/19/0004",
        300,
        "ACC",
        Role.STUDENT,
    ),
    (
        "ifeoma.nnaji@student.veritas.edu.ng",
        "Ifeoma Nnaji",
        "VUA/ACC/20/0005",
        200,
        "ACC",
        Role.STUDENT,
    ),
]

COURSES = [
    ("MTH 101", "Elementary Mathematics I", 3, Level.L100, "MTH"),
    ("MTH 201", "Mathematical Methods I", 3, Level.L200, "MTH"),
    ("CSC 101", "Introduction to Computer Science", 2, Level.L100, "CSC"),
    ("CSC 103", "Introduction to Problem Solving", 2, Level.L100, "CSC"),
    ("CSC 201", "Computer Programming I", 3, Level.L200, "CSC"),
    # The approval pipeline needs a sheet at every stage at once, and a sheet is
    # unique per course + term. These give the demo five concurrent stages inside
    # one department, so a single HOD and Dean can walk the whole chain.
    ("CSC 202", "Object-Oriented Programming", 3, Level.L200, "CSC"),
    ("CSC 301", "Data Structures and Algorithms", 3, Level.L300, "CSC"),
    ("CSC 305", "Operating Systems", 3, Level.L300, "CSC"),
    ("ACC 101", "Principles of Accounting I", 3, Level.L100, "ACC"),
    ("ACC 201", "Cost Accounting I", 3, Level.L200, "ACC"),
    ("ACC 301", "Financial Accounting", 3, Level.L300, "ACC"),
    ("ACC 303", "Taxation I", 3, Level.L300, "ACC"),
]

# Named staff logins, one per stage of the approval chain. Each is scoped so the
# accounts can actually act on the seeded sheets: the HOD owns the department the
# pipeline courses sit in, the Dean owns that department's faculty, and the
# Senate admin is institution-wide.
HOD_EMAIL = "hod.csc@veritas.edu.ng"
DEAN_EMAIL = "dean.nas@veritas.edu.ng"
SENATE_EMAIL = "senate@veritas.edu.ng"
EXAM_OFFICER_EMAIL = "examofficer.csc@veritas.edu.ng"
ADVISER_EMAIL = "adviser.csc@veritas.edu.ng"
PIPELINE_DEPARTMENT = "CSC"
PIPELINE_LECTURER = "ada.obi@veritas.edu.ng"

# (email, name, role, department, faculty). The department and faculty are the
# whole point: the API answers an approver from their own scope, so an HOD
# seeded without a department — or with the wrong one — logs in to an empty
# worklist and the demo dies on its second click.
STAFF = [
    (HOD_EMAIL, "Dr. Ifeanyi Umeh", Role.HOD, "CSC", "NAS"),
    (DEAN_EMAIL, "Prof. Grace Eluwa", Role.DEAN, None, "NAS"),
    (SENATE_EMAIL, "Dr. Yemi Balogun", Role.SENATE_ADMIN, None, None),
    (EXAM_OFFICER_EMAIL, "Mr. Tobi Adewale", Role.EXAM_OFFICER, "CSC", "NAS"),
    (ADVISER_EMAIL, "Dr. Ngozi Iheanacho", Role.COURSE_ADVISER, "CSC", "NAS"),
]

# (course, target stage, score profile, roster cap). Ordered as the chain runs so
# the printed summary reads top to bottom.
PIPELINE = [
    ("CSC 103", "draft", "normal", 30),
    ("CSC 201", "submitted_to_hod", "weak", 28),
    ("CSC 202", "approved_by_hod", "normal", 26),
    ("CSC 301", "approved_by_dean", "strong", 24),
    ("CSC 101", "ratified_by_senate", "normal", 40),
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

# The taught side of the roster course: two modules, one item of every kind, so
# the content screen shows a file to download, a lesson page, a reading link and
# an embedded video rather than one lonely row.
CONTENT_PLAN = [
    (
        "Week 1 — What a computer actually is",
        "Von Neumann architecture, the fetch-execute cycle, and why any of it matters.",
        [
            (
                "Course outline (PDF)",
                "file",
                {"description": "Grading breakdown, reading list and the semester calendar."},
            ),
            (
                "Lesson: the fetch-execute cycle",
                "page",
                {
                    "body": (
                        "A processor repeats four steps forever: fetch the next instruction "
                        "from memory, decode it, execute it, then store the result.\n\n"
                        "Everything else in this course — compilers, operating systems, "
                        "data structures — is an argument about how to arrange work so that "
                        "this loop does something useful."
                    ),
                },
            ),
        ],
    ),
    (
        "Week 2 — Representing data",
        "Binary, two's complement, and why 0.1 + 0.2 is not 0.3.",
        [
            (
                "Reading: number systems primer",
                "link",
                {
                    "url": "https://en.wikipedia.org/wiki/Two%27s_complement",
                    "description": "Read up to the section on arithmetic before Thursday.",
                },
            ),
            (
                "Recorded lecture: floating point",
                "video",
                {
                    "url": "https://www.youtube.com/embed/PZRI1IfStY0",
                    "description": "Watch this before the tutorial — we build on it directly.",
                },
            ),
        ],
    ),
]

OUTLINE_PDF = (
    b"%PDF-1.4\n% Senet demo course outline\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
)

ANNOUNCEMENTS = [
    (
        "Thursday's class moves to LT2",
        (
            "The usual room is being used for a departmental defence this week, so "
            "Thursday's 10am lecture will run in Lecture Theatre 2.\n\n"
            "Bring the Week 2 reading — we start on two's complement."
        ),
        True,
    ),
    (
        "Assignment 1 is now open",
        (
            "Assignment 1 is up under Continuous Assessment and closes on 25 October "
            "at 23:59. It is worth 15 of the 40 CA points.\n\n"
            "Submit a PDF. Late uploads are accepted but flagged."
        ),
        False,
    ),
]

WALKTHROUGH = [
    (
        "School Admin",
        ADMIN_EMAIL,
        [
            "People → drill Faculty → Department → Role to find anyone; Courses and",
            "Lecturer Assignments drill the same way. This is where the term, the",
            "catalogue and the staffing all come from.",
        ],
    ),
    (
        "Lecturer",
        ROSTER_LECTURER,
        [
            "My Courses → CSC 101. Content shows two published modules with a PDF, a",
            "lesson page, a reading link and a video; Announcements has a pinned notice;",
            "Discussions has a question from a student you have already answered.",
            "Then open CSC 103 — still a DRAFT. Enter or edit scores and submit it to",
            "watch a sheet enter the approval chain.",
        ],
    ),
    (
        "Student",
        STUDENT_EMAIL,
        [
            "Same course from the other side: the materials are readable and downloadable,",
            "the announcement is on the feed, and you can reply on the discussion board.",
            "My Results shows CSC 101 already RATIFIED with a grade and GPA.",
        ],
    ),
    (
        "Course Rep",
        COURSE_REP_EMAIL,
        [
            "A student account with the rep role — same enrolments, same course material,",
            "already part of the discussion thread.",
        ],
    ),
    (
        "HOD",
        HOD_EMAIL,
        [
            "Departmental Board → CSC 201 is waiting on you. Open it: the vetting panel",
            "flags the failure rate, because that sheet was seeded mostly-failing.",
            "Approve it (→ Dean) or return it with a reason.",
        ],
    ),
    (
        "Exam Officer",
        EXAM_OFFICER_EMAIL,
        [
            "Scoped to Computer Science — the department's exams and CBT sittings.",
        ],
    ),
    (
        "Course Adviser",
        ADVISER_EMAIL,
        [
            "Academic standing for Computer Science students: GPA and CGPA are already",
            "computed for the term, so the advising list has real numbers.",
        ],
    ),
    (
        "Dean",
        DEAN_EMAIL,
        [
            "Faculty Board → pick Computer Science. CSC 202 is waiting (and CSC 201 too,",
            "once the HOD approves it). Approve to send it on to Senate.",
        ],
    ),
    (
        "Senate Admin",
        SENATE_EMAIL,
        [
            "Senate Ratification → pick the NAS faculty. CSC 301 is waiting. Tick it and",
            "batch-ratify: that publishes it to students and locks it permanently.",
            "Sign back in as the student to see it land.",
        ],
    ),
]

DISCUSSIONS = [
    (
        "Why does two's complement have one extra negative number?",
        (
            "In an 8-bit signed integer the range is -128 to 127, so there is one more "
            "negative than positive. I follow the arithmetic but I don't understand why "
            "the asymmetry is there at all. Is it a design choice or does it fall out of "
            "the representation?"
        ),
        (
            "Good question — it falls out of the representation. Zero has to live "
            "somewhere, and in two's complement it sits in the non-negative half. That "
            "leaves 128 bit patterns for the negatives and only 127 for the positives "
            "once zero has taken one.\n\n"
            "Try writing out the 4-bit case by hand before Thursday; it is much clearer "
            "at 16 values than at 256."
        ),
    ),
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
                    Role.STUDENT,
                )
            )
    return rows


def score_profile(profile, ca_max, exam_max, index):
    """A deterministic (course, seat) -> (ca, exam) spread.

    Seeded per row so re-running the command reproduces the same broadsheet, and
    shaped per profile so the Departmental Board's anomaly indicators say
    something: ``weak`` puts most of the class under the pass mark, ``strong``
    piles them into the top band, ``normal`` spreads across the grades with a
    realistic tail of failures.
    """
    # Demo marks, deliberately reproducible; nothing here is a secret.
    rng = random.Random(f"{profile}:{index}")  # nosec B311
    ca_top, exam_top = int(ca_max), int(exam_max)
    if profile == "weak":
        ca = rng.randint(2, max(3, int(ca_top * 0.45)))
        exam = rng.randint(4, max(5, int(exam_top * 0.42)))
    elif profile == "strong":
        ca = rng.randint(int(ca_top * 0.82), ca_top)
        exam = rng.randint(int(exam_top * 0.80), exam_top)
    else:
        ca = rng.randint(int(ca_top * 0.35), ca_top)
        exam = rng.randint(int(exam_top * 0.28), exam_top)
    return Decimal(ca), Decimal(exam)


class Command(BaseCommand):
    help = "Seed a demo institution, school admin, academic structure and users for local dev."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Allow running with DEBUG=False. Never use against production.",
        )

    # ----------------------------------------------------------------- #
    # Approval pipeline                                                  #
    # ----------------------------------------------------------------- #

    def _seed_staff(self, institution, faculties, departments, password, created):
        """The approving accounts, each scoped to what it must be able to act on.

        Scope is the whole point: the API decides what an approver may see from
        their own department/faculty, so an HOD seeded without a department (or
        with the wrong one) would log in to an empty worklist.
        """
        staff = {}
        n = 0
        for email, full_name, role, dept_code, faculty_code in STAFF:
            staff[role], was_created = User.objects.get_or_create(
                email=email,
                defaults={
                    "full_name": full_name,
                    "role": role,
                    "institution": institution,
                    "faculty": faculties[faculty_code] if faculty_code else None,
                    "department": departments[dept_code] if dept_code else None,
                    "is_verified": True,
                },
            )
            if was_created:
                staff[role].set_password(password)
                staff[role].save(update_fields=["password"])
            n += was_created
        created["approval_staff"] = n
        return staff

    def _seed_pipeline(
        self, *, institution, session, semester, courses, lecturer, staff, students, created
    ):
        """One result sheet parked at each stage of the approval chain.

        Sheets are advanced through the real transition service rather than by
        writing a status, so every seeded sheet carries the same audit trail and
        state guarantees a sheet created through the UI would have.
        """
        from results.models import CourseResult, ResultStatus
        from results.services import (
            create_draft_result,
            record_score,
            submit_result,
            transition_result,
        )

        # The actor for each step of the chain, in order.
        chain = [
            (ResultStatus.APPROVED_BY_HOD, staff[Role.HOD]),
            (ResultStatus.APPROVED_BY_DEAN, staff[Role.DEAN]),
            (ResultStatus.RATIFIED_BY_SENATE, staff[Role.SENATE_ADMIN]),
        ]

        rows = []
        sheets = 0
        enrolments = 0
        for code, target, profile, cap in PIPELINE:
            course = courses[code]

            CourseAssignment.all_objects.get_or_create(
                institution=institution,
                lecturer=lecturer,
                course=course,
                session=session,
                semester=semester,
            )

            # Named demo students first, so the student login always appears on
            # the published sheet rather than falling outside the roster cap.
            roster = students[:cap]
            for student in roster:
                _, was_created = Enrolment.all_objects.get_or_create(
                    institution=institution,
                    student=student,
                    course=course,
                    session=session,
                    semester=semester,
                )
                enrolments += was_created

            existing = CourseResult.all_objects.filter(
                course=course, session=session, semester=semester
            ).first()
            if existing is not None:
                rows.append((code, existing.status, len(roster), profile, "already existed"))
                continue

            result = create_draft_result(
                lecturer=lecturer, course=course, session=session, semester=semester
            )
            for index, student in enumerate(roster):
                ca, exam = score_profile(
                    profile, course.effective_ca_weight, course.effective_exam_weight, index
                )
                record_score(
                    actor=lecturer,
                    result_id=result.id,
                    student=student,
                    ca_score=ca,
                    exam_score=exam,
                )

            if target != "draft":
                result = submit_result(actor=lecturer, result_id=result.id)
                for to_status, actor in chain:
                    if result.status == target:
                        break
                    result = transition_result(
                        actor=actor, result_id=result.id, to_status=to_status
                    )

            sheets += 1
            rows.append((code, result.status, len(roster), profile, "seeded"))

        created["result_sheets"] = sheets
        created["pipeline_enrolments"] = enrolments
        return rows

    def _compute_standings(self, department, session, semester):
        """Persist GPA/CGPA for the pipeline department so the Dean's CGPA column
        and the student's standing have real numbers, not blanks."""
        from grading.tasks import compute_department_standing

        compute_department_standing(str(department.id), str(session.id), str(semester.id))

    # ----------------------------------------------------------------- #
    # Teaching side: content, announcements, discussions                 #
    # ----------------------------------------------------------------- #

    def _seed_teaching(self, *, course, session, semester, lecturer, student, rep, created):
        """Fill the taught side of one course so no LMS screen opens empty.

        Everything goes through the real services, so what the demo shows is
        what the API would have produced. Each step looks for its own row first:
        the services reject duplicate titles, and this command must stay safe to
        re-run.
        """
        from announcements.models import Announcement
        from announcements.services import create_announcement
        from content.models import ContentItem, Module
        from content.services import create_item, create_module
        from discussions.models import Reply, Thread
        from discussions.services import create_reply, create_thread

        term = {"course": course, "session": session, "semester": semester}
        counts = {"modules": 0, "items": 0, "announcements": 0, "threads": 0}

        for module_title, description, items in CONTENT_PLAN:
            module = Module.all_objects.filter(title=module_title, **term).first()
            if module is None:
                module = create_module(
                    actor=lecturer,
                    title=module_title,
                    description=description,
                    is_published=True,
                    **term,
                )
                counts["modules"] += 1

            for title, kind, payload in items:
                if ContentItem.all_objects.filter(module=module, title=title).exists():
                    continue
                extra = dict(payload)
                if kind == "file":
                    # A real (if minimal) PDF, so the download link resolves
                    # instead of 404ing the moment anyone clicks it.
                    extra["file"] = ContentFile(OUTLINE_PDF, name="csc101-outline.pdf")
                create_item(
                    actor=lecturer,
                    module=module,
                    title=title,
                    kind=kind,
                    is_published=True,
                    **extra,
                )
                counts["items"] += 1

        for title, body, pinned in ANNOUNCEMENTS:
            if Announcement.all_objects.filter(title=title, **term).exists():
                continue
            create_announcement(
                actor=lecturer,
                title=title,
                body=body,
                is_pinned=pinned,
                # The seed runs inside one transaction and there is no broker in
                # front of a local dev box; the announcement is the point here,
                # not the mail.
                notify=False,
                **term,
            )
            counts["announcements"] += 1

        # A thread started by a student and answered by the lecturer, so the
        # board shows a real exchange rather than one orphaned post.
        for title, body, reply_body in DISCUSSIONS:
            thread = Thread.all_objects.filter(title=title, **term).first()
            if thread is None:
                thread = create_thread(actor=student, title=title, body=body, **term)
                counts["threads"] += 1
            if not Reply.all_objects.filter(thread=thread).exists():
                create_reply(actor=lecturer, thread=thread, body=reply_body)
                create_reply(
                    actor=rep,
                    thread=thread,
                    body="Thanks — I'll put this in the class group as well.",
                )

        created["content_modules"] = counts["modules"]
        created["content_items"] = counts["items"]
        created["announcements"] = counts["announcements"]
        created["discussion_threads"] = counts["threads"]
        return counts

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            raise CommandError(
                "Refusing to seed demo data with DEBUG=False. "
                "This command is for local/dev databases only (pass --force to override)."
            )

        self._seed()

    @transaction.atomic
    def _seed(self):
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
        for email, full_name, matric, level, dept_code, role in STUDENTS + extra_students():
            department = departments[dept_code]
            student, was_created = User.objects.get_or_create(
                email=email,
                defaults={
                    "full_name": full_name,
                    "role": role,
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

        staff = self._seed_staff(institution, faculties, departments, password, created)
        pipeline = self._seed_pipeline(
            institution=institution,
            session=session,
            semester=semester,
            courses=courses,
            lecturer=lecturers[PIPELINE_LECTURER],
            staff=staff,
            students=[student for student, _dept, _level in students],
            created=created,
        )
        self._compute_standings(departments[PIPELINE_DEPARTMENT], session, semester)

        by_email = {student.email: student for student, _dept, _level in students}
        teaching = self._seed_teaching(
            course=roster_course,
            session=session,
            semester=semester,
            lecturer=roster_lecturer,
            student=by_email[STUDENT_EMAIL],
            rep=by_email[COURSE_REP_EMAIL],
            created=created,
        )

        roster_size = Enrolment.all_objects.filter(
            institution=institution,
            course=roster_course,
            session=session,
            semester=semester,
        ).count()

        term = f"{session.name} · {semester.name} semester"
        rule = "─" * 108

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Seeded: {institution.name} ({institution.code})"))
        self.stdout.write(f"Term:   {term}")
        self.stdout.write("")

        self.stdout.write(self.style.MIGRATE_HEADING("DEMO LOGINS"))
        self.stdout.write(
            f"  Every account is verified and signs in immediately. "
            f"Password for all: {self.style.SUCCESS(password)}"
        )
        self.stdout.write("")
        self.stdout.write(f"  {'ROLE':<15} {'EMAIL':<40} {'PASSWORD':<18} SCOPE")
        self.stdout.write(f"  {rule}")
        for role_label, email, scope in [
            ("School Admin", ADMIN_EMAIL, "whole institution"),
            ("Dean", DEAN_EMAIL, "Faculty of Natural and Applied Sciences"),
            ("HOD", HOD_EMAIL, "Computer Science department"),
            ("Exam Officer", EXAM_OFFICER_EMAIL, "Computer Science department"),
            ("Course Adviser", ADVISER_EMAIL, "Computer Science department"),
            ("Lecturer", ROSTER_LECTURER, f"{roster_course.code} + {roster_size} enrolled"),
            ("Senate Admin", SENATE_EMAIL, "whole institution"),
            ("Student", STUDENT_EMAIL, "VUA/CSC/21/0001 — CSC 101, CSC 103, MTH 101"),
            ("Course Rep", COURSE_REP_EMAIL, "VUA/CSC/21/0006 — same courses, rep role"),
        ]:
            self.stdout.write(f"  {role_label:<15} {email:<40} {password:<18} {scope}")
        self.stdout.write("")

        self.stdout.write(
            self.style.MIGRATE_HEADING(f"TAUGHT CONTENT — {roster_course.code} is fully populated")
        )
        self.stdout.write(f"  {rule}")
        for label, count, detail in [
            ("Modules", teaching["modules"], "published, ordered, with a description each"),
            ("Materials", teaching["items"], "a PDF download, a lesson page, a link and a video"),
            ("Announcements", teaching["announcements"], "one pinned, one ordinary"),
            ("Discussions", teaching["threads"], "student question, lecturer answer, rep reply"),
            (
                "CA items",
                created["assessment_items"],
                "Assignment 1 and Test 1, Test 1 partly graded",
            ),
        ]:
            note = "seeded this run" if count else "already existed"
            self.stdout.write(f"  {label:<15} {count:<4} {detail}  ({note})")
        self.stdout.write("")

        self.stdout.write(self.style.MIGRATE_HEADING("RESULT SHEETS — one at every pipeline stage"))
        self.stdout.write(f"  {'COURSE':<9} {'STATE':<20} {'STUDENTS':<9} SPREAD")
        self.stdout.write(f"  {rule}")
        for code, state, size, profile, note in pipeline:
            spread = {
                "weak": "mostly failing — trips the high-failure-rate flag",
                "strong": "top-heavy — trips the abnormal-grades flag",
                "normal": "realistic spread across the grade bands",
            }[profile]
            suffix = "" if note == "seeded" else f"  ({note})"
            self.stdout.write(f"  {code:<9} {state:<20} {size:<9} {spread}{suffix}")
        self.stdout.write("")

        self.stdout.write(
            self.style.MIGRATE_HEADING("WALKTHROUGH — teach a course, then push a result to Senate")
        )
        self.stdout.write("")
        for step, (who, email, what) in enumerate(WALKTHROUGH, start=1):
            self.stdout.write(f"  {step}. Sign in as {self.style.SUCCESS(who)} — {email}")
            for line in what:
                self.stdout.write(f"     {line}")
            self.stdout.write("")

        self.stdout.write(self.style.MIGRATE_HEADING("Created this run (0 = already existed)"))
        for key, count in created.items():
            self.stdout.write(f"  {key:<20} {count}")
        self.stdout.write("")
