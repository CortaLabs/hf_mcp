from __future__ import annotations

import copy
import textwrap
from pathlib import Path

import pytest
import yaml


from hf_mcp.capabilities import CapabilityPolicy
from hf_mcp.registry import FAMILY_KEY, TOOLS, WIRE_KEY, get_tool_spec
from hf_mcp.config import (
    ALL_CAPABILITIES,
    ALL_PARAMETER_FAMILIES,
    DEFAULT_PROFILE,
    HFMCPSettings,
    PRESET_CAPABILITIES,
    PRESET_PARAMETER_FAMILIES,
    load_settings,
)

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PRODUCT_ROOT / "src"


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


def _policy(capabilities: set[str], families: set[str]) -> CapabilityPolicy:
    return CapabilityPolicy(
        HFMCPSettings(
            profile="custom",
            enabled_capabilities=frozenset(capabilities),
            enabled_parameter_families=frozenset(families),
        )
    )


def _preset_policy(profile: str) -> CapabilityPolicy:
    return CapabilityPolicy(
        HFMCPSettings(
            profile=profile,
            enabled_capabilities=PRESET_CAPABILITIES[profile],
            enabled_parameter_families=PRESET_PARAMETER_FAMILIES[profile],
        )
    )


def _any_of_families(spec) -> set[str]:
    properties = spec.input_schema["properties"]
    return {
        properties[name][FAMILY_KEY]
        for branch in spec.input_schema.get("anyOf", ())
        for name in branch["required"]
    }


def _walk_keys(node: object):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _walk_keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_keys(item)


def test_default_profile_is_reader_when_profile_omitted(tmp_path: Path) -> None:
    settings = load_settings(config_path=tmp_path / "missing.yaml", env={})

    assert DEFAULT_PROFILE == "reader"
    assert settings.profile == DEFAULT_PROFILE
    assert settings.enabled_capabilities == PRESET_CAPABILITIES["reader"]
    assert settings.enabled_parameter_families == PRESET_PARAMETER_FAMILIES["reader"]


def test_full_api_profile_is_explicit_opt_in_and_registers_every_tool(
    tmp_path: Path,
) -> None:
    config_path = _write_config(tmp_path, "profile: full_api")
    settings = load_settings(config_path=config_path, env={})
    policy = CapabilityPolicy(settings)

    assert settings.enabled_capabilities == ALL_CAPABILITIES
    assert settings.enabled_parameter_families == ALL_PARAMETER_FAMILIES
    assert len(TOOLS) == 27
    assert all(policy.can_register(spec.name) for spec in TOOLS)


def test_unknown_names_fail_with_config_errors(tmp_path: Path) -> None:
    for phantom in ("contracts.write", "sigmarket.write", "admin.high_risk.write"):
        config_path = _write_config(
            tmp_path, f"profile: custom\nenabled_capabilities: [{phantom}]"
        )
        with pytest.raises(ValueError, match="Unknown capability"):
            load_settings(config_path=config_path, env={})
    config_path = _write_config(
        tmp_path, "profile: reader\nenabled_parameter_families: [nope.family]"
    )
    with pytest.raises(ValueError, match="Unknown parameter family"):
        load_settings(config_path=config_path, env={})
    assert not _policy({"posts.read"}, set()).can_register("hf.doctor")


def test_every_tool_requires_all_of_its_required_families() -> None:
    for spec in TOOLS:
        enabled = set(spec.required_families) | _any_of_families(spec)
        assert _policy({spec.capability}, enabled).can_register(spec.name), spec.name
        for family in spec.required_families:
            policy = _policy({spec.capability}, enabled - {family})
            assert not policy.can_register(spec.name), (spec.name, family)
        assert not _policy(set(), set(ALL_PARAMETER_FAMILIES)).can_register(spec.name)


def test_optional_only_read_tools_register_with_no_filters_enabled() -> None:
    optional_only = [
        spec
        for spec in TOOLS
        if not spec.required_families and "anyOf" not in spec.input_schema
    ]
    assert {spec.name for spec in optional_only} >= {
        "me.read",
        "bytes.read",
        "contracts.read",
        "admin.high_risk.read",
        "forums.index",
        "drafts.list",
    }
    for spec in optional_only:
        assert _policy({spec.capability}, set()).can_register(spec.name), spec.name


def test_bytes_bump_requires_thread_selector_and_live_confirmation() -> None:
    spec = get_tool_spec("bytes.bump")
    assert spec.required_families == {"selectors.thread", "confirm.live"}
    assert _policy({"bytes.bump"}, {"selectors.thread", "confirm.live"}).can_register(
        "bytes.bump"
    )
    assert not _policy({"bytes.bump"}, {"selectors.thread"}).can_register("bytes.bump")
    assert not _policy({"bytes.bump"}, {"confirm.live"}).can_register("bytes.bump")


def test_any_of_tool_is_not_registrable_when_every_branch_is_pruned() -> None:
    capabilities = {"threads.read"}
    assert not _policy(capabilities, {"filters.pagination"}).can_register(
        "threads.read"
    )
    policy = _policy(capabilities, {"selectors.forum"})
    assert policy.can_register("threads.read")
    schema = policy.input_schema(get_tool_spec("threads.read"))
    assert schema["anyOf"] == [{"required": ["fid"]}]
    assert "tid" not in schema["properties"]


