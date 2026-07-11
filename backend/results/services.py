from decimal import Decimal

from django.db import IntegrityError, transaction
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from accounts.models import Enrolment, Role
from accounts.services import lecturer_can_access_course
from grading.scales import grade_for_score, scale_bands
from results.models import (
    LECTURER_EDITABLE_STATUSES,
    AmendmentStatus,
    AuditAction,
    CourseResult,
    ExternalExaminerReport,
    ResultAmendment,
    ResultAuditLog,
    ResultStatus,
    StudentScore,
)


def _owns_result(actor, result):
    return result.lecturer_id == actor.id


def _hod_scope(actor, result):
    return actor.department_id is not None and actor.department_id == result.course.department_id


def _dean_scope(actor, result):
    return actor.faculty_id is not None and actor.faculty_id == result.course.department.faculty_id


def _senate_scope(actor, result):
    return True


# (from_status, to_status) -> (required role, scope check, reason required).
# Every legal move in the pipeline is enumerated here; anything absent is
# rejected, so states cannot be skipped and ratified results have no exit.
TRANSITIONS = {
    (ResultStatus.DRAFT, ResultStatus.SUBMITTED_TO_HOD): (Role.LECTURER, _owns_result, False),
    (ResultStatus.RETURNED, ResultStatus.SUBMITTED_TO_HOD): (Role.LECTURER, _owns_result, False),
    (ResultStatus.SUBMITTED_TO_HOD, ResultStatus.APPROVED_BY_HOD): (Role.HOD, _hod_scope, False),
    (ResultStatus.SUBMITTED_TO_HOD, ResultStatus.RETURNED): (Role.HOD, _hod_scope, True),
    (ResultStatus.APPROVED_BY_HOD, ResultStatus.APPROVED_BY_DEAN): (
        Role.DEAN,
        _dean_scope,
        False,
    ),
    (ResultStatus.APPROVED_BY_HOD, ResultStatus.RETURNED): (Role.DEAN, _dean_scope, True),
    (ResultStatus.APPROVED_BY_DEAN, ResultStatus.RATIFIED_BY_SENATE): (
        Role.SENATE_ADMIN,
        _senate_scope,
        False,
    ),
    (ResultStatus.APPROVED_BY_DEAN, ResultStatus.RETURNED): (
        Role.SENATE_ADMIN,
        _senate_scope,
        True,
    ),
}


def _log(*, result, actor, action, score=None, before=None, after=None, reason=""):
    """Audit write. Callers must already be inside the same transaction as the
    change being logged, so both commit or neither does."""
    ResultAuditLog.all_objects.create(
        institution=result.institution,
        result=result,
        score=score,
        actor=actor,
        action=action,
        before=before,
        after=after,
        reason=reason,
    )


def _two_dp(value):
    return str(Decimal(value).quantize(Decimal("0.01")))


def _score_snapshot(score):
    return {
        "student": str(score.student_id),
        "ca_score": _two_dp(score.ca_score),
        "exam_score": _two_dp(score.exam_score),
        "total": _two_dp(score.total),
        "grade": score.grade,
    }


def _locked_result(result_id, actor):
    """Fetch a result row-locked for the current transaction, scoped to the
    actor's institution. All state checks after this read are race-free."""
    try:
        return (
            CourseResult.all_objects.select_for_update()
            .select_related("course__department")
            .get(pk=result_id, institution_id=actor.institution_id)
        )
    except CourseResult.DoesNotExist:
        raise NotFound("Result not found.") from None


def create_draft_result(*, lecturer, course, session, semester):
    if semester.session_id != session.id:
        raise ValidationError({"semester": "Semester does not belong to the selected session."})
    if not lecturer_can_access_course(lecturer, course, session, semester):
        raise PermissionDenied("You are not assigned to this course for the selected term.")

    try:
        with transaction.atomic():
            result = CourseResult.all_objects.create(
                institution=lecturer.institution,
                course=course,
                session=session,
                semester=semester,
                lecturer=lecturer,
            )
            _log(
                result=result,
                actor=lecturer,
                action=AuditAction.RESULT_CREATED,
                after={"status": ResultStatus.DRAFT.value},
            )
    except IntegrityError:
        raise ValidationError(
            {"course": "A result sheet already exists for this course and term."}
        ) from None
    return result


