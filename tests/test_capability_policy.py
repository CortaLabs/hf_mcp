from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest
import yaml

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PRODUCT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from hf_mcp.capabilities import CapabilityPolicy
from hf_mcp.config import (
    ALL_CAPABILITIES,
    ALL_PARAMETER_FAMILIES,
    DEFAULT_PROFILE,
    HFMCPSettings,
    PRESET_CAPABILITIES,
    PRESET_PARAMETER_FAMILIES,
    load_settings,
)


def _write_config(tmp_path: Path, content: str) -> Path:
    config_path = tmp_path / "hf_mcp.yaml"
    config_path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")
    return config_path


def _extract_commented_csv_rows(example_text: str, heading: str) -> set[str]:
    lines = example_text.splitlines()
    start_index: int | None = None
    for index, line in enumerate(lines):
        if line.strip() == f"# {heading}":
            start_index = index + 1
            break

    if start_index is None:
        raise AssertionError(f"Missing heading: {heading}")

    values: set[str] = set()
    for line in lines[start_index:]:
        stripped = line.strip()
        if not stripped:
            break
        if not stripped.startswith("#"):
            break
        payload = stripped.removeprefix("#").strip()
        if not payload:
            break
        for token in payload.split(","):
            value = token.strip()
            if value:
                values.add(value)
    return values


def test_default_profile_is_reader_when_profile_omitted(tmp_path: Path) -> None:
    settings = load_settings(config_path=tmp_path / "missing.yaml", env={})

    assert DEFAULT_PROFILE == "reader"
    assert settings.profile == DEFAULT_PROFILE
    assert settings.enabled_capabilities == PRESET_CAPABILITIES["reader"]
    assert settings.enabled_parameter_families == PRESET_PARAMETER_FAMILIES["reader"]


def test_full_api_profile_is_explicit_opt_in(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        """
        profile: full_api
        """,
    )
    settings = load_settings(config_path=config_path, env={})

    assert settings.profile == "full_api"
    assert settings.enabled_capabilities == PRESET_CAPABILITIES["full_api"]
    assert settings.enabled_parameter_families == PRESET_PARAMETER_FAMILIES["full_api"]
    assert settings.enabled_parameter_families == ALL_PARAMETER_FAMILIES


def test_full_api_profile_exposes_verified_concrete_surface_only() -> None:
    settings = HFMCPSettings(
        profile="full_api",
        enabled_capabilities=PRESET_CAPABILITIES["full_api"],
        enabled_parameter_families=PRESET_PARAMETER_FAMILIES["full_api"],
    )
    policy = CapabilityPolicy(settings)

    retained_rows = {
        "admin.high_risk.read",
        "threads.create",
        "posts.reply",
        "bytes.transfer",
        "bytes.deposit",
        "bytes.withdraw",
        "bytes.bump",
    }
    removed_rows = {
        "contracts.write",
        "sigmarket.write",
        "admin.high_risk.write",
    }
    for name in retained_rows:
        assert name in settings.enabled_capabilities
        assert policy.can_register(name) is True
    for name in removed_rows:
        assert name not in settings.enabled_capabilities
        assert policy.can_register(name) is False


def test_reader_preset_disables_registration_for_write_capabilities(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        """
        profile: reader
        """,
    )
    settings = load_settings(config_path=config_path, env={})
    policy = CapabilityPolicy(settings)

    assert policy.can_register("posts.read") is True
    assert policy.can_register("posts.reply") is False
    assert "writes.content" not in policy.allowed_parameter_families("posts.read")


def test_forum_operator_can_disable_parameter_family_explicitly(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        """
        profile: forum_operator
        disabled_parameter_families:
          - confirm.live
        """,
    )
    settings = load_settings(config_path=config_path, env={})
    policy = CapabilityPolicy(settings)

    assert policy.can_register("posts.reply") is True
    assert "writes.content" in policy.allowed_parameter_families("posts.reply")
    assert "confirm.live" not in policy.allowed_parameter_families("posts.reply")


@pytest.mark.parametrize(
    ("disabled_family", "tool", "expected_register"),
    [
        ("selectors.user", "users.read", True),
        ("selectors.contract", "contracts.read", True),
        ("selectors.sigmarket", "sigmarket.market.read", True),
        ("formatting.content", "formatting.preflight", False),
        ("writes.content", "posts.reply", True),
        ("writes.bytes", "bytes.transfer", True),
        ("confirm.live", "threads.create", True),
    ],
)
def test_full_api_family_disables_support_required_permission_groups(
    tmp_path: Path,
    disabled_family: str,
    tool: str,
    expected_register: bool,
) -> None:
    config_path = _write_config(
        tmp_path,
        f"""
        profile: full_api
        disabled_parameter_families:
          - {disabled_family}
        """,
    )
    settings = load_settings(config_path=config_path, env={})
    policy = CapabilityPolicy(settings)

    assert policy.can_register(tool) is expected_register
    assert disabled_family not in policy.allowed_parameter_families(tool)


