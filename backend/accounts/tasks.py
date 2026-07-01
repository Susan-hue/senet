from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

from accounts.importers import ImportFileError, import_courses, import_students
from accounts.models import ImportJob
from tenancy.models import Institution


@shared_task
def send_verification_email(email, token):
    link = f"{settings.FRONTEND_URL}/verify-email?token={token}"
    send_mail(
        subject="Verify your email address",
        message=f"Confirm your account by visiting this link:\n{link}",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
    )


@shared_task
def send_password_reset_email(email, token):
    link = f"{settings.FRONTEND_URL}/reset-password?token={token}"
    send_mail(
        subject="Reset your password",
        message=f"Reset your password by visiting this link:\n{link}",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
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

    importer = import_students if kind == ImportJob.Kind.STUDENT else import_courses
    try:
        result = importer(institution, text)
    except ImportFileError as exc:
        _fail_import(job, str(exc))
        return
    except Exception:  # noqa: BLE001 - any failure rolls back; record and surface it
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
