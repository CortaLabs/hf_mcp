from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from collections.abc import Mapping
from typing import Any

from .normalizers import normalize_asks, normalize_response
from .token_store import TokenStore

DEFAULT_API_BASE = "https://hackforums.net/api/v2"
HF_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)

MAX_RETRY_AFTER_SECONDS = 3600
MAX_LOCAL_MESSAGE_CHARS = 200


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: a 3xx surfaces as HTTPError, so a POST is sent
    once and the bearer token cannot be forwarded to another host."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirectHandler)

# One fixed, safe sentence per code. Remote and transport codes never carry
# upstream text, URLs, identifiers, or exception contents.
_ERROR_MESSAGES: dict[str, str] = {
    "INVALID_ARGUMENT": "The request arguments are invalid.",
    "CONFIG_INVALID": "The hf-mcp configuration is invalid.",
    "AUTH_UNAVAILABLE": (
        "No usable Hack Forums access token is available. Run auth bootstrap."
    ),
    "AUTH_REJECTED": "Hack Forums rejected the access token.",
    "PERMISSION_DENIED": "Hack Forums denied this request for the current token.",
    "RESOURCE_UNAVAILABLE": "The requested Hack Forums resource is unavailable.",
    "RATE_LIMITED": "Hack Forums rate limit reached. Try again later.",
    "UPSTREAM_UNAVAILABLE": "Hack Forums is temporarily unavailable.",
    "UPSTREAM_REJECTED": "Hack Forums rejected the request.",
    "UPSTREAM_PROTOCOL_ERROR": (
        "Hack Forums returned an unreadable or unexpected response."
    ),
    "NETWORK_ERROR": "Could not reach Hack Forums.",
    "TIMEOUT": "The request to Hack Forums timed out.",
    "WRITE_OUTCOME_UNKNOWN": (
        "The write was sent but its outcome is unknown. "
        "Check the forum before retrying."
    ),
    "FORMAT_NOT_READY": "The content is not ready to be written.",
    "DRAFT_UNAVAILABLE": "The requested draft is unavailable.",
    "INTERNAL_ERROR": "An internal error occurred.",
}
_LOCAL_MESSAGE_CODES = frozenset(
    {"INVALID_ARGUMENT", "FORMAT_NOT_READY", "DRAFT_UNAVAILABLE"}
)
_OPERATIONS = frozenset({"read", "write", "local"})
_MUTATION_OUTCOMES = frozenset({"not_attempted", "explicitly_rejected", "unknown"})
_READ_STATUS_CODES: dict[int, str] = {
    401: "AUTH_REJECTED",
    403: "PERMISSION_DENIED",
    404: "RESOURCE_UNAVAILABLE",
    429: "RATE_LIMITED",
}
_RETRYABLE_READ_STATUSES = frozenset({429, 503})
_REJECTED_SUCCESS_STRINGS = frozenset({"0", "false"})


def _is_safe_local_message(message: str) -> bool:
    """A package-authored sentence: short, non-empty, and free of path text."""
    return (
        bool(message.strip())
        and len(message) <= MAX_LOCAL_MESSAGE_CHARS
        and "/" not in message
        and "\\" not in message
    )


def build_error(
    code: str,
    *,
    operation: str,
    tool: str | None = None,
    message: str | None = None,
    http_status: int | None = None,
    retry_after: int | None = None,
    retryable: bool = False,
    mutation_outcome: str = "not_attempted",
) -> dict[str, object]:
    """Return the closed nine-field ErrorV1 mapping (hf-error.v1)."""
    if code not in _ERROR_MESSAGES:
        raise ValueError("Unknown ErrorV1 code.")
    if operation not in _OPERATIONS:
        raise ValueError("Unknown ErrorV1 operation.")
    if mutation_outcome not in _MUTATION_OUTCOMES:
        raise ValueError("Unknown ErrorV1 mutation outcome.")
    if (
        message is None
        or code not in _LOCAL_MESSAGE_CODES
        or not _is_safe_local_message(message)
    ):
        message = _ERROR_MESSAGES[code]
    if http_status is not None and not 100 <= http_status <= 599:
        http_status = None
    if retry_after is not None and not 0 <= retry_after <= MAX_RETRY_AFTER_SECONDS:
        retry_after = None
    return {
        "code": code,
        "operation": operation,
        "tool": tool,
        "message": message,
        "http_status": http_status,
        "retry_after": retry_after,
        "retryable": retryable,
        "correlation_id": str(uuid.uuid4()),
        "mutation_outcome": mutation_outcome,
    }


