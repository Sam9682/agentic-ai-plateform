"""Import-time smoke check: the app factory module and new ARO/ZAF modules
import cleanly (no live DB needed). Catches broken imports / blueprint wiring."""
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ZAF_SECRET_KEY", "import-check-key")

mods = [
    "src.authz",
    "src.aro.event_service",
    "src.aro.events_repository",
    "src.aro.runtime_registry_service",
    "src.aro.runtime_registry_repository",
    "src.zaf.credential_vault",
    "src.routes.aro_common",
    "src.routes.aro_runtime_routes",
    "src.routes.aro_agent_routes",
    "src.routes.aro_task_routes",
    "src.aro.adapters.base",
    "src.aro.adapters.kiro_acp",
    "src.aro.adapters.shai_cli",
    "src.aro.adapters.shai_http_sse",
    "src.aro.agent_worker",
    "src.aro.task_repository",
    "src.aro.lifecycle_service",
    "src.zaf.policy_engine",
    "src.zaf.policy_repository",
    "src.zaf.governance_service",
    "src.zaf.approval_service",
    "src.zaf.mcp_gateway",
    "src.zaf.infra_proxy",
    "src.zaf.providers.openstack",
    "src.zaf.response_service",
    "src.aro.runtime_scanner",
    "src.obs.anomaly_engine",
    "src.obs.risk_scoring",
    "src.obs.obs_repository",
    "src.routes.zaf_governance_routes",
    "src.routes.obs_routes",
]
for m in mods:
    importlib.import_module(m)
    print("ok", m)

# The app factory module imports every blueprint at module top; importing it
# verifies the ARO blueprint import line is valid.
import src.ControlPlanFlaskApp_postgres as app_mod  # noqa: E402
assert hasattr(app_mod, "create_app")
print("ok src.ControlPlanFlaskApp_postgres (create_app present)")
