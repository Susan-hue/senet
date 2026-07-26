"""CBT orchestration: who may manage what, and the server-authoritative attempt
lifecycle (start -> save answers -> submit / auto-submit -> grade).

Every timing and scoring decision lives here, server-side. The client only ever
supplies answer *content*; it never sets a clock and never sees a correct answer.
"""

from datetime import timedelta
from decimal import Decimal

from django.db import connection, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from accounts.models import Enrolment, Role
from accounts.services import lecturer_can_access_course
from cbt.assembly import assemble_attempt_questions, bank_question_pool
from cbt.grading import grade_answer
from cbt.models import (
    Answer,
    AttemptQuestion,
    AttemptStatus,
    Exam,
    ExamAttempt,
    Question,
    QuestionBank,
    QuestionType,
)

# --------------------------------------------------------------------------- #
# Access control                                                              #
# --------------------------------------------------------------------------- #


def can_manage_bank(user, course):
    """Whether ``user`` may create/edit banks and questions for ``course``.

    A bank is course-wide (reusable across terms), so a lecturer qualifies if
    they are assigned to the course in *any* term; HODs/deans by scope; admins
    tenant-wide.
    """
    role = getattr(user, "role", None)
    if role == Role.LECTURER:
        from accounts.models import CourseAssignment

        return CourseAssignment.all_objects.filter(lecturer=user, course=course).exists()
    return _manages_course_by_scope(user, course)


def can_manage_exam(user, course, session, semester):
    """Whether ``user`` may create/edit exams for a specific course term."""
    role = getattr(user, "role", None)
    if role == Role.LECTURER:
        return lecturer_can_access_course(user, course, session, semester)
    return _manages_course_by_scope(user, course)


def _manages_course_by_scope(user, course):
    role = getattr(user, "role", None)
    if role == Role.HOD:
        return user.department_id is not None and user.department_id == course.department_id
    if role == Role.DEAN:
        return user.faculty_id is not None and user.faculty_id == course.department.faculty_id
    if role in (Role.SENATE_ADMIN, Role.SCHOOL_ADMIN):
        return True
    return False


def visible_exams(user):
    """Exams the user may see: lecturers their assigned terms, students their
    enrolled terms, HODs/deans/admins by scope."""
    from django.db.models import Exists, OuterRef

    from accounts.models import CourseAssignment

    role = getattr(user, "role", None)
    qs = Exam.objects.select_related("course", "course__department", "session", "semester")

    if role == Role.LECTURER:
        assigned = CourseAssignment.all_objects.filter(
            lecturer=user,
            course=OuterRef("course"),
            session=OuterRef("session"),
            semester=OuterRef("semester"),
        )
        return qs.filter(Exists(assigned))
    if role in (Role.STUDENT, Role.COURSE_REP):
        enrolled = Enrolment.all_objects.filter(
            student=user,
            course=OuterRef("course"),
            session=OuterRef("session"),
            semester=OuterRef("semester"),
        )
        return qs.filter(Exists(enrolled))
    if role == Role.HOD:
        return qs.filter(course__department_id=user.department_id)
    if role == Role.DEAN:
        return qs.filter(course__department__faculty_id=user.faculty_id)
    if role in (Role.SENATE_ADMIN, Role.SCHOOL_ADMIN):
        return qs
    return qs.none()


# --------------------------------------------------------------------------- #
# Authoring (banks / questions / exams)                                       #
# --------------------------------------------------------------------------- #


def create_question_bank(*, actor, course, title, description=""):
    if not can_manage_bank(actor, course):
        raise PermissionDenied("You are not permitted to manage banks for this course.")
    if QuestionBank.all_objects.filter(course=course, title=title).exists():
        raise ValidationError({"title": "A bank with this title already exists for this course."})
    return QuestionBank.all_objects.create(
        institution=actor.institution,
        course=course,
        title=title,
        description=description,
        created_by=actor,
    )