class HFAPIError(RuntimeError):
    """One safe, closed Hack Forums failure carrying an ErrorV1 mapping."""

    def __init__(self, error: Mapping[str, object]) -> None:
        self._error: dict[str, object] = dict(error)
        super().__init__(str(self._error.get("message", "")))

    @property
    def error(self) -> dict[str, object]:
        return dict(self._error)

    def __str__(self) -> str:
        return str(self._error.get("message", ""))


class _WireFailure(Exception):
    """Internal: the HTTP exchange did not yield a JSON object."""

    def __init__(
        self,
        kind: str,
        status: int | None = None,
        retry_after_header: str | None = None,
    ) -> None:
        super().__init__(kind)
        self.kind = kind
        self.status = status
        self.retry_after_header = retry_after_header


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

    def read(
        self, asks: Mapping[str, Any], helper: str | None = None
    ) -> dict[str, Any]:
        return self._request(operation="read", asks=asks, helper=helper, normalize=True)

    def read_raw(
        self, asks: Mapping[str, Any], helper: str | None = None
    ) -> dict[str, Any]:
        return self._request(
            operation="read", asks=asks, helper=helper, normalize=False
        )

    def write(
        self, asks: Mapping[str, Any], helper: str | None = None
    ) -> dict[str, Any]:
        return self._request(
            operation="write", asks=asks, helper=helper, normalize=True
        )

    def _request(
        self,
        operation: str,
        asks: Mapping[str, Any],
        helper: str | None,
        *,
        normalize: bool,
    ) -> dict[str, Any]:
        outcome = self._attempt(operation, asks, helper)
        if isinstance(outcome, HFAPIError):
            raise outcome
        if not normalize:
            return outcome
        return normalize_response(outcome)

    def _attempt(
        self, operation: str, asks: Mapping[str, Any], helper: str | None
    ) -> dict[str, Any] | HFAPIError:
        """Dispatch at most once; return the payload or a built (unraised) error."""
        try:
            normalized_asks = normalize_asks(asks)
            route = self._build_route(operation=operation, helper=helper)
        except ValueError as local_error:
            return _local_error(str(local_error))

        token = self._usable_token()
        if token is None:
            return HFAPIError(build_error("AUTH_UNAVAILABLE", operation="local"))

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": HF_BROWSER_USER_AGENT,
        }
        try:
            payload = self._post_json(
                route=route, payload={"asks": normalized_asks}, headers=headers
            )
        except _WireFailure as failure:
            return _wire_error(operation, failure)

        if not isinstance(payload, dict):
            return _wire_error(operation, _WireFailure("protocol"))
        return _classify_payload(operation, payload, normalized_asks)

    def _usable_token(self) -> str | None:
        try:
            token = self._token_store.require_bundle().access_token
        except Exception:  # any token-store failure is the one safe category
            return None
        if not isinstance(token, str) or not token:
            return None
        if any(ord(char) < 33 or ord(char) == 127 for char in token):
            return None
        return token

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
        try:
            data = json.dumps(payload).encode("utf-8")
        except (TypeError, ValueError):
            raise _WireFailure("invalid") from None
        request = urllib.request.Request(
            f"{self._base_url}{route}",
            data=data,
            headers=dict(headers),
            method="POST",
        )

        failure: _WireFailure | None = None
        parsed: Any = None
        try:
            with _OPENER.open(request, timeout=self._timeout_seconds) as response:
                response_body = response.read()
            parsed = json.loads(response_body.decode("utf-8"))
        except urllib.error.HTTPError as error:
            header_value = None
            if error.headers is not None:
                header_value = error.headers.get("Retry-After")
            failure = _WireFailure("http", error.code, header_value)
            error.close()
        except urllib.error.URLError as error:
            timed_out = isinstance(error.reason, TimeoutError)
            failure = _WireFailure("timeout" if timed_out else "network")
        except TimeoutError:
            failure = _WireFailure("timeout")
        except ValueError:  # invalid UTF-8 or invalid JSON (both ValueError)
            failure = _WireFailure("protocol")
        except Exception:  # connection reset, disconnect, TLS, anything else
            failure = _WireFailure("network")

        if failure is not None:
            raise failure
        if not isinstance(parsed, dict):
            raise _WireFailure("protocol")
        return parsed