def record_score(*, actor, result_id, student, exam_score, ca_score=None):
    """Create or update the current score row for a student, atomically with
    its audit entry. Locks the result so a concurrent submit cannot interleave.

    When ``ca_score`` is omitted, it is aggregated from the student's graded
    assessment items for this course term, so the CA that enters the pipeline
    comes from real graded work rather than a retyped number."""
    with transaction.atomic():
        result = _locked_result(result_id, actor)
        if not _owns_result(actor, result):
            raise PermissionDenied("Only the lecturer who owns this result sheet can enter scores.")
        if result.status not in LECTURER_EDITABLE_STATUSES:
            raise PermissionDenied("This result has been submitted and is locked for editing.")
        if not lecturer_can_access_course(actor, result.course, result.session, result.semester):
            raise PermissionDenied("You are not assigned to this course for this term.")
        if not Enrolment.all_objects.filter(
            institution_id=result.institution_id,
            student=student,
            course=result.course,
            session=result.session,
            semester=result.semester,
        ).exists():
            raise ValidationError(
                {"student": "This student is not enrolled in the course for this term."}
            )

        if ca_score is None:
            from assessments.services import aggregate_ca_for_student

            ca_score = aggregate_ca_for_student(
                result.course, result.session, result.semester, student
            )

        ca_max = Decimal(result.course.effective_ca_weight)
        exam_max = Decimal(result.course.effective_exam_weight)
        errors = {}
        if not Decimal("0") <= ca_score <= ca_max:
            errors["ca_score"] = f"CA score must be between 0 and {ca_max}."
        if not Decimal("0") <= exam_score <= exam_max:
            errors["exam_score"] = f"Exam score must be between 0 and {exam_max}."
        if errors:
            raise ValidationError(errors)

        total = ca_score + exam_score
        grade, _points = grade_for_score(result.institution, total)

        row = (
            StudentScore.all_objects.select_for_update()
            .filter(result=result, student=student, is_current=True)
            .first()
        )
        if row is None:
            row = StudentScore.all_objects.create(
                institution=result.institution,
                result=result,
                student=student,
                ca_score=ca_score,
                exam_score=exam_score,
                total=total,
                grade=grade,
            )
            _log(
                result=result,
                actor=actor,
                action=AuditAction.SCORE_ADDED,
                score=row,
                after=_score_snapshot(row),
            )
        else:
            before = _score_snapshot(row)
            row.ca_score = ca_score
            row.exam_score = exam_score
            row.total = total
            row.grade = grade
            row.save(update_fields=["ca_score", "exam_score", "total", "grade", "updated_at"])
            _log(
                result=result,
                actor=actor,
                action=AuditAction.SCORE_CHANGED,
                score=row,
                before=before,
                after=_score_snapshot(row),
            )
    return row


def transition_result(*, actor, result_id, to_status, reason=""):
    """Move a result through the pipeline. The rule table is consulted against
    the row-locked current state, so a stale client can never double-apply or
    skip a step."""
    reason = (reason or "").strip()
    with transaction.atomic():
        result = _locked_result(result_id, actor)

        rule = TRANSITIONS.get((result.status, to_status))
        if rule is None:
            raise ValidationError(
                {"status": (f"A result in state '{result.status}' cannot move to '{to_status}'.")}
            )
        required_role, scope_check, reason_required = rule
        if actor.role != required_role or not scope_check(actor, result):
            raise PermissionDenied("You cannot perform this transition on this result.")
        if reason_required and not reason:
            raise ValidationError({"reason": "A reason is required when returning a result."})
        if (
            to_status == ResultStatus.SUBMITTED_TO_HOD
            and not StudentScore.all_objects.filter(result=result, is_current=True).exists()
        ):
            raise ValidationError({"status": "Cannot submit a result sheet with no scores."})

        before = result.status
        result.status = to_status
        result.returned_reason = reason if to_status == ResultStatus.RETURNED else ""
        result.save(update_fields=["status", "returned_reason", "updated_at"])
        _log(
            result=result,
            actor=actor,
            action=AuditAction.STATUS_CHANGED,
            before={"status": before},
            after={"status": to_status.value},
            reason=reason,
        )
    return result


