from __future__ import annotations

import copy
import email.message
import http.client
import io
import json
import logging
import urllib.error
import urllib.request
import urllib.response
import uuid
from collections.abc import Callable
from typing import Any

import pytest

from hf_mcp.normalizers import normalize_extended_payload, normalize_response
from hf_mcp.token_store import TokenBundle
from hf_mcp.server import _error_call_tool_result
from hf_mcp.transport import HFAPIError, HFTransport, _NoRedirectHandler
from hf_mcp.write_preflight import WritePreflightError

ERROR_V1_FIELDS = {
    "code",
    "operation",
    "tool",
    "message",
    "http_status",
    "retry_after",
    "retryable",
    "correlation_id",
    "mutation_outcome",
}
SEED_TOKEN = "TOKENSEED9f3a1c"
SEED_ASKS = "ASKSSEED77b2"
SEED_BODY = "BODYSEED51de"
SEED_HEADER = "HEADERSEED08aa"
SEED_HOST = "hostseed42.invalid"
SEED_HELPER = "helperseed19"
SEEDS = (SEED_TOKEN, SEED_ASKS, SEED_BODY, SEED_HEADER, SEED_HOST, SEED_HELPER)


class _StubTokenStore:
    def require_bundle(self) -> TokenBundle:
        return TokenBundle(
            access_token=SEED_TOKEN, token_type="Bearer", scope=frozenset()
        )


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _http_error(
    status: int, body: str = SEED_BODY, headers: dict[str, str] | None = None
) -> urllib.error.HTTPError:
    message = email.message.Message()
    for key, value in (headers or {}).items():
        message[key] = value
    return urllib.error.HTTPError(
        f"https://{SEED_HOST}/api/v2/read",
        status,
        "msg",
        message,
        io.BytesIO(body.encode()),
    )


class _FakeOpener:
    def __init__(self, behavior: Callable[[], Any], requests: list[Any]) -> None:
        self._behavior = behavior
        self._requests = requests

    def open(self, request: Any, timeout: float | None = None) -> _FakeResponse:
        self._requests.append(request)
        result = self._behavior()
        return _FakeResponse(
            result if isinstance(result, bytes) else json.dumps(result).encode()
        )


def _install_urlopen(
    monkeypatch: pytest.MonkeyPatch, behavior: Callable[[], Any]
) -> list[Any]:
    """Replace the network edge; ``behavior`` returns bytes/JSON or raises."""
    requests: list[Any] = []
    monkeypatch.setattr("hf_mcp.transport._OPENER", _FakeOpener(behavior, requests))
    return requests


def _raising(error: BaseException) -> Callable[[], Any]:
    def _raise() -> Any:
        raise error

    return _raise


def _transport() -> HFTransport:
    return HFTransport(
        token_store=_StubTokenStore(), base_url=f"https://{SEED_HOST}/api/v2"
    )


ASKS = {"posts": {"_tid": 5, "_message": SEED_ASKS}}
METHODS = ("read", "read_raw", "write")


def _call(transport: HFTransport, method: str, helper: str | None = None) -> Any:
    return getattr(transport, method)(asks=ASKS, helper=helper)


def _assert_error_v1(error: HFAPIError) -> dict[str, Any]:
    data = error.error
    assert set(data) == ERROR_V1_FIELDS
    assert uuid.UUID(data["correlation_id"])
    assert data["tool"] is None
    assert data["operation"] in {"read", "write", "local"}
    assert data["mutation_outcome"] in {
        "not_attempted",
        "explicitly_rejected",
        "unknown",
    }
    assert isinstance(data["retryable"], bool)
    assert data["http_status"] is None or 100 <= data["http_status"] <= 599
    assert data["retry_after"] is None or 0 <= data["retry_after"] <= 3600
    assert str(error) == data["message"]
    return data


def _assert_no_seeds(*texts: str) -> None:
    for text in texts:
        for seed in SEEDS:
            assert seed not in text


