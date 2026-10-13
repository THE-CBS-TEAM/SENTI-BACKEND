from rest_framework import serializers
from django.contrib.auth import get_user_model, authenticate
from django.conf import settings
from apps.accounts.models import Workspace, Brand, WorkspaceMembership
from apps.campaigns.models import Campaign, TrackedPost
from apps.influencers.models import Influencer, GlobalInfluencer, FetchJob, PlatformMetrics
from apps.reports.models import GeneratedReport
from apps.admin_panel.models import AdminAuditLog, SystemConfig, AdminNotification
from apps.admin_panel.utils.diagnostics import classify_scraper_error
import uuid
from django.utils.crypto import constant_time_compare

User = get_user_model()


class AdminRegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    access_key = serializers.CharField(write_only=True)
    username = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        key = attrs.get('access_key', '').strip()
        super_key = getattr(settings, 'SUPER_ADMIN_ACCESS_KEY', '').strip()
        dev_key = getattr(settings, 'DEVELOPER_ACCESS_KEY', '').strip()
        sup_key = getattr(settings, 'SUPPORT_ACCESS_KEY', '').strip()

        matched_role = None
        if super_key and constant_time_compare(key, super_key):
            matched_role = User.AdminRoles.SUPER_ADMIN
        elif dev_key and constant_time_compare(key, dev_key):
            matched_role = User.AdminRoles.DEVELOPER
        elif sup_key and constant_time_compare(key, sup_key):
            matched_role = User.AdminRoles.SUPPORT

        if not matched_role:
            raise serializers.ValidationError({
                'access_key': "Invalid access key. The key provided is not authorized to create any administrative account."
            })

        attrs['resolved_admin_role'] = matched_role
        return attrs

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email address already exists.")
        return value

    def create(self, validated_data):
        email = validated_data['email'].lower()
        password = validated_data['password']
        admin_role = validated_data['resolved_admin_role']
        base_username = validated_data.get('username') or email.split('@')[0]
        
        username = base_username
        while User.objects.filter(username=username).exists():
            username = f"{base_username}_{uuid.uuid4().hex[:6]}"

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            role=User.Roles.ADMIN,
            is_platform_admin=True,
            admin_role=admin_role,
            is_staff=True
        )

        default_ws = Workspace.objects.first()
        if default_ws:
            WorkspaceMembership.objects.get_or_create(
                workspace=default_ws,
                user=user,
                defaults={'role': WorkspaceMembership.Roles.ADMIN}
            )
        else:
            ws = Workspace.objects.create(
                name="Primary Operations Workspace",
                type=Workspace.Types.BRAND,
                owner=user
            )
            WorkspaceMembership.objects.create(
                workspace=ws,
                user=user,
                role=WorkspaceMembership.Roles.ADMIN
            )
        return user


class AdminLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs.get('email', '').lower()
        password = attrs.get('password')

        user = authenticate(username=email, password=password)
        if not user:
            user_obj = User.objects.filter(email__iexact=email).first()
            if user_obj and user_obj.check_password(password):
                user = user_obj

        if not user:
            raise serializers.ValidationError("Invalid email address or password.")

        if not user.is_active:
            raise serializers.ValidationError("This admin account has been suspended.")

        if not (getattr(user, 'is_platform_admin', False) or user.is_superuser):
            raise serializers.ValidationError(
                "Access denied. This account does not possess platform administration privileges."
            )

        attrs['user'] = user
        return attrs


class AdminUserSerializer(serializers.ModelSerializer):
    owned_workspaces_count = serializers.SerializerMethodField()
    memberships_count = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'role', 'is_platform_admin', 'admin_role',
            'is_active', 'is_staff', 'is_superuser', 'date_joined',
            'last_login', 'owned_workspaces_count', 'memberships_count'
        )
        read_only_fields = ('id', 'date_joined', 'last_login')

    def get_owned_workspaces_count(self, obj):
        return obj.owned_workspaces.count()

    def get_memberships_count(self, obj):
        return obj.workspace_memberships.count()


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN INVITATION SERIALIZERS
# ─────────────────────────────────────────────────────────────────────────────

