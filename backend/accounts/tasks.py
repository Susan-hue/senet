from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail


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