def submit_result(*, actor, result_id):
    return transition_result(
        actor=actor, result_id=result_id, to_status=ResultStatus.SUBMITTED_TO_HOD
    )


def visible_results(user):
    """Role-scoped queryset: lecturers see their own sheets, HODs their
    department, deans their faculty, senate/school admins the institution."""
    qs = CourseResult.objects.all()
    role = getattr(user, "role", None)
    if role == Role.LECTURER:
        return qs.filter(lecturer=user)
    if role == Role.HOD:
        return qs.filter(course__department_id=user.department_id)
    if role == Role.DEAN:
        return qs.filter(course__department__faculty_id=user.faculty_id)
    if role in (Role.SENATE_ADMIN, Role.SCHOOL_ADMIN):
        return qs
    return qs.none()


# The stage each approving role is waiting on. Combined with the role-scoped
# queryset, this yields exactly the sheets sitting in that actor's inbox.
PENDING_STAGE = {
    Role.HOD: ResultStatus.SUBMITTED_TO_HOD,
    Role.DEAN: ResultStatus.APPROVED_BY_HOD,
    Role.SENATE_ADMIN: ResultStatus.APPROVED_BY_DEAN,
    Role.SCHOOL_ADMIN: ResultStatus.APPROVED_BY_DEAN,
}

# The next state each approving role advances a sheet to when they approve it.
APPROVE_TARGET = {
    Role.HOD: ResultStatus.APPROVED_BY_HOD,
    Role.DEAN: ResultStatus.APPROVED_BY_DEAN,
    Role.SENATE_ADMIN: ResultStatus.RATIFIED_BY_SENATE,
}


def pending_results_for(user):
    """The approval worklist for ``user``: the sheets awaiting their action,
    already scoped to their department/faculty/institution."""
    stage = PENDING_STAGE.get(getattr(user, "role", None))
    if stage is None:
        return CourseResult.objects.none()
    return visible_results(user).filter(status=stage)


def approve_result(*, actor, result_id):
    """Advance a sheet one stage for the actor's role, through the guarded
    transition service (which enforces the exact from-state, role and scope)."""
    to_status = APPROVE_TARGET.get(getattr(actor, "role", None))
    if to_status is None:
        raise PermissionDenied("Your role cannot approve results.")
    return transition_result(actor=actor, result_id=result_id, to_status=to_status)


def return_result(*, actor, result_id, reason):
    """Return a sheet to the lecturer with a mandatory reason."""
    return transition_result(
        actor=actor, result_id=result_id, to_status=ResultStatus.RETURNED, reason=reason
    )


def batch_ratify(*, actor, result_ids, reason=""):
    """Ratify several dean-approved sheets in one senate action. All-or-nothing:
    every sheet goes through the guarded transition (so each is scope-checked,
    row-locked and audited); if any one is not ratifiable the whole batch rolls
    back and nothing is committed."""
    if not result_ids:
        raise ValidationError({"result_ids": "Provide at least one result to ratify."})
    ratified = []
    with transaction.atomic():
        for result_id in result_ids:
            ratified.append(
                transition_result(
                    actor=actor,
                    result_id=result_id,
                    to_status=ResultStatus.RATIFIED_BY_SENATE,
                    reason=reason,
                )
            )
    return ratified


# --------------------------------------------------------------------------- #
# Departmental Board anomaly indicators                                        #
# --------------------------------------------------------------------------- #

HIGH_FAILURE_RATE_THRESHOLD = Decimal("0.50")
HIGH_DISTINCTION_RATE_THRESHOLD = Decimal("0.50")


