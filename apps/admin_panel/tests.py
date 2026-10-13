from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from apps.admin_panel.models import AdminAuditLog, SystemConfig, AdminNotification

User = get_user_model()


@override_settings(
    SUPER_ADMIN_ACCESS_KEY='test-super-admin-key',
    DEVELOPER_ACCESS_KEY='test-developer-key',
    SUPPORT_ACCESS_KEY='test-support-key',
)
class AdminPanelSecurityTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_registration_with_invalid_key_fails(self):
        payload = {
            'email': 'hacker@example.com',
            'password': 'StrongPassword123!',
            'access_key': 'wrong-key-attempt'
        }
        response = self.client.post('/api/v1/admin/auth/register/', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('access_key', response.data)
        self.assertFalse(User.objects.filter(email='hacker@example.com').exists())

    def test_registration_with_developer_key_creates_developer_role(self):
        payload = {
            'email': 'developer@sentimentri.com',
            'password': 'StrongPassword123!',
            'access_key': 'test-developer-key'
        }
        response = self.client.post('/api/v1/admin/auth/register/', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['user']['admin_role'], 'DEVELOPER')
        self.assertTrue(response.data['user']['is_platform_admin'])

        user = User.objects.get(email='developer@sentimentri.com')
        self.assertEqual(user.admin_role, User.AdminRoles.DEVELOPER)
        self.assertTrue(user.is_platform_admin)

    def test_registration_with_support_key_creates_support_role(self):
        payload = {
            'email': 'support@sentimentri.com',
            'password': 'StrongPassword123!',
            'access_key': 'test-support-key'
        }
        response = self.client.post('/api/v1/admin/auth/register/', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['user']['admin_role'], 'SUPPORT')

        user = User.objects.get(email='support@sentimentri.com')
        self.assertEqual(user.admin_role, User.AdminRoles.SUPPORT)

    def test_registration_with_super_admin_key_creates_super_admin_role(self):
        payload = {
            'email': 'superadmin@sentimentri.com',
            'password': 'StrongPassword123!',
            'access_key': 'test-super-admin-key'
        }
        response = self.client.post('/api/v1/admin/auth/register/', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['user']['admin_role'], 'SUPER_ADMIN')

        user = User.objects.get(email='superadmin@sentimentri.com')
        self.assertEqual(user.admin_role, User.AdminRoles.SUPER_ADMIN)
        self.assertTrue(user.is_platform_admin)

    def test_admin_login_rejects_non_platform_admin(self):
        # Create regular user
        regular_user = User.objects.create_user(
            username='regularuser',
            email='regular@sentimentri.com',
            password='UserPass123!',
            is_platform_admin=False
        )

        response = self.client.post('/api/v1/admin/auth/login/', {
            'email': 'regular@sentimentri.com',
            'password': 'UserPass123!'
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('non_field_errors', response.data)

    def test_role_based_permissions(self):
        # Create a support admin
        support_user = User.objects.create_user(
            username='support_user',
            email='sup@sentimentri.com',
            password='Pass123456!',
            is_platform_admin=True,
            admin_role=User.AdminRoles.SUPPORT
        )

        # Create a developer admin
        dev_user = User.objects.create_user(
            username='dev_user',
            email='dev@sentimentri.com',
            password='Pass123456!',
            is_platform_admin=True,
            admin_role=User.AdminRoles.DEVELOPER
        )

        # Create super admin
        super_admin = User.objects.create_user(
            username='super_user',
            email='super@sentimentri.com',
            password='Pass123456!',
            is_platform_admin=True,
            admin_role=User.AdminRoles.SUPER_ADMIN
        )

        # 1. Support user cannot access system health
        self.client.force_authenticate(user=support_user)
        res = self.client.get('/api/v1/admin/system/health/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # 2. Developer CAN access system health
        self.client.force_authenticate(user=dev_user)
        res = self.client.get('/api/v1/admin/system/health/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # 3. Developer CANNOT create system configs
        res = self.client.post('/api/v1/admin/configs/', {
            'key': 'NEW_VAR',
            'value': '123',
            'value_type': 'int'
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # 4. Super admin CAN create system configs
        self.client.force_authenticate(user=super_admin)
        res = self.client.post('/api/v1/admin/configs/', {
            'key': 'NEW_VAR',
            'value': '123',
            'value_type': 'int'
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(SystemConfig.objects.filter(key='NEW_VAR').exists())

    def test_dashboard_overview_endpoint(self):
        super_admin = User.objects.create_user(
            username='admin_overview',
            email='admin_overview@sentimentri.com',
            password='Pass123456!',
            is_platform_admin=True,
            admin_role=User.AdminRoles.SUPER_ADMIN
        )
        self.client.force_authenticate(user=super_admin)
        response = self.client.get('/api/v1/admin/dashboard/overview/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('kpis', response.data)
        self.assertIn('total_users', response.data['kpis'])
        self.assertIn('scraper_trend_7d', response.data)
