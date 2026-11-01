"""OBS cost pipeline (Task 2.6). Pure, deterministic, no I/O.

Computes an estimated cost from usage dimensions while preserving the
measured-vs-estimated provenance of every dimension (R4). The cost pipeline
lives entirely under ``src/obs/`` and is strictly separate from the billing
surface (``billing_routes.py`` / ``billing_activities``) — it never touches
those tables or blueprint (R4.9).

``compute_cost`` is pure: it performs no I/O and never raises on data. A
missing rate maps the dimension's contribution to ``0.0`` (unknown rate), and
empty dims classify as ``ESTIMATED`` with ``estimated_cost = 0.0`` so the
classifier is total — every input maps to exactly one data source.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# The usage dimensions a cost record may carry (R4.6). Rates for each are
# supplied by the injected rate card (loaded from conf/obs.ini [rate_card]).
USAGE_DIMS = (
    "cpu_seconds",
    "memory_gb_seconds",
    "gpu_seconds",
    "storage_gb_hours",
    "network_gb",
    "llm_tokens",
)


@dataclass(frozen=True)
class UsageDim:
    """A single usage dimension's value and its provenance."""

    value: float
    measured: bool  # True = metered, False = estimated/assumed


def compute_cost(usage_dims: Dict[str, UsageDim], rate_card: Dict[str, float]) -> Dict:
    """Pure cost computation with measured-vs-estimated provenance (R4). No I/O.

    data_source classification (R4.2-R4.5):
      all present dims measured   -> MEASURED
      no present dim measured     -> ESTIMATED (including the empty case, R4.4)
      mix of measured + estimated -> MIXED

    ``estimated_cost = sum(dim.value * rate_card[name])`` over present dims,
    rounded to 6 decimals and stored SEPARATELY from the measured usage values
    (R4.7). Never raises on data: an unknown rate contributes ``0.0``.
    """
    present = {k: v for k, v in usage_dims.items() if v is not None}
    measured_flags = [v.measured for v in present.values()]
    if not measured_flags:
        data_source = "ESTIMATED"
    elif all(measured_flags):
        data_source = "MEASURED"
    elif any(measured_flags):
        data_source = "MIXED"
    else:
        data_source = "ESTIMATED"
    estimated_cost = round(
        sum(v.value * rate_card.get(k, 0.0) for k, v in present.items()), 6
    )
    return {
        "usage": {
            k: {"value": v.value, "measured": v.measured}
            for k, v in present.items()
        },  # measured dims preserved
        "estimated_cost": estimated_cost,  # stored separately (R4.7)
        "data_source": data_source,  # MEASURED|ESTIMATED|MIXED
    }


# ---------------------------------------------------------------------------
# Cost-record reader (Task 6.1). The I/O surface for the OBS cost pipeline.
#
# ``compute_cost`` above stays pure; the helpers below are the thin,
# tenant-scoped persistence/read layer over ``agent_cost_records`` (created by
# migration add_agent_cost_records.sql). They live under ``src/obs/`` (R4.1)
# and never touch the billing tables/blueprint (R4.9).
# ---------------------------------------------------------------------------


def _get_db():
    from ..database_postgres import db_manager
    return db_manager


def _as_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def list_cost_records(
    tenant_id: int,
    limit: int = 200,
    *,
    parent_task_id: Optional[int] = None,
    delegation_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return tenant-scoped cost records (newest first).

    Surfaces the measured ``usage`` dimensions, the separately stored
    ``estimated_cost``, and the ``data_source`` label so the measured-vs-
    estimated distinction is visible on the cost route (R4.8). Optionally
    filtered by ``parent_task_id`` / ``delegation_id`` for budget aggregation
    over a delegation chain (R11). Parameterized and tenant-scoped in the
    repository style of the rest of the codebase.
    """
    conditions = ["tenant_id = %s"]
    params: List[Any] = [tenant_id]
    if parent_task_id is not None:
        conditions.append("parent_task_id = %s")
        params.append(int(parent_task_id))
    if delegation_id is not None:
        conditions.append("delegation_id = %s")
        params.append(delegation_id)
    where = " WHERE " + " AND ".join(conditions)
    params.append(max(1, min(int(limit), 1000)))
    rows = _get_db().execute_query(
        "SELECT id, agent_identity, parent_task_id, delegation_id, usage, "
        "estimated_cost, data_source, created_at "
        f"FROM agent_cost_records{where} ORDER BY created_at DESC, id DESC LIMIT %s",
        tuple(params),
        fetch_all=True,
    )
    return [
        {
            "id": int(r[0]),
            "agent_identity": r[1],
            "parent_task_id": int(r[2]) if r[2] is not None else None,
            "delegation_id": r[3],
            "usage": _as_json(r[4]) or {},
            "estimated_cost": float(r[5]) if r[5] is not None else 0.0,
            "data_source": r[6],
            "created_at": r[7].isoformat() if r[7] else None,
        }
        for r in (rows or [])
    ]