def create_question(
    *, actor, bank, type, prompt, options=None, correct_answer=None, marks, difficulty="", topic=""
):
    if not can_manage_bank(actor, bank.course):
        raise PermissionDenied("You are not permitted to manage this bank.")
    options, correct_answer, requires_manual = _validate_question_payload(
        type, options or [], correct_answer
    )
    if marks <= 0:
        raise ValidationError({"marks": "Marks must be greater than zero."})
    return Question.all_objects.create(
        institution=actor.institution,
        bank=bank,
        type=type,
        prompt=prompt,
        options=options,
        correct_answer=correct_answer,
        marks=marks,
        requires_manual_grading=requires_manual,
        difficulty=difficulty,
        topic=topic,
        created_by=actor,
    )


def _validate_question_payload(qtype, options, correct_answer):
    """Validate and normalize a question's options/answer for its type. Returns
    ``(options, correct_answer, requires_manual_grading)``."""
    if qtype in (QuestionType.MCQ, QuestionType.MULTI):
        if not isinstance(options, list) or len(options) < 2:
            raise ValidationError({"options": "Choice questions need at least two options."})
        options = [str(o) for o in options]
        indices = range(len(options))
        if qtype == QuestionType.MCQ:
            if not isinstance(correct_answer, int) or isinstance(correct_answer, bool):
                raise ValidationError({"correct_answer": "Provide the correct option index."})
            if correct_answer not in indices:
                raise ValidationError({"correct_answer": "Correct option index is out of range."})
            return options, correct_answer, False
        if (
            not isinstance(correct_answer, list)
            or not correct_answer
            or any(not isinstance(i, int) or isinstance(i, bool) for i in correct_answer)
            or any(i not in indices for i in correct_answer)
        ):
            raise ValidationError(
                {"correct_answer": "Provide a non-empty list of valid option indices."}
            )
        return options, sorted({int(i) for i in correct_answer}), False

    if qtype == QuestionType.TRUE_FALSE:
        if not isinstance(correct_answer, bool):
            raise ValidationError({"correct_answer": "Provide true or false."})
        return [], correct_answer, False

    if qtype == QuestionType.FILL_BLANK:
        if (
            not isinstance(correct_answer, list)
            or not correct_answer
            or any(not str(a).strip() for a in correct_answer)
        ):
            raise ValidationError(
                {"correct_answer": "Provide at least one accepted answer string."}
            )
        return [], [str(a) for a in correct_answer], False

    if qtype == QuestionType.SHORT_ANSWER:
        # Manual grading: no stored key, flagged for the lecturer.
        return [], None, True

    raise ValidationError({"type": "Unknown question type."})


def create_exam(
    *,
    actor,
    course,
    session,
    semester,
    banks,
    title,
    exam_type,
    duration_minutes,
    opens_at,
    closes_at,
    num_questions,
    shuffle_questions=True,
    shuffle_options=True,
    pass_mark=Decimal("50"),
):
    if semester.session_id != session.id:
        raise ValidationError({"semester": "Semester does not belong to the selected session."})
    if not can_manage_exam(actor, course, session, semester):
        raise PermissionDenied("You are not assigned to this course for the selected term.")

    banks = list(banks)
    errors = {}
    if not banks:
        errors["banks"] = "Select at least one question bank."
    elif any(bank.course_id != course.id for bank in banks):
        errors["banks"] = "Every bank must belong to the exam's course."
    if closes_at <= opens_at:
        errors["closes_at"] = "The close time must be after the open time."
    if duration_minutes <= 0:
        errors["duration_minutes"] = "Duration must be greater than zero."
    if num_questions <= 0:
        errors["num_questions"] = "Draw at least one question."
    if not Decimal("0") <= Decimal(pass_mark) <= Decimal("100"):
        # "pass mark" is an exam term, not a credential.
        errors["pass_mark"] = "Pass mark must be a percentage between 0 and 100."  # nosec B105
    if errors:
        raise ValidationError(errors)

    exam = Exam.all_objects.create(
        institution=actor.institution,
        course=course,
        session=session,
        semester=semester,
        created_by=actor,
        title=title,
        exam_type=exam_type,
        duration_minutes=duration_minutes,
        opens_at=opens_at,
        closes_at=closes_at,
        num_questions=num_questions,
        shuffle_questions=shuffle_questions,
        shuffle_options=shuffle_options,
        pass_mark=pass_mark,
    )
    exam.banks.set(banks)

    available = len(bank_question_pool(exam))
    if available < num_questions:
        raise ValidationError(
            {
                "num_questions": (
                    f"The selected banks hold {available} questions; cannot draw {num_questions}."
                )
            }
        )
    return exam


