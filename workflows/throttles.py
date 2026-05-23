"""Throttling específico da app workflows (endpoints públicos, webhooks)."""

from rest_framework.throttling import SimpleRateThrottle


class WebhookCatchRateThrottle(SimpleRateThrottle):
    """
    Limite por IP para ``POST .../webhooks/catch/<uuid>/`` (URL com token pode vazar).
    Taxa em ``REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['webhook_catch']``.
    """

    scope = "webhook_catch"