def test_reader_preset_has_positive_and_negative_controls() -> None:
    policy = _preset_policy("reader")

    for name in (
        "threads.read",
        "bytes.read",
        "forums.index",
        "drafts.list",
        "drafts.read",
    ):
        assert policy.can_register(name), name
    for name in (
        "formatting.preflight",
        "drafts.update",
        "drafts.delete",
        "threads.create",
        "posts.reply",
        "bytes.transfer",
    ):
        assert not policy.can_register(name), name
    assert "writes.content" not in policy.allowed_parameter_families("posts.read")


def test_forum_operator_preset_has_positive_and_negative_controls() -> None:
    policy = _preset_policy("forum_operator")

    for name in (
        "threads.read",
        "drafts.read",
        "formatting.preflight",
        "drafts.update",
        "drafts.delete",
        "threads.create",
        "posts.reply",
    ):
        assert policy.can_register(name), name
    for name in ("bytes.transfer", "bytes.deposit", "bytes.withdraw", "bytes.bump"):
        assert not policy.can_register(name), name


def test_custom_preset_is_empty_and_full_api_is_everything() -> None:
    assert PRESET_CAPABILITIES["custom"] == frozenset()
    assert PRESET_PARAMETER_FAMILIES["custom"] == frozenset()
    custom = _preset_policy("custom")
    assert not any(custom.can_register(spec.name) for spec in TOOLS)
    assert PRESET_CAPABILITIES["full_api"] == ALL_CAPABILITIES


def test_draft_grants_split_read_and_write() -> None:
    families = {
        "drafts.selector",
        "drafts.filters",
        "drafts.metadata",
        "drafts.confirm_delete",
    }
    read_only = _policy({"drafts.read"}, families)
    assert read_only.can_register("drafts.list")
    assert read_only.can_register("drafts.read")
    assert not read_only.can_register("drafts.update")
    assert not read_only.can_register("drafts.delete")
    write_only = _policy({"drafts.write"}, families)
    assert write_only.can_register("drafts.update")
    assert write_only.can_register("drafts.delete")
    assert not write_only.can_register("drafts.list")
    assert not _policy({"formatting.preflight"}, families).can_register("drafts.read")


def test_forum_operator_can_disable_parameter_family_explicitly(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        """
        profile: forum_operator
        disabled_parameter_families:
          - confirm.live
        """,
    )
    policy = CapabilityPolicy(load_settings(config_path=config_path, env={}))

    assert policy.can_register("posts.reply") is False
    assert policy.allowed_parameter_families("posts.reply") == frozenset()
    assert policy.can_register("posts.read") is True


@pytest.mark.parametrize(
    ("disabled_family", "tool", "expected_register"),
    [
        ("selectors.user", "users.read", False),
        ("selectors.contract", "contracts.read", True),
        ("selectors.sigmarket", "sigmarket.market.read", True),
        ("formatting.content", "formatting.preflight", False),
        ("writes.content", "posts.reply", False),
        ("writes.bytes", "bytes.transfer", False),
        ("confirm.live", "threads.create", False),
        ("drafts.confirm_delete", "drafts.delete", False),
        ("drafts.metadata", "drafts.update", False),
        ("drafts.metadata", "drafts.read", True),
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
    policy = CapabilityPolicy(load_settings(config_path=config_path, env={}))

    assert policy.can_register(tool) is expected_register
    assert disabled_family not in policy.allowed_parameter_families(tool)


def test_published_schemas_are_pruned_clean_idempotent_and_leave_tools_intact() -> None:
    snapshot = copy.deepcopy([spec.input_schema for spec in TOOLS])
    for dropped in sorted(ALL_PARAMETER_FAMILIES):
        policy = _policy(set(ALL_CAPABILITIES), set(ALL_PARAMETER_FAMILIES) - {dropped})
        for spec in TOOLS:
            if not policy.can_register(spec.name):
                continue
            schema = policy.input_schema(spec)
            assert schema == policy.input_schema(spec)
            properties = schema["properties"]
            for name in properties:
                assert spec.input_schema["properties"][name][FAMILY_KEY] != dropped
            assert all(name in properties for name in schema.get("required", ()))
            if "anyOf" in spec.input_schema:
                assert schema["anyOf"], (spec.name, dropped)
            for branch in schema.get("anyOf", ()):
                assert all(name in properties for name in branch["required"])
            assert not any(
                str(key).startswith("x-hf-") for key in _walk_keys(schema)
            ), spec.name
    assert snapshot == [spec.input_schema for spec in TOOLS]


def test_internal_tags_exist_on_every_table_property_but_never_publish() -> None:
    for spec in TOOLS:
        for prop in spec.input_schema["properties"].values():
            assert prop[FAMILY_KEY] in ALL_PARAMETER_FAMILIES
        assert spec.input_schema["additionalProperties"] is False
        published = _policy(set(ALL_CAPABILITIES), set(ALL_PARAMETER_FAMILIES))
        assert FAMILY_KEY not in str(published.input_schema(spec))
        assert WIRE_KEY not in str(published.input_schema(spec))


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


def test_custom_profile_accepts_explicit_capability_and_parameter_family(
    tmp_path: Path,
) -> None:
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


def test_example_config_defaults_to_reader_profile() -> None:
    data = yaml.safe_load(
        (PRODUCT_ROOT / "config.example.yaml").read_text(encoding="utf-8")
    )
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
