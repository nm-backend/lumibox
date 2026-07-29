"""Stripe Payment Provider — реальная интеграция с Stripe Checkout Sessions.

Никаких моков: создаёт настоящие Stripe Checkout Sessions, обрабатывает
вебхуки и обновляет статусы платежей в LumiBox.

Переменные окружения (в production.py или .env):
  STRIPE_SECRET_KEY       — секретный ключ из Stripe Dashboard
  STRIPE_WEBHOOK_SECRET   — секретный ключ вебхука из Stripe Dashboard
  STRIPE_PRICE_MONTHLY    — ID цены для месячной подписки
  STRIPE_PRICE_YEARLY     — ID цены для годовой подписки

Если STRIPE_SECRET_KEY не задан, провайдер работает в "offline"-режиме:
создаёт фиктивные URL и логирует события. Это безопасно для локальной
разработки.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.urls import reverse_lazy
from django.utils import timezone

from apps.billing.models import Payment, Subscription, SubscriptionPlan
from apps.billing.services import PaymentProvider

logger = logging.getLogger("apps.billing.stripe")


@dataclass(frozen=True)
class StripeCheckoutResult:
    url: str
    session_id: str


class StripeProvider(PaymentProvider):
    """Настоящая интеграция Stripe или offline-режим при отсутствии ключа."""

    def __init__(self):
        self._secret_key = getattr(settings, "STRIPE_SECRET_KEY", "")
        self._webhook_secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", "")
        self._enabled = bool(self._secret_key)

        if self._enabled:
            import stripe

            stripe.api_key = self._secret_key
            self._stripe = stripe
        else:
            logger.warning(
                "STRIPE_SECRET_KEY не задан — Stripe работает в offline-режиме. "
                "Платежи не проходят по-настоящему."
            )

    def create_checkout(self, payment: Any, return_url: str) -> str:
        """Создаёт Stripe Checkout Session и возвращает URL для редиректа."""
        if not self._enabled:
            return self._offline_checkout_url(payment)

        if payment.subscription_id:
            return self._create_subscription_checkout(payment, return_url)
        if payment.offer_id:
            return self._create_payment_checkout(payment, return_url)
        raise ValueError("Платёж должен быть привязан к подписке или предложению.")

    def verify_webhook(self, payload: bytes, signature: str) -> dict[str, Any]:
        """Верифицирует и парсит Stripe webhook."""
        if not self._enabled:
            logger.info("Stripe offline: пропускаем вебхук (signature=%s)", signature[:16])
            return {}

        try:
            event = self._stripe.Webhook.construct_event(
                payload=payload,
                sig_header=signature,
                secret=self._webhook_secret,
            )
            return event.to_dict_recursive()
        except ValueError:
            logger.error("Stripe webhook: неверный payload")
            raise
        except self._stripe.error.SignatureVerificationError:
            logger.error("Stripe webhook: неверная подпись (подозрение на подделку)")
            raise

    def handle_checkout_completed(self, session: dict[str, Any]) -> Payment | None:
        """Обрабатывает session.checkout.completed — обновляет Payment и создаёт подписку."""
        session_id = session.get("id", "")
        payment = Payment.objects.filter(provider_payment_id=session_id).first()
        if not payment:
            logger.warning("Stripe webhook: платёж %s не найден в БД", session_id)
            return None

        payment.status = Payment.Status.SUCCEEDED
        payment.metadata.setdefault("stripe_session", session)
        payment.save(update_fields=["status", "metadata"])

        if payment.subscription_id:
            self._activate_subscription_from_stripe(payment, session)

        logger.info("Stripe webhook: платёж %s подтверждён", payment.pk)
        return payment

    def _create_subscription_checkout(self, payment: Payment, return_url: str) -> str:
        """Создаёт Stripe Checkout Session для подписки."""
        plan = payment.subscription.plan
        price_id = self._get_price_id(plan)
        if not price_id:
            logger.error("Stripe: не найден price_id для тарифа %s", plan.slug)
            return self._offline_checkout_url(payment)

        session = self._stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=return_url + "?payment=success",
            cancel_url=return_url + "?payment=canceled",
            client_reference_id=str(payment.user.pk),
            metadata={"payment_id": str(payment.pk)},
        )

        payment.metadata["stripe_session_id"] = session.id
        payment.save(update_fields=["metadata"])

        return session.url

    def _create_payment_checkout(self, payment: Payment, return_url: str) -> str:
        """Создаёт Stripe Checkout Session для разовой покупки/аренды."""
        price_minor = payment.amount_minor

        session = self._stripe.checkout.Session.create(
            mode="payment",
            line_items=[
                {
                    "price_data": {
                        "currency": payment.currency.lower(),
                        "product_data": {
                            "name": str(payment.offer or "Покупка контента"),
                        },
                        "unit_amount": price_minor,
                    },
                    "quantity": 1,
                }
            ],
            success_url=return_url + "?payment=success",
            cancel_url=return_url + "?payment=canceled",
            client_reference_id=str(payment.user.pk),
            metadata={"payment_id": str(payment.pk)},
        )

        payment.metadata["stripe_session_id"] = session.id
        payment.provider = Payment.Provider.STRIPE
        payment.provider_payment_id = session.id
        payment.status = Payment.Status.PENDING
        payment.save(update_fields=["metadata", "provider", "provider_payment_id", "status"])

        return session.url

    def _activate_subscription_from_stripe(self, payment: Payment, session: dict[str, Any]) -> None:
        """Активирует подписку после успешного платежа в Stripe."""
        sub = payment.subscription
        if not sub:
            return

        sub.status = Subscription.Status.ACTIVE
        sub.current_period_start = timezone.now()
        sub.current_period_end = timezone.now() + self._plan_duration(sub.plan)
        sub.provider = Payment.Provider.STRIPE
        sub.provider_subscription_id = session.get("subscription", "")
        sub.save(update_fields=[
            "status", "current_period_start", "current_period_end",
            "provider", "provider_subscription_id",
        ])

    @staticmethod
    def _plan_duration(plan: SubscriptionPlan) -> timezone.timedelta:
        if plan.period == SubscriptionPlan.Period.YEAR:
            return timezone.timedelta(days=365)
        return timezone.timedelta(days=30)

    @staticmethod
    def _get_price_id(plan: SubscriptionPlan) -> str:
        """Получает Stripe Price ID из настроек по слагу тарифа."""
        prices = getattr(settings, "STRIPE_PRICE_IDS", {})
        return prices.get(plan.slug, "")

    @staticmethod
    def _offline_checkout_url(payment: Payment) -> str:
        """Генерирует заглушечный URL для разработки без Stripe-ключа."""
        return str(reverse_lazy("catalog:home")) + "?payment=simulated"
