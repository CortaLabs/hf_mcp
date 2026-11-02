from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pytest

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PRODUCT_ROOT / "src"
_CORE_SOURCE_TEST_MODULES = {
    "test_chatgpt_read_surface.py",
    "test_entrypoints.py",
    "test_onboarding_cli.py",
}
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark known offline source-test modules as core without filtering tests."""
    for item in items:
        if Path(str(item.path)).name in _CORE_SOURCE_TEST_MODULES:
            item.add_marker(pytest.mark.core)


@pytest.fixture(autouse=True)
def isolate_hf_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep each test's HF config and credentials under its disposable temp root."""
    for name in tuple(os.environ):
        if name.startswith("HF_MCP_"):
            monkeypatch.delenv(name, raising=False)

    home = tmp_path / "hf-test-state" / "home"
    config_dir = home / ".config" / "hf_mcp"
    draft_dir = config_dir / "drafts"
    draft_dir.mkdir(parents=True)

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    from hf_mcp import config as hf_config

    monkeypatch.setattr(hf_config, "DEFAULT_CONFIG_PATH", config_dir / "config.yaml")
    monkeypatch.setenv("HF_MCP_TOKEN_PATH", str(config_dir / "token.json"))
    monkeypatch.setenv("HF_MCP_DRAFT_DIR", str(draft_dir))


@dataclass(frozen=True)
class SyntheticHFState:
    home: Path
    config_path: Path
    token_path: Path
    draft_dir: Path


@dataclass(frozen=True)
class IsolatedChildContext:
    state: SyntheticHFState
    source_path: Path
    guard_path: Path

    def environment(self) -> dict[str, str]:
        """Return only the child's executable, source, and synthetic HF state."""
        return {
            "PATH": os.defpath,
            "HOME": str(self.state.home),
            "XDG_CONFIG_HOME": str(self.state.home / ".config"),
            "HF_MCP_CONFIG": str(self.state.config_path),
            "HF_MCP_TOKEN_PATH": str(self.state.token_path),
            "HF_MCP_DRAFT_DIR": str(self.state.draft_dir),
            "HF_BUILD_SRC": str(self.source_path),
            "PYTHONPATH": os.pathsep.join(
                (str(self.guard_path), str(self.source_path))
            ),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
        }


@pytest.fixture
def isolated_child_context(tmp_path: Path) -> Iterator[IsolatedChildContext]:
    """Prepare disposable state and a startup-loaded child network guard."""
    child_root = tmp_path / "child"
    home = child_root / "home"
    config_dir = home / ".config" / "hf_mcp"
    draft_dir = config_dir / "drafts"
    guard_path = child_root / "network_guard"
    config_dir.mkdir(parents=True)
    draft_dir.mkdir()
    guard_path.mkdir(parents=True)

    config_path = config_dir / "config.yaml"
    token_path = config_dir / "token.json"
    config_path.write_text("profile: reader\n", encoding="utf-8")
    (guard_path / "sitecustomize.py").write_text(
        "import pytest_socket\npytest_socket.disable_socket()\n",
        encoding="utf-8",
    )

    state = SyntheticHFState(
        home=home,
        config_path=config_path,
        token_path=token_path,
        draft_dir=draft_dir,
    )
    yield IsolatedChildContext(state=state, source_path=SRC_PATH, guard_path=guard_path)
