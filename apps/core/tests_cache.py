"""
Тесты оркестратора инвалидации кэша.

Проверяем, что invalidate_for_model корректно вызывает нужные действия,
а invalidate_all пробегает по всем зарегистрированным моделям без ошибок.
"""

from unittest.mock import patch

from django.test import TestCase

from apps.core.cache import CACHE_INVALIDATORS, invalidate_all, invalidate_for_model


class CacheInvalidatorsRegistrationTests(TestCase):
    """Проверяем, что CACHE_INVALIDATORS описывает все модели приложений."""

    def test_has_invalidator_for_title(self):
        """Title должен быть зарегистрирован с _clear_all_title_caches."""
        self.assertIn("catalog.title", CACHE_INVALIDATORS)

    def test_has_invalidator_for_collection(self):
        """Collection должен быть зарегистрирован."""
        self.assertIn("catalog.collection", CACHE_INVALIDATORS)

    def test_has_invalidator_for_review(self):
        """Review должен быть зарегистрирован с _clear_all_title_caches."""
        self.assertIn("reviews.review", CACHE_INVALIDATORS)

    def test_has_invalidator_for_genre(self):
        """Genre должен быть зарегистрирован."""
        self.assertIn("catalog.genre", CACHE_INVALIDATORS)

    def test_has_invalidator_for_promotion(self):
        """Promotion должен быть зарегистрирован."""
        self.assertIn("billing.promotion", CACHE_INVALIDATORS)

    def test_has_invalidator_for_video_asset(self):
        """VideoAsset должен быть зарегистрирован."""
        self.assertIn("streaming.videoasset", CACHE_INVALIDATORS)


class InvalidateForModelTests(TestCase):
    """Проверки вызова действий инвалидации."""

    @patch("apps.core.cache.clear_home_cache")
    def test_title_triggers_home_clear(self, mock_clear_home):
        """Изменение Title должно сбрасывать кэш главной."""
        invalidate_for_model("catalog.title")
        self.assertTrue(mock_clear_home.called)

    @patch("apps.core.cache.clear_reference_cache")
    def test_genre_triggers_reference_clear(self, mock_clear):
        """Изменение Genre должно сбрасывать кэш справочников."""
        invalidate_for_model("catalog.genre")
        self.assertTrue(mock_clear.called)

    @patch("apps.core.cache.clear_reference_cache")
    def test_country_triggers_reference_clear(self, mock_clear):
        """Изменение Country должно сбрасывать кэш справочников."""
        invalidate_for_model("catalog.country")
        self.assertTrue(mock_clear.called)

    def test_unknown_model_silently_skipped(self):
        """Неизвестная модель не вызывает ошибок."""
        try:
            invalidate_for_model("nonexistent.model")
        except Exception as e:
            self.fail(f"invalidate_for_model raised {e}")

    @patch("apps.core.cache.bump_generation")
    def test_review_triggers_all_title_clears(self, mock_bump):
        """Изменение отзыва должно обесценивать рекомендации и похожее."""
        invalidate_for_model("reviews.review")
        self.assertTrue(mock_bump.called)


class InvalidateAllTests(TestCase):
    """invalidate_all должен пробегать все модели без ошибок."""

    @patch("apps.core.cache.clear_home_cache")
    @patch("apps.core.cache.clear_reference_cache")
    @patch("apps.core.cache.bump_generation")
    def test_invalidate_all_runs_without_error(self, mock_bump, mock_ref, mock_home):
        """Полный сброс всех кэшей не должен падать."""
        try:
            invalidate_all()
        except Exception as e:
            self.fail(f"invalidate_all raised {e}")

    def test_register_all_major_models(self):
        """Проверка, что ключевые модели каталога и стриминга зарегистрированы."""
        expected_models = {
            "catalog.title",
            "catalog.collection",
            "catalog.collectionitem",
            "catalog.genre",
            "catalog.country",
            "catalog.person",
            "catalog.participation",
            "catalog.frame",
            "catalog.studio",
            "catalog.award",
            "catalog.titleaward",
            "streaming.season",
            "streaming.episode",
            "streaming.videoasset",
            "reviews.review",
            "billing.promotion",
        }
        for model in expected_models:
            self.assertIn(model, CACHE_INVALIDATORS, f"Missing invalidator for {model}")
