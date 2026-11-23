from django.core.mail import send_mail
from django.conf import settings


def send_otp_email(to_email, code, first_name=''):
    subject = 'Your GEIZMO Verification Code'
    message = f"""Hi {first_name},

Your GEIZMO email verification code is:

    {code}

This code expires in 10 minutes. Do not share it with anyone.

If you did not request this, please ignore this email.

— The GEIZMO Team
"""
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [to_email],
        fail_silently=False,
    )


def send_approval_email(to_email, first_name=''):
    subject = 'Your GEIZMO Lecturer Account Has Been Approved'
    message = f"""Hi {first_name},

Great news! Your GEIZMO lecturer account has been approved by an administrator.

You can now sign in at:
http://127.0.0.1:8000/login/lecturer/

— The GEIZMO Team
"""
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [to_email],
        fail_silently=False,
    )


def send_maintenance_email(to_email, first_name='', message=''):
    subject = '⚙️ GEIZMO Platform — Scheduled Maintenance'
    body = f"""Hi {first_name},

We wanted to let you know that the GEIZMO platform is currently undergoing scheduled maintenance.

{message}

During this time you will not be able to access the platform. We apologise for any inconvenience and will notify you as soon as we are back online.

Thank you for your patience.

— The GEIZMO Team
"""
    send_mail(
        subject,
        body,
        settings.DEFAULT_FROM_EMAIL,
        [to_email],
        fail_silently=True,
    )


def send_maintenance_over_email(to_email, first_name=''):
    subject = '✅ GEIZMO is Back Online'
    body = f"""Hi {first_name},

Great news — the GEIZMO platform is back online and fully operational.

You can sign in at:
http://127.0.0.1:8000/

— The GEIZMO Team
"""
    send_mail(
        subject,
        body,
        settings.DEFAULT_FROM_EMAIL,
        [to_email],
        fail_silently=True,
    )