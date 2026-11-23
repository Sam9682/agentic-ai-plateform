"""ABF deterministic rule catalogue (pure, no I/O).

Every rule is deterministic and explainable: a hit carries the **observed
facts** (what was literally seen: the matched fragment, counts, timestamps,
event ids) separately from the **inference** (what the platform concludes from
those facts), plus a confidence label. Nothing here calls an LLM, and nothing
in an agent-supplied string is ever interpreted as an instruction: inputs are
matched as inert text only.

Two families:

* **Single-action rules** (:func:`evaluate_action`) look at one action — a
  pre-execution request (``guard``) or one recorded event (``inspect``).
* **Window rules** (:func:`evaluate_window`) look at the agent's recent events
  (bursts, repeated failures, exfiltration sequences).

Tenants can disable or re-level a built-in rule, and add count-in-window
threshold rules, through :class:`RuleOverride` / :class:`ThresholdRule`
(persisted in ``agent_behavior_rules``); they can never inject a pattern or code.

All regexes are linear: no nested quantifiers, bounded repetitions, and input
text is truncated to :data:`MAX_TEXT` characters before matching.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

CATALOG_VERSION = "abf-rules-1.0.0"
MAX_TEXT = 8192

RISK_LEVELS = ("info", "low", "medium", "high", "critical")
_RISK_RANK = {lvl: i for i, lvl in enumerate(RISK_LEVELS)}
SEVERITY_FOR_RISK = {"info": "INFO", "low": "LOW", "medium": "MEDIUM",
                     "high": "HIGH", "critical": "CRITICAL"}

# Enforcement actions an ABF rule may request. DENY / REQUIRE_APPROVAL only make
# sense before execution; after the fact (inspect) they degrade to ALERT.
ALERT = "ALERT"
REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
DENY = "DENY"
RATE_LIMIT = "RATE_LIMIT"
REVOKE_PERMISSION = "REVOKE_PERMISSION"
QUARANTINE = "QUARANTINE"
ENFORCEMENT_ACTIONS = (ALERT, REQUIRE_APPROVAL, DENY, RATE_LIMIT,
                       REVOKE_PERMISSION, QUARANTINE)
PRE_EXECUTION_ONLY = frozenset({DENY, REQUIRE_APPROVAL})


def max_risk(levels: Iterable[str]) -> str:
    best = "info"
    for lvl in levels:
        if _RISK_RANK.get(lvl, 0) > _RISK_RANK[best]:
            best = lvl
    return best


@dataclass(frozen=True)
class RuleHit:
    rule_id: str
    rule_version: str
    category: Optional[str]
    risk_level: str
    enforcement_action: str
    observed_facts: Dict[str, Any]
    inference: str
    confidence: str  # 'high' | 'medium' | 'low'
    source_event_id: Optional[str] = None
    dedupe_key: Optional[str] = None

    @property
    def severity(self) -> str:
        return SEVERITY_FOR_RISK[self.risk_level]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_version": self.rule_version,
            "category": self.category,
            "risk_level": self.risk_level,
            "severity": self.severity,
            "enforcement_action": self.enforcement_action,
            "observed_facts": self.observed_facts,
            "inference": self.inference,
            "confidence": self.confidence,
            "source_event_id": self.source_event_id,
        }


# --------------------------------------------------------------------------- #
# Action view: the uniform input of single-action rules
# --------------------------------------------------------------------------- #
@dataclass
class ActionView:
    category: Optional[str]
    action: str = ""
    resource: str = ""
    text: str = ""            # command line / SQL / tool arguments, as inert text
    outcome: Optional[str] = None
    event_id: Optional[str] = None
    occurred_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    tenant_slug: Optional[str] = None


_TEXT_KEYS = ("command", "cmd", "command_line", "query", "sql", "statement",
              "script", "args", "argv", "arguments", "path", "url", "target")


def _flatten_text(value: Any, out: List[str], budget: List[int]) -> None:
    if budget[0] <= 0:
        return
    if isinstance(value, str):
        piece = value[: budget[0]]
        out.append(piece)
        budget[0] -= len(piece) + 1
    elif isinstance(value, (list, tuple)):
        for v in value:
            _flatten_text(v, out, budget)
    elif isinstance(value, dict):
        for v in value.values():
            _flatten_text(v, out, budget)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        out.append(str(value))


def text_from_metadata(metadata: Optional[Dict[str, Any]]) -> str:
    """Collect the command-like fields of a metadata dict into one string."""
    if not isinstance(metadata, dict):
        return ""
    parts: List[str] = []
    budget = [MAX_TEXT]
    for key in _TEXT_KEYS:
        if key in metadata:
            _flatten_text(metadata[key], parts, budget)
    return " ".join(parts)[:MAX_TEXT]


def view_from_event(event: Dict[str, Any], *, tenant_slug: Optional[str] = None) -> ActionView:
    """Build an :class:`ActionView` from a stored/normalized event dict."""
    payload = event.get("action") if isinstance(event.get("action"), dict) else {}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    if not metadata:
        metadata = payload  # control-plane events keep their fields at top level
    occurred = event.get("occurred_at")
    if isinstance(occurred, str):
        try:
            occurred = datetime.fromisoformat(occurred.replace("Z", "+00:00"))
        except ValueError:
            occurred = None
    return ActionView(
        category=event.get("category"),
        action=event.get("normalized_action") or "",
        resource=event.get("resource") or "",
        text=text_from_metadata(metadata),
        outcome=event.get("outcome"),
        event_id=event.get("event_id"),
        occurred_at=occurred,
        metadata=metadata,
        tenant_slug=tenant_slug,
    )


def _haystack(view: ActionView) -> str:
    joined = " ".join(p for p in (view.text, view.resource) if p)
    return re.sub(r"\s+", " ", joined[:MAX_TEXT]).lower()


# --------------------------------------------------------------------------- #
# Single-action rule definitions
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PatternRule:
    rule_id: str
    risk_level: str
    enforcement_action: str
    inference: str
    patterns: Sequence["re.Pattern[str]"]
    categories: Optional[frozenset] = None   # None = any category
    requires: Optional["re.Pattern[str]"] = None  # extra pre-condition on the text
    confidence: str = "high"
    description: str = ""


def _c(p: str) -> "re.Pattern[str]":
    return re.compile(p, re.IGNORECASE)


_SYSTEM_PATHS = r"(?:/|/\*|~|~/|\$home|/etc|/usr|/var|/boot|/bin|/sbin|/lib|/lib64|/root|/home|/opt|/srv)"
_RM_RECURSIVE = (
    r"\brm\s+(?:-{1,2}[a-z-]{1,24}\s+){0,6}"
)

SQL_CATS = frozenset({"DATABASE", "SHELL", "PROCESS", "MCP", "API"})
SHELL_CATS = frozenset({"SHELL", "PROCESS", "FILESYSTEM", "MCP", "RUNTIME"})

SINGLE_ACTION_RULES: Sequence[PatternRule] = (
    PatternRule(
        "abf.sql.drop_database", "critical", QUARANTINE,
        "Destructive schema operation: the statement removes a whole database or schema.",
        (_c(r"\bdrop\s+(?:database|schema)\b"),), SQL_CATS,
        description="DROP DATABASE / DROP SCHEMA",
    ),
    PatternRule(
        "abf.sql.drop_table", "high", ALERT,
        "Destructive schema operation: the statement removes a table.",
        (_c(r"\bdrop\s+table\b"),), SQL_CATS, description="DROP TABLE",
    ),
    PatternRule(
        "abf.sql.truncate", "high", ALERT,
        "Bulk data destruction: TRUNCATE removes every row of the table.",
        (_c(r"\btruncate\s+(?:table\s+)?[\w.\"`]"),), SQL_CATS, description="TRUNCATE",
    ),
    PatternRule(
        "abf.sql.unscoped_delete", "high", ALERT,
        "Unscoped write: DELETE without a WHERE clause affects every row.",
        (_c(r"\bdelete\s+from\s+[\w.\"`]{1,128}\s*(?:;|$|\)|')"),), SQL_CATS,
        description="DELETE FROM <table> without WHERE",
    ),
    PatternRule(
        "abf.sql.unscoped_update", "high", ALERT,
        "Unscoped write: UPDATE without a WHERE clause affects every row.",
        (_c(r"\bupdate\s+[\w.\"`]{1,128}\s+set\s+[^;]{0,512}?(?:;|$)"),), SQL_CATS,
        requires=None, description="UPDATE <table> SET ... without WHERE",
    ),
    PatternRule(
        "abf.fs.recursive_delete_system_path", "critical", QUARANTINE,
        "Destructive filesystem operation: recursive deletion of the root or a system directory.",
        (_c(_RM_RECURSIVE + r"(?:--no-preserve-root\s+)?" + _SYSTEM_PATHS + r"(?:\s|$|;|&|\|)"),),
        SHELL_CATS, requires=_c(r"\brm\s.*(?:-[a-z]*r|--recursive)"),
        description="rm -r on / or a system path",
    ),
    PatternRule(
        "abf.fs.mkfs", "critical", QUARANTINE,
        "Destructive filesystem operation: formatting a block device.",
        (_c(r"\bmkfs(?:\.[a-z0-9]{1,10})?\s"),), SHELL_CATS, description="mkfs",
    ),
    PatternRule(
        "abf.fs.dd_to_device", "critical", QUARANTINE,
        "Destructive filesystem operation: raw write to a block device.",
        (_c(r"\bdd\s[^;|&]{0,512}\bof=/dev/(?:sd|hd|vd|xvd|nvme|mmcblk|disk|mapper/)"),),
        SHELL_CATS, description="dd of=/dev/<disk>",
    ),
    PatternRule(
        "abf.fs.world_writable_root", "high", ALERT,
        "Permission weakening: recursive world-writable permissions on the root or a system path.",
        (_c(r"\bchmod\s+(?:-[a-z]*r[a-z]*\s+|--recursive\s+)(?:0?777|a\+rwx|ugo\+rwx)\s+" + _SYSTEM_PATHS + r"(?:\s|$)"),),
        SHELL_CATS, description="chmod -R 777 /",
    ),
    PatternRule(
        "abf.container.privileged", "high", REQUIRE_APPROVAL,
        "Container escape risk: privileged container or host namespace / root filesystem sharing.",
        (
            _c(r"--privileged\b"),
            _c(r"(?:-v|--volume|--mount)[= ]\s?(?:type=bind,\s?)?(?:source=)?/(?:etc)?(?::|,)"),
            _c(r"--pid[= ]host\b"),
            _c(r"--net(?:work)?[= ]host\b"),
            _c(r"--cap-add[= ](?:all|sys_admin)\b"),
        ),
        SHELL_CATS | frozenset({"API"}),
        requires=_c(r"\b(?:docker|podman|nerdctl|ctr)\b"),
        description="docker run --privileged / host mounts / host namespaces",
    ),
    PatternRule(
        "abf.container.docker_socket", "high", REQUIRE_APPROVAL,
        "Container escape risk: access to the Docker daemon socket grants root on the host.",
        (_c(r"/var/run/docker\.sock|/run/docker\.sock"),), None,
        description="docker.sock access",
    ),
    PatternRule(
        "abf.security.config_disable", "high", ALERT,
        "Security control tampering: a host firewall or mandatory access control is being disabled.",
        (
            _c(r"\biptables\s+(?:-t\s+\w+\s+)?(?:-F|--flush)\b"),
            _c(r"\bufw\s+disable\b"),
            _c(r"\bsetenforce\s+0\b"),
            _c(r"\bsystemctl\s+(?:stop|disable|mask)\s+(?:firewalld|apparmor|auditd|ufw|nftables)\b"),
            _c(r"\bnft\s+flush\s+ruleset\b"),
        ),
        SHELL_CATS, description="iptables -F, ufw disable, setenforce 0, ...",
    ),
    PatternRule(
        "abf.secret.access", "high", ALERT,
        "Secret access: the action reads a credential store or the process environment.",
        (
            _c(r"/proc/(?:self|\d{1,10}|\*)/environ\b"),
            _c(r"(?:^|[\s;&|])(?:printenv|env)(?:\s*$|\s*[;&|>])"),
            _c(r"\.aws/credentials\b"),
            _c(r"\bid_(?:rsa|ed25519|ecdsa|dsa)\b(?!\.pub)"),
            _c(r"/etc/shadow\b"),
            _c(r"\.kube/config\b"),
            _c(r"\.docker/config\.json\b"),
            _c(r"\.netrc\b"),
        ),
        None, confidence="medium",
        description="/proc/*/environ, printenv, ~/.aws/credentials, id_rsa, /etc/shadow, ...",
    ),
)

_AGENT_REF = re.compile(r"agent://([a-z0-9][a-z0-9_.-]{0,62})/", re.IGNORECASE)


def _excerpt(text: str, m: "re.Match[str]", width: int = 60) -> str:
    start = max(0, m.start() - width // 2)
    return text[start: m.end() + width // 2]


def evaluate_action(
    view: ActionView,
    *,
    overrides: Optional[Dict[str, "RuleOverride"]] = None,
    approved_mcp_tools: Optional[Iterable[str]] = None,
) -> List[RuleHit]:
    """Evaluate every single-action rule against one action. Pure."""
    overrides = overrides or {}
    hay = _haystack(view)
    cat = (view.category or "").upper() or None
    hits: List[RuleHit] = []

    for rule in SINGLE_ACTION_RULES:
        if rule.categories is not None and cat is not None and cat not in rule.categories:
            continue
        if not hay:
            break
        if rule.requires is not None and not rule.requires.search(hay):
            continue
        match = None
        for pat in rule.patterns:
            match = pat.search(hay)
            if match:
                break
        if not match:
            continue
        if rule.rule_id == "abf.sql.unscoped_update" and re.search(r"\bwhere\b", hay[match.start():match.end() + 1]):
            continue
        hits.append(RuleHit(
            rule.rule_id, CATALOG_VERSION, cat, rule.risk_level, rule.enforcement_action,
            {"matched": match.group(0)[:200], "excerpt": _excerpt(hay, match),
             "category": cat, "action": view.action, "resource": view.resource[:256]},
            rule.inference, rule.confidence, view.event_id,
        ))

    # Cross-tenant reference: an agent identity of another tenant in the action.
    if view.tenant_slug and hay:
        for m in _AGENT_REF.finditer(hay):
            if m.group(1).lower() != view.tenant_slug.lower():
                hits.append(RuleHit(
                    "abf.tenant.cross_reference", CATALOG_VERSION, cat, "high", DENY,
                    {"referenced_tenant": m.group(1), "own_tenant": view.tenant_slug,
                     "excerpt": _excerpt(hay, m)},
                    "Tenant isolation: the action references a resource of another tenant.",
                    "high", view.event_id,
                ))
                break

    # Unapproved MCP tool (only when the caller supplies the approved set).
    if cat == "MCP" and approved_mcp_tools is not None:
        tool = view.resource or view.action
        if tool and not any(fnmatch.fnmatchcase(tool, p) for p in approved_mcp_tools):
            hits.append(RuleHit(
                "abf.mcp.unapproved_tool", CATALOG_VERSION, cat, "medium", ALERT,
                {"tool": tool[:256]},
                "The agent used an MCP tool that is not in the approved tool list.",
                "high", view.event_id,
            ))

    # One alert per (rule, recorded event): replayed telemetry never re-alerts.
    hits = [h if h.dedupe_key or not h.source_event_id
            else replace(h, dedupe_key=f"{h.rule_id}:{h.source_event_id}") for h in hits]
    return apply_overrides(hits, overrides)


# --------------------------------------------------------------------------- #
# Window rules
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class WindowRule:
    rule_id: str
    risk_level: str
    enforcement_action: str
    window_seconds: int
    threshold: int
    inference: str
    predicate: Callable[[ActionView], bool]
    categories: Optional[frozenset] = None
    description: str = ""


def _metric(view: ActionView, *keys: str) -> Optional[float]:
    for k in keys:
        v = view.metadata.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


WINDOW_RULES: Sequence[WindowRule] = (
    WindowRule("abf.burst.process", "medium", RATE_LIMIT, 60, 60,
               "Process burst: unusually many process/shell executions in one minute.",
               lambda v: (v.category or "") in ("PROCESS", "SHELL"),
               description=">= 60 PROCESS/SHELL events in 60 s"),
    WindowRule("abf.burst.mcp", "medium", RATE_LIMIT, 60, 60,
               "MCP burst: unusually many MCP tool calls in one minute.",
               lambda v: (v.category or "") == "MCP",
               description=">= 60 MCP events in 60 s"),
    WindowRule("abf.burst.llm", "medium", RATE_LIMIT, 60, 30,
               "LLM burst: unusually many model calls in one minute (possible loop).",
               lambda v: (v.category or "") == "LLM",
               description=">= 30 LLM events in 60 s"),
    WindowRule("abf.failures.repeated", "medium", ALERT, 120, 10,
               "Repeated failures: the agent keeps failing API/MCP/network calls.",
               lambda v: (v.category or "") in ("API", "MCP", "NETWORK", "DATABASE")
               and (v.outcome or "") in ("FAILURE", "DENIED"),
               description=">= 10 failed API/MCP/NETWORK/DATABASE events in 120 s"),
    WindowRule("abf.resource.spike", "medium", ALERT, 300, 3,
               "Resource spike: sustained CPU or memory saturation.",
               lambda v: (v.category or "") == "RESOURCE" and (
                   (_metric(v, "cpu_percent", "cpu") or 0) >= 95
                   or (_metric(v, "memory_percent", "mem_percent", "memory") or 0) >= 95),
               description=">= 3 RESOURCE samples at >= 95 % CPU or memory in 300 s"),
)

REPEAT_WINDOW_SECONDS = 60
REPEAT_THRESHOLD = 10
EXFIL_WINDOW_SECONDS = 300
EXFIL_MIN_BYTES = 1_000_000


def _bucket(now: datetime, window: int) -> int:
    return int(now.timestamp()) // max(1, window)


def evaluate_window(
    views: Sequence[ActionView],
    *,
    now: datetime,
    agent_key: str,
    overrides: Optional[Dict[str, "RuleOverride"]] = None,
    thresholds: Sequence["ThresholdRule"] = (),
) -> List[RuleHit]:
    """Evaluate window rules over the agent's recent events. Pure.

    ``views`` must carry ``occurred_at``; views without a timestamp are ignored.
    Each hit carries a dedupe key bucketed on the rule window so the same burst
    is alerted once per window, however many batches re-trigger it.
    """
    overrides = overrides or {}
    timed = [v for v in views if v.occurred_at is not None]
    hits: List[RuleHit] = []

    def within(seconds: int) -> List[ActionView]:
        lo = now - timedelta(seconds=seconds)
        return [v for v in timed if lo <= v.occurred_at <= now]

    for rule in WINDOW_RULES:
        matching = [v for v in within(rule.window_seconds) if rule.predicate(v)]
        if len(matching) >= rule.threshold:
            hits.append(RuleHit(
                rule.rule_id, CATALOG_VERSION, matching[-1].category, rule.risk_level,
                rule.enforcement_action,
                {"count": len(matching), "threshold": rule.threshold,
                 "window_seconds": rule.window_seconds,
                 "sample_event_ids": [v.event_id for v in matching[-5:] if v.event_id]},
                rule.inference, "high", None,
                f"{rule.rule_id}:{agent_key}:{_bucket(now, rule.window_seconds)}",
            ))

    # Repeated identical command.
    counts: Dict[str, List[ActionView]] = {}
    for v in within(REPEAT_WINDOW_SECONDS):
        key = "|".join((v.category or "", v.action, v.text[:512] or v.resource[:256]))
        if key.strip("|"):
            counts.setdefault(key, []).append(v)
    for key, vs in counts.items():
        if len(vs) >= REPEAT_THRESHOLD:
            hits.append(RuleHit(
                "abf.repeat.identical_action", CATALOG_VERSION, vs[-1].category, "medium",
                RATE_LIMIT,
                {"count": len(vs), "threshold": REPEAT_THRESHOLD,
                 "window_seconds": REPEAT_WINDOW_SECONDS, "action": vs[-1].action,
                 "text": (vs[-1].text or vs[-1].resource)[:200]},
                "Loop suspicion: the same action was repeated many times in one minute.",
                "medium", vs[-1].event_id,
                f"abf.repeat.identical_action:{agent_key}:{_bucket(now, REPEAT_WINDOW_SECONDS)}",
            ))
            break

    hits.extend(_exfiltration(within(EXFIL_WINDOW_SECONDS), agent_key))
    for th in thresholds:
        hit = th.evaluate(timed, now=now, agent_key=agent_key)
        if hit is not None:
            hits.append(hit)
    return apply_overrides(hits, overrides)


def _exfiltration(views: Sequence[ActionView], agent_key: str) -> List[RuleHit]:
    """Sensitive read followed by a large or new outbound transfer."""
    ordered = sorted(views, key=lambda v: v.occurred_at)
    secret_rule = next(r for r in SINGLE_ACTION_RULES if r.rule_id == "abf.secret.access")
    seen_destinations = set()
    secret_read: Optional[ActionView] = None
    for v in ordered:
        cat = v.category or ""
        if secret_read is None:
            hay = _haystack(v)
            if hay and any(p.search(hay) for p in secret_rule.patterns):
                secret_read = v
                continue
            if cat == "NETWORK" and v.resource:
                seen_destinations.add(v.resource.lower())
            continue
        if cat != "NETWORK" or (v.outcome or "SUCCESS") not in ("SUCCESS", "UNKNOWN"):
            continue
        sent = _metric(v, "bytes_out", "bytes_sent", "upload_bytes")
        dest = (v.resource or "").lower()
        new_dest = bool(dest) and dest not in seen_destinations
        large = sent is not None and sent >= EXFIL_MIN_BYTES
        if large or new_dest:
            return [RuleHit(
                "abf.exfiltration.sequence", CATALOG_VERSION, "NETWORK", "critical", QUARANTINE,
                {"sensitive_read_event_id": secret_read.event_id,
                 "sensitive_read_excerpt": (secret_read.text or secret_read.resource)[:200],
                 "transfer_event_id": v.event_id, "destination": dest[:256],
                 "bytes_out": sent, "new_destination": new_dest,
                 "seconds_between": int((v.occurred_at - secret_read.occurred_at).total_seconds())},
                "Possible exfiltration: a secret was read and then data left the runtime "
                "to a new destination or in a large volume.",
                "medium", v.event_id,
                f"abf.exfiltration.sequence:{agent_key}:{secret_read.event_id or ''}",
            )]
    return []


# --------------------------------------------------------------------------- #
# Tenant customisation (persisted in agent_behavior_rules)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RuleOverride:
    rule_key: str
    enabled: bool = True
    risk_level: Optional[str] = None
    enforcement_action: Optional[str] = None
    version: int = 1


def apply_overrides(hits: List[RuleHit], overrides: Dict[str, RuleOverride]) -> List[RuleHit]:
    out = []
    for hit in hits:
        ov = overrides.get(hit.rule_id)
        if ov is None:
            out.append(hit)
            continue
        if not ov.enabled:
            continue
        out.append(replace(
            hit,
            risk_level=ov.risk_level if ov.risk_level in _RISK_RANK else hit.risk_level,
            enforcement_action=(ov.enforcement_action
                                if ov.enforcement_action in ENFORCEMENT_ACTIONS
                                else hit.enforcement_action),
            rule_version=f"{hit.rule_version}+t{ov.version}",
        ))
    return out


@dataclass(frozen=True)
class ThresholdRule:
    """Custom count-in-window rule. The matcher is data, never code."""
    rule_key: str
    threshold: int
    window_seconds: int
    risk_level: str = "medium"
    enforcement_action: str = ALERT
    category: Optional[str] = None
    action_glob: Optional[str] = None
    outcome: Optional[str] = None
    resource_prefix: Optional[str] = None
    version: int = 1
    description: str = ""

    def matches(self, v: ActionView) -> bool:
        if self.category and (v.category or "") != self.category:
            return False
        if self.action_glob and not fnmatch.fnmatchcase(v.action or "", self.action_glob):
            return False
        if self.outcome and (v.outcome or "") != self.outcome:
            return False
        if self.resource_prefix and not (v.resource or "").startswith(self.resource_prefix):
            return False
        return True

    def evaluate(self, views: Sequence[ActionView], *, now: datetime, agent_key: str) -> Optional[RuleHit]:
        lo = now - timedelta(seconds=self.window_seconds)
        matching = [v for v in views if lo <= v.occurred_at <= now and self.matches(v)]
        if len(matching) < self.threshold:
            return None
        rid = f"custom.{self.rule_key}"
        return RuleHit(
            rid, f"custom-v{self.version}", self.category, self.risk_level,
            self.enforcement_action,
            {"count": len(matching), "threshold": self.threshold,
             "window_seconds": self.window_seconds,
             "matcher": {"category": self.category, "action_glob": self.action_glob,
                         "outcome": self.outcome, "resource_prefix": self.resource_prefix}},
            self.description or f"Tenant threshold rule {self.rule_key} exceeded.",
            "high", matching[-1].event_id,
            f"{rid}:{agent_key}:{_bucket(now, self.window_seconds)}",
        )


def catalog() -> List[Dict[str, Any]]:
    """Describe the built-in rules (for the API / UI)."""
    out = [{"rule_id": r.rule_id, "kind": "single_action", "risk_level": r.risk_level,
            "enforcement_action": r.enforcement_action, "description": r.description,
            "categories": sorted(r.categories) if r.categories else None,
            "version": CATALOG_VERSION} for r in SINGLE_ACTION_RULES]
    out.append({"rule_id": "abf.tenant.cross_reference", "kind": "single_action",
                "risk_level": "high", "enforcement_action": DENY,
                "description": "agent://<other-tenant>/ reference", "categories": None,
                "version": CATALOG_VERSION})
    out.append({"rule_id": "abf.mcp.unapproved_tool", "kind": "single_action",
                "risk_level": "medium", "enforcement_action": ALERT,
                "description": "MCP tool outside the approved list", "categories": ["MCP"],
                "version": CATALOG_VERSION})
    out.extend({"rule_id": r.rule_id, "kind": "window", "risk_level": r.risk_level,
                "enforcement_action": r.enforcement_action, "description": r.description,
                "window_seconds": r.window_seconds, "threshold": r.threshold,
                "version": CATALOG_VERSION} for r in WINDOW_RULES)
    out.append({"rule_id": "abf.repeat.identical_action", "kind": "window", "risk_level": "medium",
                "enforcement_action": RATE_LIMIT,
                "description": f">= {REPEAT_THRESHOLD} identical actions in {REPEAT_WINDOW_SECONDS} s",
                "version": CATALOG_VERSION})
    out.append({"rule_id": "abf.exfiltration.sequence", "kind": "window", "risk_level": "critical",
                "enforcement_action": QUARANTINE,
                "description": "secret read then new/large outbound transfer within "
                               f"{EXFIL_WINDOW_SECONDS} s",
                "version": CATALOG_VERSION})
    return out


BUILTIN_RULE_IDS = frozenset(r["rule_id"] for r in catalog())
