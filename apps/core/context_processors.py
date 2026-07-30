import time
from datetime import date

from django.conf import settings


def global_settings(request):
    return {
        "ga_measurement_id": getattr(settings, "GA_MEASUREMENT_ID", ""),
    }


def static_version(request):
    return {
        "static_version": int(time.time()),
    }
