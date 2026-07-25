from celery import shared_task
from django.core.files.base import ContentFile

from results.exports import build_broadsheet_xlsx
from results.models import ExportJob


@shared_task
def generate_broadsheet(export_job_id):
    """Render a broadsheet for a large class off the request path and store the
    file on its ExportJob. Read-only with respect to the result: it only reads
    score rows and writes the job's own file/status."""
    job = ExportJob.all_objects.select_related(
        "institution", "result__course", "result__session", "result__semester", "result__lecturer"
    ).get(pk=export_job_id)
    try:
        job.status = ExportJob.Status.PROCESSING
        job.save(update_fields=["status", "updated_at"])
        data = build_broadsheet_xlsx(job.result)
        job.file.save(job.filename, ContentFile(data), save=False)
        job.status = ExportJob.Status.COMPLETED
        job.save(update_fields=["file", "status", "updated_at"])
    except Exception as exc:  # noqa: BLE001 - persist failure then re-raise for the worker log
        job.status = ExportJob.Status.FAILED
        job.message = str(exc)[:255]
        job.save(update_fields=["status", "message", "updated_at"])
        raise
    return str(job.id)
