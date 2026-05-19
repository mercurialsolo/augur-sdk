from augur_sdk import CaptureMode, resolve_capture_mode


def test_resolve_explicit_wins() -> None:
    assert resolve_capture_mode(CaptureMode.SCREENSHOTS) is CaptureMode.SCREENSHOTS


def test_resolve_from_env() -> None:
    env = {"AUGUR_CAPTURE_MODE": "trace"}
    assert resolve_capture_mode(env=env) is CaptureMode.TRACE  # type: ignore[arg-type]


def test_resolve_default_is_off() -> None:
    assert resolve_capture_mode(env={}) is CaptureMode.OFF  # type: ignore[arg-type]


def test_ordering() -> None:
    assert CaptureMode.SCREENSHOTS > CaptureMode.TRACE
    assert CaptureMode.OFF < CaptureMode.METADATA
    assert CaptureMode.FULL >= CaptureMode.REPLAY
