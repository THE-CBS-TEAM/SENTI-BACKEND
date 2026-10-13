from django.db import models
from django.contrib.auth.models import AbstractUser
import secrets
from django.utils import timezone
from datetime import timedelta


class User(AbstractUser):
    class Roles(models.TextChoices):
        ADMIN = 'ADMIN', 'Admin'
        VIEWER = 'VIEWER', 'Viewer'

    class AdminRoles(models.TextChoices):
        SUPER_ADMIN = 'SUPER_ADMIN', 'Super Admin'
        DEVELOPER = 'DEVELOPER', 'Developer'
        SUPPORT = 'SUPPORT', 'Support'

    email = models.EmailField(unique=True)
    role = models.CharField(
        max_length=10,
        choices=Roles.choices,
        default=Roles.ADMIN
    )
    is_platform_admin = models.BooleanField(
        default=False,
        help_text='Designates whether this user has access to the internal operations admin panel.'
    )
    admin_role = models.CharField(
        max_length=20,
        choices=AdminRoles.choices,
        default=AdminRoles.SUPPORT,
        blank=True,
        null=True,
        help_text='Tiered operational role for platform administration.'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    # Use email for username
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    def __str__(self):
        return f"{self.email} ({self.role})"


class Workspace(models.Model):
    class Types(models.TextChoices):
        AGENCY = 'AGENCY', 'Agency'
        BRAND = 'BRAND', 'Brand'

    name = models.CharField(max_length=255)
    type = models.CharField(
        max_length=10,
        choices=Types.choices,
        default=Types.BRAND
    )
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='owned_workspaces'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    show_authenticity_scores = models.BooleanField(default=False)
    use_llm_sentiment_analysis = models.BooleanField(default=True)

    # Campaign Tracking thresholds & aging
    t1_max_age_hours = models.IntegerField(default=24)
    t1_interval_hours = models.IntegerField(default=2)
    t2_max_age_hours = models.IntegerField(default=72)
    t2_interval_hours = models.IntegerField(default=6)
    t3_max_age_hours = models.IntegerField(default=168)
    t3_interval_hours = models.IntegerField(default=24)

    # Document Layout styling for PDF reports
    proposal_theme = models.CharField(max_length=10, default='DARK')
    proposal_primary_color = models.CharField(max_length=7, default='#8B5CF6')
    proposal_font_style = models.CharField(max_length=15, default='POPPINS')
    proposal_show_watermark = models.BooleanField(default=True)

    report_theme = models.CharField(max_length=10, default='DARK')
    report_primary_color = models.CharField(max_length=7, default='#8B5CF6')
    report_font_style = models.CharField(max_length=15, default='POPPINS')
    report_show_watermark = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.type})"


class AICreditUsage(models.Model):
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name='ai_credit_usages'
    )
    feature = models.CharField(max_length=255)
    model_name = models.CharField(max_length=100, default='deepseek-chat')
    prompt_tokens = models.IntegerField(default=0)
    completion_tokens = models.IntegerField(default=0)
    total_tokens = models.IntegerField(default=0)
    cost = models.DecimalField(max_digits=10, decimal_places=6, default=0.0)
    metadata = models.JSONField(blank=True, null=True, default=dict)
    used_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-used_at']

    def __str__(self):
        return f"{self.workspace.name} - {self.feature} - {self.total_tokens} tokens"


class WorkspaceMembership(models.Model):
    class Roles(models.TextChoices):
        ADMIN = 'ADMIN', 'Admin'
        VIEWER = 'VIEWER', 'Viewer'

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name='memberships'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='workspace_memberships'
    )
    role = models.CharField(
        max_length=10,
        choices=Roles.choices,
        default=Roles.VIEWER
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('workspace', 'user')

    def __str__(self):
        return f"{self.user.email} in {self.workspace.name} ({self.role})"


class Brand(models.Model):
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name='brands'
    )
    name = models.CharField(max_length=255)
    logo_url = models.URLField(max_length=500, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


# ─────────────────────────────────────────────────────────────────────────────
# Invitation System
# ─────────────────────────────────────────────────────────────────────────────

def _invitation_expiry():
    """72-hour expiry window for all invitation tokens."""
    return timezone.now() + timedelta(hours=72)


class WorkspaceInvitation(models.Model):
    """
    Tracks pending email invitations to join a workspace.

    Flow:
      1. Workspace owner (or ADMIN member) sends invite → creates this record + emails token.
      2. Invitee clicks link → POST /auth/accept-invite/ with token.
      3. Backend validates token (not expired, status=PENDING) → creates WorkspaceMembership.
      4. Token is single-use: status set to ACCEPTED immediately.

    Protection:
      - The workspace owner cannot be removed by members — enforced in views/permissions.
      - An ADMIN member can invite others but cannot change the owner's role.
    """
    class Statuses(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        ACCEPTED = 'ACCEPTED', 'Accepted'
        EXPIRED = 'EXPIRED', 'Expired'
        REVOKED = 'REVOKED', 'Revoked'

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name='invitations'
    )
    invited_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='sent_workspace_invitations'
    )
    email = models.EmailField()
    role = models.CharField(
        max_length=10,
        choices=WorkspaceMembership.Roles.choices,
        default=WorkspaceMembership.Roles.VIEWER
    )
    # Secure random token — generated on first save, never exposed in list APIs
    token = models.CharField(max_length=64, unique=True, editable=False)
    status = models.CharField(
        max_length=10,
        choices=Statuses.choices,
        default=Statuses.PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=_invitation_expiry)
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(24)
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_valid(self):
        return self.status == self.Statuses.PENDING and not self.is_expired

    def __str__(self):
        return f"Invite to {self.workspace.name} for {self.email} [{self.status}]"
