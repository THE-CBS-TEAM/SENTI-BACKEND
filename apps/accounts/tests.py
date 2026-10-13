from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from apps.accounts.models import User, Workspace, WorkspaceMembership

class WorkspacePermissionsTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        
        # Create Owner/Admin
        self.admin_user = User.objects.create_user(
            username='ws_admin',
            email='admin@workspace.com',
            password='Password123!',
            role=User.Roles.ADMIN
        )
        
        # Create Viewer
        self.viewer_user = User.objects.create_user(
            username='ws_viewer',
            email='viewer@workspace.com',
            password='Password123!',
            role=User.Roles.VIEWER
        )

        # Create Outsider
        self.outsider_user = User.objects.create_user(
            username='outsider',
            email='outsider@other.com',
            password='Password123!',
            role=User.Roles.VIEWER
        )

        # Create Workspace
        self.workspace = Workspace.objects.create(
            name='Test Workspace',
            type=Workspace.Types.AGENCY,
            owner=self.admin_user
        )

        # Memberships
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=self.admin_user,
            role=WorkspaceMembership.Roles.ADMIN
        )
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=self.viewer_user,
            role=WorkspaceMembership.Roles.VIEWER
        )

    def test_admin_can_update_workspace(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.patch(
            f'/api/v1/auth/workspaces/{self.workspace.id}/',
            {'name': 'Updated Workspace Name', 'workspace': self.workspace.id},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.workspace.refresh_from_db()
        self.assertEqual(self.workspace.name, 'Updated Workspace Name')

    def test_viewer_cannot_update_workspace(self):
        """CRITICAL SECURITY TEST: Ensure VIEWER role is rejected with 403."""
        self.client.force_authenticate(user=self.viewer_user)
        response = self.client.patch(
            f'/api/v1/auth/workspaces/{self.workspace.id}/',
            {'name': 'Malicious Update by Viewer', 'workspace': self.workspace.id},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.workspace.refresh_from_db()
        self.assertEqual(self.workspace.name, 'Test Workspace')

    def test_outsider_cannot_update_workspace(self):
        self.client.force_authenticate(user=self.outsider_user)
        response = self.client.patch(
            f'/api/v1/auth/workspaces/{self.workspace.id}/',
            {'name': 'Malicious Update by Outsider', 'workspace': self.workspace.id},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