# ---------------------------------------------------------------- A1 status


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("flag", [0, "0", False, 0.0, "false", "False"])
@pytest.mark.parametrize("position", ["top", "envelope"])
def test_success_zero_is_upstream_rejected_before_normalization(
    monkeypatch: pytest.MonkeyPatch, method: str, flag: Any, position: str
) -> None:
    body: dict[str, Any] = (
        {"success": flag, "posts": {"pid": 1}}
        if position == "top"
        else {"posts": {"success": flag, "message": SEED_BODY}}
    )
    requests = _install_urlopen(monkeypatch, lambda: body)

    with pytest.raises(HFAPIError) as raised:
        _call(_transport(), method)

    data = _assert_error_v1(raised.value)
    assert data["code"] == "UPSTREAM_REJECTED"
    assert data["operation"] == ("write" if method == "write" else "read")
    assert data["mutation_outcome"] == (
        "explicitly_rejected" if method == "write" else "not_attempted"
    )
    assert data["retryable"] is False
    assert len(requests) == 1
    _assert_no_seeds(str(raised.value), repr(raised.value), json.dumps(data))


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize(
    "body",
    [
        {"posts": [{"pid": "1", "success": "1"}]},
        {"success": 1, "posts": {"pid": 1}},
        {"success": True, "posts": []},
        {"posts": {}},
        {"posts": []},
        {"bytes": [{"amount": 0, "flag": False, "note": "no error here"}]},
        {"posts": [{"message": "success: 0 and error"}]},
    ],
)
def test_valid_payloads_including_zero_values_succeed(
    monkeypatch: pytest.MonkeyPatch, method: str, body: dict[str, Any]
) -> None:
    raw = copy.deepcopy(body)
    _install_urlopen(monkeypatch, lambda: body)

    result = _call(_transport(), method)

    if method == "read_raw":
        assert result == raw
    else:
        assert result == normalize_response(raw)


def test_empty_mapping_and_list_normalize_to_no_rows() -> None:
    assert normalize_response({"posts": {}, "bytes": []}) == {"posts": [], "bytes": []}
    assert normalize_response({"posts": {"pid": 7}}) == {"posts": [{"pid": "7"}]}


# ----------------------------------------------------------- A2 read mapping


@pytest.mark.parametrize("method", ["read", "read_raw"])
@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (400, "UPSTREAM_REJECTED", False),
        (401, "AUTH_REJECTED", False),
        (403, "PERMISSION_DENIED", False),
        (404, "RESOURCE_UNAVAILABLE", False),
        (418, "UPSTREAM_REJECTED", False),
        (429, "RATE_LIMITED", True),
        (500, "UPSTREAM_UNAVAILABLE", False),
        (502, "UPSTREAM_UNAVAILABLE", False),
        (503, "UPSTREAM_UNAVAILABLE", True),
    ],
)
def test_read_http_statuses_map_to_closed_codes(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    status: int,
    code: str,
    retryable: bool,
) -> None:
    requests = _install_urlopen(monkeypatch, _raising(_http_error(status)))

    with pytest.raises(HFAPIError) as raised:
        _call(_transport(), method)

    data = _assert_error_v1(raised.value)
    assert (data["code"], data["http_status"], data["retryable"]) == (
        code,
        status,
        retryable,
    )
    assert data["operation"] == "read"
    assert data["mutation_outcome"] == "not_attempted"
    assert len(requests) == 1


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("0", 0),
        ("30", 30),
        ("3600", 3600),
        ("3601", None),
        ("99999999999999999999", None),
        ("-1", None),
        ("1.5", None),
        ("abc", None),
        ("", None),
        ("Wed, 21 Oct 2015 07:28:00 GMT", None),
        ("٣", None),
        (SEED_HEADER, None),
    ],
)
def test_retry_after_is_bounded_integer_seconds_or_null(
    monkeypatch: pytest.MonkeyPatch, header: str, expected: int | None
) -> None:
    _install_urlopen(
        monkeypatch, _raising(_http_error(429, headers={"Retry-After": header}))
    )

    with pytest.raises(HFAPIError) as raised:
        _transport().read(asks=ASKS)

    data = _assert_error_v1(raised.value)
    assert data["code"] == "RATE_LIMITED"
    assert data["retry_after"] == expected
    _assert_no_seeds(json.dumps(data))


