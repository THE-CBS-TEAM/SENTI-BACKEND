from rest_framework import serializers
from django.contrib.auth import get_user_model
from apps.accounts.models import Workspace, Brand, WorkspaceMembership, AICreditUsage
import uuid

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'first_name', 'last_name', 'role', 'created_at')
        read_only_fields = ('id', 'role', 'created_at')


class WorkspaceSerializer(serializers.ModelSerializer):
    is_owner = serializers.SerializerMethodField()
    user_role = serializers.SerializerMethodField()
    members_count = serializers.SerializerMethodField()

    class Meta:
        model = Workspace
        fields = (
            'id', 'name', 'type', 'owner', 'created_at', 
            'is_owner', 'user_role', 'members_count',
            'use_llm_sentiment_analysis',
            't1_max_age_hours', 't1_interval_hours',
            't2_max_age_hours', 't2_interval_hours',
            't3_max_age_hours', 't3_interval_hours',
            'proposal_theme', 'proposal_primary_color', 'proposal_font_style', 'proposal_show_watermark',
            'report_theme', 'report_primary_color', 'report_font_style', 'report_show_watermark'
        )
        read_only_fields = ('owner',)

    def get_is_owner(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return obj.owner_id == request.user.id

    def get_user_role(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        if obj.owner_id == request.user.id:
            return 'OWNER'
        membership = obj.memberships.filter(user=request.user).first()
        return membership.role if membership else None

    def get_members_count(self, obj):
        return obj.memberships.count()


class AICreditUsageSerializer(serializers.ModelSerializer):
    class Meta:
        model = AICreditUsage
        fields = ('id', 'feature', 'model_name', 'prompt_tokens', 'completion_tokens', 'total_tokens', 'cost', 'metadata', 'used_at')


class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = ('id', 'workspace', 'name', 'logo_url', 'created_at')


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    workspace_name = serializers.CharField(write_only=True)
    workspace_type = serializers.ChoiceField(
        choices=Workspace.Types.choices,
        write_only=True,
        default=Workspace.Types.AGENCY
    )

    class Meta:
        model = User
        fields = ('id', 'email', 'password', 'role', 'workspace_name', 'workspace_type')

    def create(self, validated_data):
        workspace_name = validated_data.pop('workspace_name')
        workspace_type = validated_data.pop('workspace_type')
        password = validated_data.pop('password')
        
        email = validated_data['email']
        base_username = email.split('@')[0]
        from django.db import IntegrityError
        
        max_retries = 5
        for i in range(max_retries):
            username = f"{base_username}_{uuid.uuid4().hex[:6]}"
            try:
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    role=validated_data.get('role', User.Roles.ADMIN)
                )
                break
            except IntegrityError:
                if i == max_retries - 1:
                    raise

        # Automatically create the first workspace for the user
        workspace = Workspace.objects.create(
            name=workspace_name,
            type=workspace_type,
            owner=user
        )

        # Automatically add the user as an ADMIN member of their new workspace
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=user,
            role=WorkspaceMembership.Roles.ADMIN
        )

        return user


# ─────────────────────────────────────────────────────────────────────────────
# WORKSPACE INVITATION & MEMBERSHIP SERIALIZERS
# ─────────────────────────────────────────────────────────────────────────────

from apps.accounts.models import WorkspaceInvitation


class WorkspaceMemberSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source='user.id', read_only=True)
    email = serializers.EmailField(source='user.email', read_only=True)
    username = serializers.CharField(source='user.username', read_only=True)
    is_owner = serializers.SerializerMethodField()

    class Meta:
        model = WorkspaceMembership
        fields = ('id', 'user_id', 'email', 'username', 'role', 'is_owner', 'joined_at')
        read_only_fields = ('id', 'joined_at')

    def get_is_owner(self, obj):
        return obj.workspace.owner_id == obj.user_id


class WorkspaceInvitationSerializer(serializers.ModelSerializer):
    invited_by_email = serializers.EmailField(source='invited_by.email', read_only=True)
    workspace_name = serializers.CharField(source='workspace.name', read_only=True)

    class Meta:
        model = WorkspaceInvitation
        fields = (
            'id', 'workspace', 'workspace_name', 'email', 'role',
            'status', 'invited_by_email', 'created_at', 'expires_at', 'accepted_at'
        )
        read_only_fields = ('id', 'status', 'created_at', 'expires_at', 'accepted_at')


class SendWorkspaceInvitationSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(
        choices=WorkspaceMembership.Roles.choices,
        default=WorkspaceMembership.Roles.VIEWER
    )

    def validate_email(self, value):
        workspace = self.context.get('workspace')
        if not workspace:
            return value

        # Owner cannot be invited to their own workspace
        if workspace.owner.email.lower() == value.lower():
            raise serializers.ValidationError("This user is already the owner of this workspace.")

        # Check if user is already an active member
        if WorkspaceMembership.objects.filter(workspace=workspace, user__email__iexact=value).exists():
            raise serializers.ValidationError("This user is already a member of this workspace.")

        return value


class AcceptWorkspaceInvitationSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=64)
    password = serializers.CharField(required=False, allow_blank=True, write_only=True)
    full_name = serializers.CharField(required=False, allow_blank=True)

