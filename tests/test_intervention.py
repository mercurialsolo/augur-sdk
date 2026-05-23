"""Intervention channel — server→SDK control plane (#12)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from augur_sdk import CaptureMode, DebugSession
from augur_sdk.intervention import InterventionChannel


class FakeAdapter:
    """Records hook invocations for assertion."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Any:
        if not name.startswith("on_"):
            raise AttributeError(name)

        def _record(*args: Any, **kwargs: Any) -> None:
            self.calls.append((name, args, kwargs))

        return _record


class FakeResponse:
    """urllib3-shaped response."""

    def __init__(self, status: int, data: bytes) -> None:
        self.status = status
        self.data = data


class FakeHttp:
    """Hands back queued responses in order; records GETs."""

    def __init__(self) -> None:
        self.queue: list[FakeResponse] = []
        self.requests: list[tuple[str, str]] = []

    def queue_commands(
        self, commands: list[dict[str, Any]], cursor: str | None = None
    ) -> None:
        body: dict[str, Any] = {"commands": commands}
        if cursor is not None:
            body["cursor"] = cursor
        self.queue.append(FakeResponse(200, json.dumps(body).encode("utf-8")))

    def queue_empty(self) -> None:
        self.queue.append(FakeResponse(200, b""))

    def queue_error(self, status: int = 500) -> None:
        self.queue.append(FakeResponse(status, b"err"))

    def request(self, method: str, url: str, **_: Any) -> FakeResponse:
        self.requests.append((method, url))
        if self.queue:
            return self.queue.pop(0)
        return FakeResponse(200, b"")


@pytest.fixture
def session(tmp_path: Any) -> Any:
    with DebugSession(
        run_id="run_iv",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=tmp_path / "b",
    ) as s:
        yield s


def _channel(session: Any, adapter: Any, http: FakeHttp) -> InterventionChannel:
    return InterventionChannel(
        session=session,
        adapter=adapter,
        base_url="http://srv/api/v1",
        token="tok",
        http=http,  # type: ignore[arg-type]
    )


def test_pause_command_calls_on_pause(session: Any) -> None:
    adapter = FakeAdapter()
    http = FakeHttp()
    http.queue_commands(
        [
            {
                "command_id": "c1",
                "type": "pause",
                "issued_at": "2026-05-23T00:00:00Z",
                "operator_id": "op",
            }
        ],
        cursor="c1",
    )
    ch = _channel(session, adapter, http)
    n = ch.poll_once()
    assert n == 1
    assert ch.paused is True
    assert any(c[0] == "on_pause" for c in adapter.calls)


def test_resume_clears_paused(session: Any) -> None:
    adapter = FakeAdapter()
    http = FakeHttp()
    http.queue_commands(
        [
            {"command_id": "c1", "type": "pause", "issued_at": "t"},
            {"command_id": "c2", "type": "resume", "issued_at": "t"},
        ],
        cursor="c2",
    )
    ch = _channel(session, adapter, http)
    ch.poll_once()
    assert ch.paused is False
    names = [c[0] for c in adapter.calls]
    assert names == ["on_pause", "on_resume"]


def test_kill_aborts_pending_side_effects(session: Any) -> None:
    adapter = FakeAdapter()
    sid = session.declare_side_effect(0, resource="x", action="y")

    http = FakeHttp()
    http.queue_commands(
        [{"command_id": "c1", "type": "kill", "issued_at": "t", "operator_id": "op"}],
        cursor="c1",
    )
    ch = _channel(session, adapter, http)
    ch.poll_once()

    record = session._recorder.get_side_effect(sid)
    assert record["status"] == "aborted"
    assert "intervention.kill" in record["abort_reason"]
    assert any(c[0] == "on_kill" for c in adapter.calls)


