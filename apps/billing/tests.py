"""
Тесты для billing models.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.billing.models import (
    Entitlement,
    Payment,
    PromoCode,
    Subscription,
    SubscriptionPlan,
)

User = get_user_model()


class SubscriptionPlanTests(TestCase):
    """Тесты тарифных планов."""

    def test_create_plan(self):
        plan = SubscriptionPlan.objects.create(
            slug="premium-month",
            name="Premium",
            level=SubscriptionPlan.Level.PREMIUM,
            period=SubscriptionPlan.Period.MONTH,
            price_minor=29900,
            currency="RUB",
        )
        self.assertEqual(str(plan), "Premium")
        self.assertEqual(plan.level, "premium")


class SubscriptionTests(TestCase):
    """Тесты подписок."""

    def test_active_subscription(self):
        user = User.objects.create_user(email="sub@test.com", username="sub", password="pass123")
        plan = SubscriptionPlan.objects.create(
            slug="premium-month", name="Premium",
            level="premium", period="month", price_minor=29900,
        )
        sub = Subscription.objects.create(
            user=user,
            plan=plan,
            status=Subscription.Status.ACTIVE,
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timedelta(days=30),
        )
        self.assertTrue(sub.is_active)

    def test_expired_subscription(self):
        user = User.objects.create_user(email="exp@test.com", username="exp", password="pass123")
        plan = SubscriptionPlan.objects.create(
            slug="premium-month", name="Premium",
            level="premium", period="month", price_minor=29900,
        )
        sub = Subscription.objects.create(
            user=user,
            plan=plan,
            status=Subscription.Status.ACTIVE,
            current_period_start=timezone.now() - timedelta(days=60),
            current_period_end=timezone.now() - timedelta(days=1),
        )
        self.assertFalse(sub.is_active)

    def test_canceled_subscription(self):
        user = User.objects.create_user(email="can@test.com", username="can", password="pass123")
        plan = SubscriptionPlan.objects.create(
            slug="premium-month", name="Premium",
            level="premium", period="month", price_minor=29900,
        )
        sub = Subscription.objects.create(
            user=user,
            plan=plan,
            status=Subscription.Status.CANCELED,
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timedelta(days=30),
        )
        self.assertFalse(sub.is_active)


class EntitlementTests(TestCase):
    """Тесты прав доступа."""

    def test_active_entitlement(self):
        user = User.objects.create_user(email="ent@test.com", username="ent", password="pass123")
        from apps.catalog.models import Title
        title = Title.objects.create(name="T", slug="t", release_year=2024, status="published")
        from apps.streaming.models import VideoAsset
        asset = VideoAsset.objects.create(
            title=title, provider="cloudflare_stream", stream_type="hls",
            asset_key="test", duration_seconds=100, status="ready",
        )
        ent = Entitlement.objects.create(
            user=user, asset=asset, source=Entitlement.Source.PURCHASE,
        )
        self.assertTrue(ent.is_active)

    def test_revoked_entitlement(self):
        user = User.objects.create_user(email="rev@test.com", username="rev", password="pass123")
        from apps.catalog.models import Title
        title = Title.objects.create(name="T2", slug="t2", release_year=2024, status="published")
        from apps.streaming.models import VideoAsset
        asset = VideoAsset.objects.create(
            title=title, provider="cloudflare_stream", stream_type="hls",
            asset_key="test2", duration_seconds=100, status="ready",
        )
        ent = Entitlement.objects.create(
            user=user, asset=asset, source=Entitlement.Source.PURCHASE,
            revoked_at=timezone.now(),
        )
        self.assertFalse(ent.is_active)


class PromoCodeTests(TestCase):
    """Тесты промокодов."""

    def test_create_promo_code(self):
        plan = SubscriptionPlan.objects.create(
            slug="vip-month", name="VIP",
            level="vip", period="month", price_minor=49900,
        )
        promo = PromoCode.objects.create(
            code="SUMMER2024",
            plan=plan,
            grant_days=30,
            is_active=True,
        )
        self.assertEqual(str(promo), "SUMMER2024")


class PaymentTests(TestCase):
    """Тесты платежей."""

    def test_create_payment(self):
        user = User.objects.create_user(email="pay@test.com", username="pay", password="pass123")
        plan = SubscriptionPlan.objects.create(
            slug="premium-month", name="Premium",
            level="premium", period="month", price_minor=29900,
        )
        sub = Subscription.objects.create(
            user=user, plan=plan,
            status=Subscription.Status.PENDING,
        )
        payment = Payment.objects.create(
            user=user,
            subscription=sub,
            provider=Payment.Provider.STRIPE,
            provider_payment_id="pi_test_123",
            status=Payment.Status.CREATED,
            amount_minor=29900,
            currency="RUB",
        )
        self.assertEqual(str(payment), "Stripe #pi_test_123")
