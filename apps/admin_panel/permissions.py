from rest_framework import permissions


class IsPlatformAdmin(permissions.BasePermission):
    """
    Base permission for all admin endpoints.
    Allows access only to authenticated users with is_platform_admin=True or is_superuser=True.
    """
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (
                getattr(request.user, 'is_platform_admin', False)
                or getattr(request.user, 'is_superuser', False)
            )
        )


class RequireSuperAdmin(permissions.BasePermission):
    """Restricts access strictly to Super Admins."""
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        return getattr(request.user, 'admin_role', None) == 'SUPER_ADMIN'


class RequireDeveloperOrAbove(permissions.BasePermission):
    """Allows Super Admins and Developers."""
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        return getattr(request.user, 'admin_role', None) in ['SUPER_ADMIN', 'DEVELOPER']


class RequireSupportOrAbove(permissions.BasePermission):
    """Allows any active platform admin role."""
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        return getattr(request.user, 'is_platform_admin', False)
