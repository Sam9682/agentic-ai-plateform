"""Agent Behavioral Firewall (ABF) — detection and pre-execution enforcement.

Two entry points:

* :meth:`Firewall.guard` — **before** a sensitive action. Deterministic rules
  produce context (risk level, rule hits); the decision is taken by the ZAF PDP
  (:func:`governance_service.decide`), never by ABF alone. ABF can only make a
  decision *stricter* (a rule requesting DENY or approval is a floor), never
  looser. REQUIRE_APPROVAL is satisfied only by a single-use approval bound to
  the exact request, the agent and the session.
* :meth:`Firewall.inspect` — **after** events are recorded (telemetry
  ingestion, control-plane events). Records alerts (facts and inference kept
  apart) and applies containment: QUARANTINE, REVOKE_PERMISSION, RATE_LIMIT or
  ALERT. DENY / REQUIRE_APPROVAL cannot be applied after the fact and are
  recorded as ``not_enforceable_post_hoc``.

Fail closed: if the PDP or its store is unavailable, ``guard`` denies.
Telemetry ingestion is never blocked by a detection failure.

Honest scope: ``guard`` only protects actions that are routed through it (the
platform MCP server, the ZAF seams, and runtimes that call
``POST /api/v1/firewall/check``). It cannot see an action an uncooperative
runtime performs without asking; such actions surface later through telemetry
and ``inspect``, or not at all if the runtime does not report them.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

from . import baseline as B
from . import rules as R

GUARD_ACTION_PREFIX = "abf"
RATE_LIMIT_COOLDOWN_SECONDS = 60
RECENT_WINDOW_SECONDS = 300

_STRICTNESS = {"ALLOW": 0, "REQUIRE_APPROVAL": 1, "QUARANTINE": 2, "DENY": 3}
_RISK_POINTS = {"info": 0, "low": 20, "medium": 45, "high": 70, "critical": 95}


def tenant_slug_of(identity: Optional[str]) -> Optional[str]:
    if identity and identity.startswith("agent://"):
        return identity[len("agent://"):].split("/", 1)[0] or None
    return None


def guard_action(category: str, action: str) -> str:
    return f"{GUARD_ACTION_PREFIX}.{(category or 'unknown').lower()}.{action or 'unknown'}"


@dataclass
class GuardRequest:
    tenant_id: int
    agent_db_id: int
    category: str
    action: str
    resource: str = ""
    command: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    session_id: Optional[str] = None
    trace_id: Optional[str] = None
    task_id: Optional[str] = None


@dataclass
class GuardResult:
    decision: str
    allowed: bool
    reason: str
    action: str
    risk_level: str = "info"
    rule_hits: List[Dict[str, Any]] = field(default_factory=list)
    enforcement: List[str] = field(default_factory=list)
    approval: Optional[Dict[str, Any]] = None
    approval_consumed: Optional[int] = None
    params_hash: Optional[str] = None
    pdp_decision: Optional[str] = None
    status_code: int = 200

    def as_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision, "allowed": self.allowed, "reason": self.reason,
            "action": self.action, "risk_level": self.risk_level,
            "rule_hits": self.rule_hits, "enforcement": self.enforcement,
            "approval": self.approval, "approval_consumed": self.approval_consumed,
            "params_hash": self.params_hash, "pdp_decision": self.pdp_decision,
        }


class CooldownStore:
    """Per-process RATE_LIMIT cooldowns keyed by (tenant, agent).

    Limitation (documented): with several API processes each keeps its own
    cooldowns. The PDP-level controls (quarantine, revocation) are shared.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._until: Dict[tuple, float] = {}
        self._lock = threading.Lock()
        self._clock = clock

    def set(self, key: tuple, seconds: int) -> None:
        with self._lock:
            self._until[key] = max(self._until.get(key, 0.0), self._clock() + seconds)

    def remaining(self, key: tuple) -> int:
        with self._lock:
            left = self._until.get(key, 0.0) - self._clock()
        return max(0, int(left + 0.999))

    def clear(self, key: tuple) -> None:
        with self._lock:
            self._until.pop(key, None)


