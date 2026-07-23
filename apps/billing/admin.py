from django.contrib import admin

from apps.billing.models import (
    ContentOffer,
    Entitlement,
    Payment,
    PromoCode,
    PromoRedemption,
    Promotion,
    Referral,
    ReferralProfile,
    Subscription,
    SubscriptionPlan,
)


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ["name", "level", "period", "price_minor", "currency", "is_active"]
    list_filter = ["level", "period", "is_active"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ["name"]}


@admin.register(ContentOffer)
class ContentOfferAdmin(admin.ModelAdmin):
    list_display = ["asset", "kind", "price_minor", "currency", "rental_hours", "is_active"]
    list_filter = ["kind", "is_active", "currency"]
    search_fields = ["asset__title__name", "asset__episode__name"]
    autocomplete_fields = ["asset"]


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ["user", "plan", "status", "current_period_end", "cancel_at_period_end"]
    list_filter = ["status", "plan"]
    search_fields = ["user__email", "user__username", "provider_subscription_id"]
    autocomplete_fields = ["user", "plan"]


@admin.register(Entitlement)
class EntitlementAdmin(admin.ModelAdmin):
    list_display = ["user", "asset", "source", "expires_at", "revoked_at"]
    list_filter = ["source", "revoked_at"]
    search_fields = ["user__email", "asset__title__name"]
    autocomplete_fields = ["user", "asset"]


@admin.register(PromoCode)
class PromoCodeAdmin(admin.ModelAdmin):
    list_display = ["code", "plan", "asset", "grant_days", "max_uses", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["code"]
    autocomplete_fields = ["plan", "asset"]


@admin.register(PromoRedemption)
class PromoRedemptionAdmin(admin.ModelAdmin):
    list_display = ["promo_code", "user", "created_at"]
    search_fields = ["promo_code__code", "user__email"]
    autocomplete_fields = ["promo_code", "user"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ["provider", "provider_payment_id", "user", "status", "amount_minor", "currency", "created_at"]
    list_filter = ["provider", "status", "currency"]
    search_fields = ["provider_payment_id", "user__email"]
    autocomplete_fields = ["user", "subscription", "offer"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(ReferralProfile)
class ReferralProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "code"]
    search_fields = ["user__email", "code"]
    autocomplete_fields = ["user"]


@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    list_display = ["referrer", "referred_user", "reward_granted_at"]
    search_fields = ["referrer__email", "referred_user__email"]
    autocomplete_fields = ["referrer", "referred_user"]


@admin.register(Promotion)
class PromotionAdmin(admin.ModelAdmin):
    list_display = ["name", "placement", "is_active", "starts_at", "ends_at"]
    list_filter = ["placement", "is_active"]
    search_fields = ["name", "title"]
