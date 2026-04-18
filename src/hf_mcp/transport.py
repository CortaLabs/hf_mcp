from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

from .normalizers import normalize_asks, normalize_response
from .token_store import TokenStore

DEFAULT_API_BASE = "https://hackforums.net/api/v2"


class HFTransport:
    def __init__(
        self,
        token_store: TokenStore,
        base_url: str = DEFAULT_API_BASE,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._token_store = token_store
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def read(self, asks: Mapping[str, Any], helper: str | None = None) -> dict[str, Any]:
        return self._request(operation="read", asks=asks, helper=helper)

    def write(self, asks: Mapping[str, Any], helper: str | None = None) -> dict[str, Any]:
        return self._request(operation="write", asks=asks, helper=helper)

    def _request(self, operation: str, asks: Mapping[str, Any], helper: str | None) -> dict[str, Any]:
        normalized_asks = normalize_asks(asks)
        route = self._build_route(operation=operation, helper=helper)
        token = self._token_store.require_bundle().access_token

        payload = {"asks": normalized_asks}
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        response_payload = self._post_json(route=route, payload=payload, headers=headers)
        if not isinstance(response_payload, dict):
            raise ValueError("HF transport expected object JSON response payload.")
        return normalize_response(response_payload)

    def _build_route(self, operation: str, helper: str | None) -> str:
        route = f"/{operation}"
        if helper is None:
            return route

        cleaned = helper.strip("/")
        if not cleaned:
            raise ValueError("Helper path cannot be empty.")
        if cleaned.startswith("read/") or cleaned.startswith("write/"):
            raise ValueError("Helper path must not include an operation prefix.")
        return f"{route}/{cleaned}"

    def _post_json(
        self,
        route: str,
        payload: Mapping[str, Any],
        headers: Mapping[str, str],
    ) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self._base_url}{route}",
            data=data,
            headers=dict(headers),
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            error_body = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HF {route} failed with HTTP {error.code}. {error_body}") from error

        parsed = json.loads(response_body)
        if not isinstance(parsed, dict):
            raise ValueError("HF transport expected object JSON response payload.")
        return parsed


__all__ = ["HFTransport"]