@pytest.mark.parametrize(
    ("failure", "code", "retryable"),
    [
        (TimeoutError(SEED_BODY), "TIMEOUT", True),
        (urllib.error.URLError(TimeoutError(SEED_BODY)), "TIMEOUT", True),
        (urllib.error.URLError(SEED_BODY), "NETWORK_ERROR", True),
        (ConnectionResetError(SEED_BODY), "NETWORK_ERROR", True),
        (http.client.RemoteDisconnected(SEED_BODY), "NETWORK_ERROR", True),
        (b"\xff\xfe not utf-8", "UPSTREAM_PROTOCOL_ERROR", False),
        (b"{not json " + SEED_BODY.encode(), "UPSTREAM_PROTOCOL_ERROR", False),
        (b'["a", "list"]', "UPSTREAM_PROTOCOL_ERROR", False),
        (b'"text"', "UPSTREAM_PROTOCOL_ERROR", False),
        (b'{"posts": ["scalar-row"]}', "UPSTREAM_PROTOCOL_ERROR", False),
        (b'{"posts": [[{"pid": 1}]]}', "UPSTREAM_PROTOCOL_ERROR", False),
        (b'{"posts": [{"pid": 1}, null]}', "UPSTREAM_PROTOCOL_ERROR", False),
        (b'{"posts": null}', "UPSTREAM_PROTOCOL_ERROR", False),
        (b'{"posts": "scalar"}', "UPSTREAM_PROTOCOL_ERROR", False),
    ],
)
@pytest.mark.parametrize("method", ["read", "read_raw"])
def test_read_network_and_protocol_failures_map_to_closed_codes(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    failure: Any,
    code: str,
    retryable: bool,
) -> None:
    behavior = (
        _raising(failure) if isinstance(failure, BaseException) else (lambda: failure)
    )
    requests = _install_urlopen(monkeypatch, behavior)

    with pytest.raises(HFAPIError) as raised:
        _call(_transport(), method)

    data = _assert_error_v1(raised.value)
    assert (data["code"], data["retryable"], data["http_status"]) == (
        code,
        retryable,
        None,
    )
    assert data["retry_after"] is None
    assert len(requests) == 1
    _assert_no_seeds(str(raised.value), repr(raised.value), json.dumps(data))
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


def test_same_code_has_one_fixed_message_regardless_of_upstream_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages = set()
    for body in ("one", "two <script>", SEED_BODY * 20):
        _install_urlopen(monkeypatch, _raising(_http_error(403, body=body)))
        with pytest.raises(HFAPIError) as raised:
            _transport().read(asks=ASKS)
        messages.add(str(raised.value))
    assert len(messages) == 1


def test_error_ids_are_unique_and_error_property_is_a_defensive_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_urlopen(monkeypatch, _raising(_http_error(404)))
    ids = set()
    for _ in range(2):
        with pytest.raises(HFAPIError) as raised:
            _transport().read(asks=ASKS)
        data = raised.value.error
        ids.add(data["correlation_id"])
        data["code"] = "TAMPERED"
        assert raised.value.error["code"] == "RESOURCE_UNAVAILABLE"
    assert len(ids) == 2


# --------------------------------------------------------------- A3 writes


@pytest.mark.parametrize(
    "failure",
    [
        TimeoutError(SEED_BODY),
        urllib.error.URLError(SEED_BODY),
        ConnectionResetError(SEED_BODY),
        http.client.RemoteDisconnected(SEED_BODY),
        _http_error(401),
        _http_error(404),
        _http_error(429, headers={"Retry-After": "30"}),
        _http_error(500),
        _http_error(503, headers={"Retry-After": "30"}),
        b"\xff\xfe",
        b"{broken",
        b"[1, 2]",
    ],
)
def test_write_failure_after_dispatch_is_unknown_outcome_with_one_request(
    monkeypatch: pytest.MonkeyPatch, failure: Any
) -> None:
    behavior = (
        _raising(failure) if isinstance(failure, BaseException) else (lambda: failure)
    )
    requests = _install_urlopen(monkeypatch, behavior)

    with pytest.raises(HFAPIError) as raised:
        _transport().write(asks=ASKS, helper="posts")

    data = _assert_error_v1(raised.value)
    assert data["code"] == "WRITE_OUTCOME_UNKNOWN"
    assert data["operation"] == "write"
    assert data["mutation_outcome"] == "unknown"
    assert data["retryable"] is False
    assert data["retry_after"] is None
    assert len(requests) == 1
    _assert_no_seeds(str(raised.value), repr(raised.value), json.dumps(data))


