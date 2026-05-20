"""Optional streaming sink — Sentry-style.

Activated by passing `dsn=` to `DebugSession(...)` or setting `AUGUR_DSN`.
When set, the SDK POSTs each new step + screenshot to the server in
addition to writing the bundle to disk locally. The local bundle is still
the source of truth; streaming is observe-only on top.

The DSN format is `<base>/api/v1?token=<api_key>&tenant=<tenant_slug>`.
Network failures are non-fatal and logged at DEBUG — the bundle on disk
is always complete even if the network is flapping.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.parse
import uuid
from dataclasses import dataclass
from typing import Any

import urllib3

from augur_sdk.models import DecisionEvent, StepTrace

logger = logging.getLogger(__name__)


@dataclass
class DSN:
    """Parsed augur DSN. The token is the secret api_key."""

    base_url: str  # e.g. http://127.0.0.1:8765/api/v1
    token: str
    tenant: str

    @classmethod
    def parse(cls, raw: str) -> DSN:
        parsed = urllib.parse.urlparse(raw)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"DSN must be an absolute URL, got: {raw!r}")
        qs = urllib.parse.parse_qs(parsed.query)
        token = (qs.get("token") or [""])[0]
        tenant = (qs.get("tenant") or [""])[0]
        if not token:
            raise ValueError(f"DSN missing token=… query param: {raw!r}")
        # Reconstruct the base without query/fragment.
        base = urllib.parse.urlunparse(
            (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", "")
        )
        return cls(base_url=base, token=token, tenant=tenant)

    @classmethod
    def from_env(cls, explicit: str | None = None) -> DSN | None:
        raw = explicit if explicit is not None else os.environ.get("AUGUR_DSN", "").strip()
        if not raw:
            return None
        try:
            return cls.parse(raw)
        except ValueError as exc:
            logger.warning("ignoring malformed AUGUR_DSN: %s", exc)
            return None


class StreamingSink:
    """Posts SDK events to an Augur server. Best-effort; never raises.

    Each network call goes on a background thread so the CUA runtime is not
    blocked on a slow server. A short queue per call site is plenty for the
    rate at which CUAs produce steps.
    """

    def __init__(self, dsn: DSN, *, client_name: str, client_version: str | None) -> None:
        self.dsn = dsn
        self.client_name = client_name
        self.client_version = client_version or ""
        self.client_id = f"sdk_{uuid.uuid4().hex[:12]}"
        self._http = urllib3.PoolManager(num_pools=4, maxsize=4, retries=False, timeout=urllib3.Timeout(connect=2.0, read=5.0))
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self._run_id: str | None = None
        self._capture_mode: str = "off"
        # Fire an immediate "session_opened" heartbeat so the server's
        # connection list shows this client the moment the SDK is wired
        # up — before any step/event has been recorded. Without this, a
        # user who configures AUGUR_DSN but hasn't started their agent
        # loop yet sees a stale "no clients connected" badge in the
        # viewer. The periodic loop still starts later in begin().
        self._spawn(lambda: self._send_heartbeat(last_event="session_opened"))

    # ── lifecycle ──────────────────────────────────────────────────────────

    def begin(self, *, run_id: str, capture_mode: str) -> None:
        self._run_id = run_id
        self._capture_mode = capture_mode
        # Heartbeat every 15s so the viewer's connection badge stays green
        # between events.
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True, name="augur-heartbeat"
        )
        self._heartbeat_thread.start()

    def end(self) -> None:
        self._heartbeat_stop.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=1.0)

    # ── posts ──────────────────────────────────────────────────────────────

    def post_manifest(self, manifest: dict[str, Any]) -> None:
        self._spawn(lambda: self._post_json("/runs", manifest, method="POST"))

    def put_trace(self, trace: dict[str, Any]) -> None:
        run_id = trace.get("session", {}).get("run_id") or self._run_id or "unknown"
        self._spawn(lambda: self._post_json(f"/runs/{run_id}/trace", trace, method="PUT"))

    def put_step(self, step: StepTrace) -> None:
        run_id = self._run_id or "unknown"
        idx = step.get("step_index")
        if idx is None:
            return
        self._spawn(lambda: self._post_json(f"/runs/{run_id}/steps/{idx}", dict(step), method="PUT"))

    def post_events(self, events: list[DecisionEvent], *, step_index: int | None) -> None:
        run_id = self._run_id or "unknown"
        body: dict[str, Any] = {"events": [dict(e) for e in events]}
        if step_index is not None:
            body["step_index"] = step_index
        self._spawn(lambda: self._post_json(f"/runs/{run_id}/events", body, method="POST"))

    def post_screenshot(self, step_index: int, kind: str, png_bytes: bytes) -> None:
        run_id = self._run_id or "unknown"
        self._spawn(
            lambda: self._post_multipart(
                f"/runs/{run_id}/screenshots/{step_index}/{kind}", png_bytes
            )
        )

    def post_logs(self, *, text: str, name: str = "run", step_index: int | None = None) -> None:
        """Append a text chunk to the server's logs/ directory (#17).

        POST /api/v1/runs/<run_id>/logs with a JSON body. Server
        appends to logs/<name>.log (or logs/step-<idx>.log when
        step_index is set), bounded at 1 MB per file. Like every
        other post on this sink, fire-and-forget on a background
        thread — the bundle on disk is the source of truth.
        """
        run_id = self._run_id or "unknown"
        body: dict[str, Any] = {"text": text, "name": name}
        if step_index is not None:
            body["step_index"] = step_index
        self._spawn(lambda: self._post_json(f"/runs/{run_id}/logs", body, method="POST"))

    # ── internals ──────────────────────────────────────────────────────────

    def _spawn(self, fn: Any) -> None:
        threading.Thread(target=lambda: self._safe_call(fn), daemon=True).start()

    def _safe_call(self, fn: Any) -> None:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            logger.debug("augur streaming sink error: %s", exc)

    def _post_json(self, path: str, payload: Any, *, method: str = "POST") -> None:
        url = self.dsn.base_url + path
        body = json.dumps(payload).encode("utf-8")
        resp = self._http.request(
            method,
            url,
            body=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.dsn.token}",
            },
        )
        if resp.status >= 400:
            logger.debug("augur stream %s %s -> %s %s", method, path, resp.status, resp.data[:200])

    def _post_multipart(self, path: str, payload: bytes) -> None:
        url = self.dsn.base_url + path
        # urllib3 multipart: pass (filename, bytes, content_type)
        resp = self._http.request(
            "POST",
            url,
            fields={"image": ("shot.png", payload, "image/png")},
            headers={"Authorization": f"Bearer {self.dsn.token}"},
        )
        if resp.status >= 400:
            logger.debug("augur stream upload %s -> %s %s", path, resp.status, resp.data[:200])

    def _heartbeat_loop(self) -> None:
        while not self._heartbeat_stop.is_set():
            self._safe_call(self._send_heartbeat)
            # 15s window; the server's default heartbeat horizon is 60s.
            if self._heartbeat_stop.wait(timeout=15.0):
                return

    def _send_heartbeat(self, *, last_event: str | None = None) -> None:
        url = self.dsn.base_url + "/heartbeat"
        payload: dict[str, Any] = {
            "client_id": self.client_id,
            "client_name": self.client_name,
            "client_version": self.client_version,
            "capture_mode": self._capture_mode,
        }
        if self._run_id:
            payload["run_id"] = self._run_id
        if last_event:
            payload["last_event"] = last_event
        body = json.dumps(payload).encode("utf-8")
        resp = self._http.request(
            "POST",
            url,
            body=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.dsn.token}",
            },
        )
        if resp.status >= 400:
            logger.debug("augur heartbeat -> %s %s", resp.status, resp.data[:200])


__all__ = ["DSN", "StreamingSink"]
