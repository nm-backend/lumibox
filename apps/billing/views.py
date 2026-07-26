"""
Stripe webhook handler.

Принимает webhook от Stripe, верифицирует подпись,
и обновляет статус платежа/подписки.
"""

import logging

from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.billing.models import Payment
from apps.billing.services import StripePaymentProvider

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def stripe_webhook(request):
    """
    Обработчик webhook от Stripe.

    Принимает события:
    - checkout.session.completed — платёж завершён
    - customer.subscription.created — подписка создана
    - customer.subscription.updated — подписка обновлена
    - customer.subscription.deleted — подписка удалена
    """
    provider = StripePaymentProvider()

    try:
        event = provider.verify_webhook(
            request.body,
            request.META.get("HTTP_STRIPE_SIGNATURE", ""),
        )
    except Exception as e:
        logger.warning(f"Stripe webhook verification failed: {e}")
        return HttpResponseBadRequest("Invalid signature")

    event_type = event.get("type", "")

    if event_type == "checkout.session.completed":
        _handle_checkout_completed(event["data"]["object"])
    elif event_type == "customer.subscription.created":
        _handle_subscription_created(event["data"]["object"])
    elif event_type == "customer.subscription.updated":
        _handle_subscription_updated(event["data"]["object"])
    elif event_type == "customer.subscription.deleted":
        _handle_subscription_deleted(event["data"]["object"])
    else:
        logger.info(f"Unhandled Stripe event: {event_type}")

    return HttpResponse(status=200)


def _handle_checkout_completed(session):
    """Обрабатывает завершение checkout."""
    payment_id = session.get("metadata", {}).get("payment_id")
    if not payment_id:
        return

    try:
        payment = Payment.objects.get(pk=payment_id)
        payment.status = Payment.Status.SUCCEEDED
        payment.provider_payment_id = session.get("payment_intent", "")
        payment.save(update_fields=["status", "provider_payment_id", "updated_at"])
        logger.info(f"Payment {payment_id} succeeded")
    except Payment.DoesNotExist:
        logger.warning(f"Payment {payment_id} not found")


def _handle_subscription_created(subscription_data):
    """Обрабатывает создание подписки."""
    subscription_id = subscription_data.get("id")
    logger.info(f"Stripe subscription created: {subscription_id}")


def _handle_subscription_updated(subscription_data):
    """Обрабатывает обновление подписки."""
    subscription_id = subscription_data.get("id")
    logger.info(f"Stripe subscription updated: {subscription_id}")


def _handle_subscription_deleted(subscription_data):
    """Обрабатывает удаление подписки."""
    subscription_id = subscription_data.get("id")
    logger.info(f"Stripe subscription deleted: {subscription_id}")
