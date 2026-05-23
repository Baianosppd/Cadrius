import json
from typing import Any

import requests

from workflows.models import Action


class WebhookExecutor:
    """
    Dispara o pedido HTTP de uma ação tipo webhook.

    Lê ``endpoint_url``, ``method`` e ``headers`` do modelo ``Action`` e envia o corpo
    JSON já renderizado (``json_body``).
    """

    def __init__(self, action: Action, *, timeout: int = 15):
        self.action = action
        self.timeout = timeout

    @staticmethod
    def _headers_from_action(headers: Any) -> dict:
        if not headers:
            return {}
        if isinstance(headers, dict):
            return dict(headers)
        return json.loads(headers)

    def execute(self, json_body: dict) -> requests.Response:
        url = self.action.endpoint_url
        if not url:
            raise ValueError("Ação webhook sem endpoint_url configurado.")

        method = (self.action.method or "POST").upper()
        hdrs = self._headers_from_action(self.action.headers)

        return requests.request(
            method=method,
            url=url,
            json=json_body,
            headers=hdrs,
            timeout=self.timeout,
        )
