from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.api.v1 import views
from apps.billing.views import CreateCheckoutSessionView, StripeWebhookView

# Версия в адресе с самого начала: когда API понадобится изменить
# несовместимо, появится v2, а старые клиенты продолжат работать на v1.
app_name = "v1"

router = DefaultRouter()
router.register("titles", views.TitleViewSet, basename="title")
router.register("genres", views.GenreViewSet, basename="genre")
router.register("countries", views.CountryViewSet, basename="country")
router.register("collections", views.CollectionViewSet, basename="collection")

# Отзывы вложены в запись: отдельного списка всех отзывов сайту не нужно.
reviews = views.ReviewViewSet.as_view({"get": "list", "post": "create"})
review_detail = views.ReviewViewSet.as_view({"put": "update", "patch": "partial_update", "delete": "destroy"})

urlpatterns = [
    path("", include(router.urls)),
    path("titles/<slug:title_slug>/reviews/", reviews, name="title-reviews"),
    path("titles/<slug:title_slug>/reviews/<int:pk>/", review_detail, name="title-review-detail"),
    path("titles/<slug:title_slug>/rate/", views.RateTitleView.as_view(), name="title-rate"),
    # Stripe — платёжный шлюз.
    path("billing/checkout/", CreateCheckoutSessionView.as_view(), name="billing-checkout"),
    path("billing/webhook/", StripeWebhookView.as_view(), name="billing-webhook"),
]
