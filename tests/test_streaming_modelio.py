"""Streaming modelio ingest — 403 disables further POSTs (issue #5).

The server's modelio ingest is per-tenant opt-in. When the tenant
hasn't enabled it, the route returns 403. The SDK must latch on the
first 403 and stop firing further POSTs for the session so we don't
spam the server (or our own logs) for every staged record.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

from augur_sdk.streaming import DSN, StreamingSink


def _make_sink(monkeypatch: Any) -> tuple[StreamingSink, MagicMock]:
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
    sink._run_id = "run_xyz"
    return sink, mock_http


def _modelio_paths(http: MagicMock) -> list[str]:
    """Return the URL paths of every POST that targeted the modelio route."""
    paths: list[str] = []
    for call in http.request.call_args_list:
        args, kwargs = call
        if not args or args[0] != "POST":
            continue
        url = args[1] if len(args) > 1 else kwargs.get("url", "")
        if "/modelio/" in url:
            paths.append(url)
    return paths


def test_post_modelio_posts_json_to_run_route(monkeypatch: Any) -> None:
    sink, http = _make_sink(monkeypatch)
    http.request.reset_mock()

    record = {"schema_version": "0.1", "layer": "planner"}
    sink.post_modelio("modelio/0003-planner-0.json", record)

    assert http.request.call_count == 1
    args, kwargs = http.request.call_args
    assert args[0] == "POST"
    assert args[1] == (
        "https://augur.example/api/v1/runs/run_xyz/modelio/0003-planner-0.json"
    )
    assert kwargs["headers"]["Content-Type"] == "application/json"
    assert kwargs["headers"]["Authorization"] == "Bearer t0k"
    assert "fields" not in kwargs
    assert json.loads(kwargs["body"]) == record


def test_403_response_latches_disable(monkeypatch: Any) -> None:
    sink, http = _make_sink(monkeypatch)
    http.request.reset_mock()
    http.request.return_value = MagicMock(status=403, data=b"tenant opt-in required")

    # First call hits the server and gets 403 → latch.
    sink.post_modelio("modelio/0000-planner-0.json", {"layer": "planner"})
    assert sink._modelio_disabled is True
    assert len(_modelio_paths(http)) == 1

    # Subsequent calls are no-ops: no further requests.
    http.request.reset_mock()
    sink.post_modelio("modelio/0000-grounding-0.json", {"layer": "grounding"})
    sink.post_modelio("modelio/0001-planner-0.json", {"layer": "planner"})
    assert http.request.call_count == 0


def test_non_403_errors_do_not_disable(monkeypatch: Any) -> None:
    sink, http = _make_sink(monkeypatch)
    http.request.reset_mock()
    http.request.return_value = MagicMock(status=500, data=b"oops")

    sink.post_modelio("modelio/0000-planner-0.json", {"layer": "planner"})
    sink.post_modelio("modelio/0001-planner-0.json", {"layer": "planner"})

    assert sink._modelio_disabled is False
    assert len(_modelio_paths(http)) == 2
