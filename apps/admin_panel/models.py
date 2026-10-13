from django.db import models
from django.conf import settings
import json


class AdminAuditLog(models.Model):
    """Tracks every significant administrative action for compliance and accountability."""
    class Actions(models.TextChoices):
        CREATE = 'CREATE', 'Create'
        UPDATE = 'UPDATE', 'Update'
        DELETE = 'DELETE', 'Delete'
        RETRY = 'RETRY', 'Retry Task'
        CONFIG_CHANGE = 'CONFIG_CHANGE', 'Config Change'
        LOGIN = 'LOGIN', 'Login'
        EXPORT = 'EXPORT', 'Export'

    admin_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='admin_audit_logs'
    )
    action = models.CharField(max_length=20, choices=Actions.choices)
    entity_type = models.CharField(max_length=100)
    entity_id = models.IntegerField(null=True, blank=True)
    description = models.TextField(blank=True, default='')
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at'], name='idx_audit_created_at'),
            models.Index(fields=['entity_type', 'entity_id'], name='idx_audit_entity'),
        ]

    def __str__(self):
        return f"[{self.action}] {self.entity_type} #{self.entity_id} by {self.admin_user}"

    @classmethod
    def log_action(cls, admin_user, action, entity_type, entity_id=None, description='', metadata=None, request=None):
        ip = None
        if request:
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                ip = x_forwarded_for.split(',')[0].strip()
            else:
                ip = request.META.get('REMOTE_ADDR')

        return cls.objects.create(
            admin_user=admin_user if getattr(admin_user, 'is_authenticated', False) else None,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            description=description,
            metadata=metadata or {},
            ip_address=ip
        )


class SystemConfig(models.Model):
    """Runtime-configurable settings editable by Super Admins."""
    key = models.CharField(max_length=100, unique=True, db_index=True)
    value = models.TextField(default='')
    value_type = models.CharField(
        max_length=20,
        default='string',
        choices=[
            ('string', 'String'),
            ('int', 'Integer'),
            ('float', 'Float'),
            ('bool', 'Boolean'),
            ('json', 'JSON')
        ]
    )
    description = models.TextField(blank=True, default='')
    is_sensitive = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_system_configs'
    )

    class Meta:
        ordering = ['key']

    def __str__(self):
        return f"{self.key} = {'***' if self.is_sensitive else self.value}"

    def get_typed_value(self):
        if self.value_type == 'int':
            try:
                return int(self.value)
            except ValueError:
                return 0
        elif self.value_type == 'float':
            try:
                return float(self.value)
            except ValueError:
                return 0.0
        elif self.value_type == 'bool':
            return self.value.strip().lower() in ('true', '1', 'yes', 't', 'y')
        elif self.value_type == 'json':
            try:
                return json.loads(self.value)
            except Exception:
                return {}
        return self.value


class AdminNotification(models.Model):
    """In-app role-targeted alerts for system anomalies, budget thresholds, and failures."""
    class Categories(models.TextChoices):
        DEV_ALERT = 'DEV_ALERT', 'Developer Alert'
        SUPPORT_ALERT = 'SUPPORT_ALERT', 'Support Alert'
        FINANCIAL_ALERT = 'FINANCIAL_ALERT', 'Financial Alert'

    class Severities(models.TextChoices):
        INFO = 'INFO', 'Info'
        WARNING = 'WARNING', 'Warning'
        CRITICAL = 'CRITICAL', 'Critical'

    title = models.CharField(max_length=255)
    message = models.TextField()
    category = models.CharField(max_length=20, choices=Categories.choices)
    severity = models.CharField(max_length=15, choices=Severities.choices, default=Severities.INFO)
    is_read = models.BooleanField(default=False)
    read_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='read_admin_notifications'
    )
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    link = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['category', 'is_read'], name='idx_notif_cat_read'),
        ]

    def __str__(self):
        return f"[{self.severity}] {self.title} ({self.category})"


import secrets
from datetime import timedelta
from django.utils import timezone


def _admin_invitation_expiry():
    return timezone.now() + timedelta(hours=72)


class AdminInvitation(models.Model):
    """
    Tracks pending platform administrator invitations.
    Invites are sent by the Super Admin with a specific admin role (SUPER_ADMIN, DEVELOPER, SUPPORT).
    Invitee receives an email with a secure token to set their password and activate their admin account.
    """
    class Statuses(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        ACCEPTED = 'ACCEPTED', 'Accepted'
        EXPIRED = 'EXPIRED', 'Expired'
        REVOKED = 'REVOKED', 'Revoked'

    class AdminRoles(models.TextChoices):
        SUPER_ADMIN = 'SUPER_ADMIN', 'Super Admin'
        DEVELOPER = 'DEVELOPER', 'Developer'
        SUPPORT = 'SUPPORT', 'Support'

    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_admin_invitations'
    )
    email = models.EmailField()
    admin_role = models.CharField(
        max_length=20,
        choices=AdminRoles.choices,
        default=AdminRoles.SUPPORT
    )
    token = models.CharField(max_length=64, unique=True, editable=False)
    status = models.CharField(
        max_length=10,
        choices=Statuses.choices,
        default=Statuses.PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=_admin_invitation_expiry)
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(48)
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_valid(self):
        return self.status == self.Statuses.PENDING and not self.is_expired

    def __str__(self):
        return f"Admin Invite for {self.email} [{self.admin_role}] - {self.status}"