@pytest.mark.parametrize(
    "asks",
    [
        {},
        {"posts": "not-a-mapping"},
        {"": {"_tid": 1}},
        {"posts": {"_perpage": 0}},
        {"posts": {"_perpage": SEED_ASKS}},
        {"posts": {"_perpage": float("inf")}},
        {"posts": {"_tid": {1, 2, 3}}},
    ],
)
@pytest.mark.parametrize("method", METHODS)
def test_local_invalid_asks_never_dispatch(
    monkeypatch: pytest.MonkeyPatch, method: str, asks: Any
) -> None:
    requests = _install_urlopen(monkeypatch, lambda: {"posts": []})

    with pytest.raises(HFAPIError) as raised:
        getattr(_transport(), method)(asks=asks)

    data = _assert_error_v1(raised.value)
    assert (data["code"], data["operation"], data["mutation_outcome"]) == (
        "INVALID_ARGUMENT",
        "local",
        "not_attempted",
    )
    assert data["retryable"] is False
    assert requests == []
    _assert_no_seeds(str(raised.value), json.dumps(data))


@pytest.mark.parametrize("helper", ["", "/", "read/posts", "write/posts"])
def test_local_invalid_helper_never_dispatches(
    monkeypatch: pytest.MonkeyPatch, helper: str
) -> None:
    requests = _install_urlopen(monkeypatch, lambda: {"posts": []})

    with pytest.raises(HFAPIError) as raised:
        _transport().read(asks={"posts": {"pid": True}}, helper=helper)

    assert raised.value.error["code"] == "INVALID_ARGUMENT"
    assert requests == []


def test_helper_operation_prefix_message_is_the_authored_sentence() -> None:
    with pytest.raises(HFAPIError, match="operation prefix"):
        _transport().read(asks={"posts": {"pid": True}}, helper="write/posts")


class _BrokenTokenStore:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def require_bundle(self) -> TokenBundle:
        raise self._error


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize(
    "error",
    [
        RuntimeError(f"No token {SEED_TOKEN}"),
        PermissionError(f"/home/{SEED_TOKEN}/token.json too broad"),
        ValueError(SEED_TOKEN),
        json.JSONDecodeError(SEED_TOKEN, "doc", 0),
        OSError(SEED_TOKEN),
    ],
)
def test_missing_or_unusable_token_is_auth_unavailable_without_dispatch(
    monkeypatch: pytest.MonkeyPatch, method: str, error: Exception
) -> None:
    requests = _install_urlopen(monkeypatch, lambda: {"posts": []})
    transport = HFTransport(
        token_store=_BrokenTokenStore(error),
        base_url=f"https://{SEED_HOST}",  # type: ignore[arg-type]
    )

    with pytest.raises(HFAPIError) as raised:
        _call(transport, method)

    data = _assert_error_v1(raised.value)
    assert (data["code"], data["operation"], data["mutation_outcome"]) == (
        "AUTH_UNAVAILABLE",
        "local",
        "not_attempted",
    )
    assert requests == []
    _assert_no_seeds(str(raised.value), repr(raised.value), json.dumps(data))
    assert raised.value.__context__ is None


@pytest.mark.parametrize("token", ["", "has space", "line\nbreak", "tab\there"])
def test_unusable_token_value_is_auth_unavailable_without_dispatch(
    monkeypatch: pytest.MonkeyPatch, token: str
) -> None:
    class _Store:
        def require_bundle(self) -> TokenBundle:
            return TokenBundle(
                access_token=token, token_type="Bearer", scope=frozenset()
            )

    requests = _install_urlopen(monkeypatch, lambda: {"posts": []})
    transport = HFTransport(token_store=_Store(), base_url="https://example.test")  # type: ignore[arg-type]

    with pytest.raises(HFAPIError) as raised:
        transport.write(asks=ASKS)

    assert raised.value.error["code"] == "AUTH_UNAVAILABLE"
    assert requests == []


# ----------------------------------------------------------- A4 disclosure