def test_inject_hint_passes_text(session: Any) -> None:
    adapter = FakeAdapter()
    http = FakeHttp()
    http.queue_commands(
        [
            {
                "command_id": "c1",
                "type": "inject_hint",
                "issued_at": "t",
                "payload": {"text": "click the green button"},
            }
        ],
        cursor="c1",
    )
    ch = _channel(session, adapter, http)
    ch.poll_once()
    calls = [c for c in adapter.calls if c[0] == "on_inject_hint"]
    assert len(calls) == 1
    assert calls[0][1] == ("click the green button",)


def test_override_action_provenance_is_human_override(session: Any) -> None:
    adapter = FakeAdapter()
    http = FakeHttp()
    http.queue_commands(
        [
            {
                "command_id": "c1",
                "type": "override_action",
                "issued_at": "t",
                "operator_id": "op",
                "payload": {"coordinates": {"x": 100, "y": 200}},
            }
        ],
        cursor="c1",
    )
    ch = _channel(session, adapter, http)
    ch.poll_once()
    calls = [c for c in adapter.calls if c[0] == "on_action_override"]
    assert len(calls) == 1
    _, args, kwargs = calls[0]
    assert args[0] == {"x": 100.0, "y": 200.0}
    assert kwargs == {"provenance": "human_override"}


def test_unknown_command_type_is_skipped(session: Any) -> None:
    adapter = FakeAdapter()
    http = FakeHttp()
    http.queue_commands(
        [{"command_id": "c1", "type": "nuke_from_orbit", "issued_at": "t"}],
        cursor="c1",
    )
    ch = _channel(session, adapter, http)
    n = ch.poll_once()
    # Unknown types are not dispatched.
    assert n == 0
    assert adapter.calls == []


def test_idempotent_on_command_id(session: Any) -> None:
    """At-least-once delivery; SDK dedupes on command_id."""
    adapter = FakeAdapter()
    http = FakeHttp()
    cmd = {"command_id": "c1", "type": "pause", "issued_at": "t"}
    http.queue_commands([cmd], cursor="c1")
    http.queue_commands([cmd], cursor="c1")

    ch = _channel(session, adapter, http)
    ch.poll_once()
    ch.poll_once()
    assert [c[0] for c in adapter.calls] == ["on_pause"]


def test_audit_event_logged_per_command(session: Any) -> None:
    adapter = FakeAdapter()
    http = FakeHttp()
    http.queue_commands(
        [
            {
                "command_id": "c1",
                "type": "pause",
                "issued_at": "2026-05-23T00:00:00Z",
                "operator_id": "op",
            }
        ],
        cursor="c1",
    )
    ch = _channel(session, adapter, http)
    ch.poll_once()
    events = session._recorder.events_for_step(None)
    summaries = [e.get("summary") for e in events]
    assert "intervention.pause" in summaries


def test_minimal_adapter_does_not_raise(session: Any) -> None:
    """Adapter missing intervention hooks degrades to no-op."""

    class BareAdapter:
        pass

    adapter = BareAdapter()
    http = FakeHttp()
    http.queue_commands(
        [{"command_id": "c1", "type": "pause", "issued_at": "t"}], cursor="c1"
    )
    ch = _channel(session, adapter, http)
    # Should not raise; the hook simply isn't called.
    n = ch.poll_once()
    assert n == 1


def test_server_error_logged_not_raised(session: Any) -> None:
    adapter = FakeAdapter()
    http = FakeHttp()
    http.queue_error(503)
    ch = _channel(session, adapter, http)
    n = ch.poll_once()
    assert n == 0


def test_bind_intervention_returns_none_without_dsn(session: Any) -> None:
    assert session.bind_intervention(FakeAdapter()) is None


def test_cursor_propagates_through_polls(session: Any) -> None:
    adapter = FakeAdapter()
    http = FakeHttp()
    http.queue_commands(
        [{"command_id": "c1", "type": "pause", "issued_at": "t"}], cursor="c1"
    )
    http.queue_commands(
        [{"command_id": "c2", "type": "resume", "issued_at": "t"}], cursor="c2"
    )
    ch = _channel(session, adapter, http)
    ch.poll_once()
    ch.poll_once()
    # Second request includes the cursor from the first.
    assert "?cursor=c1" in http.requests[1][1]
