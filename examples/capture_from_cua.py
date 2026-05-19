"""Capture from a CUA into an Augur bundle.

This is the canonical integration example for **any** screenshot-grounded CUA.
The runtime here is a 3-step stub — replace `pretend_cua_step()` with calls
into your own framework. Everything else is the actual public API a host CUA
uses.

Run:

    uv run python examples/capture_from_cua.py --out /tmp/my-run
    uv run augur summarize /tmp/my-run
    uv run augur diagnose /tmp/my-run

The bundle is path-stable and schema-validated — drop it into the viewer
(`pnpm -F @augur/viewer dev`) once the bundle loader lands, or hand it to a
coding agent via `augur diagnose --json`.
"""

from __future__ import annotations

import argparse
import struct
import sys
import time
import zlib
from datetime import UTC, datetime
from pathlib import Path

from augur_sdk import CaptureMode, DebugSession
from augur_sdk.models import StepTrace

# --- 1x1 PNG bytes; stand-ins for real screenshots. -----------------------------

def _png(color: tuple[int, int, int]) -> bytes:
    r, g, b = color
    raw = b"\x00" + bytes([r, g, b])
    deflated = zlib.compress(raw)

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", deflated) + chunk(b"IEND", b"")


# --- A pretend CUA runtime. Your real CUA would emit these from its loop. ------

def pretend_cua_step(
    *,
    index: int,
    intent: str,
    backend: str = "playwright.click",
) -> dict:
    """Imagine: this is your CUA's per-step record after running one action."""
    time.sleep(0.02)  # pretend latency
    succeeded = index != 2  # step 2 fails to demonstrate the failure path
    return {
        "intent": intent,
        "started_at": _now(),
        "duration_ms": 540 + index * 80,
        "succeeded": succeeded,
        "pre_png": _png((220 + index * 5, 230, 250)),
        "post_png": _png((220, 230, 200 if succeeded else 220) ),
        "action": {
            "type": "click",
            "x": 100 + 50 * index,
            "y": 200,
            "executor_backend": backend,
        },
        "grounding": {
            "provider": "myagent.grounder",
            "x": 100 + 50 * index,
            "y": 200,
            "confidence": 0.92 if succeeded else 0.61,
            "evidence": "label_match",
        },
        "verdict": {
            "status": "passed" if succeeded else "recoverable",
            "reason": "ok" if succeeded else "no visible state change",
        },
        "failure_class": None if succeeded else "no_state_change",
    }


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


# --- Integration: hand each step to Augur. -------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="/tmp/augur-cua-run", help="Output bundle dir")
    parser.add_argument(
        "--capture-mode",
        default="screenshots",
        choices=["off", "metadata", "trace", "screenshots", "model_io", "dispatch", "replay", "full"],
        help="Augur capture mode (see SPEC §7)",
    )
    args = parser.parse_args(argv)

    out = Path(args.out)
    if out.exists():
        import shutil

        shutil.rmtree(out)

    run_id = f"run_demo_{int(time.time())}"

    # The whole integration is this `with` block.
    with DebugSession(
        run_id=run_id,
        client_name="myagent",
        client_version="0.1.0",
        client_git_sha="abc1234",
        capture_mode=CaptureMode(args.capture_mode),
        out_dir=out,
        tags={"tenant": "demo", "env": "local"},
    ) as session:
        # Run the CUA. For each step, hand the raw record to Augur.
        for i, intent in enumerate(
            [
                "Navigate to the login page",
                "Type the username",
                "Click the submit button",  # this one fails
            ]
        ):
            raw = pretend_cua_step(index=i, intent=intent)

            # Stage screenshots (no-op when capture_mode < screenshots).
            pre = session.attach_observation(step_index=i, kind="pre", png_bytes=raw["pre_png"])
            post = session.attach_observation(step_index=i, kind="post", png_bytes=raw["post_png"])

            # Translate the framework-native step to an Augur StepTrace.
            step: StepTrace = {
                "step_id": f"{run_id}/step/{i:04d}",
                "step_index": i,
                "step_type": raw["action"]["type"],
                "intent": raw["intent"],
                "required": True,
                "status": "succeeded" if raw["succeeded"] else "failed",
                "started_at": raw["started_at"],
                "ended_at": _now(),
                "duration_ms": raw["duration_ms"],
                "observation_pre": pre,
                "observation_post": post,
                "action": {
                    "type": raw["action"]["type"],
                    "params": {"x": raw["action"]["x"], "y": raw["action"]["y"]},
                    "coordinate_space": "viewport_css_px",
                    "dispatch_backend": raw["action"]["executor_backend"],
                },
                "grounding": {
                    "provider": raw["grounding"]["provider"],
                    "coordinates": {"x": raw["grounding"]["x"], "y": raw["grounding"]["y"]},
                    "confidence": raw["grounding"]["confidence"],
                    "evidence": raw["grounding"]["evidence"],
                    "provenance": "screenshot",
                },
                "verdict": raw["verdict"],
            }
            if raw["failure_class"]:
                step["failure_class"] = raw["failure_class"]
            session.record_step(step)

            # Optional: emit decision events from the framework's internals.
            session.record_event(
                {
                    "ts": _now(),
                    "step_index": i,
                    "layer": "model",
                    "kind": "decision",
                    "summary": f"chose {raw['action']['type']} target",
                }
            )

        # Override the run's terminal status if the CUA halted.
        session.set_status("halted")

    # The bundle is on disk and schema-validated.
    print(f"wrote bundle: {out}")
    print(f"run_id:       {run_id}")
    print()
    print("Next steps:")
    print(f"  uv run augur summarize  {out}")
    print(f"  uv run augur validate   {out}")
    print(f"  uv run augur diagnose   {out} --rules cua")
    return 0


if __name__ == "__main__":
    sys.exit(main())
