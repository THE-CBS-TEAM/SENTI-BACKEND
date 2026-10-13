import uuid
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework import generics, viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model

from apps.accounts.models import (
    Workspace,
    Brand,
    WorkspaceMembership,
    AICreditUsage,
    WorkspaceInvitation,
)
from apps.accounts.permissions import IsWorkspaceAdmin, IsWorkspaceOwner
from apps.accounts.serializers import (
    UserSerializer,
    RegisterSerializer,
    WorkspaceSerializer,
    BrandSerializer,
    AICreditUsageSerializer,
    WorkspaceMemberSerializer,
    WorkspaceInvitationSerializer,
    SendWorkspaceInvitationSerializer,
    AcceptWorkspaceInvitationSerializer,
)
from apps.core.services.email import send_workspace_invitation

User = get_user_model()


class RegisterView(generics.CreateAPIView):
    """
    Standard user registration:
    Creates a User account, their initial default Workspace, and ADMIN membership.
    """
    queryset = User.objects.all()
    permission_classes = (permissions.AllowAny,)
    serializer_class = RegisterSerializer


class UserMeView(generics.RetrieveUpdateAPIView):
    """
    Returns current authenticated user profile and allows updating user details (username, email, first_name, last_name).
    """
    serializer_class = UserSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_object(self):
        return self.request.user


