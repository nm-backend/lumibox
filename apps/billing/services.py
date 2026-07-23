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
