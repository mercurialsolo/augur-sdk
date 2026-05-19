"""Storage abstraction (issue #13).

Filesystem-first. `LocalFSStore` is the default and only complete implementation
in `0.1`. `S3Store` exists as a stub so callers depend on the abstraction from
day one; it raises `NotImplementedError` from every method.

Atomic-write contract: every write goes to `<path>.tmp` and is renamed into
place on close, so partial bundles never appear on disk.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Protocol


class Store(Protocol):
    """Minimal storage interface for the bundle writer.

    Paths are POSIX-style relative paths within the store's root.
    """

    @property
    def root_uri(self) -> str:
        """Root URI (`file://...`, `s3://...`). Always trailing slash-free."""
        ...

    def signed_url(self, relpath: str, *, ttl_seconds: int = 3600) -> str:
        """Return a URI a viewer can dereference. For local stores: `file://...`."""
        ...

    @contextmanager
    def open_write_binary(self, relpath: str) -> Iterator[IO[bytes]]:
        """Atomic binary write."""
        ...

    @contextmanager
    def open_write_text(self, relpath: str) -> Iterator[IO[str]]:
        """Atomic UTF-8 text write."""
        ...

    def exists(self, relpath: str) -> bool: ...

    def read_text(self, relpath: str) -> str: ...

    def read_bytes(self, relpath: str) -> bytes: ...


class LocalFSStore:
    """Filesystem-backed store."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    @property
    def root_uri(self) -> str:
        return self._root.as_uri()

    def _full(self, relpath: str) -> Path:
        if relpath.startswith("/") or ".." in Path(relpath).parts:
            raise ValueError(f"relpath must be a relative path inside the store: {relpath!r}")
        p = (self._root / relpath).resolve()
        # Guard: resolved path must stay under root (symlink/.. defence).
        if self._root not in p.parents and p != self._root:
            raise ValueError(f"relpath escapes store root: {relpath!r}")
        return p

    def signed_url(self, relpath: str, *, ttl_seconds: int = 3600) -> str:
        return self._full(relpath).as_uri()

    @contextmanager
    def open_write_binary(self, relpath: str) -> Iterator[IO[bytes]]:
        target = self._full(relpath)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        f = tmp.open("wb")
        try:
            yield f
            f.flush()
            os.fsync(f.fileno())
        finally:
            f.close()
        os.replace(tmp, target)

    @contextmanager
    def open_write_text(self, relpath: str) -> Iterator[IO[str]]:
        target = self._full(relpath)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        f = tmp.open("w", encoding="utf-8", newline="\n")
        try:
            yield f
            f.flush()
            os.fsync(f.fileno())
        finally:
            f.close()
        os.replace(tmp, target)

    def exists(self, relpath: str) -> bool:
        return self._full(relpath).exists()

    def read_text(self, relpath: str) -> str:
        return self._full(relpath).read_text(encoding="utf-8")

    def read_bytes(self, relpath: str) -> bytes:
        return self._full(relpath).read_bytes()

    def remove_tree(self) -> None:
        """Delete everything in the store. Use only in tests."""
        shutil.rmtree(self._root, ignore_errors=True)


class S3Store:
    """Stub. Wired so callers depend on the abstraction; filled in post-0.1."""

    def __init__(self, bucket: str, prefix: str = "") -> None:
        self.bucket = bucket
        self.prefix = prefix.rstrip("/")

    @property
    def root_uri(self) -> str:
        base = f"s3://{self.bucket}"
        return f"{base}/{self.prefix}" if self.prefix else base

    def signed_url(self, relpath: str, *, ttl_seconds: int = 3600) -> str:
        raise NotImplementedError("S3Store is a stub; use LocalFSStore for 0.1")

    @contextmanager
    def open_write_binary(self, relpath: str) -> Iterator[IO[bytes]]:
        raise NotImplementedError("S3Store is a stub; use LocalFSStore for 0.1")
        yield  # pragma: no cover

    @contextmanager
    def open_write_text(self, relpath: str) -> Iterator[IO[str]]:
        raise NotImplementedError("S3Store is a stub; use LocalFSStore for 0.1")
        yield  # pragma: no cover

    def exists(self, relpath: str) -> bool:
        raise NotImplementedError("S3Store is a stub; use LocalFSStore for 0.1")

    def read_text(self, relpath: str) -> str:
        raise NotImplementedError("S3Store is a stub; use LocalFSStore for 0.1")

    def read_bytes(self, relpath: str) -> bytes:
        raise NotImplementedError("S3Store is a stub; use LocalFSStore for 0.1")


__all__ = ["LocalFSStore", "S3Store", "Store"]