def compute_anomaly_stats(result):
    """Summary statistics a Departmental Board vets a submitted sheet on:
    failure rate, per-letter grade distribution, class average, and flags for an
    unusually high failure rate or an abnormally high share of top grades. All
    computed server-side from the current score rows."""
    rows = list(
        StudentScore.all_objects.filter(result=result, is_current=True).values_list(
            "total", "grade"
        )
    )
    letters = [letter for _min_score, letter, _points in scale_bands(result.institution)]
    distribution = dict.fromkeys(letters, 0)

    n = len(rows)
    if n == 0:
        return {
            "total_students": 0,
            "class_average": None,
            "highest_score": None,
            "lowest_score": None,
            "failure_count": 0,
            "failure_rate": "0.00",
            "grade_distribution": distribution,
            "flags": {"high_failure_rate": False, "abnormally_high_grades": False},
        }

    pass_mark = Decimal(result.institution.pass_mark)
    totals = []
    total_sum = Decimal("0")
    failure_count = 0
    for total, grade in rows:
        total = Decimal(total)
        totals.append(total)
        total_sum += total
        distribution[grade] = distribution.get(grade, 0) + 1
        if total < pass_mark:
            failure_count += 1

    class_average = (total_sum / n).quantize(Decimal("0.01"))
    failure_rate = (Decimal(failure_count) / n).quantize(Decimal("0.01"))
    top_letter = letters[0] if letters else None
    distinction_count = distribution.get(top_letter, 0) if top_letter is not None else 0
    distinction_rate = Decimal(distinction_count) / n

    return {
        "total_students": n,
        "class_average": _two_dp(class_average),
        "highest_score": _two_dp(max(totals)),
        "lowest_score": _two_dp(min(totals)),
        "failure_count": failure_count,
        "failure_rate": str(failure_rate),
        "grade_distribution": distribution,
        "flags": {
            "high_failure_rate": failure_rate > HIGH_FAILURE_RATE_THRESHOLD,
            "abnormally_high_grades": distinction_rate > HIGH_DISTINCTION_RATE_THRESHOLD,
        },
    }


# --------------------------------------------------------------------------- #
# External examiner capture (Faculty / Dean level)                            #
# --------------------------------------------------------------------------- #


def create_external_examiner_report(
    *,
    actor,
    programme,
    session,
    semester,
    examiner_name,
    examiner_institution,
    audit_date,
    remarks="",
):
    if semester.session_id != session.id:
        raise ValidationError({"semester": "Semester does not belong to the selected session."})
    faculty_id = programme.department.faculty_id
    if actor.role == Role.DEAN and actor.faculty_id != faculty_id:
        raise PermissionDenied(
            "You can only capture examiner reports for programmes in your own faculty."
        )
    return ExternalExaminerReport.all_objects.create(
        institution=actor.institution,
        faculty_id=faculty_id,
        programme=programme,
        session=session,
        semester=semester,
        examiner_name=examiner_name,
        examiner_institution=examiner_institution,
        audit_date=audit_date,
        remarks=remarks,
        created_by=actor,
    )


def visible_examiner_reports(user):
    qs = ExternalExaminerReport.objects.all()
    role = getattr(user, "role", None)
    if role == Role.DEAN:
        return qs.filter(faculty_id=user.faculty_id)
    if role in (Role.SENATE_ADMIN, Role.SCHOOL_ADMIN):
        return qs
    return qs.none()


# --------------------------------------------------------------------------- #
# Result amendment workflow                                                    #
# --------------------------------------------------------------------------- #


def _amend_hod_scope(actor, amendment):
    return _hod_scope(actor, amendment.result)


def _amend_dean_scope(actor, amendment):
    return _dean_scope(actor, amendment.result)


def _amend_senate_scope(actor, amendment):
    return True


