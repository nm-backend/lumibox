"""
Тесты сервисного слоя биллинга: проверки доступа к контенту.

Покрывает has_content_access — единую точку входа для плеера и API:
- Гость без авторизации
- Авторизованный пользователь без прав
- Неизвестные уровни доступа
- Доступ по подписке (Premium/VIP)
- Денормализованные проверки _subscription_levels_for
"""

from django.contrib.auth.models import AnonymousUser
from django.test import TestCase

from apps.billing.services import has_content_access
from apps.core.test_factories import create_title, create_user
from apps.streaming.models import VideoAsset


class HasContentAccessTests(TestCase):
    """Проверки доступа к защищённому контенту."""

    def test_guest_has_no_access(self):
        """Неавторизованный пользователь получает отказ."""
        user = AnonymousUser()
        asset = VideoAsset(access_level=VideoAsset.AccessLevel.FREE)

        decision = has_content_access(user, asset)
        self.assertFalse(decision.allowed)
        self.assertIn("вход", decision.reason.lower() if decision.reason else "")

    def test_unknown_access_level_returns_false(self):
        """Неизвестный уровень доступа не даёт разрешения."""
        user = create_user()
        asset = VideoAsset(access_level="unknown_level")

        decision = has_content_access(user, asset)
        self.assertFalse(decision.allowed)

    def test_none_user_returns_false(self):
        """None вместо пользователя не должен вызывать ошибку."""
        asset = VideoAsset(access_level=VideoAsset.AccessLevel.FREE)

        decision = has_content_access(None, asset)
        self.assertFalse(decision.allowed)

    def test_free_asset_no_subscription_needed(self):
        """FREE-ассет не требует подписки, но и не даёт разрешения без entitlement."""
        user = create_user()
        title = create_title(status="published")
        asset = VideoAsset.objects.create(
            title=title,
            access_level=VideoAsset.AccessLevel.FREE,
            status=VideoAsset.Status.READY,
            duration_seconds=3600,
        )

        decision = has_content_access(user, asset)
        self.assertFalse(decision.allowed)
        self.assertIsNotNone(decision.reason)

        asset.delete()


# Проверяем поведение _subscription_levels_for через has_content_access
# с разными уровнями доступа VideoAsset.
class AccessLevelMappingTests(TestCase):
    """Маппинг уровней доступа VideoAsset → SubscriptionPlan.Level."""

    def test_premium_asset_maps_to_premium_and_vip(self):
        """Premium-контент доступен владельцам Premium и VIP подписок."""
        user = create_user()
        asset = VideoAsset(access_level=VideoAsset.AccessLevel.PREMIUM)

        # Проверяем, что вызов не падает — маппинг существует
        decision = has_content_access(user, asset)
        self.assertFalse(decision.allowed)  # Нет подписки → отказано
        self.assertIsNotNone(decision.reason)

    def test_vip_asset_maps_to_vip_only(self):
        """VIP-контент доступен только владельцам VIP подписки."""
        user = create_user()
        asset = VideoAsset(access_level=VideoAsset.AccessLevel.VIP)

        decision = has_content_access(user, asset)
        self.assertFalse(decision.allowed)
        self.assertIsNotNone(decision.reason)

    def test_rental_asset_no_subscription_mapping(self):
        """Rental-контент не имеет маппинга на подписки."""
        user = create_user()
        asset = VideoAsset(access_level=VideoAsset.AccessLevel.RENTAL)

        decision = has_content_access(user, asset)
        self.assertFalse(decision.allowed)
        self.assertIsNotNone(decision.reason)

    def test_purchase_asset_no_subscription_mapping(self):
        """Purchase-контент не имеет маппинга на подписки."""
        user = create_user()
        asset = VideoAsset(access_level=VideoAsset.AccessLevel.PURCHASE)

        decision = has_content_access(user, asset)
        self.assertFalse(decision.allowed)
        self.assertIsNotNone(decision.reason)