def _local_error(message: str) -> HFAPIError:
    return HFAPIError(
        build_error("INVALID_ARGUMENT", operation="local", message=message)
    )


def _wire_error(operation: str, failure: _WireFailure) -> HFAPIError:
    if failure.kind == "invalid":
        return _local_error("`asks` must be JSON serializable.")

    status = failure.status if failure.kind == "http" else None
    if operation == "write":
        return HFAPIError(
            build_error(
                "WRITE_OUTCOME_UNKNOWN",
                operation="write",
                http_status=status,
                mutation_outcome="unknown",
            )
        )

    retry_after = None
    retryable = False
    if failure.kind == "http":
        assert status is not None
        if status in _READ_STATUS_CODES:
            code = _READ_STATUS_CODES[status]
        elif 500 <= status <= 599:
            code = "UPSTREAM_UNAVAILABLE"
        else:
            code = "UPSTREAM_REJECTED"
        retry_after = _parse_retry_after(failure.retry_after_header)
        retryable = status in _RETRYABLE_READ_STATUSES
    elif failure.kind == "timeout":
        code, retryable = "TIMEOUT", True
    elif failure.kind == "network":
        code, retryable = "NETWORK_ERROR", True
    else:
        code = "UPSTREAM_PROTOCOL_ERROR"
    return HFAPIError(
        build_error(
            code,
            operation="read",
            http_status=status,
            retry_after=retry_after,
            retryable=retryable,
        )
    )


def _parse_retry_after(raw: str | None) -> int | None:
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip()
    if not cleaned or not cleaned.isascii() or not cleaned.isdigit():
        return None
    seconds = int(cleaned)
    return seconds if seconds <= MAX_RETRY_AFTER_SECONDS else None


def _is_rejected_success(value: Any) -> bool:
    if isinstance(value, bool):
        return value is False
    if isinstance(value, (int, float)):
        return value == 0
    return isinstance(value, str) and value.strip().lower() in _REJECTED_SUCCESS_STRINGS


def _classify_payload(
    operation: str,
    payload: dict[str, Any],
    normalized_asks: Mapping[str, Any],
) -> dict[str, Any] | HFAPIError:
    """Single application-status and envelope check shared by every method."""
    envelopes: list[Mapping[str, Any]] = [payload]
    envelopes.extend(
        value
        for endpoint in normalized_asks
        if isinstance(value := payload.get(endpoint), Mapping)
    )
    if any(
        "success" in env and _is_rejected_success(env["success"]) for env in envelopes
    ):
        return HFAPIError(
            build_error(
                "UPSTREAM_REJECTED",
                operation=operation,
                mutation_outcome=(
                    "explicitly_rejected" if operation == "write" else "not_attempted"
                ),
            )
        )

    if operation == "read":
        for endpoint in normalized_asks:
            value = payload.get(endpoint)
            if endpoint not in payload or isinstance(value, Mapping):
                continue
            if isinstance(value, list) and all(
                isinstance(row, Mapping) for row in value
            ):
                continue
            return _wire_error(operation, _WireFailure("protocol"))
    return payload


__all__ = ["HFAPIError", "HFTransport", "build_error"]