# --------------------------------------------------------------------------- #
# Attempt lifecycle (server-authoritative)                                    #
# --------------------------------------------------------------------------- #


def _require_can_attempt(student, exam):
    enrolled = Enrolment.all_objects.filter(
        institution_id=exam.institution_id,
        student=student,
        course_id=exam.course_id,
        session_id=exam.session_id,
        semester_id=exam.semester_id,
    ).exists()
    if not enrolled:
        raise PermissionDenied("You are not enrolled in this course for this term.")
    now = timezone.now()
    if now < exam.opens_at:
        raise PermissionDenied("This exam has not opened yet.")
    if now > exam.closes_at:
        raise PermissionDenied("This exam has closed.")


@transaction.atomic
def start_attempt(*, student, exam):
    """Start (or resume) a student's single attempt. The server sets the start
    time and computes the deadline; the paper is assembled and frozen on first
    start and replayed verbatim on every resume."""
    existing = ExamAttempt.all_objects.filter(exam=exam, student=student).first()
    if existing is not None:
        finalize_if_expired(existing)
        return existing

    _require_can_attempt(student, exam)
    now = timezone.now()
    deadline = min(now + timedelta(minutes=exam.duration_minutes), exam.closes_at)
    attempt, created = ExamAttempt.all_objects.get_or_create(
        exam=exam,
        student=student,
        defaults={
            "institution_id": exam.institution_id,
            "started_at": now,
            "deadline": deadline,
            "status": AttemptStatus.IN_PROGRESS,
        },
    )
    if created:
        assemble_attempt_questions(attempt, exam)
    else:
        finalize_if_expired(attempt)
    return attempt


def _require_owner(attempt, student):
    if attempt.student_id != student.id:
        raise PermissionDenied("This attempt does not belong to you.")


def _lock_in_progress(attempt_id, *, skip_locked):
    """Lock an attempt row FOR UPDATE and return it only if still in progress.

    The ``status`` predicate is re-evaluated against the freshly locked row
    version (PostgreSQL EvalPlanQual), so once one transaction finalizes an
    attempt every other locker sees it is no longer in progress and backs off —
    this is what makes finalization exactly-once under concurrency. ``skip_locked``
    lets the periodic finalizer step over rows another worker (or a live request)
    is already handling rather than blocking on them.

    Row locking is applied only where the backend supports it; on SQLite (local
    test runs) it degrades to a plain status-guarded read, and the concurrency
    tests are Postgres-gated.
    """
    qs = ExamAttempt.all_objects.filter(pk=attempt_id, status=AttemptStatus.IN_PROGRESS)
    features = connection.features
    if features.has_select_for_update:
        qs = qs.select_for_update(
            skip_locked=skip_locked and features.has_select_for_update_skip_locked
        )
    return qs.first()


def _reject_closed_attempt(attempt):
    """Finalize-if-expired (defense in depth) then refuse a write to a settled
    attempt. Run before taking the write lock so the finalize commits on its own
    transaction instead of being rolled back by the rejection."""
    finalize_if_expired(attempt)
    if attempt.status != AttemptStatus.IN_PROGRESS:
        raise PermissionDenied(
            "This attempt is closed; the deadline has passed or it was already submitted."
        )