@pytest.mark.parametrize(
    ("disabled_family", "tool", "schema", "removed_property"),
    [
        (
            "selectors.user",
            "users.read",
            {
                "type": "object",
                "properties": {
                    "_uid": {"type": "integer", "x-hf-parameter-family": "selectors.user"},
                    "_page": {"type": "integer", "x-hf-parameter-family": "filters.pagination"},
                },
            },
            "_uid",
        ),
        (
            "selectors.contract",
            "contracts.read",
            {
                "type": "object",
                "properties": {
                    "_cid": {"type": "integer", "x-hf-parameter-family": "selectors.contract"},
                    "_page": {"type": "integer", "x-hf-parameter-family": "filters.pagination"},
                },
            },
            "_cid",
        ),
        (
            "selectors.sigmarket",
            "sigmarket.market.read",
            {
                "type": "object",
                "properties": {
                    "_smid": {"type": "integer", "x-hf-parameter-family": "selectors.sigmarket"},
                    "_page": {"type": "integer", "x-hf-parameter-family": "filters.pagination"},
                },
            },
            "_smid",
        ),
        (
            "fields.me.advanced",
            "me.read",
            {
                "type": "object",
                "properties": {
                    "_uid": {"type": "integer", "x-hf-parameter-family": "selectors.user"},
                    "_stats": {"type": "boolean", "x-hf-parameter-family": "fields.me.advanced"},
                },
            },
            "_stats",
        ),
        (
            "fields.posts.body",
            "posts.read",
            {
                "type": "object",
                "properties": {
                    "_tid": {"type": "integer", "x-hf-parameter-family": "selectors.thread"},
                    "_body": {"type": "boolean", "x-hf-parameter-family": "fields.posts.body"},
                },
            },
            "_body",
        ),
        (
            "fields.bytes.amount",
            "bytes.read",
            {
                "type": "object",
                "properties": {
                    "_uid": {"type": "integer", "x-hf-parameter-family": "selectors.bytes"},
                    "_amount": {"type": "boolean", "x-hf-parameter-family": "fields.bytes.amount"},
                },
            },
            "_amount",
        ),
    ],
)
def test_full_api_family_disables_prune_advanced_users_posts_and_bytes_fields(
    tmp_path: Path,
    disabled_family: str,
    tool: str,
    schema: dict[str, object],
    removed_property: str,
) -> None:
    config_path = _write_config(
        tmp_path,
        f"""
        profile: full_api
        disabled_parameter_families:
          - {disabled_family}
        """,
    )
    settings = load_settings(config_path=config_path, env={})
    policy = CapabilityPolicy(settings)

    pruned = policy.prune_schema(tool, schema)

    assert removed_property not in pruned.get("properties", {})


def test_full_api_can_disable_capability_explicitly(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        """
        profile: full_api
        disabled_capabilities:
          - posts.reply
        """,
    )
    settings = load_settings(config_path=config_path, env={})
    policy = CapabilityPolicy(settings)

    assert "posts.reply" not in settings.enabled_capabilities
    assert "threads.create" in settings.enabled_capabilities
    assert policy.can_register("posts.reply") is False
    assert policy.can_register("threads.create") is True


def test_custom_profile_accepts_explicit_capability_and_parameter_family(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        """
        profile: custom
        enabled_capabilities:
          - posts.read
        enabled_parameter_families:
          - selectors.thread
          - fields.posts.body
        """,
    )
    settings = load_settings(config_path=config_path, env={})
    policy = CapabilityPolicy(settings)

    assert settings.profile == "custom"
    assert settings.enabled_capabilities == frozenset({"posts.read"})
    assert settings.enabled_parameter_families == frozenset(
        {"selectors.thread", "fields.posts.body"}
    )
    assert policy.can_register("posts.read") is True
    assert policy.can_register("posts.reply") is False


def test_family_without_parent_capability_fails_closed(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        """
        profile: custom
        enabled_parameter_families:
          - writes.content
        """,
    )

    with pytest.raises(ValueError, match="requires at least one enabled capability"):
        load_settings(config_path=config_path, env={})


def test_prune_schema_removes_disabled_parameter_families() -> None:
    settings = HFMCPSettings(
        profile="custom",
        enabled_capabilities=frozenset({"posts.read"}),
        enabled_parameter_families=frozenset({"selectors.thread", "fields.posts.body"}),
    )
    policy = CapabilityPolicy(settings)

    schema = {
        "type": "object",
        "properties": {
            "_tid": {"type": "integer", "x-hf-parameter-family": "selectors.thread"},
            "_body": {"type": "boolean", "x-hf-parameter-family": "fields.posts.body"},
            "_message": {"type": "string", "x-hf-parameter-family": "writes.content"},
        },
        "required": ["_tid", "_body", "_message"],
    }

    pruned = policy.prune_schema("posts.read", schema)

    assert set(pruned["properties"]) == {"_tid", "_body"}
    assert pruned["required"] == ["_tid", "_body"]


def test_prune_schema_returns_closed_schema_for_disabled_tool() -> None:
    settings = HFMCPSettings(
        profile="reader",
        enabled_capabilities=frozenset({"posts.read"}),
        enabled_parameter_families=frozenset({"selectors.thread"}),
    )
    policy = CapabilityPolicy(settings)

    pruned = policy.prune_schema("posts.reply", {"type": "object", "properties": {"_tid": {}}})

    assert pruned == {"type": "object", "properties": {}, "additionalProperties": False}


def test_example_config_defaults_to_reader_profile() -> None:
    data = yaml.safe_load((PRODUCT_ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    assert data["profile"] == "reader"


def test_example_config_full_api_commentary_matches_runtime_presets() -> None:
    example_text = (PRODUCT_ROOT / "config.example.yaml").read_text(encoding="utf-8")

    capability_rows = _extract_commented_csv_rows(
        example_text,
        'Capabilities currently exposed by profile = "full_api":',
    )
    parameter_rows = _extract_commented_csv_rows(
        example_text,
        'Parameter families currently exposed by profile = "full_api":',
    )

    assert capability_rows == set(PRESET_CAPABILITIES["full_api"])
    assert parameter_rows == set(PRESET_PARAMETER_FAMILIES["full_api"])


def test_full_api_profile_is_strict_subset_of_all_capabilities() -> None:
    assert PRESET_CAPABILITIES["full_api"].issubset(ALL_CAPABILITIES)
    assert PRESET_CAPABILITIES["full_api"] != ALL_CAPABILITIES