# Mirrors the result pipeline's rule table but for an amendment's own chain.
AMENDMENT_TRANSITIONS = {
    (AmendmentStatus.PENDING_HOD, AmendmentStatus.APPROVED_BY_HOD): (
        Role.HOD,
        _amend_hod_scope,
        False,
    ),
    (AmendmentStatus.PENDING_HOD, AmendmentStatus.RETURNED): (Role.HOD, _amend_hod_scope, True),
    (AmendmentStatus.APPROVED_BY_HOD, AmendmentStatus.APPROVED_BY_DEAN): (
        Role.DEAN,
        _amend_dean_scope,
        False,
    ),
    (AmendmentStatus.APPROVED_BY_HOD, AmendmentStatus.RETURNED): (
        Role.DEAN,
        _amend_dean_scope,
        True,
    ),
    (AmendmentStatus.APPROVED_BY_DEAN, AmendmentStatus.APPLIED): (
        Role.SENATE_ADMIN,
        _amend_senate_scope,
        False,
    ),
    (AmendmentStatus.APPROVED_BY_DEAN, AmendmentStatus.RETURNED): (
        Role.SENATE_ADMIN,
        _amend_senate_scope,
        True,
    ),
}

AMENDMENT_APPROVE_TARGET = {
    Role.HOD: AmendmentStatus.APPROVED_BY_HOD,
    Role.DEAN: AmendmentStatus.APPROVED_BY_DEAN,
    Role.SENATE_ADMIN: AmendmentStatus.APPLIED,
}


def _can_raise_amendment(actor, result):
    role = getattr(actor, "role", None)
    if role == Role.LECTURER:
        return _owns_result(actor, result)
    if role == Role.HOD:
        return _hod_scope(actor, result)
    if role == Role.DEAN:
        return _dean_scope(actor, result)
    if role in (Role.SENATE_ADMIN, Role.SCHOOL_ADMIN):
        return True
    return False


def _locked_amendment(amendment_id, actor):
    try:
        return (
            ResultAmendment.all_objects.select_for_update()
            .select_related("result__course__department", "student", "original_score")
            .get(pk=amendment_id, institution_id=actor.institution_id)
        )
    except ResultAmendment.DoesNotExist:
        raise NotFound("Amendment not found.") from None


def raise_amendment(
    *, actor, result_id, student, proposed_ca_score, proposed_exam_score, justification
):
    """Raise a correction against a ratified result. The original score row is
    only referenced, never touched; the amendment then runs its own approval
    chain and, once ratified, supersedes that row."""
    justification = (justification or "").strip()
    if not justification:
        raise ValidationError(
            {"justification": "A justification is required to raise an amendment."}
        )
    with transaction.atomic():
        result = _locked_result(result_id, actor)
        if result.status != ResultStatus.RATIFIED_BY_SENATE:
            raise ValidationError({"result": "Only a ratified result can be amended."})
        if not _can_raise_amendment(actor, result):
            raise PermissionDenied("You are not permitted to raise an amendment on this result.")

        original = (
            StudentScore.all_objects.filter(result=result, student=student, is_current=True)
            .select_related("student")
            .first()
        )
        if original is None:
            raise ValidationError(
                {"student": "This student has no current score on this result to amend."}
            )

        ca_max = Decimal(result.course.effective_ca_weight)
        exam_max = Decimal(result.course.effective_exam_weight)
        errors = {}
        if not Decimal("0") <= proposed_ca_score <= ca_max:
            errors["proposed_ca_score"] = f"CA score must be between 0 and {ca_max}."
        if not Decimal("0") <= proposed_exam_score <= exam_max:
            errors["proposed_exam_score"] = f"Exam score must be between 0 and {exam_max}."
        if errors:
            raise ValidationError(errors)

        total = proposed_ca_score + proposed_exam_score
        grade, _points = grade_for_score(result.institution, total)

        amendment = ResultAmendment.all_objects.create(
            institution=result.institution,
            result=result,
            student=student,
            original_score=original,
            proposed_ca_score=proposed_ca_score,
            proposed_exam_score=proposed_exam_score,
            proposed_total=total,
            proposed_grade=grade,
            justification=justification,
            status=AmendmentStatus.PENDING_HOD,
            raised_by=actor,
        )
        _log(
            result=result,
            actor=actor,
            action=AuditAction.AMENDMENT_STATUS_CHANGED,
            before={"amendment_status": None},
            after={
                "amendment": str(amendment.id),
                "amendment_status": AmendmentStatus.PENDING_HOD.value,
            },
            reason=justification,
        )
    return amendment


