"""DebugSession.append_log streams to /api/v1/runs/<id>/logs (#17)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

from augur_sdk import CaptureMode, DebugSession


def test_append_log_noop_when_streaming_disabled(tmp_path) -> None:
    """No DSN configured => append_log is a no-op (doesn't raise)."""
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_test",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as session:
        # Must not raise even though there's no stream.
        session.append_log("hello", name="runner")
        session.append_log("step boundary", step_index=3)


def test_append_log_posts_json_with_routing(monkeypatch: Any, tmp_path) -> None:
    """With DSN configured, append_log POSTs JSON to /runs/<id>/logs."""
    # Synchronise the otherwise-async sink so the mock sees the call.
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

    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_test",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
        dsn="https://augur.example/api/v1?token=t0k&tenant=acme",
    ) as session:
        mock_http.request.reset_mock()  # forget the session_opened heartbeat
        session.append_log("starting work", name="runner")
        session.append_log("step boundary", step_index=3)

    calls = [c for c in mock_http.request.call_args_list if "/logs" in c.args[1]]
    assert len(calls) == 2

    # First — name-routed (no step_index in body)
    args, kwargs = calls[0]
    assert args[0] == "POST"
    assert args[1].endswith("/runs/run_test/logs")
    assert kwargs["headers"]["Content-Type"] == "application/json"
    assert kwargs["headers"]["Authorization"] == "Bearer t0k"
    body = json.loads(kwargs["body"])
    assert body == {"text": "starting work", "name": "runner"}

    # Second — step-routed
    body = json.loads(calls[1].kwargs["body"])
    assert body == {"text": "step boundary", "name": "run", "step_index": 3}
