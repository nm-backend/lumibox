"""
Healthcheck плеера: LiveServerTestCase + Selenium.

Заменяет bash-скрипт scripts/healthcheck-player.sh полноценным unittest-ом.
Django сам запускает dev-сервер (LiveServerTestCase), а Selenium управляет
браузером. Никаких внешних зависимостей кроме Chrome.

Запуск:
    python -m django test apps.streaming.test_selenium \
      --settings=config.settings.development -v 2

Только selenium-тесты:
    python -m django test apps.streaming.test_selenium \
      --settings=config.settings.development --tag=selenium -v 2
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from django.conf import settings as django_settings
from django.test import LiveServerTestCase, override_settings, tag

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from apps.catalog.models import Title
import apps.core.py314_compat  # noqa: F401 — Python 3.14 workaround

from apps.streaming.models import VideoAsset

TEST_MOVIE_SLUG = "test-player-movie"

_STREAMING_CONFIG_STUB = {
    "cloudflare_stream": {"delivery_base_url": "https://media.example.test/cf-stream"},
    "cloudflare_r2": {"delivery_base_url": "https://media.example.test/r2"},
    "aws_s3": {"delivery_base_url": "https://media.example.test/s3"},
    "backblaze_b2": {"delivery_base_url": "https://media.example.test/b2"},
    "minio": {"delivery_base_url": "https://media.example.test/minio"},
}

# CSP middleware блокирует CDN-скрипты HLS.js — убираем для теста.
_MIDDLEWARE_WO_CSP = [
    mw
    for mw in django_settings.MIDDLEWARE
    if "ContentSecurityPolicyMiddleware" not in mw
]


def _create_test_data():
    title = Title.objects.create(
        slug=TEST_MOVIE_SLUG,
        name="Тестовый фильм плеера",
        type=Title.Type.MOVIE,
        status=Title.Status.PUBLISHED,
        release_year=2026,
        description="Тестовый фильм для healthcheck страницы плеера.",
        short_description="Healthcheck-фильм для проверки работы плеера.",
        duration_minutes=2,
    )
    VideoAsset.objects.create(
        title=title,
        provider=VideoAsset.Provider.CLOUDFLARE_R2,
        stream_type=VideoAsset.StreamType.MP4,
        asset_key="healthcheck/test-video.mp4",
        status=VideoAsset.Status.READY,
        access_level=VideoAsset.AccessLevel.FREE,
        duration_seconds=120,
        available_qualities=["auto", "1080p", "720p", "480p"],
    )


@tag("selenium", "healthcheck")
@override_settings(
    STREAMING_PROVIDER_CONFIG=_STREAMING_CONFIG_STUB,
    MIDDLEWARE=_MIDDLEWARE_WO_CSP,
)
class PlayerHealthcheckTest(LiveServerTestCase):
    """Интеграционный тест плеера: LiveServerTestCase + Selenium."""

    databases = {"default"}

    def setUp(self):
        _create_test_data()

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.set_capability("goog:loggingPrefs", {"browser": "ALL"})
        cls.driver = webdriver.Chrome(options=options)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "driver"):
            cls.driver.quit()
        super().tearDownClass()

    def _player_url(self) -> str:
        return f"{self.live_server_url}/watch/{TEST_MOVIE_SLUG}/"

    def _await_player(self, timeout: int = 10):
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "[data-stream-player]")
            )
        )

    def _screenshot_dir(self) -> Path:
        return django_settings.BASE_DIR / ".healthcheck"

    def test_player_healthcheck(self):
        """Полная проверка плеера: рендеринг, DOM, консоль, скриншот."""
        screenshot_dir = self._screenshot_dir()
        screenshot_dir.mkdir(parents=True, exist_ok=True)

        # ── 1. Открыть страницу ──────────────────────────────────
        self.driver.get(self._player_url())
        self.assertNotIn(
            "not-found",
            self.driver.current_url.lower(),
            f"Страница редиректнула на 404: {self.driver.current_url}",
        )

        # ── 2. Дождаться рендеринга плеера ────────────────────────
        player_el = self._await_player(timeout=15)
        self.assertIsNotNone(player_el, "Плеер не отрендерился в DOM")

        body = self.driver.find_element(By.TAG_NAME, "body")
        self.assertNotIn("Страница не найдена", body.text)
        self.assertNotIn("Ошибка сервера", body.text)

        # ── 3. Конфигурация в DOM ────────────────────────────────
        # json_script создаёт <script id="stream-player-config">...</script>.
        # У script-элементов .text пуст — используем textContent.
        config_el = self.driver.find_element(By.ID, "stream-player-config")
        raw = config_el.get_attribute("textContent") or ""
        self.assertTrue(raw.strip(), "stream-player-config пуст")
        config = json.loads(raw)
        self.assertIn("assetId", config)
        self.assertIn("source", config)
        self.assertEqual(config["duration"], 120)
        self.assertEqual(config["source"]["type"], "mp4")
        self.assertIn(
            "https://media.example.test/r2/healthcheck/test-video.mp4",
            config["source"]["url"],
        )

        # ── 4. Кнопка «Воспроизвести» видна ──────────────────────
        buttons = self.driver.find_elements(
            By.CSS_SELECTOR, "[data-player-toggle]"
        )
        self.assertGreater(
            len(buttons), 0, "Не найдено ни одного data-player-toggle"
        )
        self.assertTrue(
            any(btn.is_displayed() for btn in buttons),
            "Ни одна кнопка «Воспроизвести» не видна",
        )

        # ── 5. Заголовок страницы ────────────────────────────────
        self.assertIn("Тестовый фильм", self.driver.title)

        # ── 6. Нет неожиданных JS-ошибок ──────────────────────────
        time.sleep(3)
        entries = self.driver.get_log("browser")
        ignored = [
            "HLS", "hls", "MEDIA_ERR", "MEDIA", "media",
            "video", "source", "network", "Network",
            "buffer", "Buffer", "manifest", "Manifest",
            "playback", "Playback", "decoder", "Decoder",
            "ERR_BLOCKED_BY_CSP",
            "Refused to apply",
            "Refused to execute",
            "favicon.ico",
        ]
        unexpected = [
            e
            for e in entries
            if e["level"] in ("SEVERE", "ERROR")
            and not any(p in e["message"] for p in ignored)
        ]
        if unexpected:
            lines = "\n".join(
                f"  [{e['level']}] {e['message'][:200]}"
                for e in unexpected[:10]
            )
            self.fail(
                f"Найдено {len(unexpected)} неожиданных JS-ошибок:\n{lines}"
            )

        # ── 7. Скриншот ──────────────────────────────────────────
        path = screenshot_dir / "player-render.png"
        self.driver.save_screenshot(str(path))
        self.assertTrue(path.exists(), f"Скриншот не сохранён: {path}")
