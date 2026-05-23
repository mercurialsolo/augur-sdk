# Playwright

Drop-in patterns for a Python CUA that uses
[Playwright](https://playwright.dev/python/) for the dispatch layer.

## Minimal capture wrapper

```python
import asyncio
from datetime import datetime, UTC
from augur_sdk import CaptureMode, DebugSession
from playwright.async_api import Page, async_playwright


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class AugurCapturingPage:
    """A thin wrapper that records every dispatch into a DebugSession."""

    def __init__(self, page: Page, session: DebugSession, step_index: int = 0):
        self.page = page
        self.session = session
        self.step_index = step_index

    async def click(self, *, x: int, y: int, intent: str, grounding_provider: str):
        pre = await self.page.screenshot()
        started = _now_iso()
        await self.page.mouse.click(x, y)
        post = await self.page.screenshot()

        pre_path  = self.session.attach_observation(step_index=self.step_index, kind="pre",  png_bytes=pre)
        post_path = self.session.attach_observation(step_index=self.step_index, kind="post", png_bytes=post)

        self.session.record_step({
            "step_id":          f"{self.session.run_id}/step/{self.step_index:04d}",
            "step_index":       self.step_index,
            "step_type":        "click",
            "intent":           intent,
            "status":           "succeeded",
            "started_at":       started,
            "ended_at":         _now_iso(),
            "observation_pre":  pre_path,
            "observation_post": post_path,
            "action": {
                "type":             "click",
                "params":           {"x": x, "y": y},
                "coordinate_space": "viewport_css_px",
                "dispatch_backend": "playwright",
            },
            "grounding": {"provider": grounding_provider, "provenance": "screenshot"},
            "verdict":   {"status": "passed"},
        })
        self.step_index += 1


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        await page.goto("https://example.com")

        with DebugSession(
            run_id="run_demo",
            client_name="my-playwright-cua",
            capture_mode=CaptureMode.SCREENSHOTS,
            out_dir="/var/log/augur/run_demo",
        ) as session:
            cap = AugurCapturingPage(page, session)
            await cap.click(x=100, y=200, intent="Click Login", grounding_provider="manual")
            await cap.click(x=200, y=300, intent="Click Submit", grounding_provider="manual")


asyncio.run(main())
```

## Coordinate space

Playwright dispatches in **viewport CSS pixels** by default. Always tag
the action with:

```python
"coordinate_space": "viewport_css_px"
```

If you use device-pixel coordinates (rare; only when feeding device-pixel
grounding directly), use `device_px`. The viewer will refuse to overlay
across mismatched spaces.

## Device scale factor

If your viewport's DSF ≠ 1, attach it to the observation when you build
your own observation record (not via `attach_observation` which only
takes the PNG). Easier path: keep the runner at DSF=1 and resize the
viewport instead.

## Page navigation events

Playwright fires page-load events that are useful as `DecisionEvent`s:

```python
page.on("framenavigated", lambda frame: session.record_event({
    "ts":      _now_iso(),
    "layer":   "dispatch",
    "kind":    "observation",
    "summary": f"navigated to {frame.url}",
}))
```

## Sensitivity

For steps that touch payment pages or PII:

```python
self.session.record_step({
    ...,
    "sensitive": True,   # screenshots are dropped from the bundle
})
```

See [redaction.md](../concepts/redaction.md) for the full policy.

## Playwright trace + Augur

If you already use Playwright's built-in tracing (`page.tracing.start()`),
keep doing so — Augur and Playwright traces are complementary. Augur
captures the *CUA loop* (grounding + verifier + recovery decisions);
Playwright traces capture the *browser plumbing*. Both can coexist.