from apps.admin_panel.models import AdminInvitation


class AdminInvitationSerializer(serializers.ModelSerializer):
    invited_by_email = serializers.EmailField(source='invited_by.email', read_only=True)

    class Meta:
        model = AdminInvitation
        fields = (
            'id', 'email', 'admin_role', 'status',
            'invited_by_email', 'created_at', 'expires_at', 'accepted_at'
        )
        read_only_fields = ('id', 'status', 'created_at', 'expires_at', 'accepted_at')


class SendAdminInvitationSerializer(serializers.Serializer):
    email = serializers.EmailField()
    admin_role = serializers.ChoiceField(
        choices=AdminInvitation.AdminRoles.choices,
        default=AdminInvitation.AdminRoles.SUPPORT
    )

    def validate_email(self, value):
        user = User.objects.filter(email__iexact=value).first()
        if user and user.is_platform_admin:
            raise serializers.ValidationError("This user is already an active platform administrator.")
        return value


class AcceptAdminInvitationSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=64)
    password = serializers.CharField(min_length=8, write_only=True)
    full_name = serializers.CharField(required=False, allow_blank=True)


class AdminUserUpdateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, min_length=8)

    class Meta:
        model = User
        fields = ('username', 'email', 'role', 'is_platform_admin', 'admin_role', 'is_active', 'password')

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class AdminWorkspaceSerializer(serializers.ModelSerializer):
    owner_email = serializers.CharField(source='owner.email', read_only=True)
    campaigns_count = serializers.SerializerMethodField()
    influencers_count = serializers.SerializerMethodField()
    brands_count = serializers.SerializerMethodField()
    members_count = serializers.SerializerMethodField()

    class Meta:
        model = Workspace
        fields = '__all__'

    def get_campaigns_count(self, obj):
        return obj.campaigns.count()

    def get_influencers_count(self, obj):
        return obj.influencers.count()

    def get_brands_count(self, obj):
        return obj.brands.count()

    def get_members_count(self, obj):
        return obj.memberships.count()


class AdminCampaignSerializer(serializers.ModelSerializer):
    workspace_name = serializers.CharField(source='workspace.name', read_only=True)
    brand_name = serializers.CharField(source='brand.name', read_only=True)
    influencers_count = serializers.SerializerMethodField()
    tracked_posts_count = serializers.SerializerMethodField()
    error_posts_count = serializers.SerializerMethodField()

    class Meta:
        model = Campaign
        fields = '__all__'

    def get_influencers_count(self, obj):
        return obj.campaign_influencers.count()

    def get_tracked_posts_count(self, obj):
        return TrackedPost.objects.filter(campaign_inf__campaign=obj).count()

    def get_error_posts_count(self, obj):
        return TrackedPost.objects.filter(campaign_inf__campaign=obj, status=TrackedPost.Statuses.ERROR).count()


class AdminGlobalInfluencerSerializer(serializers.ModelSerializer):
    platforms = serializers.SerializerMethodField()
    total_followers = serializers.SerializerMethodField()
    workspaces_count = serializers.SerializerMethodField()
    data_freshness = serializers.ReadOnlyField()
    is_data_stale = serializers.ReadOnlyField()
    age_hours = serializers.ReadOnlyField()
    age_display = serializers.ReadOnlyField()

    class Meta:
        model = GlobalInfluencer
        fields = '__all__'

    def get_platforms(self, obj):
        res = []
        if obj.ig_handle: res.append('IG')
        if obj.tiktok_handle: res.append('TT')
        if obj.x_handle: res.append('X')
        return res

    def get_total_followers(self, obj):
        return sum(m.followers for m in obj.platform_metrics.all())

    def get_workspaces_count(self, obj):
        return obj.workspace_links.count()


