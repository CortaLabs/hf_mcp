from __future__ import annotations

import json
import os
import stat
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
        token_type = raw_token_type if isinstance(raw_token_type, str) and raw_token_type else "Bearer"

        raw_scope = payload.get("scope")
        if isinstance(raw_scope, str):
            scope = frozenset(part for part in raw_scope.split(" ") if part)
        elif isinstance(raw_scope, list):
            scope = frozenset(str(part).strip() for part in raw_scope if str(part).strip())
        else:
            scope = frozenset()

        return cls(access_token=access_token.strip(), token_type=token_type, scope=scope)

    @classmethod
    def from_record(cls, record: Mapping[str, object]) -> TokenBundle:
        return cls.from_payload(record)

    def to_record(self) -> dict[str, object]:
        return {
            "access_token": self.access_token,
            "token_type": self.token_type,
            "scope": sorted(self.scope),
        }


class TokenStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def load_bundle(self) -> TokenBundle | None:
        if not self._path.exists():
            return None

        mode = stat.S_IMODE(self._path.stat().st_mode)
        if mode & 0o077:
            raise PermissionError(
                "Token file permissions are too broad. Expected owner-only access (0600)."
            )

        raw = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Token store must contain a JSON object.")
        return TokenBundle.from_record(raw)

    def require_bundle(self) -> TokenBundle:
        bundle = self.load_bundle()
        if bundle is None:
            raise RuntimeError("No access token found. Run auth bootstrap first.")
        return bundle

    def save_bundle(self, bundle: TokenBundle) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temp_path = self._path.with_suffix(self._path.suffix + ".tmp")

        file_descriptor = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            json.dump(bundle.to_record(), handle, indent=2, sort_keys=True)
            handle.write("\n")

        os.replace(temp_path, self._path)
        os.chmod(self._path, 0o600)

    def clear(self) -> None:
        if self._path.exists():
            self._path.unlink()


def load_token_store(settings: HFMCPSettings) -> TokenStore:
    raw_override = settings.runtime_env.get("HF_MCP_TOKEN_PATH") or os.environ.get("HF_MCP_TOKEN_PATH")
    selected_path = Path(raw_override).expanduser() if raw_override else settings.token_path
    if not selected_path.is_absolute():
        raise ValueError("HF_MCP_TOKEN_PATH must be an absolute path.")

    resolved_path = selected_path.resolve(strict=False)
    if _is_within_product_tree(resolved_path):
        raise ValueError("Token path may not point inside the tracked repository tree.")

    return TokenStore(path=resolved_path)


def _is_within_product_tree(path: Path) -> bool:
    return _PRODUCT_ROOT == path or _PRODUCT_ROOT in path.parents


__all__ = ["TokenBundle", "TokenStore", "load_token_store"]
