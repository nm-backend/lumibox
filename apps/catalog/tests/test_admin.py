from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class TitleAdminTests(TestCase):
    def test_add_form_opens_for_staff(self):
        """Нередактируемое поле не должно ломать создание записи в админке."""
        user = get_user_model().objects.create_superuser(
            email="editor@example.com",
            username="editor",
            password="secure-test-password",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("admin:catalog_title_add"))

        self.assertEqual(response.status_code, 200)