class AdminCreateInfluencerSerializer(serializers.Serializer):
    display_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    niche = serializers.CharField(max_length=100, required=False, allow_blank=True)
    ig_handle = serializers.CharField(max_length=255, required=False, allow_blank=True)
    tiktok_handle = serializers.CharField(max_length=255, required=False, allow_blank=True)
    x_handle = serializers.CharField(max_length=255, required=False, allow_blank=True)

    def _extract_handle(self, val):
        if not val:
            return None
        val = val.strip().rstrip('/')
        if val.startswith('@'):
            return val[1:]
        if '/' in val:
            parts = [p for p in val.split('/') if p]
            if parts:
                return parts[-1].lstrip('@')
        return val

    def validate(self, data):
        ig = self._extract_handle(data.get('ig_handle'))
        tt = self._extract_handle(data.get('tiktok_handle'))
        x = self._extract_handle(data.get('x_handle'))
        if not ig and not tt and not x:
            raise serializers.ValidationError("Please provide at least one handle or URL (Instagram, TikTok, or X).")
        data['ig_handle'] = ig
        data['tiktok_handle'] = tt
        data['x_handle'] = x
        return data


class AdminInfluencerSerializer(serializers.ModelSerializer):
    workspace_name = serializers.CharField(source='workspace.name', read_only=True)
    platforms = serializers.SerializerMethodField()
    total_followers = serializers.SerializerMethodField()

    class Meta:
        model = Influencer
        fields = '__all__'

    def get_platforms(self, obj):
        res = []
        if obj.ig_handle: res.append('IG')
        if obj.tiktok_handle: res.append('TT')
        if obj.x_handle: res.append('X')
        return res

    def get_total_followers(self, obj):
        return sum(m.followers for m in obj.platform_metrics.all())


class AdminReportSerializer(serializers.ModelSerializer):
    campaign_name = serializers.CharField(source='campaign.name', read_only=True)
    generated_by_email = serializers.CharField(source='generated_by.email', read_only=True)

    class Meta:
        model = GeneratedReport
        fields = '__all__'


class AdminFetchJobSerializer(serializers.ModelSerializer):
    diagnostic = serializers.SerializerMethodField()

    class Meta:
        model = FetchJob
        fields = '__all__'

    def get_diagnostic(self, obj):
        if obj.error_message:
            return classify_scraper_error(obj.error_message, provider=obj.provider, entity_type=obj.entity_type)
        return None


class AdminTrackedPostErrorSerializer(serializers.ModelSerializer):
    campaign_name = serializers.CharField(source='campaign_inf.campaign.name', read_only=True)
    campaign_id = serializers.IntegerField(source='campaign_inf.campaign.id', read_only=True)
    influencer_name = serializers.CharField(source='campaign_inf.influencer.display_name', read_only=True)
    influencer_id = serializers.IntegerField(source='campaign_inf.influencer.id', read_only=True)
    diagnostic = serializers.SerializerMethodField()

    class Meta:
        model = TrackedPost
        fields = (
            'id', 'campaign_id', 'campaign_name', 'influencer_id', 'influencer_name',
            'platform', 'post_url', 'status', 'polling_tier', 'consecutive_fetch_failures',
            'last_fetch_attempt_at', 'last_successful_fetch_at', 'last_fetch_error',
            'created_at', 'views', 'likes', 'comments_count', 'diagnostic'
        )

    def get_diagnostic(self, obj):
        if obj.last_fetch_error:
            provider = 'SOCIALDATA' if obj.platform == 'X' else 'APIFY'
            return classify_scraper_error(obj.last_fetch_error, provider=provider, entity_type='POST')
        return None


class AdminNotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdminNotification
        fields = '__all__'


class AdminAuditLogSerializer(serializers.ModelSerializer):
    admin_email = serializers.CharField(source='admin_user.email', read_only=True)
    admin_username = serializers.CharField(source='admin_user.username', read_only=True)

    class Meta:
        model = AdminAuditLog
        fields = '__all__'


class SystemConfigSerializer(serializers.ModelSerializer):
    updated_by_email = serializers.CharField(source='updated_by.email', read_only=True)

    class Meta:
        model = SystemConfig
        fields = '__all__'
