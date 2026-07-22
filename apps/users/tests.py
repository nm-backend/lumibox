from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from apps.core.test_factories import create_user

User = get_user_model()


class UserModelTests(TestCase):
    def test_login_field_is_email(self):
        self.assertEqual(User.USERNAME_FIELD, "email")

    def test_email_is_unique(self):
        create_user(email="one@example.com")
        with self.assertRaises(IntegrityError):
            create_user(email="one@example.com")

    def test_create_user_hashes_password(self):
        """Открытый пароль не должен попадать в базу никогда."""
        user = create_user(password="plain-text-secret")

        self.assertNotEqual(user.password, "plain-text-secret")
        self.assertTrue(user.check_password("plain-text-secret"))

    def test_create_user_without_email_rejected(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(email="", password="x")

    def test_create_superuser(self):
        admin = User.objects.create_superuser(
            email="admin@example.com", username="admin", password="pass"
        )
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)

    def test_display_name_falls_back_to_email(self):
        user = create_user(username="", email="ivan@example.com")
        self.assertEqual(user.display_name, "ivan")


class RegistrationTests(TestCase):
    def test_register_creates_and_logs_in(self):
        response = self.client.post(
            reverse("users:register"),
            {
                "email": "new@example.com",
                "username": "newbie",
                "password1": "sложный-Пароль-99",
                "password2": "sложный-Пароль-99",
            },
        )

        self.assertRedirects(response, reverse("catalog:home"))
        self.assertTrue(User.objects.filter(email="new@example.com").exists())
        # Регистрация сразу логинит — лишний шаг никому не нужен.
        self.assertIn("_auth_user_id", self.client.session)

    def test_email_normalised_to_lowercase(self):
        """Ivan@mail.ru и ivan@mail.ru — один адрес, а не два аккаунта."""
        self.client.post(
            reverse("users:register"),
            {
                "email": "MiXeD@Example.COM",
                "username": "mixed",
                "password1": "sложный-Пароль-99",
                "password2": "sложный-Пароль-99",
            },
        )
        self.assertTrue(User.objects.filter(email="mixed@example.com").exists())

    def test_duplicate_email_rejected(self):
        create_user(email="taken@example.com")
        response = self.client.post(
            reverse("users:register"),
            {
                "email": "taken@example.com",
                "username": "another",
                "password1": "sложный-Пароль-99",
                "password2": "sложный-Пароль-99",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.filter(email="taken@example.com").count(), 1)

    def test_weak_password_rejected(self):
        response = self.client.post(
            reverse("users:register"),
            {
                "email": "weak@example.com",
                "username": "weak",
                "password1": "123",
                "password2": "123",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email="weak@example.com").exists())

    def test_mismatched_passwords_rejected(self):
        response = self.client.post(
            reverse("users:register"),
            {
                "email": "mismatch@example.com",
                "username": "mismatch",
                "password1": "sложный-Пароль-99",
                "password2": "другой-Пароль-99",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email="mismatch@example.com").exists())

    def test_authenticated_user_redirected_away(self):
        self.client.force_login(create_user())
        response = self.client.get(reverse("users:register"))
        self.assertRedirects(response, reverse("catalog:home"))


class LoginLogoutTests(TestCase):
    def setUp(self):
        self.user = create_user(email="ivan@example.com", password="pass-Слово-77")

    def test_login_by_email(self):
        response = self.client.post(
            reverse("users:login"),
            {"username": "ivan@example.com", "password": "pass-Слово-77"},
        )
        self.assertRedirects(response, reverse("catalog:home"))
        self.assertIn("_auth_user_id", self.client.session)

    def test_login_is_case_insensitive_for_email(self):
        self.client.post(
            reverse("users:login"),
            {"username": "IVAN@example.com", "password": "pass-Слово-77"},
        )
        self.assertIn("_auth_user_id", self.client.session)

    def test_wrong_password_rejected(self):
        self.client.post(
            reverse("users:login"),
            {"username": "ivan@example.com", "password": "не тот"},
        )
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_requires_post(self):
        """По GET-ссылке пользователя мог бы разлогинить чужой сайт."""
        self.client.force_login(self.user)

        self.client.get(reverse("users:logout"))
        self.assertIn("_auth_user_id", self.client.session)

        self.client.post(reverse("users:logout"))
        self.assertNotIn("_auth_user_id", self.client.session)


class ProfileTests(TestCase):
    def setUp(self):
        self.user = create_user()

    def test_profile_requires_login(self):
        response = self.client.get(reverse("users:profile"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("users:login"), response.url)

    def test_profile_opens_for_owner(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("users:profile"))
        self.assertEqual(response.status_code, 200)

    def test_profile_edits_own_account_only(self):
        """Номер пользователя из адреса не берётся — правим всегда себя."""
        other = create_user(username="other")
        self.client.force_login(self.user)

        self.client.post(reverse("users:profile"), {"username": "новое-имя", "bio": ""})

        self.user.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(self.user.username, "новое-имя")
        self.assertEqual(other.username, "other")