def _apply_amendment(actor, amendment):
    """Supersede the original score row with the proposed values. The original
    row keeps its values forever and only loses currency via ``is_current``."""
    result = amendment.result
    original = (
        StudentScore.all_objects.select_for_update()
        .filter(result=result, student_id=amendment.student_id, is_current=True)
        .first()
    )
    if original is None:
        raise ValidationError({"student": "The score being amended is no longer current."})

    before = _score_snapshot(original)
    original.is_current = False
    original.save(update_fields=["is_current", "updated_at"])

    new_row = StudentScore.all_objects.create(
        institution=result.institution,
        result=result,
        student_id=amendment.student_id,
        ca_score=amendment.proposed_ca_score,
        exam_score=amendment.proposed_exam_score,
        total=amendment.proposed_total,
        grade=amendment.proposed_grade,
        supersedes=original,
        is_current=True,
    )
    amendment.applied_score = new_row
    _log(
        result=result,
        actor=actor,
        action=AuditAction.SCORE_SUPERSEDED,
        score=new_row,
        before=before,
        after=_score_snapshot(new_row),
        reason=amendment.justification,
    )


def amendment_transition(*, actor, amendment_id, to_status, reason=""):
    """Move an amendment through its own approval chain, guarded by the rule
    table against its row-locked current state. The final APPLIED move performs
    the supersession atomically with the audit write."""
    reason = (reason or "").strip()
    with transaction.atomic():
        amendment = _locked_amendment(amendment_id, actor)

        rule = AMENDMENT_TRANSITIONS.get((amendment.status, to_status))
        if rule is None:
            raise ValidationError(
                {
                    "status": (
                        f"An amendment in state '{amendment.status}' cannot move to '{to_status}'."
                    )
                }
            )
        required_role, scope_check, reason_required = rule
        if actor.role != required_role or not scope_check(actor, amendment):
            raise PermissionDenied("You cannot perform this transition on this amendment.")
        if reason_required and not reason:
            raise ValidationError({"reason": "A reason is required when returning an amendment."})

        before = amendment.status
        if to_status == AmendmentStatus.APPLIED:
            _apply_amendment(actor, amendment)
        amendment.status = to_status
        amendment.returned_reason = reason if to_status == AmendmentStatus.RETURNED else ""
        amendment.save(update_fields=["status", "returned_reason", "applied_score", "updated_at"])
        _log(
            result=amendment.result,
            actor=actor,
            action=AuditAction.AMENDMENT_STATUS_CHANGED,
            before={"amendment": str(amendment.id), "amendment_status": before},
            after={"amendment": str(amendment.id), "amendment_status": to_status.value},
            reason=reason,
        )
    return amendment


def approve_amendment(*, actor, amendment_id):
    to_status = AMENDMENT_APPROVE_TARGET.get(getattr(actor, "role", None))
    if to_status is None:
        raise PermissionDenied("Your role cannot approve amendments.")
    return amendment_transition(actor=actor, amendment_id=amendment_id, to_status=to_status)


def return_amendment(*, actor, amendment_id, reason):
    return amendment_transition(
        actor=actor, amendment_id=amendment_id, to_status=AmendmentStatus.RETURNED, reason=reason
    )


def visible_amendments(user):
    """Role-scoped amendment queryset, mirroring ``visible_results``."""
    qs = ResultAmendment.objects.all()
    role = getattr(user, "role", None)
    if role == Role.LECTURER:
        return qs.filter(result__lecturer=user)
    if role == Role.HOD:
        return qs.filter(result__course__department_id=user.department_id)
    if role == Role.DEAN:
        return qs.filter(result__course__department__faculty_id=user.faculty_id)
    if role in (Role.SENATE_ADMIN, Role.SCHOOL_ADMIN):
        return qs
    return qs.none()
