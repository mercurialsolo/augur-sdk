"""Intervention channel (#12) — server→SDK control plane.

The DSN is normally one-way (SDK → server) for steps, events, and
screenshots. The intervention channel reverses the direction: the
server can pause, resume, kill, hint, or override coordinates while
the run is live.

v1 transport is **long-poll** on ``GET /runs/{run_id}/commands``:

- the SDK opens a request with ``?cursor=<last_command_id>``;
- the server holds it open until either a command is available or
  the configured timeout elapses;
- the SDK dispatches each returned command to the adapter, then
  reopens the poll with the new cursor.

Latency on the happy path is bounded by the server's hold-time
(typically a few seconds), well within the 2s target the issue calls
for. WebSocket is a future-proof option; the channel class is shaped
so that swap is a transport-only change.

Delivery is at-least-once with idempotency keys on ``command_id`` so
a reconnect after a dropped poll never loses a command. Adapters that
don't implement a particular hook see the SDK degrade to a no-op for
that command type rather than raising.

Operator-supplied coordinates are stamped with ``provenance =
"human_override"`` so the trajectory preserves the SPEC §4 invariant
that runtime action selection is screenshot-grounded — never silently
mixed with grounder output.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

import urllib3

logger = logging.getLogger(__name__)


COMMAND_TYPES = frozenset(
    {"pause", "resume", "kill", "inject_hint", "override_action"}
)


@dataclass
class InterventionCommand:
    command_id: str
    type: str
    issued_at: str
    operator_id: str | None = None
    payload: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> InterventionCommand:
        return cls(
            command_id=str(raw.get("command_id") or raw.get("id") or ""),
            type=str(raw.get("type", "")),
            issued_at=str(raw.get("issued_at", "")),
            operator_id=(
                str(raw["operator_id"]) if raw.get("operator_id") else None
            ),
            payload=raw.get("payload") or None,
        )


class _AdapterFacade(Protocol):
    """Subset of the Adapter contract the channel touches.

    Spelled out as a Protocol so the channel doesn't import from
    ``augur_sdk.adapter`` (avoids a circular reference) and so tests
    can supply a fake without subclassing the full Adapter.
    """

    def on_pause(self) -> None: ...
    def on_resume(self) -> None: ...
    def on_kill(self) -> None: ...
    def on_inject_hint(self, hint_text: str) -> None: ...
    def on_action_override(
        self, coordinates: dict[str, float], *, provenance: str
    ) -> None: ...


class _SessionFacade(Protocol):
    """Subset of the DebugSession the channel touches."""

    run_id: str

    def abort_pending_side_effects(self, reason: str) -> list[str]: ...
    def record_event(self, event: dict[str, Any]) -> None: ...


class InterventionChannel:
    """Long-poll intervention channel.

    Wired up by ``DebugSession.bind_adapter()``; producers don't
    normally instantiate this directly. The channel runs on its own
    background thread; ``poll_once()`` is exposed for tests that want
    to drive a synchronous tick without spinning up the thread.
    """

    def __init__(
        self,
        *,
        session: _SessionFacade,
        adapter: _AdapterFacade,
        base_url: str,
        token: str,
        http: urllib3.PoolManager | None = None,
        poll_timeout: float = 25.0,
    ) -> None:
        self._session = session
        self._adapter = adapter
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._http = http or urllib3.PoolManager(
            num_pools=1,
            maxsize=1,
            retries=False,
            timeout=urllib3.Timeout(connect=2.0, read=poll_timeout + 5.0),
        )
        self._poll_timeout = poll_timeout
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._cursor: str | None = None
        self._seen_commands: set[str] = set()
        # Paused flag is owned by the adapter, but the channel keeps a
        # lightweight mirror so a kill-after-pause still aborts every
        # pending side-effect.
        self.paused = False

    # ── lifecycle ──────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="augur-intervention", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    # ── poll loop ──────────────────────────────────────────────────────

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception as exc:  # noqa: BLE001
                logger.debug("intervention poll error: %s", exc)
                # Wait briefly so a flapping server doesn't burn CPU.
                if self._stop.wait(timeout=1.0):
                    return

    def poll_once(self) -> int:
        """Open one long-poll, dispatch any returned commands, return
        the number dispatched. Public for tests."""
        url = f"{self._base_url}/runs/{self._session.run_id}/commands"
        if self._cursor:
            url = f"{url}?cursor={self._cursor}"
        resp = self._http.request(
            "GET",
            url,
            headers={"Authorization": f"Bearer {self._token}"},
        )
        if resp.status >= 400:
            logger.debug(
                "intervention poll %s -> %s %s",
                url,
                resp.status,
                resp.data[:200],
            )
            return 0
        if not resp.data:
            return 0
        try:
            body = json.loads(resp.data)
        except json.JSONDecodeError:
            logger.debug("intervention poll non-JSON body: %r", resp.data[:200])
            return 0
        commands = body.get("commands") or []
        dispatched = self.dispatch(commands)
        # Cursor is the highest command_id we've seen, so the server
        # knows what we've already processed and dedupes on reconnect.
        next_cursor = body.get("cursor")
        if next_cursor:
            self._cursor = str(next_cursor)
        return dispatched

    def dispatch(self, commands: Iterable[dict[str, Any]]) -> int:
        """Run each command against the adapter.

        Unknown command types are logged and skipped. Adapter hooks
        that raise are logged and treated as no-ops — a buggy hook
        must not kill the channel. Returns the number dispatched."""
        dispatched = 0
        for raw in commands:
            cmd = InterventionCommand.from_dict(raw)
            if not cmd.command_id:
                logger.debug("intervention command missing command_id: %r", raw)
                continue
            if cmd.command_id in self._seen_commands:
                # At-least-once delivery; SDK dedupes locally.
                continue
            if cmd.type not in COMMAND_TYPES:
                logger.debug("intervention unknown command type: %r", cmd.type)
                self._seen_commands.add(cmd.command_id)
                continue
            try:
                self._handle(cmd)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "intervention adapter hook raised on %s: %s",
                    cmd.type,
                    exc,
                )
            self._seen_commands.add(cmd.command_id)
            self._audit(cmd)
            dispatched += 1
        return dispatched

    # ── handlers ───────────────────────────────────────────────────────

    def _handle(self, cmd: InterventionCommand) -> None:
        payload = cmd.payload or {}
        if cmd.type == "pause":
            self.paused = True
            self._call(self._adapter.on_pause)
        elif cmd.type == "resume":
            self.paused = False
            self._call(self._adapter.on_resume)
        elif cmd.type == "kill":
            # Couples to #11: abort every declared-but-not-committed
            # side-effect first so the ledger doesn't show dangling
            # intent_only declarations.
            try:
                self._session.abort_pending_side_effects(
                    reason=f"intervention.kill by {cmd.operator_id or 'operator'}"
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("abort_pending_side_effects failed: %s", exc)
            self._call(self._adapter.on_kill)
        elif cmd.type == "inject_hint":
            text = payload.get("text", "")
            self._call(self._adapter.on_inject_hint, str(text))
        elif cmd.type == "override_action":
            coords = payload.get("coordinates")
            if not isinstance(coords, dict):
                logger.debug(
                    "override_action missing coordinates: %r", payload
                )
                return
            # SDK guarantees provenance="human_override" so the
            # trajectory preserves the SPEC §4 invariant.
            self._call(
                self._adapter.on_action_override,
                {"x": float(coords.get("x", 0.0)), "y": float(coords.get("y", 0.0))},
                provenance="human_override",
            )

    def _call(self, fn: Any, *args: Any, **kwargs: Any) -> None:
        """Tolerant call — adapters that don't implement a hook see a
        no-op rather than a TypeError."""
        if fn is None:
            return
        try:
            fn(*args, **kwargs)
        except NotImplementedError:
            logger.debug(
                "adapter does not implement %s; treating as no-op",
                getattr(fn, "__name__", "<hook>"),
            )

    def _audit(self, cmd: InterventionCommand) -> None:
        """Log the received command to the session's decision-event
        trail so the audit log shows who did what and when."""
        try:
            self._session.record_event(
                {
                    "ts": cmd.issued_at,
                    "layer": "runner",
                    "kind": "info",
                    "summary": f"intervention.{cmd.type}",
                    "detail": {
                        "command_id": cmd.command_id,
                        "operator_id": cmd.operator_id or "",
                        "payload": cmd.payload or {},
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("intervention audit log failed: %s", exc)


__all__ = ["COMMAND_TYPES", "InterventionChannel", "InterventionCommand"]