@pytest.mark.parametrize("method", METHODS)
def test_seeded_markers_never_reach_text_stderr_or_debug_logs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    method: str,
) -> None:
    failures: list[Any] = [
        _http_error(500, headers={"Retry-After": SEED_HEADER, "X-Seed": SEED_HEADER}),
        urllib.error.URLError(f"https://{SEED_HOST}/{SEED_HELPER} {SEED_TOKEN}"),
        TimeoutError(SEED_BODY),
        f'{{"success": 0, "msg": "{SEED_BODY}"}}'.encode(),
        SEED_BODY.encode(),
    ]
    caplog.set_level(logging.DEBUG)
    for failure in failures:
        behavior = (
            _raising(failure)
            if isinstance(failure, BaseException)
            else (lambda f=failure: f)
        )
        _install_urlopen(monkeypatch, behavior)
        with pytest.raises(HFAPIError) as raised:
            _call(_transport(), method, helper=f"posts/{SEED_HELPER}")
        data = raised.value.error
        _assert_no_seeds(str(raised.value), repr(raised.value), json.dumps(data))
        assert raised.value.__cause__ is None
        assert raised.value.__context__ is None
        assert set(vars(raised.value)) == {"_error"}

    captured = capsys.readouterr()
    _assert_no_seeds(captured.out, captured.err, caplog.text)


def test_requests_are_dispatched_with_bearer_header_and_one_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = _install_urlopen(monkeypatch, lambda: {"posts": []})

    _transport().write(asks=ASKS, helper="posts")

    assert len(requests) == 1
    request = requests[0]
    assert request.get_method() == "POST"
    assert request.full_url == f"https://{SEED_HOST}/api/v2/write/posts"
    assert request.get_header("Authorization") == f"Bearer {SEED_TOKEN}"


# ------------------------------------------- moved: capture-seam transport


