"""
Тесты для admin dashboard и notifications.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.catalog.models import Title

User = get_user_model()


class AdminDashboardTests(TestCase):
    """Тесты admin dashboard."""

    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_superuser(
            email="admin@test.com", username="admin", password="pass123"
        )
        cls.user = User.objects.create_user(
            email="user@test.com", username="user", password="pass123"
        )
        cls.title = Title.objects.create(
            name="Test Movie", slug="test-movie",
            release_year=2024, status=Title.Status.PUBLISHED, view_count=42
        )

    def test_dashboard_requires_staff(self):
        self.client.force_login(self.user)
        response = self.client.get("/admin/dashboard/")
        self.assertEqual(response.status_code, 302)  # Redirect to login

    def test_dashboard_loads_for_staff(self):
        self.client.force_login(self.staff)
        response = self.client.get("/admin/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Movie")

    def test_dashboard_api_requires_staff(self):
        self.client.force_login(self.user)
        response = self.client.get("/admin/dashboard/api/")
        self.assertEqual(response.status_code, 302)

    def test_dashboard_api_returns_json(self):
        self.client.force_login(self.staff)
        response = self.client.get("/admin/dashboard/api/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("total_titles", data)
        self.assertIn("total_views", data)
        self.assertEqual(data["total_titles"], 1)
        self.assertEqual(data["total_views"], 42)


class NotificationTests(TestCase):
    """Тесты системы уведомлений."""

    def test_broadcast_content_update(self):
        from apps.core.notifications import broadcast_content_update
        # Не должно падать без channels
        broadcast_content_update("new_content", "Test Movie", "/test/")

    def test_send_ws_notification(self):
        from apps.core.notifications import send_ws_notification
        # Не должно падать без channels
        send_ws_notification(1, "Test", "Body", "/test/")
