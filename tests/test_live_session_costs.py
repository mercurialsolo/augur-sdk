"""Live run-level cost streaming — augur-sdk#34.

`DebugSession.set_costs(...)` writes to in-memory `_session_costs` and
on `close()` serializes through trace.json. Before 0.3.1, that was the
only path — the viewer's Runs-list COST column had no live signal and
fell back to summing per-step `costs`, which 0.3.0's iteration PUTs
made non-monotonic.

This module pins:
- `set_costs` triggers `put_session_costs` on the stream with the
  cumulative dict each time a dimension is set.
- Multiple `set_costs` calls each fire one PUT carrying the latest
  cumulative (server is idempotent last-write-wins on `(run_id,)`).
- `put_session_costs` honours the shared 429/Retry-After retry path
  from #27 — no special-cased plumbing.
- `close()` still writes `session.costs` to trace.json (no regression).
- Empty `set_costs(**)` (no kwargs set) doesn't fire a PUT.
- When no DSN is configured, `set_costs` stays a pure in-memory update.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from augur_sdk import CaptureMode, DebugSession
from augur_sdk.streaming import DSN, StreamingSink


def _make_sink(monkeypatch: Any) -> tuple[StreamingSink, MagicMock]:
    dsn = DSN(base_url="https://augur.example/api/v1", token="t0k", tenant="acme")
    monkeypatch.setattr(
        "augur_sdk.streaming.StreamingSink._spawn",
        lambda self, fn: fn(),
    )
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


# ── StreamingSink.put_session_costs wire format ──────────────────────────


def test_put_session_costs_issues_put_to_run_costs(monkeypatch: Any) -> None:
    sink, http = _make_sink(monkeypatch)
    http.request.reset_mock()
    http.request.return_value = _resp(202)

    sink.put_session_costs({"total_usd": 1.23, "tokens_in": 4500})

    assert http.request.call_count == 1
    call = http.request.call_args
    assert call.args[0] == "PUT"
    assert call.args[1].endswith("/runs/run_xyz/costs")
    body = json.loads(call.kwargs["body"])
    assert body == {"total_usd": 1.23, "tokens_in": 4500}


def test_put_session_costs_empty_payload_is_noop(monkeypatch: Any) -> None:
    sink, http = _make_sink(monkeypatch)
    http.request.reset_mock()

    sink.put_session_costs({})

    assert http.request.call_count == 0


def test_put_session_costs_retries_on_429(
    monkeypatch: Any, caplog: pytest.LogCaptureFixture
) -> None:
    sink, http = _make_sink(monkeypatch)
    http.request.reset_mock()
    http.request.side_effect = [_resp(429, retry_after="1"), _resp(202)]

    with caplog.at_level(logging.WARNING, logger="augur_sdk.streaming"):
        sink.put_session_costs({"total_usd": 0.5})

    assert http.request.call_count == 2
    # Both attempts identical (idempotent retry).
    first, second = http.request.call_args_list
    assert first.args[0] == second.args[0] == "PUT"
    assert first.args[1] == second.args[1]
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_put_session_costs_drops_after_double_429(
    monkeypatch: Any, caplog: pytest.LogCaptureFixture
) -> None:
    sink, http = _make_sink(monkeypatch)
    http.request.reset_mock()
    http.request.side_effect = [
        _resp(429, retry_after="1"),
        _resp(429, retry_after="1"),
    ]

    with caplog.at_level(logging.WARNING, logger="augur_sdk.streaming"):
        sink.put_session_costs({"total_usd": 0.5})

    assert http.request.call_count == 2
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1
    assert "dropped after retry" in warnings[0].getMessage()


# ── DebugSession.set_costs wiring ────────────────────────────────────────


def test_set_costs_with_stream_fires_put_session_costs(monkeypatch: Any) -> None:
    """Every call to ``set_costs`` with at least one dimension MUST fire
    one ``put_session_costs`` carrying the CUMULATIVE dict — issue #34's
    happy path."""
    monkeypatch.setattr(
        "augur_sdk.session.StreamingSink._spawn",
        lambda self, fn: fn(),
    )
    monkeypatch.setattr("augur_sdk.streaming.time.sleep", lambda _s: None)
    mock_http = MagicMock()
    mock_http.request.return_value = MagicMock(status=202, data=b"", headers={})
    monkeypatch.setattr(
        "augur_sdk.streaming.urllib3.PoolManager",
        lambda **_: mock_http,
    )

    with DebugSession(
        run_id="run_live",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir="/tmp/augur-live-costs",
        dsn="https://augur.example/api/v1?token=t0k&tenant=acme",
    ) as s:
        s.set_costs(total_usd=0.10, tokens_in=100)
        s.set_costs(total_usd=0.25, tokens_out=400)
        s.set_costs(total_usd=0.42)

    cost_puts = [
        c for c in mock_http.request.call_args_list
        if c.args[0] == "PUT" and "/costs" in c.args[1] and "/steps/" not in c.args[1]
    ]
    assert len(cost_puts) == 3
    bodies = [json.loads(c.kwargs["body"]) for c in cost_puts]
    # Each PUT carries the cumulative dict at that moment (server is
    # last-write-wins; SDK MUST NOT send per-call deltas).
    assert bodies[0] == {"total_usd": 0.10, "tokens_in": 100}
    assert bodies[1] == {"total_usd": 0.25, "tokens_in": 100, "tokens_out": 400}
    assert bodies[2] == {"total_usd": 0.42, "tokens_in": 100, "tokens_out": 400}


def test_set_costs_without_stream_is_in_memory_only(tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_local",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.set_costs(total_usd=0.10, tokens_in=100)
        s.set_costs(total_usd=0.25)

    trace = json.loads((out / "trace.json").read_text())
    assert trace["session"]["costs"] == {"total_usd": 0.25, "tokens_in": 100}


def test_set_costs_no_kwargs_does_not_fire_put(monkeypatch: Any) -> None:
    """``set_costs()`` with no fields passed MUST NOT trigger a PUT —
    keeps producers that defensively call set_costs unconditionally
    from spamming the ingest queue."""
    monkeypatch.setattr(
        "augur_sdk.session.StreamingSink._spawn",
        lambda self, fn: fn(),
    )
    mock_http = MagicMock()
    mock_http.request.return_value = MagicMock(status=202, data=b"", headers={})
    monkeypatch.setattr(
        "augur_sdk.streaming.urllib3.PoolManager",
        lambda **_: mock_http,
    )

    with DebugSession(
        run_id="run_empty",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir="/tmp/augur-empty-costs",
        dsn="https://augur.example/api/v1?token=t0k&tenant=acme",
    ) as s:
        s.set_costs()

    cost_puts = [
        c for c in mock_http.request.call_args_list
        if c.args[0] == "PUT" and "/costs" in c.args[1] and "/steps/" not in c.args[1]
    ]
    assert cost_puts == []


def test_close_still_writes_session_costs_to_trace(tmp_path: Path) -> None:
    """Regression guard: streaming additions MUST NOT break the
    on-disk write of session.costs to trace.json (the bundle is the
    source of truth; the stream is an optimization)."""
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_reg",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.set_costs(total_usd=4.61, model_usd=3.10, tokens_in=12000)

    trace = json.loads((out / "trace.json").read_text())
    assert trace["session"]["costs"] == {
        "total_usd": 4.61,
        "model_usd": 3.10,
        "tokens_in": 12000,
    }
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["costs"] == trace["session"]["costs"]
