from django.urls import path, include
from rest_framework.routers import DefaultRouter
from apps.accounts.views import (
    RegisterView,
    UserMeView,
    ChangePasswordView,
    WorkspaceViewSet,
    BrandViewSet,
    AcceptWorkspaceInvitationView,
)

router = DefaultRouter()
router.register('workspaces', WorkspaceViewSet, basename='workspace')
router.register('brands', BrandViewSet, basename='brand')

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('me/', UserMeView.as_view(), name='user_me'),
    path('change-password/', ChangePasswordView.as_view(), name='change_password'),
    path('invitations/accept/', AcceptWorkspaceInvitationView.as_view(), name='accept_workspace_invite'),
    path('accept-invite/', AcceptWorkspaceInvitationView.as_view(), name='accept_workspace_invite_alias'),
    path('', include(router.urls)),
]
