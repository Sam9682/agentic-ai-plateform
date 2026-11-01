#!/usr/bin/env python3
"""Config-driven role loading tests for src/aro/supervisor.py (Task 9.2).

Feature: phase5-obs-supervisor.

Validates:
* Requirements 7.2 — the Supervisor's Role set is loaded from configuration
  (``conf/supervisor_roles.yaml``) by ``load_roles``. Each configured entry
  becomes a selectable ``Role`` carrying its ``capabilities`` and
  ``default_scope``; the seven example roles (Architect, Developer, DevOps,
  Security, FinOps, SRE, Supervisor) ship as config entries, not hardcoded
  constants.
* Requirements 7.4 — roles are data, not code: adding a brand-new entry to the
  configuration makes that role loaded and selectable with NO code change. The
  tests prove this by feeding ``load_roles`` a parsed dict that contains a role
  name absent from the module source and asserting it is loaded and usable.

These are plain pytest unit tests (examples/edge cases), not property tests.

Run directly:
    python3 tests/test_phase5_role_config_loading.py
Or via pytest:
    pytest tests/test_phase5_role_config_loading.py -q
"""
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro.supervisor import Role, load_roles  # noqa: E402

# The seven example roles shipped as config entries in conf/supervisor_roles.yaml
# (Requirement 7.3). The test asserts the default config loads exactly these.
EXPECTED_DEFAULT_ROLES = (
    "Architect",
    "Developer",
    "DevOps",
    "Security",
    "FinOps",
    "SRE",
    "Supervisor",
)


# --------------------------------------------------------------------------- #
# (1) The default config (conf/supervisor_roles.yaml) loads the example roles.
# --------------------------------------------------------------------------- #
def test_default_config_loads_seven_example_roles():
    """load_roles() with no argument reads conf/supervisor_roles.yaml (R7.2)."""
    roles = load_roles()

    # Every expected example role is present and selectable by name.
    assert set(EXPECTED_DEFAULT_ROLES).issubset(set(roles.keys()))
    assert len(roles) == len(EXPECTED_DEFAULT_ROLES)

    for name in EXPECTED_DEFAULT_ROLES:
        role = roles[name]
        assert isinstance(role, Role)
        assert role.name == name
        # Each example role carries capabilities and a default_scope as tuples.
        assert isinstance(role.capabilities, tuple)
        assert isinstance(role.default_scope, tuple)
        assert len(role.capabilities) >= 1
        assert len(role.default_scope) >= 1


def test_default_config_role_is_selectable_by_name():
    """A role present in the config is retrievable/selectable by its name."""
    roles = load_roles()
    developer = roles["Developer"]
    assert developer.name == "Developer"
    # Spot-check a capability/scope glob round-tripped from the YAML file.
    assert "code:*" in developer.capabilities
    assert "repo:*" in developer.default_scope


# --------------------------------------------------------------------------- #
# (2) Adding a NEW config entry makes it loaded/selectable with no code change.
# --------------------------------------------------------------------------- #
def test_new_config_entry_is_loaded_and_selectable_without_code_change():
    """A brand-new role in the parsed config is loaded and selectable (R7.4).

    The role name here (``DataScientist``) does not appear anywhere in the
    supervisor module source — it exists only in this config dict. If roles are
    truly data (not code), load_roles must surface it as a usable Role with no
    change to the module.
    """
    config = {
        "roles": [
            {
                "name": "DataScientist",
                "capabilities": ["train:*", "analyze:*", "read:*"],
                "default_scope": ["dataset:*", "model:*"],
            }
        ]
    }

    roles = load_roles(config)

    assert "DataScientist" in roles
    role = roles["DataScientist"]
    assert isinstance(role, Role)
    assert role.name == "DataScientist"
    assert role.capabilities == ("train:*", "analyze:*", "read:*")
    assert role.default_scope == ("dataset:*", "model:*")


def test_adding_entry_to_existing_set_grows_the_loaded_roles():
    """Appending a new entry to a config set yields +1 selectable role (R7.4).

    Demonstrates that the loaded set is exactly the config contents: the same
    config minus/plus one entry loads one fewer/more role, with no code change.
    """
    base_entries = [
        {"name": "Developer", "capabilities": ["code:*"], "default_scope": ["repo:*"]},
    ]
    extended_entries = base_entries + [
        {"name": "Reviewer", "capabilities": ["review:*", "read:*"], "default_scope": ["repo:*"]},
    ]

    base_roles = load_roles({"roles": base_entries})
    extended_roles = load_roles({"roles": extended_entries})

    assert set(base_roles.keys()) == {"Developer"}
    assert set(extended_roles.keys()) == {"Developer", "Reviewer"}
    assert len(extended_roles) == len(base_roles) + 1
    # The newly added role is immediately selectable.
    assert extended_roles["Reviewer"].capabilities == ("review:*", "read:*")


# --------------------------------------------------------------------------- #
# (3) Capabilities / default_scope round-trip from config into the Role.
# --------------------------------------------------------------------------- #
def test_capabilities_and_default_scope_round_trip_from_config():
    """A role's capabilities/default_scope are preserved verbatim (R7.2)."""
    caps = ["deploy:*", "config:*", "read:logs"]
    scope = ["staging-*", "prod-*"]
    config = {
        "roles": [
            {"name": "DevOps", "capabilities": caps, "default_scope": scope},
        ]
    }

    role = load_roles(config)["DevOps"]

    # Order and content are preserved as a tuple of the config list.
    assert role.capabilities == tuple(caps)
    assert role.default_scope == tuple(scope)


def test_entry_without_optional_lists_defaults_to_empty_tuples():
    """A role entry omitting capabilities/default_scope loads empty tuples."""
    config = {"roles": [{"name": "Minimal"}]}

    role = load_roles(config)["Minimal"]

    assert role.name == "Minimal"
    assert role.capabilities == ()
    assert role.default_scope == ()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
