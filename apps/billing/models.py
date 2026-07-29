from __future__ import annotations

import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel
from apps.core.validators import validate_image_file

PROMO_CODE_VALIDATOR = RegexValidator(
    regex=r"^[A-Z0-9][A-Z0-9_-]{2,31}$",
    message="Промокод состоит из 3–32 прописных латинских букв, цифр, дефисов или подчёркиваний.",
)


class SubscriptionPlan(TimeStampedModel):
    class Level(models.TextChoices):
        PREMIUM = "premium", "Premium"
        VIP = "vip", "VIP"

    class Period(models.TextChoices):
        MONTH = "month", "Месяц"
        YEAR = "year", "Год"

    slug = models.SlugField("Адрес", max_length=80, unique=True)
    name = models.CharField("Название", max_length=120)
    level = models.CharField("Уровень", max_length=10, choices=Level.choices)
    period = models.CharField("Период", max_length=10, choices=Period.choices, default=Period.MONTH)
    price_minor = models.PositiveIntegerField("Цена в минимальных единицах", validators=[MinValueValidator(1)])
    currency = models.CharField("Валюта", max_length=3, default="RUB")
    description = models.TextField("Описание", blank=True)
    is_active = models.BooleanField("Доступен для подключения", default=True)

    class Meta:
        verbose_name = "Тариф"
        verbose_name_plural = "Тарифы"
        ordering = ["level", "price_minor"]

    def __str__(self) -> str:
        return self.name


class ContentOffer(TimeStampedModel):
    class Kind(models.TextChoices):
        RENTAL = "rental", "Аренда"
        PURCHASE = "purchase", "Покупка"

    asset = models.ForeignKey(
        "streaming.VideoAsset",
        verbose_name="Видеоресурс",
        on_delete=models.CASCADE,
        related_name="offers",
    )
    kind = models.CharField("Тип", max_length=10, choices=Kind.choices)
    price_minor = models.PositiveIntegerField("Цена в минимальных единицах", validators=[MinValueValidator(1)])
    currency = models.CharField("Валюта", max_length=3, default="RUB")
    rental_hours = models.PositiveSmallIntegerField("Срок аренды, часов", null=True, blank=True)
    is_active = models.BooleanField("Доступен", default=True)

    class Meta:
        verbose_name = "Коммерческое предложение"
        verbose_name_plural = "Коммерческие предложения"
        constraints = [
            models.UniqueConstraint(fields=["asset", "kind"], name="unique_content_offer_kind"),
        ]

    def __str__(self) -> str:
        return f"{self.asset} — {self.get_kind_display()}"

    def clean(self) -> None:
        super().clean()
        if self.kind == self.Kind.RENTAL and not self.rental_hours:
            raise ValidationError({"rental_hours": "Укажите срок действия аренды."})
        if self.kind == self.Kind.PURCHASE and self.rental_hours:
            raise ValidationError({"rental_hours": "Для покупки срок аренды не указывается."})