def _default(name: str):
    """Lazy default collaborators (keep this module importable without a DB)."""
    if name == "decide":
        from ..zaf import governance_service
        return governance_service.decide
    if name == "params_hash":
        from ..zaf import governance_service
        return governance_service.params_hash
    if name == "consume_approval":
        from ..zaf import approval_service
        return approval_service.consume_authorization
    if name == "request_approval":
        from ..zaf import approval_service
        return approval_service.request_approval
    if name == "get_agent":
        from ..aro import agent_repository
        return agent_repository.get_agent
    if name == "events_repo":
        from ..aro import events_repository
        return events_repository
    raise KeyError(name)


class Firewall:
    def __init__(
        self,
        *,
        decide: Optional[Callable[..., Dict[str, Any]]] = None,
        params_hash: Optional[Callable[[str, Dict[str, Any]], str]] = None,
        consume_approval: Optional[Callable[..., Optional[int]]] = None,
        request_approval: Optional[Callable[..., Dict[str, Any]]] = None,
        get_agent: Optional[Callable[[int, int], Optional[Dict[str, Any]]]] = None,
        customisation: Optional[Callable[..., Any]] = None,
        record_alert: Optional[Callable[..., Optional[int]]] = None,
        set_alert_enforcement: Optional[Callable[..., Any]] = None,
        list_baselines: Optional[Callable[[int, int], List[Dict[str, Any]]]] = None,
        recent_events: Optional[Callable[..., List[Dict[str, Any]]]] = None,
        quarantine: Optional[Callable[[int, int, str], Any]] = None,
        revoke_permissions: Optional[Callable[[int, int], Any]] = None,
        events_repo: Any = None,
        seal: Optional[Callable[[int], Any]] = None,
        cooldowns: Optional[CooldownStore] = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        from . import repository as repo
        self._decide = decide or _default("decide")
        self._phash = params_hash or _default("params_hash")
        self._consume = consume_approval or _default("consume_approval")
        self._request_approval = request_approval or _default("request_approval")
        self._get_agent = get_agent or _default("get_agent")
        self._customisation = customisation or repo.effective_customisation
        self._record_alert = record_alert or repo.record_alert
        self._set_alert_enforcement = set_alert_enforcement or repo.set_alert_enforcement
        self._list_baselines = list_baselines or repo.list_baselines
        self._recent = recent_events or _default_recent_events
        self._quarantine = quarantine
        self._revoke = revoke_permissions
        self._events = events_repo if events_repo is not None else _default("events_repo")
        self._seal = seal
        self.cooldowns = cooldowns or CooldownStore()
        self._clock = clock

    # ------------------------------------------------------------------ guard
    def guard(self, req: GuardRequest) -> GuardResult:
        action = guard_action(req.category, req.action)
        agent = self._get_agent(req.tenant_id, req.agent_db_id)
        if agent is None:
            return GuardResult("DENY", False, "unknown agent", action, status_code=404)
        identity = agent.get("identity")
        hash_params = {"category": req.category, "action": req.action,
                       "resource": req.resource, "command": req.command,
                       "params": req.params or {}}
        phash = self._phash(action, hash_params)

        left = self.cooldowns.remaining((req.tenant_id, req.agent_db_id))
        if left:
            self._audit(req, identity, action, "DENY", f"rate limited ({left}s left)", [], [])
            return GuardResult("DENY", False, "rate limited", action, params_hash=phash,
                               enforcement=["RATE_LIMIT"], status_code=429)

        view = R.ActionView(
            category=(req.category or "").upper() or None, action=req.action or "",
            resource=req.resource or "",
            text=" ".join(p for p in (req.command, R.text_from_metadata(req.params)) if p),
            tenant_slug=tenant_slug_of(identity),
        )
        hits, risk, floor, context = self.assess(req.tenant_id, req.agent_db_id, view)

        try:
            decision = self._decide(
                req.tenant_id, action, agent_db_id=req.agent_db_id, agent_identity=identity,
                resource=req.resource or None, params=hash_params, context=context)
            pdp = decision.get("decision") or "DENY"
            reason = decision.get("reason") or ""
        except Exception:  # noqa: BLE001 - fail closed
            pdp, reason = "DENY", "policy decision service unavailable (fail closed)"

        final = pdp if _STRICTNESS.get(pdp, 3) >= _STRICTNESS[floor] else floor
        if final != pdp:
            reason = f"ABF rule floor {floor} over PDP {pdp}"
        result = GuardResult(final, False, reason, action, risk, [h.as_dict() for h in hits],
                             params_hash=phash, pdp_decision=pdp)

        if final == "ALLOW":
            result.allowed = True
        elif final == "REQUIRE_APPROVAL":
            consumed = None
            try:
                consumed = self._consume(req.tenant_id, action, hash_params,
                                         agent_identity=identity, session_id=req.session_id,
                                         consumer="abf-guard")
            except Exception:  # noqa: BLE001 - fail closed
                consumed = None
            if consumed is not None:
                result.allowed = True
                result.approval_consumed = consumed
                result.reason = "approved (single-use approval consumed)"
            else:
                result.status_code = 202
                try:
                    result.approval = self._request_approval(
                        req.tenant_id, action, params=hash_params, agent_identity=identity,
                        resource=req.resource or None, session_id=req.session_id,
                        risk_explanation="; ".join(h.inference for h in hits) or reason,
                        triggering_policy={"abf_rules": [h.rule_id for h in hits],
                                           "pdp_reason": reason},
                        events_repo=self._events)
                except Exception:  # noqa: BLE001 - still blocked
                    result.approval = None
        else:
            result.status_code = 403

        result.enforcement = self.enforce_hits(
            req.tenant_id, req.agent_db_id, identity, hits, pre_execution=True,
            trace_id=req.trace_id, session_id=req.session_id,
            dedupe_suffix=f"guard:{phash[:16]}:{int(self._clock().timestamp()) // 60}")
        self._audit(req, identity, action, final, result.reason, hits, result.enforcement)
        return result

    # ---------------------------------------------------------------- inspect
    def inspect(self, tenant_id: int, agent_db_id: int, agent_identity: Optional[str],
                new_events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        """Detect on freshly recorded events; never raises."""
        summary: Dict[str, Any] = {"alerts": 0, "enforcement": []}
        try:
            overrides, thresholds = self._customisation(tenant_id, agent_db_id)
        except Exception:  # noqa: BLE001
            overrides, thresholds = {}, []
        slug = tenant_slug_of(agent_identity)
        hits: List[R.RuleHit] = []
        for ev in new_events:
            hits.extend(R.evaluate_action(R.view_from_event(ev, tenant_slug=slug),
                                          overrides=overrides))
        now = self._clock()
        try:
            recent = self._recent(tenant_id, agent_identity,
                                  since=now - timedelta(seconds=RECENT_WINDOW_SECONDS))
        except Exception:  # noqa: BLE001
            recent = list(new_events)
        views = [R.view_from_event(e, tenant_slug=slug) for e in recent]
        agent_key = str(agent_db_id)
        hits.extend(R.evaluate_window(views, now=now, agent_key=agent_key,
                                      overrides=overrides, thresholds=thresholds))
        hits.extend(self._baseline_hits(tenant_id, agent_db_id, recent, now, agent_key))
        trace_id = next((e.get("trace_id") for e in new_events if e.get("trace_id")), None)
        summary["enforcement"] = self.enforce_hits(
            tenant_id, agent_db_id, agent_identity, hits, pre_execution=False,
            trace_id=trace_id, session_id=None, dedupe_suffix=None, summary=summary)
        return summary

    def _baseline_hits(self, tenant_id, agent_db_id, recent, now, agent_key) -> List[R.RuleHit]:
        try:
            stored = self._list_baselines(tenant_id, agent_db_id)
        except Exception:  # noqa: BLE001
            return []
        out = []
        for b in stored:
            metric = b.get("metric")
            if metric not in B.METRICS or b.get("confidence") in (None, "insufficient"):
                continue
            window = int(b.get("window_seconds") or B.DEFAULT_WINDOW_SECONDS)
            lo = (now - timedelta(seconds=window)).timestamp()
            observed = sum(1 for e in recent
                           if (B._ts(e) or 0) >= lo and B.METRICS[metric](e))
            base = B.Baseline(metric, window, b.get("mean"), b.get("stddev"),
                              int(b.get("sample_count") or 0), int(b.get("excluded_windows") or 0),
                              b.get("runtime_reported_ratio"), b.get("confidence"))
            hit = B.deviation(metric, observed, base)
            if hit is not None:
                out.append(R.RuleHit(**{**hit.__dict__,
                                        "dedupe_key": f"{hit.rule_id}:{agent_key}:"
                                                      f"{int(now.timestamp()) // window}"}))
        return out

    # ------------------------------------------------------------ assessment
    def assess(self, tenant_id: int, agent_db_id: int, view: R.ActionView):
        """Evaluate single-action rules; return (hits, risk_level, floor, pdp_context).

        ``floor`` is the strictest decision the hits demand (ABF can tighten a
        PDP decision, never loosen it). ``pdp_context`` is what the PDP sees.
        """
        try:
            overrides, _ = self._customisation(tenant_id, agent_db_id)
        except Exception:  # noqa: BLE001 - customisation store down: built-ins still apply
            overrides = {}
        hits = R.evaluate_action(view, overrides=overrides)
        risk = R.max_risk(h.risk_level for h in hits)
        floor = "ALLOW"
        for h in hits:
            if h.enforcement_action == R.DENY:
                floor = "DENY"
                risk = R.max_risk((risk, "critical"))
            elif h.enforcement_action == R.REQUIRE_APPROVAL and floor == "ALLOW":
                floor = "REQUIRE_APPROVAL"
                risk = R.max_risk((risk, "high"))
        context = {"risk_level": risk, "risk_score": _RISK_POINTS[risk],
                   "abf_rules": [h.rule_id for h in hits]}
        return hits, risk, floor, context

    # ------------------------------------------------------------ enforcement
    def enforce_hits(self, tenant_id, agent_db_id, identity, hits, *, pre_execution,
                      trace_id, session_id, dedupe_suffix, summary=None) -> List[str]:
        taken: List[str] = []
        quarantined = False
        for hit in hits:
            if dedupe_suffix and not hit.dedupe_key:
                hit = R.RuleHit(**{**hit.__dict__, "dedupe_key": f"{hit.rule_id}:{dedupe_suffix}"})
            try:
                alert_id = self._record_alert(
                    tenant_id, identity, agent_db_id, hit,
                    risk_score=_RISK_POINTS[hit.risk_level], trace_id=trace_id,
                    session_id=session_id)
            except Exception:  # noqa: BLE001 - detection must not break callers
                alert_id = None
                continue
            if alert_id is None:
                continue  # duplicate: already alerted and enforced once
            if summary is not None:
                summary["alerts"] += 1
            status = self._apply(tenant_id, agent_db_id, hit, pre_execution, quarantined)
            if hit.enforcement_action == R.QUARANTINE and status == "applied":
                quarantined = True
            if status == "applied":
                taken.append(hit.enforcement_action)
            try:
                self._set_alert_enforcement(tenant_id, alert_id, status)
            except Exception:  # noqa: BLE001
                pass
        return sorted(set(taken))

    def _apply(self, tenant_id, agent_db_id, hit: R.RuleHit, pre_execution: bool,
               already_quarantined: bool) -> str:
        act = hit.enforcement_action
        if act == R.ALERT:
            return "alerted"
        if act in R.PRE_EXECUTION_ONLY:
            return "applied" if pre_execution else "not_enforceable_post_hoc"
        if act == R.RATE_LIMIT:
            self.cooldowns.set((tenant_id, agent_db_id), RATE_LIMIT_COOLDOWN_SECONDS)
            return "applied"
        if act == R.REVOKE_PERMISSION:
            if self._revoke is None:
                return "not_configured"
            try:
                self._revoke(tenant_id, agent_db_id)
                return "applied"
            except Exception:  # noqa: BLE001
                return "failed"
        if act == R.QUARANTINE:
            if already_quarantined:
                return "applied"
            if self._quarantine is None:
                return "not_configured"
            try:
                self._quarantine(tenant_id, agent_db_id, f"abf:{hit.rule_id}")
                return "applied"
            except Exception:  # noqa: BLE001 - e.g. agent already quarantined
                return "failed"
        return "unknown_action"

    def _audit(self, req: GuardRequest, identity, action, decision, reason, hits, enforcement):
        try:
            from ..aro import event_service as es
            es.emit(self._events, req.tenant_id, "abf.guard", "abf",
                    agent_id=identity,
                    action={"guard_action": action, "reason": reason,
                            "category": req.category, "command": req.command,
                            "resource": req.resource,
                            "abf_rules": [h.rule_id for h in hits],
                            "enforcement": list(enforcement)},
                    decision=decision if decision in _STRICTNESS else "DENY",
                    risk_score=_RISK_POINTS[R.max_risk(h.risk_level for h in hits)],
                    severity="INFO" if decision == "ALLOW" else "HIGH",
                    category="SECURITY", trace_id=req.trace_id, session_id=req.session_id,
                    task_id=req.task_id, normalized_action=action[:255],
                    outcome="SUCCESS" if decision == "ALLOW" else "DENIED")
        except Exception:  # noqa: BLE001 - audit failure must not flip a deny into allow
            pass
        if self._seal is not None:
            try:
                self._seal(req.tenant_id)
            except Exception:  # noqa: BLE001
                pass


def _default_recent_events(tenant_id: int, agent_identity: Optional[str], *, since: datetime
                           ) -> List[Dict[str, Any]]:
    from ..aro import events_repository
    if not agent_identity:
        return []
    page = events_repository.query_events(
        tenant_id, filters={"agent_id": agent_identity}, since=since, limit=500, order="asc")
    return page.get("events", [])


# --------------------------------------------------------------------------- #
# Live composition
# --------------------------------------------------------------------------- #
_LIVE: Optional[Firewall] = None
_LIVE_LOCK = threading.Lock()


def get_firewall() -> Firewall:
    """Process-wide firewall wired to the real services."""
    global _LIVE
    with _LIVE_LOCK:
        if _LIVE is None:
            from . import audit_chain
            from ..aro.lifecycle_service import LifecycleService
            from ..obs import ingest_tokens
            from ..zaf import wiring

            def _quarantine(tenant_id, agent_db_id, reason):
                svc = LifecycleService(zaf_pre_transition=wiring.build_live_pre_transition())
                return wiring.quarantine_agent(tenant_id, agent_db_id, reason=reason,
                                               lifecycle_svc=svc)

            _LIVE = Firewall(quarantine=_quarantine,
                             revoke_permissions=ingest_tokens.revoke_acting_scopes_for_agent,
                             seal=audit_chain.safe_seal)
        return _LIVE


def set_firewall(fw: Optional[Firewall]) -> None:
    """Test hook."""
    global _LIVE
    with _LIVE_LOCK:
        _LIVE = fw
