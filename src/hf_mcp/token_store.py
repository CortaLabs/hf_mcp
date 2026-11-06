from __future__ import annotations

import contextlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .config import HFMCPSettings

_PRODUCT_ROOT = Path(__file__).resolve(strict=False).parents[2]


@dataclass(frozen=True)
class TokenBundle:
    access_token: str
    token_type: str
    scope: frozenset[str]

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> TokenBundle:
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token.strip():
            raise ValueError("Token payload is missing a valid `access_token`.")

        raw_token_type = payload.get("token_type")
        token_type = (
            raw_token_type
            if isinstance(raw_token_type, str) and raw_token_type
            else "Bearer"
        )

        raw_scope = payload.get("scope")
        if isinstance(raw_scope, str):
            scope = frozenset(part for part in raw_scope.split(" ") if part)
        elif isinstance(raw_scope, list):
            scope = frozenset(
                str(part).strip() for part in raw_scope if str(part).strip()
            )
        else:
            scope = frozenset()

        return cls(
            access_token=access_token.strip(), token_type=token_type, scope=scope
        )

    @classmethod
    def from_record(cls, record: Mapping[str, object]) -> TokenBundle:
        return cls.from_payload(record)

    def to_record(self) -> dict[str, object]:
        return {
            "access_token": self.access_token,
            "token_type": self.token_type,
            "scope": sorted(self.scope),
        }


_PRIVATE_FILE_MODE = 0o600
_MAX_TOKEN_FILE_BYTES = 1_048_576
_UNSAFE_FILE_MESSAGE = (
    "Token file is not a private regular file owned by the current user (mode 0600)."
)
_INVALID_CONTENT_MESSAGE = "Token file content is invalid."


class TokenStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def load_bundle(self) -> TokenBundle | None:
        try:
            descriptor = os.open(
                self._path,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            )
        except FileNotFoundError:
            return None
        except OSError:
            raise PermissionError(_UNSAFE_FILE_MESSAGE) from None

        try:
            status = os.fstat(descriptor)
            if (
                not stat.S_ISREG(status.st_mode)
                or status.st_uid != os.geteuid()
                or stat.S_IMODE(status.st_mode) != _PRIVATE_FILE_MODE
            ):
                raise PermissionError(_UNSAFE_FILE_MESSAGE)
            raw_bytes = _read_bounded(descriptor)
        finally:
            os.close(descriptor)

        return _bundle_from_bytes(raw_bytes)

    def require_bundle(self) -> TokenBundle:
        bundle = self.load_bundle()
        if bundle is None:
            from .transport import HFAPIError, build_error

            raise HFAPIError(build_error("AUTH_UNAVAILABLE", operation="local"))
        return bundle

    def save_bundle(self, bundle: TokenBundle) -> None:
        directory = self._path.parent
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)

        descriptor, temp_name = tempfile.mkstemp(
            dir=directory, prefix=".token-", suffix=".tmp"
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(bundle.to_record(), handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self._path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temp_name)
            raise
        _fsync_directory(directory)

    def clear(self) -> None:
        try:
            status = os.lstat(self._path)
        except FileNotFoundError:
            return
        if not stat.S_ISREG(status.st_mode):
            raise PermissionError(_UNSAFE_FILE_MESSAGE)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(self._path)


def _read_bounded(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(descriptor, 65536)
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > _MAX_TOKEN_FILE_BYTES:
            raise ValueError(_INVALID_CONTENT_MESSAGE)
        chunks.append(chunk)


def _bundle_from_bytes(raw_bytes: bytes) -> TokenBundle:
    try:
        raw = json.loads(raw_bytes.decode("utf-8"))
        if not isinstance(raw, dict):
            raise ValueError
        return TokenBundle.from_record(raw)
    except (ValueError, RecursionError):
        pass
    raise ValueError(_INVALID_CONTENT_MESSAGE)


def _fsync_directory(directory: Path) -> None:
    with contextlib.suppress(OSError):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def load_token_store(settings: HFMCPSettings) -> TokenStore:
    raw_override = settings.runtime_env.get("HF_MCP_TOKEN_PATH") or os.environ.get(
        "HF_MCP_TOKEN_PATH"
    )
    selected_path = (
        Path(raw_override).expanduser() if raw_override else settings.token_path
    )
    if not selected_path.is_absolute():
        raise ValueError("HF_MCP_TOKEN_PATH must be an absolute path.")

    # Resolve only the parent directory: a symlink at the final component must
    # reach the store so load_bundle can refuse it instead of following it.
    normalized = Path(os.path.normpath(selected_path))
    resolved_path = normalized.parent.resolve(strict=False) / normalized.name
    if _is_within_product_tree(resolved_path):
        raise ValueError("Token path may not point inside the tracked repository tree.")

    return TokenStore(path=resolved_path)


def _is_within_product_tree(path: Path) -> bool:
    return _PRODUCT_ROOT == path or _PRODUCT_ROOT in path.parents


__all__ = ["TokenBundle", "TokenStore", "load_token_store"]
