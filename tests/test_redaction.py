from augur_sdk import DefaultRedactionPolicy


def test_drops_authorization_header() -> None:
    policy = DefaultRedactionPolicy()
    out = policy.apply({"Authorization": "Bearer abc.def.ghi", "name": "ok"})
    assert "Authorization" not in out
    assert out["name"] == "ok"


def test_masks_token_key() -> None:
    policy = DefaultRedactionPolicy()
    out = policy.apply({"token": "sk-abc"})
    assert out["token"] == "***REDACTED:mask***"


def test_scrubs_bearer_in_strings() -> None:
    policy = DefaultRedactionPolicy()
    out = policy.apply("log: bearer abc.def.ghi was rejected")
    assert "abc.def.ghi" not in out
    assert "REDACTED:bearer" in out


def test_recursive_walk_lists_and_dicts() -> None:
    policy = DefaultRedactionPolicy()
    data = {"users": [{"email": "a@b.com"}, {"password": "p"}]}
    out = policy.apply(data)
    assert "a@b.com" not in str(out)
    assert "password" not in out["users"][1]


def test_custom_dropper_runs() -> None:
    policy = DefaultRedactionPolicy()
    policy.add_dropper(lambda k, v: k == "drop_me")
    out = policy.apply({"drop_me": "x", "keep": 1})
    assert "drop_me" not in out
    assert out["keep"] == 1
