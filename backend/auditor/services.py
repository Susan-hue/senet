"""Auditor Vault services: token lifecycle and the read-only data an auditor
token is allowed to see. Every query here is filtered to the token's institution
and to its programme/session scope, so a token can never reach across tenants or
outside its remit."""

from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from accounts.models import Role
from assessments.models import AssessmentItem
from auditor.models import AuditorToken, generate_raw_token, hash_token
from results.models import (
    AuditAction,
    CourseResult,
    ExternalExaminerReport,
    ResultAuditLog,
    ResultStatus,
)
from results.services import compute_anomaly_stats


def create_auditor_token(*, actor, label, expires_at, programmes=(), sessions=()):
    """Mint a token for a NUC auditor. Returns ``(token, raw_token)``; the raw
    token is shown to the admin exactly once and never stored."""
    if actor.role != Role.SCHOOL_ADMIN:
        raise PermissionDenied("Only a School Administrator can create auditor tokens.")
    programmes = list(programmes)
    sessions = list(sessions)
    if not programmes and not sessions:
        raise ValidationError({"scope": "Scope the token to at least one programme or session."})
    if expires_at <= timezone.now():
        raise ValidationError({"expires_at": "Expiry must be in the future."})

    raw = generate_raw_token()
    token = AuditorToken.all_objects.create(
        institution=actor.institution,
        label=label,
        token_hash=hash_token(raw),
        created_by=actor,
        expires_at=expires_at,
    )
    token.programmes.set(programmes)
    token.sessions.set(sessions)
    return token, raw


def revoke_auditor_token(*, actor, token):
    if actor.role != Role.SCHOOL_ADMIN:
        raise PermissionDenied("Only a School Administrator can revoke auditor tokens.")
    if token.revoked_at is None:
        token.revoked_at = timezone.now()
        token.save(update_fields=["revoked_at", "updated_at"])
    return token


def _scope_department_ids(token):
    return list(token.programmes.values_list("department_id", flat=True))


def _scope_programme_ids(token):
    return list(token.programmes.values_list("id", flat=True))


def _scope_session_ids(token):
    return list(token.sessions.values_list("id", flat=True))


def auditor_visible_results(token):
    """Ratified results within the token's institution and programme/session
    scope. Only ratified sheets are ever exposed to an auditor."""
    qs = CourseResult.all_objects.filter(
        institution_id=token.institution_id, status=ResultStatus.RATIFIED_BY_SENATE
    ).select_related("course__department", "session", "semester", "lecturer")

    department_ids = _scope_department_ids(token)
    if department_ids:
        qs = qs.filter(course__department_id__in=department_ids)
    session_ids = _scope_session_ids(token)
    if session_ids:
        qs = qs.filter(session_id__in=session_ids)
    return qs.order_by("-created_at")


def auditor_result_or_none(token, pk):
    return auditor_visible_results(token).filter(pk=pk).first()


def auditor_visible_examiner_reports(token):
    qs = ExternalExaminerReport.all_objects.filter(
        institution_id=token.institution_id
    ).select_related("faculty", "programme", "session", "semester")
    programme_ids = _scope_programme_ids(token)
    if programme_ids:
        qs = qs.filter(programme_id__in=programme_ids)
    session_ids = _scope_session_ids(token)
    if session_ids:
        qs = qs.filter(session_id__in=session_ids)
    return qs.order_by("-audit_date")


def senate_approval_log(result):
    """The approval/ratification trail for a result, drawn from the audit log."""
    entries = (
        ResultAuditLog.all_objects.filter(result=result, action=AuditAction.STATUS_CHANGED)
        .select_related("actor")
        .order_by("created_at")
    )
    return [
        {
            "actor": entry.actor.full_name if entry.actor_id else None,
            "actor_role": entry.actor.role if entry.actor_id else None,
            "from_status": (entry.before or {}).get("status"),
            "to_status": (entry.after or {}).get("status"),
            "reason": entry.reason,
            "at": entry.created_at,
        }
        for entry in entries
    ]


def marking_scheme(result):
    """The lecturer's captured CA marking scheme (assessment items) for the
    result's course term, if any were recorded."""
    items = AssessmentItem.all_objects.filter(
        institution_id=result.institution_id,
        course_id=result.course_id,
        session_id=result.session_id,
        semester_id=result.semester_id,
    ).order_by("due_date", "created_at")
    return [
        {
            "title": item.title,
            "kind": item.kind,
            "max_score": f"{item.max_score:.2f}",
            "weight": f"{item.weight:.2f}",
        }
        for item in items
    ]


def result_dossier(result):
    """Everything an auditor may read about one ratified result."""
    return {
        "statistics": compute_anomaly_stats(result),
        "approval_log": senate_approval_log(result),
        "marking_scheme": marking_scheme(result),
    }