def save_answer(*, student, attempt, question_id, raw_response):
    """Idempotent auto-save of one answer, keyed by (attempt, question).

    Last-write-wins: rapid repeats and out-of-order retries are safe, and the
    stored value always converges to the latest save for that question. Rejected
    once the server deadline has passed.
    """
    _require_owner(attempt, student)
    _reject_closed_attempt(attempt)
    with transaction.atomic():
        locked = _lock_in_progress(attempt.id, skip_locked=False)
        if locked is None:
            # Finalized between the check above and the lock — refuse the write.
            attempt.refresh_from_db()
            raise PermissionDenied("This attempt is closed; the deadline has passed.")
        return _upsert_answer(locked, question_id, raw_response)


def save_answers_batch(*, student, attempt, items):
    """Persist many answers in one locked, deadline-checked transaction — for a
    client syncing answers it buffered while offline. Idempotent per question
    (last value wins, duplicates collapse); the batch is all-or-nothing and is
    rejected outright if the deadline has passed."""
    _require_owner(attempt, student)
    _reject_closed_attempt(attempt)
    saved = []
    with transaction.atomic():
        locked = _lock_in_progress(attempt.id, skip_locked=False)
        if locked is None:
            attempt.refresh_from_db()
            raise PermissionDenied("This attempt is closed; the deadline has passed.")
        for item in items:
            saved.append(_upsert_answer(locked, item["question"], item["response"]))
    return saved


def _upsert_answer(attempt, question_id, raw_response):
    aq = (
        AttemptQuestion.all_objects.filter(attempt_id=attempt.id, question_id=question_id)
        .select_related("question")
        .first()
    )
    if aq is None:
        raise NotFound(f"Question {question_id} is not part of this attempt.")
    stored = _to_stored_response(aq.question, aq.option_order, raw_response)
    answer, _ = Answer.all_objects.update_or_create(
        attempt=attempt,
        question=aq.question,
        defaults={
            "institution_id": attempt.institution_id,
            "response": stored,
            # A fresh save invalidates any prior grading of this answer.
            "is_correct": None,
            "awarded_marks": None,
            "graded_manually": False,
        },
    )
    return answer


def _to_stored_response(question, option_order, raw):
    """Translate the client's answer into the display-order-independent stored
    form. Choice answers arrive as *display* positions and are mapped back to
    original option indices via ``option_order`` so grading ignores shuffling."""
    qtype = question.type

    if qtype == QuestionType.MCQ:
        pos = _as_option_position(raw, option_order)
        return option_order[pos]

    if qtype == QuestionType.MULTI:
        if not isinstance(raw, list):
            raise ValidationError({"response": "Provide a list of selected option positions."})
        originals = {option_order[_as_option_position(p, option_order)] for p in raw}
        return sorted(originals)

    if qtype == QuestionType.TRUE_FALSE:
        if not isinstance(raw, bool):
            raise ValidationError({"response": "Provide true or false."})
        return raw

    # FILL_BLANK / SHORT_ANSWER
    if raw is None:
        return ""
    return str(raw)


def _as_option_position(value, option_order):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError({"response": "Option positions must be integers."})
    if value < 0 or value >= len(option_order):
        raise ValidationError({"response": "Selected option is out of range."})
    return value


def submit_attempt(*, student, attempt):
    """Student-initiated submission. Grades objective questions immediately and
    queues any answered short answers. Idempotent: a settled attempt is returned
    unchanged, never re-graded. A submit arriving past the deadline is recorded as
    an auto-submission."""
    _require_owner(attempt, student)
    with transaction.atomic():
        locked = _lock_in_progress(attempt.id, skip_locked=False)
        if locked is not None:
            _finalize(locked, auto=timezone.now() > locked.deadline)
    attempt.refresh_from_db()
    return attempt


