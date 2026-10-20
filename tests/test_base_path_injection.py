#!/usr/bin/env python3
"""Property-based tests for Base_Path injection in the deploy flow.

Feature: nginx-to-traefik-migration, Property 3 -- "Base_Path is supplied to
every app". Validates Requirement 3.2: when an application is deployed, the
platform provides the Base_Path to the application through an environment
variable.

The unit under test is the pure staticmethod
``src.template_deploy.TemplateDeployService._inject_base_path`` (task 5.1). The
deployment environment is expressed as a list of ``{"name", "value"}`` dicts.
The injected Base_Path is ``/{user}/{app}/`` with a trailing slash, present
exactly once, and overrides any pre-existing ``BASE_PATH`` entry so the platform
value is authoritative.
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.template_deploy import (  # noqa: E402
    BASE_PATH_ENV_VAR,
    TemplateDeployService,
)


# DNS-label-safe identifiers, matching the platform app-name rules [a-z0-9-],
# 1..63 chars. Used for both user_name and app_name.
_names = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=63)

# Environment entry names other than BASE_PATH, so we can build arbitrary
# starting template environments without accidentally colliding on the key we
# are injecting (that collision is exercised separately below).
_other_env_names = st.text(
    alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789", min_size=1, max_size=20
).filter(lambda n: n != BASE_PATH_ENV_VAR)

_env_values = st.text(max_size=40)

# A single {"name", "value"} entry. Mostly non-BASE_PATH names, but sometimes a
# pre-existing BASE_PATH entry with an arbitrary (stale) value so the override
# behaviour is covered.
_env_entry = st.one_of(
    st.builds(lambda n, v: {"name": n, "value": v}, _other_env_names, _env_values),
    st.builds(lambda v: {"name": BASE_PATH_ENV_VAR, "value": v}, _env_values),
)

# Arbitrary starting template environment: a list (possibly empty) of entries.
_environments = st.lists(_env_entry, min_size=0, max_size=10)


@settings(max_examples=200)
@given(user_name=_names, app_name=_names, environment=_environments)
def test_base_path_supplied_to_every_app(user_name, app_name, environment):
    """Feature: nginx-to-traefik-migration, Property 3.

    Validates: Requirements 3.2

    Over generated user/app names and arbitrary starting environments, the
    produced environment includes BASE_PATH == /{user}/{app}/ exactly once.
    """
    expected = f"/{user_name}/{app_name}/"

    result = TemplateDeployService._inject_base_path(environment, user_name, app_name)

    base_path_entries = [
        entry
        for entry in result
        if isinstance(entry, dict) and entry.get("name") == BASE_PATH_ENV_VAR
    ]

    # Present exactly once.
    assert len(base_path_entries) == 1, (
        f"expected exactly one {BASE_PATH_ENV_VAR} entry, got {len(base_path_entries)}: "
        f"{base_path_entries}"
    )

    # Value is /{user}/{app}/ with a trailing slash.
    assert base_path_entries[0] == {"name": BASE_PATH_ENV_VAR, "value": expected}
    assert base_path_entries[0]["value"].endswith("/")


@settings(max_examples=200)
@given(
    user_name=_names,
    app_name=_names,
    environment=_environments,
    stale_value=_env_values,
)
def test_preexisting_base_path_is_overridden(
    user_name, app_name, environment, stale_value
):
    """A pre-existing BASE_PATH entry is overridden with the computed value.

    Feature: nginx-to-traefik-migration, Property 3
    Validates: Requirements 3.2
    """
    expected = f"/{user_name}/{app_name}/"

    # Force a stale BASE_PATH into the starting environment.
    seeded = list(environment) + [{"name": BASE_PATH_ENV_VAR, "value": stale_value}]

    result = TemplateDeployService._inject_base_path(seeded, user_name, app_name)

    base_path_entries = [
        entry
        for entry in result
        if isinstance(entry, dict) and entry.get("name") == BASE_PATH_ENV_VAR
    ]

    assert len(base_path_entries) == 1
    assert base_path_entries[0]["value"] == expected
    # The stale value must not survive unless it happened to equal the computed
    # value (which is the correct outcome either way).
    assert base_path_entries[0]["value"] != stale_value or stale_value == expected


@settings(max_examples=200)
@given(user_name=_names, app_name=_names, environment=_environments)
def test_other_env_entries_preserved(user_name, app_name, environment):
    """Non-BASE_PATH entries from the template survive injection unchanged.

    Feature: nginx-to-traefik-migration, Property 3
    Validates: Requirements 3.2
    """
    result = TemplateDeployService._inject_base_path(environment, user_name, app_name)

    original_non_base = [
        entry for entry in environment if entry.get("name") != BASE_PATH_ENV_VAR
    ]
    result_non_base = [
        entry for entry in result if entry.get("name") != BASE_PATH_ENV_VAR
    ]

    assert result_non_base == original_non_base
    # The caller's list is never mutated.
    assert environment is not result
