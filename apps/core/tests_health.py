"""
Тест health-check. Эндпоинт опрашивает хостинг, чтобы решать, жив ли
контейнер, поэтому его контракт важен: 200 и валидный JSON, пока база отвечает.
"""

from django.test import TestCase


class HealthCheckTests(TestCase):
    def test_ok_when_database_available(self):
        response = self.client.get("/healthz/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")

        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["database"], "ok")
        self.assertEqual(payload["cache"], "ok")

    def test_not_redirected(self):
        """
        Хостинг опрашивает пробу по внутреннему HTTP. Если бы она уходила
        в редирект на HTTPS, платформа сочла бы сервис недоступным.
        """
        response = self.client.get("/healthz/")
        self.assertNotIn(response.status_code, (301, 302))
