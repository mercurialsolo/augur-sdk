"""Streaming sink — 429 backpressure handling (issue #27).

The server's high-frequency ingest endpoints (augur#114) now return 429
with ``Retry-After: <seconds>`` when the ingest queue is saturated.
Previously the SDK silently dropped these — producer thought the write
landed but the server never got it. The sink must:

  * sleep for the ``Retry-After`` value and reissue exactly once;
  * if the second attempt also 429s, warn and return (no spam);
  * leave the 202 happy path completely undisturbed.

These tests pin that contract across every endpoint that goes through
the shared ``_request_with_retry`` helper: JSON, modelio, multipart,
heartbeat.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from augur_sdk.streaming import DSN, StreamingSink, _parse_retry_after


def _make_sink(monkeypatch: Any) -> tuple[StreamingSink, MagicMock]:
    dsn = DSN(base_url="https://augur.example/api/v1", token="t0k", tenant="acme")
    monkeypatch.setattr(
        "augur_sdk.streaming.StreamingSink._spawn",
        lambda self, fn: fn(),
    )
    # No real sleeps in the retry path.
    monkeypatch.setattr("augur_sdk.streaming.time.sleep", lambda _s: None)
    mock_http = MagicMock()
    mock_http.request.return_value = MagicMock(status=202, data=b"", headers={})
    monkeypatch.setattr(
        "augur_sdk.streaming.urllib3.PoolManager",
        lambda **_: mock_http,
    )
    sink = StreamingSink(dsn, client_name="testclient", client_version="0.0.0")
    sink._run_id = "run_xyz"
    return sink, mock_http


def _resp(status: int, *, retry_after: str | None = None) -> MagicMock:
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return MagicMock(status=status, data=b"", headers=headers)


# ── _parse_retry_after unit tests ────────────────────────────────────────


def test_parse_retry_after_integer() -> None:
    assert _parse_retry_after("3") == 3.0


def test_parse_retry_after_float() -> None:
    assert _parse_retry_after("0.5") == 0.5


def test_parse_retry_after_whitespace() -> None:
    assert _parse_retry_after("  2  ") == 2.0


def test_parse_retry_after_missing_defaults_to_one_second() -> None:
    assert _parse_retry_after(None) == 1.0


def test_parse_retry_after_garbage_defaults_to_one_second() -> None:
    # HTTP-date form (we don't support it) — falls back to default.
    assert _parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 1.0
    assert _parse_retry_after("nonsense") == 1.0


def test_parse_retry_after_negative_clamped_to_zero() -> None:
    assert _parse_retry_after("-5") == 0.0


def test_parse_retry_after_huge_value_clamped() -> None:
    # Don't let a malformed/hostile header park the worker thread.
    assert _parse_retry_after("999999") == 30.0


# ── _post_json retry contract ────────────────────────────────────────────


def test_post_json_passes_through_202(monkeypatch: Any) -> None:
    sink, http = _make_sink(monkeypatch)
    http.request.reset_mock()
    http.request.return_value = _resp(202)

    sink.put_step({"step_index": 0, "actions": []})  # type: ignore[typeddict-item]

    assert http.request.call_count == 1


def test_post_json_retries_once_on_429(
    monkeypatch: Any, caplog: pytest.LogCaptureFixture
) -> None:
    sink, http = _make_sink(monkeypatch)
    http.request.reset_mock()
    http.request.side_effect = [_resp(429, retry_after="1"), _resp(202)]

    with caplog.at_level(logging.WARNING, logger="augur_sdk.streaming"):
        sink.put_step({"step_index": 0, "actions": []})  # type: ignore[typeddict-item]

    assert http.request.call_count == 2
    # Both calls were the same PUT to the same URL (idempotent retry).
    first_call, second_call = http.request.call_args_list
    assert first_call.args[0] == second_call.args[0] == "PUT"
    assert first_call.args[1] == second_call.args[1]
    # Success path: no warning emitted.
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_post_json_drops_after_double_429(
    monkeypatch: Any, caplog: pytest.LogCaptureFixture
) -> None:
    sink, http = _make_sink(monkeypatch)
    http.request.reset_mock()
    http.request.side_effect = [
        _resp(429, retry_after="1"),
        _resp(429, retry_after="1"),
    ]

    with caplog.at_level(logging.WARNING, logger="augur_sdk.streaming"):
        sink.put_step({"step_index": 0, "actions": []})  # type: ignore[typeddict-item]

    assert http.request.call_count == 2
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1
    assert "dropped after retry" in warnings[0].getMessage()


def test_retry_sleeps_for_retry_after_value(monkeypatch: Any) -> None:
    sink, http = _make_sink(monkeypatch)
    http.request.reset_mock()
    http.request.side_effect = [_resp(429, retry_after="2"), _resp(202)]

    sleeps: list[float] = []
    monkeypatch.setattr(
        "augur_sdk.streaming.time.sleep", lambda s: sleeps.append(s)
    )

    sink.put_step({"step_index": 0, "actions": []})  # type: ignore[typeddict-item]

    assert sleeps == [2.0]


def test_retry_sleeps_default_when_header_missing(monkeypatch: Any) -> None:
    sink, http = _make_sink(monkeypatch)
    http.request.reset_mock()
    http.request.side_effect = [_resp(429), _resp(202)]

    sleeps: list[float] = []
    monkeypatch.setattr(
        "augur_sdk.streaming.time.sleep", lambda s: sleeps.append(s)
    )

    sink.put_step({"step_index": 0, "actions": []})  # type: ignore[typeddict-item]

    assert sleeps == [1.0]


# ── retry coverage across the other endpoints ────────────────────────────


def test_post_multipart_retries_once_on_429(monkeypatch: Any) -> None:
    sink, http = _make_sink(monkeypatch)
    http.request.reset_mock()
    http.request.side_effect = [_resp(429, retry_after="1"), _resp(202)]

    sink.post_screenshot(0, "pre", b"\x89PNG...")

    assert http.request.call_count == 2
    # Both attempts used the multipart fields= path (not body=).
    for call in http.request.call_args_list:
        assert "fields" in call.kwargs


def test_heartbeat_retries_once_on_429(monkeypatch: Any) -> None:
    sink, http = _make_sink(monkeypatch)
    http.request.reset_mock()
    http.request.side_effect = [_resp(429, retry_after="1"), _resp(202)]

    sink._send_heartbeat()

    assert http.request.call_count == 2
    for call in http.request.call_args_list:
        assert call.args[1].endswith("/heartbeat")


def test_modelio_retries_once_on_429_then_succeeds(monkeypatch: Any) -> None:
    sink, http = _make_sink(monkeypatch)
    http.request.reset_mock()
    http.request.side_effect = [_resp(429, retry_after="1"), _resp(202)]

    sink.post_modelio("modelio/0000-planner-0.json", {"layer": "planner"})

    assert http.request.call_count == 2
    # The 202 path does not latch the modelio kill-switch.
    assert sink._modelio_disabled is False


def test_modelio_retry_then_403_latches_disable(monkeypatch: Any) -> None:
    """If the retry returns 403, the existing modelio opt-in latch still wins."""
    sink, http = _make_sink(monkeypatch)
    http.request.reset_mock()
    http.request.side_effect = [
        _resp(429, retry_after="1"),
        _resp(403),
    ]

    sink.post_modelio("modelio/0000-planner-0.json", {"layer": "planner"})

    assert http.request.call_count == 2
    assert sink._modelio_disabled is True
