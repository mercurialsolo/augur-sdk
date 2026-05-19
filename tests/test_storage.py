import pytest

from augur_sdk import LocalFSStore, S3Store


def test_local_atomic_write(tmp_path) -> None:
    store = LocalFSStore(tmp_path)
    with store.open_write_text("a/b.json") as f:
        f.write("hello")
    assert store.read_text("a/b.json") == "hello"


def test_local_signed_url_is_file_uri(tmp_path) -> None:
    store = LocalFSStore(tmp_path)
    with store.open_write_text("manifest.json") as f:
        f.write("{}")
    uri = store.signed_url("manifest.json")
    assert uri.startswith("file://")
    assert uri.endswith("manifest.json")


def test_local_rejects_path_escape(tmp_path) -> None:
    store = LocalFSStore(tmp_path)
    with pytest.raises(ValueError), store.open_write_text("../escape.json"):
        pass


def test_s3_stub_raises(tmp_path) -> None:
    store = S3Store("bucket", "prefix")
    assert store.root_uri == "s3://bucket/prefix"
    with pytest.raises(NotImplementedError):
        store.exists("x")