class Subscription(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает оплаты"
        ACTIVE = "active", "Активна"
        CANCELED = "canceled", "Отменена"
        EXPIRED = "expired", "Истекла"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subscriptions")
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField("Статус", max_length=10, choices=Status.choices, default=Status.PENDING)
    current_period_start = models.DateTimeField("Начало оплаченного периода", null=True, blank=True)
    current_period_end = models.DateTimeField("Конец оплаченного периода", null=True, blank=True)
    cancel_at_period_end = models.BooleanField("Отменить по окончании периода", default=False)
    provider = models.CharField("Платёжный провайдер", max_length=32, blank=True)
    provider_subscription_id = models.CharField("Идентификатор подписки у провайдера", max_length=255, blank=True)

    class Meta:
        verbose_name = "Подписка"
        verbose_name_plural = "Подписки"
        indexes = [
            models.Index(fields=["user", "status", "current_period_end"], name="subscription_access_idx"),
            # Проверка активной подписки: SELECT ... WHERE user=%s AND status='active'.
            models.Index(fields=["user", "status"], name="subscription_user_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user} — {self.plan}"

    @property
    def is_active(self) -> bool:
        return bool(
            self.status == self.Status.ACTIVE
            and self.current_period_end
            and self.current_period_end > timezone.now()
        )


class Entitlement(TimeStampedModel):
    class Source(models.TextChoices):
        PURCHASE = "purchase", "Покупка"
        RENTAL = "rental", "Аренда"
        PROMO = "promo", "Промокод"
        SUPPORT = "support", "Поддержка"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="entitlements")
    asset = models.ForeignKey("streaming.VideoAsset", on_delete=models.CASCADE, related_name="entitlements")
    source = models.CharField("Источник", max_length=12, choices=Source.choices)
    expires_at = models.DateTimeField("Действует до", null=True, blank=True)
    revoked_at = models.DateTimeField("Отозвано", null=True, blank=True)

    class Meta:
        verbose_name = "Право доступа"
        verbose_name_plural = "Права доступа"
        indexes = [
            models.Index(fields=["user", "asset", "expires_at"], name="entitlement_access_idx"),
            # Проверка активного права: SELECT ... WHERE user=%s AND asset=%s AND revoked_at IS NULL.
            models.Index(fields=["user", "asset", "revoked_at"], name="entitlement_active_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user} — {self.asset}"

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and (self.expires_at is None or self.expires_at > timezone.now())


class PromoCode(TimeStampedModel):
    code = models.CharField("Код", max_length=32, unique=True, validators=[PROMO_CODE_VALIDATOR])
    plan = models.ForeignKey(
        SubscriptionPlan,
        verbose_name="Тариф",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="promo_codes",
    )
    asset = models.ForeignKey(
        "streaming.VideoAsset",
        verbose_name="Видеоресурс",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="promo_codes",
    )
    grant_days = models.PositiveSmallIntegerField("Срок доступа, дней", validators=[MinValueValidator(1)])
    starts_at = models.DateTimeField("Действует с", null=True, blank=True)
    ends_at = models.DateTimeField("Действует до", null=True, blank=True)
    max_uses = models.PositiveIntegerField("Лимит активаций", null=True, blank=True)
    is_active = models.BooleanField("Активен", default=True)

    class Meta:
        verbose_name = "Промокод"
        verbose_name_plural = "Промокоды"

    def __str__(self) -> str:
        return self.code

    def clean(self) -> None:
        super().clean()
        if bool(self.plan_id) == bool(self.asset_id):
            raise ValidationError("Промокод должен выдавать один тариф или один видеоресурс.")
        if self.starts_at and self.ends_at and self.starts_at >= self.ends_at:
            raise ValidationError({"ends_at": "Дата окончания должна быть позже даты начала."})


class PromoRedemption(TimeStampedModel):
    promo_code = models.ForeignKey(PromoCode, on_delete=models.PROTECT, related_name="redemptions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="promo_redemptions")

    class Meta:
        verbose_name = "Активация промокода"
        verbose_name_plural = "Активации промокодов"
        constraints = [
            models.UniqueConstraint(fields=["promo_code", "user"], name="unique_promo_redemption"),
        ]


class Payment(TimeStampedModel):
    class Provider(models.TextChoices):
        STRIPE = "stripe", "Stripe"
        PAYPAL = "paypal", "PayPal"
        YOOKASSA = "yookassa", "ЮKassa"
        CLOUDPAYMENTS = "cloudpayments", "CloudPayments"

    class Status(models.TextChoices):
        CREATED = "created", "Создан"
        PENDING = "pending", "Ожидает подтверждения"
        SUCCEEDED = "succeeded", "Подтверждён"
        FAILED = "failed", "Неуспешен"
        CANCELED = "canceled", "Отменён"
        REFUNDED = "refunded", "Возвращён"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payments")
    subscription = models.ForeignKey(
        Subscription, on_delete=models.PROTECT, null=True, blank=True, related_name="payments"
    )
    offer = models.ForeignKey(ContentOffer, on_delete=models.PROTECT, null=True, blank=True, related_name="payments")
    provider = models.CharField("Провайдер", max_length=20, choices=Provider.choices)
    provider_payment_id = models.CharField("Идентификатор платежа", max_length=255, unique=True)
    status = models.CharField("Статус", max_length=10, choices=Status.choices, default=Status.CREATED)
    amount_minor = models.PositiveIntegerField("Сумма в минимальных единицах", validators=[MinValueValidator(1)])
    currency = models.CharField("Валюта", max_length=3)
    metadata = models.JSONField("Технические данные", default=dict, blank=True)

    class Meta:
        verbose_name = "Платёж"
        verbose_name_plural = "Платежи"
        indexes = [
            models.Index(fields=["user", "status", "-created_at"], name="payment_user_status_idx"),
            # Список платежей пользователя: SELECT ... WHERE user=%s ORDER BY created_at DESC.
            models.Index(fields=["user", "-created_at"], name="payment_user_date_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.get_provider_display()} #{self.provider_payment_id}"

    def clean(self) -> None:
        super().clean()
        if bool(self.subscription_id) == bool(self.offer_id):
            raise ValidationError("Платёж относится к одной подписке или одному предложению.")


class ReferralProfile(TimeStampedModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="referral_profile")
    code = models.CharField("Реферальный код", max_length=16, unique=True, editable=False)

    class Meta:
        verbose_name = "Реферальный профиль"
        verbose_name_plural = "Реферальные профили"

    def save(self, *args, **kwargs) -> None:
        if not self.code:
            self.code = self._generate_code()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_code() -> str:
        return secrets.token_urlsafe(8).upper().replace("-", "").replace("_", "")[:16]


class Referral(TimeStampedModel):
    referrer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="referrals_made")
    referred_user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="referral_received"
    )
    reward_granted_at = models.DateTimeField("Награда выдана", null=True, blank=True)

    class Meta:
        verbose_name = "Реферал"
        verbose_name_plural = "Рефералы"


class Promotion(TimeStampedModel):
    class Placement(models.TextChoices):
        HOME = "home", "Главная"
        CATALOG = "catalog", "Каталог"
        DETAIL = "detail", "Карточка произведения"

    name = models.CharField("Название", max_length=160)
    placement = models.CharField("Размещение", max_length=12, choices=Placement.choices)
    title = models.CharField("Заголовок", max_length=160)
    text = models.CharField("Текст", max_length=280, blank=True)
    image = models.ImageField(
        "Изображение",
        upload_to="promotions/%Y/%m",
        blank=True,
        validators=[validate_image_file],
    )
    target_url = models.URLField("Целевая ссылка")
    starts_at = models.DateTimeField("Показывать с", null=True, blank=True)
    ends_at = models.DateTimeField("Показывать до", null=True, blank=True)
    is_active = models.BooleanField("Активна", default=True)

    class Meta:
        verbose_name = "Партнёрский баннер"
        verbose_name_plural = "Партнёрские баннеры"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name

    @property
    def is_current(self) -> bool:
        now = timezone.now()
        return self.is_active and (self.starts_at is None or self.starts_at <= now) and (
            self.ends_at is None or self.ends_at > now
        )
