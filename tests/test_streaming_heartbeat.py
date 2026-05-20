"""Heartbeat wire-format regression tests.

The server's `/heartbeat` endpoint reads `client_id` (and friends) from a
JSON body. A previous release accidentally posted them as multipart
form-data via urllib3's `fields=` kwarg, which the server happily
accepted as a POST but parsed as an empty JSON body — returning
HTTP 422 "client_id field required". These tests pin the wire format.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

from augur_sdk.streaming import DSN, StreamingSink


def _make_sink(monkeypatch: Any) -> tuple[StreamingSink, MagicMock]:
    """Build a StreamingSink whose HTTP layer is a MagicMock.

    StreamingSink's __init__ fires an immediate session_opened heartbeat
    on a background thread; we patch _spawn to run synchronously so the
    mock sees the call deterministically.
    """
    dsn = DSN(base_url="https://augur.example/api/v1", token="t0k", tenant="acme")
    monkeypatch.setattr(
        "augur_sdk.streaming.StreamingSink._spawn",
        lambda self, fn: fn(),
    )
    mock_http = MagicMock()
    mock_http.request.return_value = MagicMock(status=200, data=b"")
    monkeypatch.setattr(
        "augur_sdk.streaming.urllib3.PoolManager",
        lambda **_: mock_http,
    )
    sink = StreamingSink(dsn, client_name="testclient", client_version="0.0.0")
    return sink, mock_http


def test_initial_heartbeat_posts_json_with_client_id(monkeypatch: Any) -> None:
    sink, http = _make_sink(monkeypatch)

    # The constructor's session_opened heartbeat must have fired exactly once.
    assert http.request.call_count == 1
    args, kwargs = http.request.call_args
    assert args[0] == "POST"
    assert args[1].endswith("/heartbeat")

    # Body must be JSON, not multipart fields=.
    assert "fields" not in kwargs, "heartbeat must not use multipart form-data"
    assert kwargs["headers"]["Content-Type"] == "application/json"
    assert kwargs["headers"]["Authorization"] == "Bearer t0k"

    body = json.loads(kwargs["body"])
    assert body["client_id"] == sink.client_id
    assert body["client_name"] == "testclient"
    assert body["client_version"] == "0.0.0"
    assert body["last_event"] == "session_opened"
    # run_id is only present once begin() is called.
    assert "run_id" not in body


def test_post_begin_heartbeat_carries_run_id(monkeypatch: Any) -> None:
    sink, http = _make_sink(monkeypatch)
    http.request.reset_mock()

    # Begin would normally spawn a thread; we just want to drive _send_heartbeat
    # directly with the run_id set, so simulate the state begin() establishes.
    sink._run_id = "run_xyz"
    sink._capture_mode = "screenshots"
    sink._send_heartbeat()

    body = json.loads(http.request.call_args.kwargs["body"])
    assert body["run_id"] == "run_xyz"
    assert body["capture_mode"] == "screenshots"
    assert body["client_id"] == sink.client_id
    assert "last_event" not in body
