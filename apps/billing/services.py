from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from django.db.models import Q
from django.utils import timezone

from apps.billing.models import Entitlement, Subscription, SubscriptionPlan
from apps.streaming.models import VideoAsset


class PaymentProvider(Protocol):
    """Контракт интеграций с платёжными провайдерами без хранения их секретов в БД."""

    def create_checkout(self, payment: Any, return_url: str) -> str: ...

    def verify_webhook(self, payload: bytes, signature: str) -> dict[str, Any]: ...


class PaymentProviderNotConfigured(RuntimeError):
    pass


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    reason: str | None = None


def has_content_access(user: Any, asset: VideoAsset) -> AccessDecision:
    """Единая точка проверки подписки, покупки или аренды для плеера и API."""
    if not getattr(user, "is_authenticated", False):
        return AccessDecision(False, "Требуется вход в аккаунт.")

    if Entitlement.objects.filter(
        user=user,
        asset=asset,
        revoked_at__isnull=True,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())).exists():
        return AccessDecision(True)

    required_levels = _subscription_levels_for(asset.access_level)
    if not required_levels:
        return AccessDecision(False, "Для этого произведения требуется отдельное право доступа.")

    has_subscription = Subscription.objects.filter(
        user=user,
        status=Subscription.Status.ACTIVE,
        current_period_end__gt=timezone.now(),
        plan__level__in=required_levels,
    ).exists()
    return AccessDecision(has_subscription, None if has_subscription else "Требуется подходящая подписка.")


def _subscription_levels_for(access_level: str) -> tuple[str, ...]:
    if access_level == VideoAsset.AccessLevel.PREMIUM:
        return (SubscriptionPlan.Level.PREMIUM, SubscriptionPlan.Level.VIP)
    if access_level == VideoAsset.AccessLevel.VIP:
        return (SubscriptionPlan.Level.VIP,)
    return ()


class StripePaymentProvider:
    """Stripe платежный провайдер.

    Использует stripe SDK для создания checkout sessions и webhook verification.
    Требует STRIPE_SECRET_KEY и STRIPE_WEBHOOK_SECRET в переменных окружения.
    """

    def __init__(self):
        import stripe
        from django.conf import settings

        self.stripe = stripe
        self.stripe.api_key = getattr(settings, "STRIPE_SECRET_KEY", "")
        self.webhook_secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", "")

    def create_checkout(self, payment, return_url: str) -> str:
        """Создаёт Stripe Checkout Session и возвращает URL для редиректа."""
        session = self.stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": payment.currency.lower(),
                    "unit_amount": payment.amount_minor,
                    "product_data": {
                        "name": f"MovieHub — {payment.subscription.plan.name if payment.subscription else 'Purchase'}",
                    },
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=f"{return_url}?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=return_url,
            metadata={"payment_id": str(payment.pk)},
        )
        return session.url

    def verify_webhook(self, payload: bytes, signature: str) -> dict:
        """Верифицирует webhook от Stripe и возвращает event data."""
        event = self.stripe.Webhook.construct_event(
            payload, signature, self.webhook_secret
        )
        return event.data.object


class YooKassaPaymentProvider:
    """ЮKassa платежный провайдер (заготовка)."""

    def __init__(self):
        pass

    def create_checkout(self, payment, return_url: str) -> str:
        raise PaymentProviderNotConfigured("ЮKassa integration not yet implemented")

    def verify_webhook(self, payload: bytes, signature: str) -> dict:
        raise PaymentProviderNotConfigured("ЮKassa integration not yet implemented")