class ChangePasswordView(generics.GenericAPIView):
    """
    Allows authenticated users to change their account password.
    """
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request, *args, **kwargs):
        user = request.user
        current_password = request.data.get('current_password')
        new_password = request.data.get('new_password')

        if not current_password or not new_password:
            return Response(
                {'error': 'Both current and new password are required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not user.check_password(current_password):
            return Response(
                {'error': 'Current password does not match.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if len(new_password) < 6:
            return Response(
                {'error': 'New password must be at least 6 characters long.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        user.set_password(new_password)
        user.save()
        return Response({'message': 'Password updated successfully.'}, status=status.HTTP_200_OK)


class WorkspaceViewSet(viewsets.ModelViewSet):
    """
    Workspaces management:
    - Lists all workspaces the user owns OR has been invited to (as ADMIN or VIEWER).
    - Allows creating additional workspaces (like Paystack).
    - Exposes member management & invitations.
    """
    serializer_class = WorkspaceSerializer
    permission_classes = (permissions.IsAuthenticated, IsWorkspaceAdmin)

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return Workspace.objects.none()

        # Platform superusers / internal operators with superadmin access can view all
        if user.is_superuser or (getattr(user, 'is_platform_admin', False) and getattr(user, 'admin_role', None) == 'SUPER_ADMIN'):
            return Workspace.objects.all()

        # Users only see workspaces they own or belong to as members
        qs = Workspace.objects.filter(
            Q(owner=user) | Q(memberships__user=user)
        ).distinct()

        # Fallback: if user somehow has no workspace, provision a personal one
        if not qs.exists():
            new_ws = Workspace.objects.create(
                name=f"{user.email.split('@')[0]}'s Workspace",
                type=Workspace.Types.BRAND,
                owner=user
            )
            WorkspaceMembership.objects.create(
                workspace=new_ws,
                user=user,
                role=WorkspaceMembership.Roles.ADMIN
            )
            qs = Workspace.objects.filter(id=new_ws.id)

        return qs

    def perform_create(self, serializer):
        workspace = serializer.save(owner=self.request.user)
        # Owner is automatically given ADMIN membership
        WorkspaceMembership.objects.get_or_create(
            workspace=workspace,
            user=self.request.user,
            defaults={'role': WorkspaceMembership.Roles.ADMIN}
        )

    # ─── Members Sub-Endpoints ───────────────────────────────────────────────

    @action(detail=True, methods=['get'], url_path='members')
    def list_members(self, request, pk=None):
        workspace = self.get_object()
        memberships = workspace.memberships.select_related('user').all()
        serializer = WorkspaceMemberSerializer(memberships, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['patch'], url_path=r'members/(?P<member_id>\d+)')
    def update_member_role(self, request, pk=None, member_id=None):
        """
        Change role of a workspace member (ADMIN or VIEWER).
        Owner protection rule: The workspace owner's role cannot be demoted or changed.
        """
        workspace = self.get_object()

        # Only workspace owner or workspace admin can change roles
        is_owner = workspace.owner_id == request.user.id
        is_admin = is_owner or workspace.memberships.filter(user=request.user, role=WorkspaceMembership.Roles.ADMIN).exists()
        if not is_admin and not request.user.is_superuser:
            return Response(
                {"detail": "You do not have permission to manage roles in this workspace."},
                status=status.HTTP_403_FORBIDDEN
            )

        membership = workspace.memberships.filter(id=member_id).first()
        if not membership:
            return Response({"detail": "Member not found."}, status=status.HTTP_404_NOT_FOUND)

        # OWNER PROTECTION: Workspace owner cannot have their role modified
        if membership.user_id == workspace.owner_id:
            return Response(
                {"detail": "The workspace owner's role cannot be modified."},
                status=status.HTTP_400_BAD_REQUEST
            )

        new_role = request.data.get('role')
        if new_role not in [WorkspaceMembership.Roles.ADMIN, WorkspaceMembership.Roles.VIEWER]:
            return Response(
                {"detail": f"Invalid role. Must be one of: {WorkspaceMembership.Roles.ADMIN}, {WorkspaceMembership.Roles.VIEWER}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        membership.role = new_role
        membership.save(update_fields=['role'])
        serializer = WorkspaceMemberSerializer(membership)
        return Response(serializer.data)

    @action(detail=True, methods=['delete'], url_path=r'members/(?P<member_id>\d+)/remove')
    def remove_member(self, request, pk=None, member_id=None):
        """
        Remove a user from the workspace.
        OWNER PROTECTION:
        - Nobody can remove the owner of the workspace!
        - The owner can remove any user.
        - An ADMIN member can remove VIEWERS or themselves, but cannot remove the owner.
        """
        workspace = self.get_object()
        membership = workspace.memberships.filter(id=member_id).first()
        if not membership:
            return Response({"detail": "Member not found."}, status=status.HTTP_404_NOT_FOUND)

        # OWNER PROTECTION: The workspace owner CANNOT be removed!
        if membership.user_id == workspace.owner_id:
            return Response(
                {"detail": "The workspace owner cannot be removed from their workspace."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Permission check: must be owner, or admin removing non-owner, or user leaving
        is_owner = workspace.owner_id == request.user.id
        is_admin = workspace.memberships.filter(user=request.user, role=WorkspaceMembership.Roles.ADMIN).exists()
        is_self = membership.user_id == request.user.id

        if not (is_owner or is_admin or is_self or request.user.is_superuser):
            return Response(
                {"detail": "You do not have permission to remove this member."},
                status=status.HTTP_403_FORBIDDEN
            )

        membership.delete()
        return Response({"detail": "Member successfully removed from workspace."}, status=status.HTTP_200_OK)

    # ─── Invitations Sub-Endpoints ───────────────────────────────────────────

    @action(detail=True, methods=['get', 'post'], url_path='invitations')
    def invitations(self, request, pk=None):
        workspace = self.get_object()

        # Check write permissions for POST
        is_owner = workspace.owner_id == request.user.id
        is_admin = is_owner or workspace.memberships.filter(user=request.user, role=WorkspaceMembership.Roles.ADMIN).exists()

        if request.method == 'GET':
            invites = workspace.invitations.filter(status=WorkspaceInvitation.Statuses.PENDING)
            serializer = WorkspaceInvitationSerializer(invites, many=True)
            return Response(serializer.data)

        # POST: Send new invite
        if not is_admin and not request.user.is_superuser:
            return Response(
                {"detail": "You do not have permission to invite users to this workspace."},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = SendWorkspaceInvitationSerializer(data=request.data, context={'workspace': workspace})
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email']
        role = serializer.validated_data['role']

        # If a pending invite already exists for this email, revoke old or reuse
        existing_invite = workspace.invitations.filter(
            email__iexact=email,
            status=WorkspaceInvitation.Statuses.PENDING
        ).first()

        if existing_invite and not existing_invite.is_expired:
            # Resend existing
            send_workspace_invitation(existing_invite)
            return Response(
                WorkspaceInvitationSerializer(existing_invite).data,
                status=status.HTTP_200_OK
            )

        # Create new invitation
        invitation = WorkspaceInvitation.objects.create(
            workspace=workspace,
            invited_by=request.user,
            email=email,
            role=role
        )

        # Send email (console in dev, Mailjet in prod)
        send_workspace_invitation(invitation)

        return Response(
            WorkspaceInvitationSerializer(invitation).data,
            status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=['delete'], url_path=r'invitations/(?P<invitation_id>\d+)/revoke')
    def revoke_invitation(self, request, pk=None, invitation_id=None):
        workspace = self.get_object()
        invitation = workspace.invitations.filter(id=invitation_id).first()
        if not invitation:
            return Response({"detail": "Invitation not found."}, status=status.HTTP_404_NOT_FOUND)

        invitation.status = WorkspaceInvitation.Statuses.REVOKED
        invitation.save(update_fields=['status'])
        return Response({"detail": "Invitation revoked."}, status=status.HTTP_200_OK)

    # ─── AI Credit Usage ─────────────────────────────────────────────────────

    @action(detail=True, methods=['get'], url_path='ai-credit-usage')
    def ai_credit_usage(self, request, pk=None):
        workspace = self.get_object()
        usages = workspace.ai_credit_usages.all()
        serializer = AICreditUsageSerializer(usages, many=True)

        totals = usages.aggregate(
            total_tokens_sum=Sum('total_tokens', default=0),
            prompt_tokens_sum=Sum('prompt_tokens', default=0),
            completion_tokens_sum=Sum('completion_tokens', default=0),
            total_cost_sum=Sum('cost', default=0),
        )
        total_tokens = totals['total_tokens_sum']
        prompt_tokens = totals['prompt_tokens_sum']
        completion_tokens = totals['completion_tokens_sum']
        total_cost = float(totals['total_cost_sum'])

        feature_breakdown = {}
        for u in usages:
            feature_breakdown[u.feature] = feature_breakdown.get(u.feature, 0) + u.total_tokens

        return Response({
            'summary': {
                'total_tokens': total_tokens,
                'prompt_tokens': prompt_tokens,
                'completion_tokens': completion_tokens,
                'total_cost': total_cost,
                'calls_count': usages.count(),
            },
            'feature_breakdown': feature_breakdown,
            'logs': serializer.data
        })


def _resolve_workspace_invitation(raw_token):
    """
    Robustly resolves a WorkspaceInvitation token.
    Cleans quoted-printable artifacts (e.g. leading '=3D' or '3D', trailing '=')
    and supports unique prefix matching if email clients truncated the token at a soft line-break.
    """
    if not raw_token:
        return None
    token = str(raw_token).strip().strip("'\"")
    if token.startswith('=3D') or token.startswith('=3d'):
        token = token[3:]
    elif token.startswith('3D') or token.startswith('3d'):
        token = token[2:]
    token = token.rstrip('=')

    # 1. Exact match
    invitation = WorkspaceInvitation.objects.select_related('workspace', 'invited_by').filter(token=token).first()
    if invitation:
        return invitation

    # 2. Prefix match fallback (if truncated at RFC 2045 soft line-break)
    if len(token) >= 12:
        candidates = list(WorkspaceInvitation.objects.select_related('workspace', 'invited_by').filter(
            token__startswith=token,
            status=WorkspaceInvitation.Statuses.PENDING
        )[:2])
        if len(candidates) == 1:
            return candidates[0]

    return None


class AcceptWorkspaceInvitationView(generics.GenericAPIView):
    """
    Inspects (GET) and accepts (POST) a workspace invitation:
    - GET: Returns invitation details, workspace info, and whether the invitee email
      already has an existing account on Sentrimetri.
    - POST:
      - If user already exists: adds user directly to the workspace with the designated role,
        marks invitation ACCEPTED, and issues JWT tokens (no password required).
      - If user is new: creates user account with provided password, personal agency workspace,
        and adds membership to the inviting workspace.
    """
    permission_classes = (permissions.AllowAny,)
    serializer_class = AcceptWorkspaceInvitationSerializer

    def get(self, request):
        raw_token = request.query_params.get('token', '')
        invitation = _resolve_workspace_invitation(raw_token)
        if not invitation:
            return Response(
                {"detail": "Invitation token is invalid."},
                status=status.HTTP_404_NOT_FOUND
            )

        if not invitation.is_valid:
            return Response(
                {"detail": "This invitation has expired or has already been used.", "status": invitation.status},
                status=status.HTTP_400_BAD_REQUEST
            )

        email = invitation.email.strip().lower()
        user = User.objects.filter(email__iexact=email).first()
        is_current_user = bool(
            request.user.is_authenticated and request.user.email.strip().lower() == email
        )
        already_member = bool(
            user and WorkspaceMembership.objects.filter(workspace=invitation.workspace, user=user).exists()
        )

        return Response({
            "valid": True,
            "token": invitation.token,
            "email": invitation.email,
            "workspace_id": invitation.workspace.id,
            "workspace_name": invitation.workspace.name,
            "workspace_type": invitation.workspace.type,
            "role": invitation.role,
            "inviter_name": invitation.invited_by.get_full_name() or invitation.invited_by.email,
            "user_exists": bool(user),
            "is_current_user": is_current_user,
            "already_member": already_member,
        }, status=status.HTTP_200_OK)

    @transaction.atomic
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        raw_token = serializer.validated_data['token']
        password = serializer.validated_data.get('password')
        full_name = serializer.validated_data.get('full_name', '')

        invitation = _resolve_workspace_invitation(raw_token)
        if not invitation:
            return Response(
                {"detail": "Invitation token is invalid."},
                status=status.HTTP_404_NOT_FOUND
            )

        if not invitation.is_valid:
            return Response(
                {"detail": "This invitation has expired or has already been used."},
                status=status.HTTP_400_BAD_REQUEST
            )

        email = invitation.email.strip().lower()
        user = User.objects.filter(email__iexact=email).first()

        if user:
            # Existing user: directly join this workspace with designated role (no password required)
            membership, _ = WorkspaceMembership.objects.get_or_create(
                workspace=invitation.workspace,
                user=user,
                defaults={'role': invitation.role}
            )
            # If user was already a member, ensure role matches
            if membership.role != invitation.role:
                membership.role = invitation.role
                membership.save(update_fields=['role'])
        else:
            # New user: requires a password
            if not password:
                return Response(
                    {"detail": "A password is required to create your account."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            base_username = email.split('@')[0]
            username = f"{base_username}_{uuid.uuid4().hex[:6]}"
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=full_name.split(' ')[0] if full_name else '',
                last_name=' '.join(full_name.split(' ')[1:]) if (full_name and len(full_name.split(' ')) > 1) else '',
                role=User.Roles.ADMIN
            )

            # Every new user gets their own personal agency workspace
            personal_ws = Workspace.objects.create(
                name=f"{base_username.capitalize()}'s Workspace",
                type=Workspace.Types.AGENCY,
                owner=user
            )
            WorkspaceMembership.objects.create(
                workspace=personal_ws,
                user=user,
                role=WorkspaceMembership.Roles.ADMIN
            )

            # Add to invited workspace with designated role
            WorkspaceMembership.objects.create(
                workspace=invitation.workspace,
                user=user,
                role=invitation.role
            )

        # Mark invitation as accepted
        invitation.status = WorkspaceInvitation.Statuses.ACCEPTED
        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=['status', 'accepted_at'])

        # Generate JWT tokens for direct login
        refresh = RefreshToken.for_user(user)

        # Return accessible workspaces
        accessible_workspaces = Workspace.objects.filter(
            Q(owner=user) | Q(memberships__user=user)
        ).distinct()

        return Response({
            "message": f"Successfully joined {invitation.workspace.name} as {invitation.role}.",
            "tokens": {
                "refresh": str(refresh),
                "access": str(refresh.access_token),
            },
            "user": UserSerializer(user).data,
            "active_workspace_id": invitation.workspace.id,
            "workspaces": WorkspaceSerializer(accessible_workspaces, many=True, context={'request': request}).data,
        }, status=status.HTTP_200_OK)


class BrandViewSet(viewsets.ModelViewSet):
    serializer_class = BrandSerializer
    permission_classes = (permissions.IsAuthenticated, IsWorkspaceAdmin)

    def get_queryset(self):
        workspace_id = self.request.query_params.get('workspace_id')
        qs = Brand.objects.filter(
            Q(workspace__owner=self.request.user) | Q(workspace__memberships__user=self.request.user)
        ).distinct()
        if workspace_id:
            qs = qs.filter(workspace_id=workspace_id)
        return qs