def test_transport_read_builds_helper_route_and_caps_perpage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def _fake_post_json(
        self: HFTransport, route: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
        captured["route"] = route
        captured["payload"] = payload
        captured["headers"] = headers
        return {"posts": {"pid": 42, "subject": "Hello"}}

    monkeypatch.setattr(HFTransport, "_post_json", _fake_post_json)

    transport = HFTransport(
        token_store=_StubTokenStore(), base_url="https://example.test"
    )
    result = transport.read(
        asks={"posts": {"_uid": [5], "_perpage": 99, "pid": True}},
        helper="posts",
    )

    assert captured["route"] == "/read/posts"
    assert captured["payload"]["asks"]["posts"]["_perpage"] == 30
    assert captured["headers"]["Authorization"] == f"Bearer {SEED_TOKEN}"
    assert captured["headers"]["User-Agent"] == (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    )
    assert result["posts"] == [{"pid": "42", "subject": "Hello"}]


def test_transport_write_builds_helper_route_and_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def _fake_post_json(
        self: HFTransport, route: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
        captured["route"] = route
        captured["payload"] = payload
        captured["headers"] = headers
        return {"posts": {"pid": 9001, "subject": "Created"}}

    monkeypatch.setattr(HFTransport, "_post_json", _fake_post_json)

    transport = HFTransport(
        token_store=_StubTokenStore(), base_url="https://example.test"
    )
    result = transport.write(
        asks={"posts": {"_tid": 123, "_message": "Hello"}},
        helper="posts/create",
    )

    assert captured["route"] == "/write/posts/create"
    assert captured["payload"] == {
        "asks": {"posts": {"_tid": 123, "_message": "Hello"}}
    }
    assert captured["headers"]["Authorization"] == f"Bearer {SEED_TOKEN}"
    assert result["posts"] == [{"pid": "9001", "subject": "Created"}]


# ------------------------------------------------------------ A6 normalizers


def test_normalize_response_handles_dict_list_and_absent_advanced_fields() -> None:
    payload = {
        "me": {"uid": 5, "username": "forge"},
        "posts": {"pid": 7, "subject": "Test"},
        "bytes": [{"id": 3, "amount": "430.43"}],
    }

    normalized = normalize_response(payload)

    assert normalized["me"] == [{"uid": "5", "username": "forge"}]
    assert "unreadpms" not in normalized["me"][0]
    assert normalized["posts"] == [{"pid": "7", "subject": "Test"}]
    assert normalized["bytes"] == [{"id": "3", "amount": "430.43"}]


UPSTREAM_ORDER_PAYLOAD: dict[str, Any] = {
    "bratings": [{"id": "3", "uid": "1"}, {"id": "12", "uid": "2"}, {"id": "7"}],
    "disputes": [{"did": "5"}, {"did": "50"}, {"did": "9"}],
    "contracts": [{"cid": "2"}, {"cid": "20"}, {"cid": "11"}],
    "sigmarket/market": [{"mid": "1"}, {"mid": "10"}, {"mid": "4"}],
    "sigmarket/order": [{"smid": "3"}, {"smid": "12"}, {"smid": "7"}],
}


@pytest.mark.parametrize("entrypoint", [normalize_response, normalize_extended_payload])
def test_upstream_row_order_is_preserved_for_every_formerly_sorted_endpoint(
    entrypoint: Callable[[dict[str, Any]], dict[str, Any]],
) -> None:
    result = entrypoint(copy.deepcopy(UPSTREAM_ORDER_PAYLOAD))

    for endpoint, rows in UPSTREAM_ORDER_PAYLOAD.items():
        assert result[endpoint] == [
            {key: str(value) for key, value in row.items()} for row in rows
        ]


@pytest.mark.parametrize("entrypoint", [normalize_response, normalize_extended_payload])
def test_amount_strings_and_big_integers_come_back_unchanged(
    entrypoint: Callable[[dict[str, Any]], dict[str, Any]],
) -> None:
    big = 1234567890123456789012345
    payload = {
        "bytes": [
            {"id": 1, "amount": "430.43"},
            {"id": 2, "amount": "001.2300"},
            {"id": 3, "amount": "1234567890123456789012345"},
            {"id": 4, "amount": big},
            {"id": 5, "amount": 430.43},
        ]
    }

    amounts = [row["amount"] for row in entrypoint(payload)["bytes"]]

    assert amounts == [
        "430.43",
        "001.2300",
        "1234567890123456789012345",
        "1234567890123456789012345",
        "430.43",
    ]


@pytest.mark.parametrize("entrypoint", [normalize_response, normalize_extended_payload])
def test_normalizers_are_idempotent_and_never_mutate_the_input(
    entrypoint: Callable[[dict[str, Any]], dict[str, Any]],
) -> None:
    payload = {
        **copy.deepcopy(UPSTREAM_ORDER_PAYLOAD),
        "me": {"uid": 5, "flag": True},
        "empty": {},
        "none": [],
        "bytes": [{"amount": 430.43}],
        "users": [
            {"avatar": "/uploads/a.png", "additionalgroups": "2, 4, ,6", "uid": 9}
        ],
    }
    original = copy.deepcopy(payload)

    once = entrypoint(payload)
    twice = entrypoint(copy.deepcopy(once))

    assert payload == original
    assert twice == once
    assert normalize_extended_payload(
        normalize_response(original)
    ) == normalize_extended_payload(original)
    assert once["empty"] == []


def test_extended_normalizer_adds_avatar_and_group_shaping_only() -> None:
    result = normalize_extended_payload(
        {"users": [{"avatar": "/u/a.png", "additionalgroups": "2, 4, ,6", "uid": 9}]}
    )

    assert result == {
        "users": [
            {
                "avatar": "https://hackforums.net/u/a.png",
                "additionalgroups": ["2", "4", "6"],
                "uid": "9",
            }
        ]
    }


def test_read_raw_returns_the_untouched_json(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"bytes": [{"amount": 430.43, "id": 3}], "posts": {"pid": 1}}
    _install_urlopen(monkeypatch, lambda: copy.deepcopy(body))

    assert _transport().read_raw(asks={"bytes": {"id": True}}, helper="bytes") == body


# ------------------------------------------------- redirects are never followed


class _RedirectingHTTPS(urllib.request.HTTPSHandler):
    def __init__(self, seen: list[tuple[str, str, str | None]]) -> None:
        super().__init__()
        self._seen = seen

    def https_open(self, req: Any) -> Any:
        self._seen.append(
            (req.get_method(), req.full_url, req.get_header("Authorization"))
        )
        headers = email.message.Message()
        headers["Location"] = "https://redirect-target.invalid/steal"
        response = urllib.response.addinfourl(
            io.BytesIO(b""), headers, req.full_url, 302
        )
        response.msg = "Found"
        return response


@pytest.mark.parametrize(
    ("method", "code", "outcome"),
    [
        ("read", "UPSTREAM_REJECTED", "not_attempted"),
        ("read_raw", "UPSTREAM_REJECTED", "not_attempted"),
        ("write", "WRITE_OUTCOME_UNKNOWN", "unknown"),
    ],
)
def test_redirects_are_not_followed_and_token_is_not_forwarded(
    monkeypatch: pytest.MonkeyPatch, method: str, code: str, outcome: str
) -> None:
    seen: list[tuple[str, str, str | None]] = []
    opener = urllib.request.build_opener(_NoRedirectHandler, _RedirectingHTTPS(seen))
    monkeypatch.setattr("hf_mcp.transport._OPENER", opener)

    with pytest.raises(HFAPIError) as raised:
        _call(_transport(), method)

    data = _assert_error_v1(raised.value)
    assert (data["code"], data["mutation_outcome"], data["http_status"]) == (
        code,
        outcome,
        302,
    )
    assert len(seen) == 1
    assert seen[0][1].startswith(f"https://{SEED_HOST}/")
    assert "redirect-target" not in json.dumps(data)


# ----------------------------------------- handler-wrapper exception mapping

FIXED_INVALID = "The request arguments are invalid."
FIXED_FORMAT = "The content is not ready to be written."
FIXED_INTERNAL = "An internal error occurred."
OS_PATH = f"/mnt/seeded/{SEED_TOKEN}/draft.json"


def _wrapped_result(error: Exception) -> dict[str, Any]:
    result = _error_call_tool_result("posts_reply", error)
    assert result.is_error is True
    assert [part.type for part in result.content] == ["text"]
    structured = result.structured_content
    assert structured is not None and set(structured) == {"error"}
    assert set(structured["error"]) == ERROR_V1_FIELDS
    assert structured["error"]["tool"] == "posts_reply"
    assert result.content[0].text == (
        f"{structured['error']['code']}: {structured['error']['message']}"
    )
    return dict(structured["error"])


@pytest.mark.parametrize(
    ("error", "code", "message"),
    [
        (
            ValueError("threads.read requires a selector."),
            "INVALID_ARGUMENT",
            "threads.read requires a selector.",
        ),
        (
            PermissionError("Tool requires confirm_live=True."),
            "INVALID_ARGUMENT",
            "Tool requires confirm_live=True.",
        ),
        (
            WritePreflightError("Write body contains nested code blocks."),
            "FORMAT_NOT_READY",
            "Write body contains nested code blocks.",
        ),
        (ValueError(f"cannot open {OS_PATH}"), "INVALID_ARGUMENT", FIXED_INVALID),
        (ValueError(SEED_TOKEN * 40), "INVALID_ARGUMENT", FIXED_INVALID),
        (
            PermissionError(13, "Permission denied", OS_PATH),
            "INVALID_ARGUMENT",
            FIXED_INVALID,
        ),
        (TypeError(f"unexpected {SEED_TOKEN}"), "INVALID_ARGUMENT", FIXED_INVALID),
        (
            UnicodeDecodeError("utf-8", b"\xff", 0, 1, SEED_TOKEN),
            "INVALID_ARGUMENT",
            FIXED_INVALID,
        ),
        (
            json.JSONDecodeError(SEED_TOKEN, "doc", 0),
            "INVALID_ARGUMENT",
            FIXED_INVALID,
        ),
        (
            WritePreflightError(f"bad {SEED_TOKEN} at {OS_PATH}"),
            "FORMAT_NOT_READY",
            FIXED_FORMAT,
        ),
        (RuntimeError(OS_PATH), "INTERNAL_ERROR", FIXED_INTERNAL),
        (KeyError(SEED_TOKEN), "INTERNAL_ERROR", FIXED_INTERNAL),
    ],
)
def test_wrapper_maps_exceptions_without_leaking_paths_or_stdlib_text(
    error: Exception, code: str, message: str
) -> None:
    data = _wrapped_result(error)

    assert data["code"] == code
    assert data["message"] == message
    assert data["operation"] == "local"
    assert data["mutation_outcome"] == "not_attempted"
    assert SEED_TOKEN not in json.dumps(data) or message == str(error)


def test_wrapper_passes_hf_api_errors_through_with_the_tool_name() -> None:
    original = HFAPIError(
        {
            "code": "RATE_LIMITED",
            "operation": "read",
            "tool": None,
            "message": "Hack Forums rate limit reached. Try again later.",
            "http_status": 429,
            "retry_after": 5,
            "retryable": True,
            "correlation_id": str(uuid.uuid4()),
            "mutation_outcome": "not_attempted",
        }
    )

    data = _wrapped_result(original)

    assert data == {**original.error, "tool": "posts_reply"}
