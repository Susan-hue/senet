import logging

from celery import shared_task
from django.conf import settings

from accounts.emails import frontend_url, send_branded_email
from accounts.importers import (
    ImportFileError,
    import_assignments,
    import_courses,
    import_students,
)
from accounts.models import ImportJob
from tenancy.models import Institution

logger = logging.getLogger(__name__)

_IMPORTERS = {
    ImportJob.Kind.STUDENT: import_students,
    ImportJob.Kind.COURSE: import_courses,
    ImportJob.Kind.ASSIGNMENT: import_assignments,
}


@shared_task
def send_verification_email(email, token):
    send_branded_email(
        to=email,
        subject="Confirm your email address",
        template="verify_email",
        context={
            "link": frontend_url("/verify-email", token=token),
            "expiry_hours": settings.EMAIL_VERIFICATION_MAX_AGE // 3600,
        },
    )


@shared_task
def send_password_reset_email(email, token):
    send_branded_email(
        to=email,
        subject="Reset your Senet password",
        template="password_reset",
        context={
            "link": frontend_url("/reset-password", token=token),
            "expiry_hours": settings.PASSWORD_RESET_MAX_AGE // 3600,
        },
    )


def _fail_import(job, message):
    job.status = ImportJob.Status.FAILED
    job.message = message
    job.save(update_fields=["status", "message", "updated_at"])


@shared_task
def run_import_job(job_id, institution_id, kind, text):
    job = ImportJob.all_objects.filter(pk=job_id).first()
    if job is None:
        return

    job.status = ImportJob.Status.PROCESSING
    job.save(update_fields=["status", "updated_at"])

    institution = Institution.objects.filter(pk=institution_id).first()
    if institution is None:
        _fail_import(job, "Institution not found.")
        return

    importer = _IMPORTERS[kind]
    try:
        result = importer(institution, text)
    except ImportFileError as exc:
        _fail_import(job, str(exc))
        return
    except Exception:  # noqa: BLE001 - any failure rolls back; record and surface it
        # The job row only carries a message an admin can read; the traceback is
        # the only way to find out what actually broke, so it goes to the log.
        logger.exception("Import job %s (%s) failed unexpectedly", job.id, kind)
        _fail_import(job, "Import failed due to an unexpected error.")
        return

    job.status = ImportJob.Status.COMPLETED
    job.total_rows = result.total
    job.created_count = result.created
    job.skipped_count = result.skipped
    job.errors = result.errors
    job.message = result.message
    job.save(
        update_fields=[
            "status",
            "total_rows",
            "created_count",
            "skipped_count",
            "errors",
            "message",
            "updated_at",
        ]
    )
