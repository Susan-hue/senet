import threading

from django.db import models

_thread_locals = threading.local()


def set_current_institution(institution):
    _thread_locals.institution = institution


def get_current_institution():
    return getattr(_thread_locals, "institution", None)


def clear_current_institution():
    if hasattr(_thread_locals, "institution"):
        del _thread_locals.institution


class TenantManager(models.Manager):
    def get_queryset(self):
        qs = super().get_queryset()
        institution = get_current_institution()
        if institution is not None:
            return qs.filter(institution=institution)
        return qs.none()


class TenantScopedModel(models.Model):
    institution = models.ForeignKey(
        "tenancy.Institution", on_delete=models.PROTECT, related_name="+"
    )

    objects = TenantManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.institution_id is None:
            current = get_current_institution()
            if current is not None:
                self.institution = current
        super().save(*args, **kwargs)
