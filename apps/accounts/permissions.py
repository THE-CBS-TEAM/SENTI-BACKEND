from rest_framework import permissions
from apps.accounts.models import WorkspaceMembership

class IsWorkspaceAdmin(permissions.BasePermission):
    """
    Custom permission to only allow workspace admins to edit/create/delete objects.
    Viewers only have read-only access.
    """
    def has_permission(self, request, view):
        # 1. Allow access to authenticated users
        if not request.user or not request.user.is_authenticated:
            return False

        # 2. Superusers, staff, platform admins, or system ADMIN users have full write access
        if request.user.is_superuser or request.user.is_staff or getattr(request.user, 'role', None) == 'ADMIN' or getattr(request.user, 'is_platform_admin', False):
            return True

        # 3. Allow all safe HTTP methods (GET, HEAD, OPTIONS)
        if request.method in permissions.SAFE_METHODS:
            return True

        # 4. For modifying requests, check workspace role
        workspace_id = (
            request.data.get('workspace_id') or 
            request.data.get('workspace') or 
            request.query_params.get('workspace_id') or 
            request.query_params.get('workspace')
        )
        
        # If no workspace_id is provided, try finding it via campaign_id if present
        campaign_pk = request.data.get('campaign_id') or view.kwargs.get('campaign_id')
        if not workspace_id and campaign_pk:
            from apps.campaigns.models import Campaign
            try:
                campaign = Campaign.objects.get(pk=campaign_pk)
                workspace_id = campaign.workspace_id
            except Campaign.DoesNotExist:
                pass

        if not workspace_id:
            if view.kwargs.get('pk'):
                return True
            return False

        from apps.accounts.models import Workspace
        ws = Workspace.objects.filter(id=workspace_id).first()
        if ws and (ws.owner == request.user or ws.memberships.filter(user=request.user, role='ADMIN').exists()):
            return True

        # Query membership
        membership = WorkspaceMembership.objects.filter(
            workspace_id=workspace_id,
            user=request.user
        ).first()

        return membership is not None and membership.role in [WorkspaceMembership.Roles.ADMIN, 'ADMIN']

    def has_object_permission(self, request, view, obj):
        # Allow safe methods
        if request.method in permissions.SAFE_METHODS:
            return True

        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser or request.user.is_staff or getattr(request.user, 'role', None) == 'ADMIN':
            return True

        # For write methods, find the workspace associated with the object
        workspace = None
        if obj.__class__.__name__ == 'Workspace':
            workspace = obj
        elif hasattr(obj, 'workspace'):
            workspace = obj.workspace
        elif hasattr(obj, 'campaign_inf') and hasattr(obj.campaign_inf, 'campaign'):
            workspace = obj.campaign_inf.campaign.workspace
        elif hasattr(obj, 'campaign') and hasattr(obj.campaign, 'workspace'):
            workspace = obj.campaign.workspace
        elif hasattr(obj, 'influencer') and hasattr(obj.influencer, 'workspace'):
            workspace = obj.influencer.workspace

        if not workspace:
            return False

        if workspace.owner == request.user or workspace.memberships.filter(user=request.user, role='ADMIN').exists():
            return True

        membership = WorkspaceMembership.objects.filter(
            workspace=workspace,
            user=request.user
        ).first()

        return membership is not None and membership.role in [WorkspaceMembership.Roles.ADMIN, 'ADMIN']


class IsWorkspaceOwner(permissions.BasePermission):
    """
    Allows access only to the explicit owner of the workspace.
    Used for destructive operations like deleting the workspace or managing admin roles.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser or request.user.is_staff or getattr(request.user, 'is_platform_admin', False):
            return True

        workspace_id = (
            view.kwargs.get('workspace_pk') or
            view.kwargs.get('workspace_id') or
            view.kwargs.get('pk') or
            request.data.get('workspace_id') or
            request.query_params.get('workspace_id')
        )
        if not workspace_id:
            return True

        from apps.accounts.models import Workspace
        ws = Workspace.objects.filter(id=workspace_id).first()
        return ws is not None and ws.owner == request.user

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser or request.user.is_staff or getattr(request.user, 'is_platform_admin', False):
            return True

        workspace = obj if obj.__class__.__name__ == 'Workspace' else getattr(obj, 'workspace', None)
        if not workspace:
            return False
        return workspace.owner == request.user

