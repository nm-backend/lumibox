from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.api.v1 import views
from apps.billing.views import stripe_webhook
from apps.core.push_views import PushSubscribeView, PushUnsubscribeView, VapidPublicKeyView

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
    path("search/autocomplete/", views.SearchAutocompleteView.as_view(), name="search-autocomplete"),
    path("webhooks/stripe/", stripe_webhook, name="stripe-webhook"),
    # Push-уведомления
    path("push/vapid-key/", VapidPublicKeyView.as_view(), name="push-vapid-key"),
    path("push/subscribe/", PushSubscribeView.as_view(), name="push-subscribe"),
    path("push/unsubscribe/", PushUnsubscribeView.as_view(), name="push-unsubscribe"),
]
