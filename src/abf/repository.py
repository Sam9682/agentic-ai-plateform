"""ABF persistence: tenant rule customisation, alerts, baselines.

Raw SQL through ``db_manager`` in the repository style of the codebase. Alerts
are stored in the existing ``agent_anomalies`` table (extended by
``migration/add_abf.sql``) so the existing OBS views keep working.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from . import rules as R


def _get_db():
    from ..database_postgres import db_manager
    return db_manager


def _as_json(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _iso(v: Any) -> Optional[str]:
    return v.isoformat() if hasattr(v, "isoformat") else v


# --------------------------------------------------------------------------- #
# Rule customisation
# --------------------------------------------------------------------------- #
_RULE_COLS = ("id, agent_id, rule_key, version, enabled, kind, category, matcher, "
              "threshold, window_seconds, risk_level, enforcement_action, description, "
              "created_by_user_id, created_at, updated_at")


def _rule_row(r) -> Dict[str, Any]:
    return {
        "id": int(r[0]), "agent_id": int(r[1]) if r[1] is not None else None,
        "rule_key": r[2], "version": int(r[3]), "enabled": bool(r[4]), "kind": r[5],
        "category": r[6], "matcher": _as_json(r[7]) or {},
        "threshold": r[8], "window_seconds": r[9], "risk_level": r[10],
        "enforcement_action": r[11], "description": r[12],
        "created_by_user_id": r[13], "created_at": _iso(r[14]), "updated_at": _iso(r[15]),
    }


def list_rules(tenant_id: int, agent_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Tenant-wide rules plus, when given, the agent's own rules."""
    if agent_id is None:
        rows = _get_db().execute_query(
            f"SELECT {_RULE_COLS} FROM agent_behavior_rules WHERE tenant_id = %s "
            "ORDER BY rule_key, agent_id NULLS FIRST, id",
            (tenant_id,), fetch_all=True) or []
    else:
        rows = _get_db().execute_query(
            f"SELECT {_RULE_COLS} FROM agent_behavior_rules WHERE tenant_id = %s "
            "AND (agent_id IS NULL OR agent_id = %s) "
            "ORDER BY rule_key, agent_id NULLS FIRST, id",
            (tenant_id, agent_id), fetch_all=True) or []
    return [_rule_row(r) for r in rows]


def get_rule(tenant_id: int, rule_db_id: int) -> Optional[Dict[str, Any]]:
    row = _get_db().execute_query(
        f"SELECT {_RULE_COLS} FROM agent_behavior_rules WHERE tenant_id = %s AND id = %s",
        (tenant_id, rule_db_id), fetch_one=True)
    return _rule_row(row) if row else None


