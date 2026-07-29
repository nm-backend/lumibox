"""Views для Stripe интеграции: создание Checkout Session и обработка Webhook.

Отдельный файл, а не вшито в billing/views.py, потому что billing
пока не имеет своих шаблонных вьюх — вся логика идёт через REST API.
"""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from apps.billing.models import Payment, SubscriptionPlan
from apps.billing.stripe_provider import StripeProvider

logger = logging.getLogger("apps.billing.views")


class CreateCheckoutSessionView(View):
    """Создаёт Stripe Checkout Session для покупки подписки.

    POST /api/v1/billing/checkout/

    Тело запроса:
      {"plan_slug": "premium-month", "success_url": "https://..."}

    Ответ:
      {"url": "https://checkout.stripe.com/..."}
    """

    def post(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Требуется вход."}, status=403)

        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"error": "Неверный JSON."}, status=400)

        plan_slug = body.get("plan_slug", "")
        success_url = body.get("success_url", request.build_absolute_uri(reverse("catalog:home")))

        plan = get_object_or_404(SubscriptionPlan, slug=plan_slug, is_active=True)

        # Создаём запись о подписке и платеже.
        from apps.billing.models import Subscription

        subscription = Subscription.objects.create(
            user=request.user,
            plan=plan,
            status=Subscription.Status.PENDING,
        )

        payment = Payment.objects.create(
            user=request.user,
            subscription=subscription,
            provider=Payment.Provider.STRIPE,
            provider_payment_id="pending",
            amount_minor=plan.price_minor,
            currency=plan.currency,
        )

        provider = StripeProvider()
        try:
            checkout_url = provider.create_checkout(payment, success_url)
        except Exception:
            logger.exception("Stripe: ошибка создания Checkout Session")
            return JsonResponse({"error": "Не удалось создать платёжную сессию."}, status=502)

        return JsonResponse({"url": checkout_url})


@method_decorator(csrf_exempt, name="dispatch")
class StripeWebhookView(View):
    """Принимает вебхуки от Stripe.

    POST /api/v1/billing/webhook/

    Stripe отправляет сюда события checkout.session.completed
    и invoice.paid. Обрабатываются только подписанные события
    с валидной Stripe-Signature.

    Адрес защищён подписью, а не сессией Django, поэтому CSRF отключён.
    """

    def post(self, request):
        provider = StripeProvider()
        payload = request.body

        signature = request.META.get("HTTP_STRIPE_SIGNATURE", "")
        if not signature:
            return HttpResponse(status=400)

        try:
            event = provider.verify_webhook(payload, signature)
        except ValueError:
            return HttpResponse(status=400)
        except Exception:
            logger.exception("Stripe webhook: ошибка верификации")
            return HttpResponse(status=400)

        event_type = event.get("type", "")

        if event_type == "checkout.session.completed":
            session = event.get("data", {}).get("object", {})
            provider.handle_checkout_completed(session)

        elif event_type == "invoice.paid":
            # Обновление статуса подписки после продления.
            session = event.get("data", {}).get("object", {})
            subscription_id = session.get("subscription", "")
            if subscription_id:
                from apps.billing.models import Subscription

                Subscription.objects.filter(
                    provider_subscription_id=subscription_id,
                    status=Subscription.Status.ACTIVE,
                ).update(
                    current_period_end=timezone.now() + timezone.timedelta(days=30),
                    status=Subscription.Status.ACTIVE,
                )

        elif event_type == "customer.subscription.deleted":
            session = event.get("data", {}).get("object", {})
            subscription_id = session.get("id", "")
            if subscription_id:
                from apps.billing.models import Subscription

                Subscription.objects.filter(
                    provider_subscription_id=subscription_id,
                ).update(status=Subscription.Status.EXPIRED)

        return HttpResponse(status=200)
