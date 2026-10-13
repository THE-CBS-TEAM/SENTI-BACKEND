"""
Modular Email Service
=====================
Development: uses Django's console backend — emails print to stdout.
             No configuration needed. Set in settings.py:
             EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

Production (Mailjet):
    1. Set EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    2. Set MAILJET_API_KEY and MAILJET_SECRET_KEY in .env
    3. Settings maps those to EMAIL_HOST_USER / EMAIL_HOST_PASSWORD automatically.

All invitation emails go through the helpers here, so swapping providers
never requires touching invitation business logic.
"""

import logging
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings

logger = logging.getLogger(__name__)

FRONTEND_URL = getattr(settings, "FRONTEND_URL", "http://localhost:3000")
DEFAULT_FROM = getattr(settings, "DEFAULT_FROM_EMAIL", "Sentimentri <noreply@sentimentri.com>")


def _send(subject, html_template, txt_template, context, recipient_email):
    """
    Internal dispatch: renders both HTML and plaintext templates, then
    calls Django's send_mail which routes to whatever EMAIL_BACKEND is configured.
    """
    try:
        html_body = render_to_string(html_template, context)
        txt_body = render_to_string(txt_template, context)
        send_mail(
            subject=subject,
            message=txt_body,
            from_email=DEFAULT_FROM,
            recipient_list=[recipient_email],
            html_message=html_body,
            fail_silently=False,
        )
        logger.info("Email '%s' sent to %s", subject, recipient_email)
        return True
    except Exception as exc:
        logger.error("Failed to send email '%s' to %s: %s", subject, recipient_email, exc)
        return False


# ─── Workspace Invitations ───────────────────────────────────────────────────

def send_workspace_invitation(invitation):
    """
    Sends a workspace join invitation email.
    invitation: WorkspaceInvitation instance
    """
    accept_url = f"{FRONTEND_URL}/invite/accept?token={invitation.token}"
    logger.info(
        "\n%s\n[SENTRIMETRI WORKSPACE INVITATION]\nRecipient: %s\nWorkspace: %s (%s)\nDirect Accept URL: %s\n%s",
        "=" * 80,
        invitation.email,
        invitation.workspace.name,
        invitation.role,
        accept_url,
        "=" * 80,
    )
    context = {
        "inviter_name": invitation.invited_by.get_full_name() or invitation.invited_by.email,
        "workspace_name": invitation.workspace.name,
        "role": invitation.role.title(),
        "accept_url": accept_url,
        "expires_in_hours": 72,
        "frontend_url": FRONTEND_URL,
    }
    return _send(
        subject=f"You've been invited to join {invitation.workspace.name} on Sentimentri",
        html_template="emails/workspace_invitation.html",
        txt_template="emails/workspace_invitation.txt",
        context=context,
        recipient_email=invitation.email,
    )


# ─── Admin Invitations ───────────────────────────────────────────────────────

def send_admin_invitation(invitation):
    """
    Sends a Sentimentri platform admin invitation email.
    invitation: AdminInvitation instance
    """
    accept_url = f"{FRONTEND_URL}/admin/invite/accept?token={invitation.token}"
    role_display = {
        "SUPER_ADMIN": "Super Admin",
        "DEVELOPER": "Developer",
        "SUPPORT": "Support",
    }.get(invitation.admin_role, invitation.admin_role.title())

    logger.info(
        "\n%s\n[SENTRIMETRI ADMIN INVITATION]\nRecipient: %s\nRole: %s\nDirect Accept URL: %s\n%s",
        "=" * 80,
        invitation.email,
        role_display,
        accept_url,
        "=" * 80,
    )

    context = {
        "inviter_name": invitation.invited_by.get_full_name() or invitation.invited_by.email,
        "role": role_display,
        "accept_url": accept_url,
        "expires_in_hours": 72,
        "frontend_url": FRONTEND_URL,
    }
    return _send(
        subject=f"You've been invited as {role_display} on Sentimentri Platform",
        html_template="emails/admin_invitation.html",
        txt_template="emails/admin_invitation.txt",
        context=context,
        recipient_email=invitation.email,
    )