def create_rule(tenant_id: int, spec: Dict[str, Any], *, created_by_user_id: Optional[int]) -> int:
    row = _get_db().execute_query(
        """
        INSERT INTO agent_behavior_rules
            (tenant_id, agent_id, rule_key, version, enabled, kind, category, matcher,
             threshold, window_seconds, risk_level, enforcement_action, description,
             created_by_user_id)
        VALUES (%s, %s, %s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (tenant_id, spec.get("agent_id"), spec["rule_key"], bool(spec.get("enabled", True)),
         spec["kind"], spec.get("category"), json.dumps(spec.get("matcher") or {}),
         spec.get("threshold"), spec.get("window_seconds"), spec.get("risk_level"),
         spec.get("enforcement_action"), spec.get("description"), created_by_user_id),
        fetch_one=True)
    return int(row[0])


def update_rule(tenant_id: int, rule_db_id: int, changes: Dict[str, Any]) -> bool:
    """Apply allowed field changes and bump the version."""
    allowed = ("enabled", "risk_level", "enforcement_action", "threshold",
               "window_seconds", "description", "matcher", "category")
    sets, args = [], []
    for key in allowed:
        if key in changes:
            sets.append(f"{key} = %s")
            args.append(json.dumps(changes[key]) if key == "matcher" else changes[key])
    if not sets:
        return False
    rows = _get_db().execute_query(
        f"UPDATE agent_behavior_rules SET {', '.join(sets)}, version = version + 1, "
        "updated_at = CURRENT_TIMESTAMP WHERE tenant_id = %s AND id = %s",
        tuple(args) + (tenant_id, rule_db_id))
    return bool(rows)


def effective_customisation(tenant_id: int, agent_id: Optional[int]
                            ) -> Tuple[Dict[str, R.RuleOverride], List[R.ThresholdRule]]:
    """Overrides keyed by built-in rule id (agent rows win over tenant rows)."""
    overrides: Dict[str, R.RuleOverride] = {}
    thresholds: List[R.ThresholdRule] = []
    for r in list_rules(tenant_id, agent_id):
        if r["kind"] == "override":
            if r["rule_key"] in overrides and r["agent_id"] is None:
                continue  # an agent-scoped override already applies
            overrides[r["rule_key"]] = R.RuleOverride(
                r["rule_key"], r["enabled"], r["risk_level"], r["enforcement_action"],
                r["version"])
        elif r["kind"] == "threshold" and r["enabled"] and r["threshold"] and r["window_seconds"]:
            m = r["matcher"] or {}
            thresholds.append(R.ThresholdRule(
                r["rule_key"], int(r["threshold"]), int(r["window_seconds"]),
                r["risk_level"] or "medium", r["enforcement_action"] or R.ALERT,
                r["category"] or m.get("category"), m.get("action_glob"), m.get("outcome"),
                m.get("resource_prefix"), r["version"], r["description"] or ""))
    return overrides, thresholds


# --------------------------------------------------------------------------- #
# Alerts (agent_anomalies)
# --------------------------------------------------------------------------- #
def record_alert(tenant_id: int, agent_identity: Optional[str], agent_db_id: Optional[int],
                 hit: R.RuleHit, *, risk_score: int, trace_id: Optional[str] = None,
                 session_id: Optional[str] = None, enforcement_status: str = "pending"
                 ) -> Optional[int]:
    """Insert one alert; returns its id, or None when deduplicated."""
    row = _get_db().execute_query(
        """
        INSERT INTO agent_anomalies
            (tenant_id, agent_identity, rule_id, severity, risk_score, evidence,
             agent_db_id, trace_id, session_id, category, observed_facts, inference,
             confidence_label, rule_version, enforcement_action, recommended_action,
             enforcement_status, source_event_id, dedupe_key)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (tenant_id, dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING
        RETURNING id
        """,
        (tenant_id, agent_identity, hit.rule_id, hit.severity, int(risk_score),
         json.dumps([hit.inference]), agent_db_id, trace_id, session_id, hit.category,
         json.dumps(hit.observed_facts, default=str), hit.inference, hit.confidence,
         hit.rule_version, hit.enforcement_action, hit.enforcement_action,
         enforcement_status, hit.source_event_id,
         hit.dedupe_key or (f"{hit.rule_id}:{hit.source_event_id}" if hit.source_event_id else None)),
        fetch_one=True)
    return int(row[0]) if row else None


def set_alert_enforcement(tenant_id: int, alert_id: int, status: str) -> None:
    _get_db().execute_query(
        "UPDATE agent_anomalies SET enforcement_status = %s WHERE tenant_id = %s AND id = %s",
        (status[:32], tenant_id, alert_id))


_ALERT_COLS = ("id, agent_identity, rule_id, severity, risk_score, status, detected_at, "
               "enforcement_status, recommended_action, agent_db_id, trace_id, session_id, "
               "category, observed_facts, inference, confidence_label, rule_version, "
               "enforcement_action, source_event_id")


def list_alerts(tenant_id: int, *, agent_db_id: Optional[int] = None,
                agent_identity: Optional[str] = None, status: Optional[str] = None,
                min_severity: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    where = ["tenant_id = %s"]
    args: List[Any] = [tenant_id]
    if agent_db_id is not None or agent_identity is not None:
        where.append("(agent_db_id = %s OR (agent_db_id IS NULL AND agent_identity = %s))")
        args += [agent_db_id, agent_identity]
    if status:
        where.append("status = %s")
        args.append(status)
    if min_severity:
        order = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
        if min_severity in order:
            where.append("severity = ANY(%s)")
            args.append(order[order.index(min_severity):])
    args.append(max(1, min(int(limit), 500)))
    rows = _get_db().execute_query(
        f"SELECT {_ALERT_COLS} FROM agent_anomalies WHERE {' AND '.join(where)} "
        "ORDER BY detected_at DESC, id DESC LIMIT %s",
        tuple(args), fetch_all=True) or []
    return [{
        "id": int(r[0]), "agent_identity": r[1], "rule_id": r[2], "severity": r[3],
        "risk_score": int(r[4]), "status": r[5], "detected_at": _iso(r[6]),
        "enforcement_status": r[7], "recommended_action": r[8],
        "agent_db_id": r[9], "trace_id": r[10], "session_id": r[11], "category": r[12],
        "observed_facts": _as_json(r[13]), "inference": r[14], "confidence": r[15],
        "rule_version": r[16], "enforcement_action": r[17], "source_event_id": r[18],
    } for r in rows]


def set_alert_status(tenant_id: int, alert_id: int, status: str) -> bool:
    rows = _get_db().execute_query(
        "UPDATE agent_anomalies SET status = %s WHERE tenant_id = %s AND id = %s",
        (status, tenant_id, alert_id))
    return bool(rows)


# --------------------------------------------------------------------------- #
# Baselines
# --------------------------------------------------------------------------- #
def upsert_baseline(tenant_id: int, agent_id: int, b) -> None:
    _get_db().execute_query(
        """
        INSERT INTO agent_baselines
            (tenant_id, agent_id, metric, window_seconds, mean, stddev, sample_count,
             excluded_windows, runtime_reported_ratio, confidence, computed_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (tenant_id, agent_id, metric) DO UPDATE SET
            window_seconds = EXCLUDED.window_seconds, mean = EXCLUDED.mean,
            stddev = EXCLUDED.stddev, sample_count = EXCLUDED.sample_count,
            excluded_windows = EXCLUDED.excluded_windows,
            runtime_reported_ratio = EXCLUDED.runtime_reported_ratio,
            confidence = EXCLUDED.confidence, computed_at = CURRENT_TIMESTAMP
        """,
        (tenant_id, agent_id, b.metric, b.window_seconds, b.mean, b.stddev, b.sample_count,
         b.excluded_windows, b.runtime_reported_ratio, b.confidence))


def list_baselines(tenant_id: int, agent_id: int) -> List[Dict[str, Any]]:
    rows = _get_db().execute_query(
        "SELECT metric, window_seconds, mean, stddev, sample_count, excluded_windows, "
        "runtime_reported_ratio, confidence, computed_at, reset_at, reset_by_user_id "
        "FROM agent_baselines WHERE tenant_id = %s AND agent_id = %s ORDER BY metric",
        (tenant_id, agent_id), fetch_all=True) or []
    return [{"metric": r[0], "window_seconds": r[1], "mean": r[2], "stddev": r[3],
             "sample_count": r[4], "excluded_windows": r[5], "runtime_reported_ratio": r[6],
             "confidence": r[7], "computed_at": _iso(r[8]), "reset_at": _iso(r[9]),
             "reset_by_user_id": r[10]} for r in rows]


def reset_baselines(tenant_id: int, agent_id: int, user_id: Optional[int]) -> int:
    """Clear statistics; the next refresh only uses events after the reset."""
    rows = _get_db().execute_query(
        "UPDATE agent_baselines SET mean = NULL, stddev = NULL, sample_count = 0, "
        "excluded_windows = 0, runtime_reported_ratio = NULL, confidence = 'insufficient', "
        "reset_at = CURRENT_TIMESTAMP, reset_by_user_id = %s "
        "WHERE tenant_id = %s AND agent_id = %s",
        (user_id, tenant_id, agent_id))
    return int(rows or 0)


def baseline_reset_at(tenant_id: int, agent_id: int):
    row = _get_db().execute_query(
        "SELECT MAX(reset_at) FROM agent_baselines WHERE tenant_id = %s AND agent_id = %s",
        (tenant_id, agent_id), fetch_one=True)
    return row[0] if row else None


def aggregated_event_rows(tenant_id: int, agent_identity: str, *, since, until,
                          window_seconds: int) -> List[Dict[str, Any]]:
    """Per-window grouped counts of an agent's events (input of baseline.compute)."""
    from datetime import datetime, timezone
    rows = _get_db().execute_query(
        """
        SELECT FLOOR(EXTRACT(EPOCH FROM occurred_at) / %s) AS bucket,
               category, outcome, ingest_source, event_type, decision, COUNT(*)
        FROM agent_events
        WHERE tenant_id = %s AND agent_id = %s AND occurred_at >= %s AND occurred_at < %s
        GROUP BY 1, 2, 3, 4, 5, 6
        """,
        (int(window_seconds), tenant_id, agent_identity, since, until), fetch_all=True) or []
    return [{"occurred_at": datetime.fromtimestamp(float(r[0]) * window_seconds, tz=timezone.utc),
             "category": r[1], "outcome": r[2], "ingest_source": r[3], "event_type": r[4],
             "decision": r[5], "_count": int(r[6])} for r in rows]
