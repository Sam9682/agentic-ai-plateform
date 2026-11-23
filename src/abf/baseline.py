"""ABF behavioural baselines (pure statistics, no I/O).

A baseline is the mean and standard deviation of one metric for one agent over
fixed windows (default 5 minutes), for example "SHELL events per window".

Poisoning resistance (what is and is not handled):

* Windows that contain a DENIED outcome, a governance deny or a quarantine
  event are **excluded**: an incident must not become "normal".
* The share of runtime-reported events is recorded. A baseline built mostly
  from agent-reported telemetry is labelled ``low`` confidence, because an
  agent could inflate its own baseline by reporting many benign events.
* Baseline deviation alone never exceeds ``medium`` risk and never triggers
  containment on its own. The deterministic rules in :mod:`rules` do not
  depend on baselines at all.

Unknown is never zero: with fewer than :data:`MIN_SAMPLES` windows the baseline
is ``insufficient`` and no deviation is reported.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence

from . import rules

DEFAULT_WINDOW_SECONDS = 300
MIN_SAMPLES = 12          # one hour of 5-minute windows
Z_THRESHOLD = 3.0
MIN_ABSOLUTE_EXCESS = 5   # ignore deviations of a handful of events

EXCLUDING_EVENT_TYPES = frozenset({
    "zaf.deny", "task.denied", "agent.quarantined", "abf.enforcement",
})

#: metric name -> predicate over a normalized event dict
METRICS = {
    "events_total": lambda e: True,
    "shell_events": lambda e: (e.get("category") or "") in ("SHELL", "PROCESS"),
    "network_events": lambda e: (e.get("category") or "") == "NETWORK",
    "mcp_events": lambda e: (e.get("category") or "") == "MCP",
    "llm_events": lambda e: (e.get("category") or "") == "LLM",
    "failures": lambda e: (e.get("outcome") or "") in ("FAILURE", "DENIED"),
}


@dataclass
class Baseline:
    metric: str
    window_seconds: int
    mean: Optional[float]
    stddev: Optional[float]
    sample_count: int
    excluded_windows: int
    runtime_reported_ratio: Optional[float]
    confidence: str  # 'insufficient' | 'low' | 'medium' | 'high'

    def as_dict(self) -> Dict[str, Any]:
        return {
            "metric": self.metric, "window_seconds": self.window_seconds,
            "mean": self.mean, "stddev": self.stddev, "sample_count": self.sample_count,
            "excluded_windows": self.excluded_windows,
            "runtime_reported_ratio": self.runtime_reported_ratio,
            "confidence": self.confidence,
        }


def _ts(e: Dict[str, Any]) -> Optional[float]:
    v = e.get("occurred_at")
    if isinstance(v, datetime):
        return v.timestamp()
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _weight(e: Dict[str, Any]) -> int:
    """Rows may be pre-aggregated (``_count``) to avoid loading every event."""
    try:
        return max(0, int(e.get("_count", 1)))
    except (TypeError, ValueError):
        return 1


def _is_excluding(e: Dict[str, Any]) -> bool:
    return (e.get("event_type") in EXCLUDING_EVENT_TYPES
            or (e.get("outcome") or "") == "DENIED"
            or e.get("decision") in ("DENY", "QUARANTINE"))


def bucketize(events: Iterable[Dict[str, Any]], window_seconds: int,
              *, start: float, end: float) -> List[List[Dict[str, Any]]]:
    """Split events into consecutive windows over [start, end). Empty windows count."""
    n = max(0, int((end - start) // window_seconds))
    buckets: List[List[Dict[str, Any]]] = [[] for _ in range(n)]
    for e in events:
        t = _ts(e)
        if t is None or t < start or t >= start + n * window_seconds:
            continue
        buckets[int((t - start) // window_seconds)].append(e)
    return buckets


def compute(metric: str, events: Sequence[Dict[str, Any]], *, start: datetime,
            end: datetime, window_seconds: int = DEFAULT_WINDOW_SECONDS) -> Baseline:
    """Compute the baseline of ``metric`` over [start, end)."""
    pred = METRICS[metric]
    buckets = bucketize(events, window_seconds, start=start.timestamp(), end=end.timestamp())
    samples: List[int] = []
    excluded = 0
    total = runtime = 0
    for b in buckets:
        if any(_is_excluding(e) for e in b):
            excluded += 1
            continue
        hits = [e for e in b if pred(e)]
        n = sum(_weight(e) for e in hits)
        samples.append(n)
        total += n
        runtime += sum(_weight(e) for e in hits if e.get("ingest_source") == "runtime_reported")
    ratio = (runtime / total) if total else None
    if len(samples) < MIN_SAMPLES:
        return Baseline(metric, window_seconds, None, None, len(samples), excluded, ratio,
                        "insufficient")
    mean = sum(samples) / len(samples)
    var = sum((s - mean) ** 2 for s in samples) / (len(samples) - 1)
    std = math.sqrt(var)
    if ratio is not None and ratio > 0.9:
        confidence = "low"
    elif len(samples) >= MIN_SAMPLES * 6:
        confidence = "high"
    else:
        confidence = "medium"
    return Baseline(metric, window_seconds, round(mean, 4), round(std, 4), len(samples),
                    excluded, None if ratio is None else round(ratio, 4), confidence)


def deviation(metric: str, observed: int, baseline: Baseline) -> Optional[rules.RuleHit]:
    """Return a ``medium``-at-most ALERT hit when ``observed`` deviates, else None."""
    if baseline.confidence == "insufficient" or baseline.mean is None:
        return None
    std = max(baseline.stddev or 0.0, 1.0)  # floor: avoid infinite z on flat baselines
    z = (observed - baseline.mean) / std
    if z < Z_THRESHOLD or (observed - baseline.mean) < MIN_ABSOLUTE_EXCESS:
        return None
    risk = "low" if baseline.confidence == "low" else "medium"
    return rules.RuleHit(
        f"abf.baseline.{metric}", rules.CATALOG_VERSION, None, risk, rules.ALERT,
        {"metric": metric, "observed": observed, "baseline_mean": baseline.mean,
         "baseline_stddev": baseline.stddev, "z_score": round(z, 2),
         "window_seconds": baseline.window_seconds, "sample_count": baseline.sample_count,
         "baseline_confidence": baseline.confidence},
        f"Behavioural deviation: {metric} is {round(z, 1)} standard deviations above "
        "this agent's baseline.",
        baseline.confidence if baseline.confidence in ("low", "medium", "high") else "low",
    )