def finalize_if_expired(attempt):
    """Opportunistic, row-locked finalize whenever a request touches an attempt
    past its deadline — defense in depth so expiry is enforced even between
    periodic runs. Idempotent via the locked status guard; refreshes the passed
    instance so callers observe the settled state."""
    if attempt.status != AttemptStatus.IN_PROGRESS or timezone.now() <= attempt.deadline:
        return
    with transaction.atomic():
        locked = _lock_in_progress(attempt.id, skip_locked=False)
        if locked is not None and timezone.now() > locked.deadline:
            _finalize(locked, auto=True)
    attempt.refresh_from_db()


def finalize_expired_attempts(*, limit=500):
    """Finalize every in-progress attempt whose deadline has passed.

    Safe to run frequently and concurrently. Candidates are gathered with a cheap
    unlocked read, then each is finalized under its own row lock
    (``FOR UPDATE SKIP LOCKED``) with the in-progress status re-checked under the
    lock — so two overlapping runs, or a run racing a late student request, can
    never finalize the same attempt twice. Returns the number finalized.

    This is the periodic safety net (see ``cbt.tasks``): it settles attempts of
    students who lost power/network and never reconnected to submit.
    """
    now = timezone.now()
    candidate_ids = list(
        ExamAttempt.all_objects.filter(status=AttemptStatus.IN_PROGRESS, deadline__lte=now)
        .order_by("deadline")
        .values_list("id", flat=True)[:limit]
    )
    finalized = 0
    for attempt_id in candidate_ids:
        with transaction.atomic():
            locked = _lock_in_progress(attempt_id, skip_locked=True)
            if locked is None or timezone.now() <= locked.deadline:
                continue
            _finalize(locked, auto=True)
            finalized += 1
    return finalized


@transaction.atomic
def _finalize(attempt, *, auto):
    objective_total, max_total, manual_pending = _grade_objective(attempt)
    attempt.score = objective_total
    attempt.max_score = max_total
    attempt.requires_manual_grading = manual_pending
    attempt.submitted_at = timezone.now()
    if manual_pending:
        attempt.status = AttemptStatus.AUTO_SUBMITTED if auto else AttemptStatus.SUBMITTED
    else:
        attempt.status = AttemptStatus.GRADED
    attempt.save(
        update_fields=[
            "score",
            "max_score",
            "requires_manual_grading",
            "submitted_at",
            "status",
            "updated_at",
        ]
    )
    if attempt.status == AttemptStatus.GRADED:
        from cbt.ca import sync_ca_grade_for_attempt

        sync_ca_grade_for_attempt(attempt)


def _grade_objective(attempt):
    """Grade every objective answer in the frozen paper and total the marks.

    Returns ``(objective_total, max_total, manual_pending)``. Unanswered questions
    score zero; answered short answers set ``manual_pending`` and are left for a
    human (never auto-scored).
    """
    # Explicit all_objects queries: grading runs off the request path (deadline
    # finalization, future Celery marking) where no tenant is bound.
    attempt_questions = AttemptQuestion.all_objects.filter(attempt=attempt).select_related(
        "question"
    )
    answers = {a.question_id: a for a in Answer.all_objects.filter(attempt=attempt)}

    objective_total = Decimal("0")
    max_total = Decimal("0")
    manual_pending = False

    for aq in attempt_questions:
        question = aq.question
        max_total += Decimal(question.marks)
        answer = answers.get(question.id)

        if question.type == QuestionType.SHORT_ANSWER:
            if answer is not None and answer.response not in (None, ""):
                manual_pending = True
            continue

        outcome = grade_answer(question, answer.response if answer else None)
        objective_total += outcome.awarded_marks
        if answer is not None:
            answer.is_correct = outcome.is_correct
            answer.awarded_marks = outcome.awarded_marks
            answer.graded_manually = False
            answer.save(
                update_fields=["is_correct", "awarded_marks", "graded_manually", "updated_at"]
            )

    return objective_total, max_total, manual_pending
