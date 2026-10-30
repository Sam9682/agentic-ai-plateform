"""Runtime observability scanner (Task 15).

Wires the already-present-but-uncalled ``runtime_monitor_repository`` writers
into a periodic scan: for each managed server it collects containers (SSH),
classifies them, upserts the inventory + an observation, marks disappeared
containers stopped, and records a scan-run audit. It also emits higher-level
agent-activity events into the unified stream.

Where a runtime does not expose a particular signal, the scanner records the
limitation (an event with ``action.limitation``) rather than fabricating data
(SRS §5.3).

Collector, classifier and repository are injectable so the scan logic is tested
without SSH or a live DB. The pure per-server reconciliation lives in
:func:`scan_server` for property testing.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import event_service as es


def scan_server(
    server: Dict[str, Any],
    collect: Callable[[Dict[str, Any]], Tuple[List[Dict[str, Any]], Optional[str]]],
    classify: Callable[[Dict[str, Any]], Dict[str, Any]],
    repo,
    *,
    tenant_id: Optional[int] = None,
    events_repo=None,
) -> Dict[str, Any]:
    """Scan one server: persist inventory + observations; return a summary.

    Returns ``{server_id, containers_seen, error, limitations}``. On an
    unreachable server (collector returns an error) the scan-run records the
    error and no containers are persisted.
    """
    server_id = server.get("id")
    scan_run_id = repo.start_scan_run(server_id)
    observations, error = collect(server)
    if error:
        repo.finish_scan_run(scan_run_id, 0, error=error)
        return {"server_id": server_id, "containers_seen": 0, "error": error, "limitations": []}

    seen_ids: List[str] = []
    limitations: List[str] = []
    for obs in observations or []:
        result = classify(obs)
        pk = repo.upsert_container(
            server_id=server_id,
            container_id=obs.get("container_id"),
            name=obs.get("name"),
            image=obs.get("image"),
            runtime=obs.get("runtime"),
            state=obs.get("state", "unknown"),
            is_platform_managed=bool(obs.get("is_platform_managed", False)),
            classification=result.get("classification", "unclassified"),
            confidence_score=float(result.get("score", 0.0)),
            classification_evidence=result.get("evidence", []),
            labels=obs.get("labels", {}),
        )
        # Record an observation. Missing metrics are stored as None (not faked),
        # and the limitation is noted for observability.
        if obs.get("cpu_percent") is None and obs.get("memory_bytes") is None:
            limitations.append(f"{obs.get('container_id')}: no resource metrics available")
        repo.record_observation(
            container_pk=pk,
            cpu_percent=obs.get("cpu_percent"),
            memory_bytes=obs.get("memory_bytes"),
            pids=obs.get("pids"),
            process_summary=obs.get("process_summary", []),
            network_summary=obs.get("network_summary", {}),
            state=obs.get("state"),
        )
        seen_ids.append(obs.get("container_id"))

    repo.mark_containers_stopped(server_id, seen_ids)
    repo.finish_scan_run(scan_run_id, len(seen_ids))

    if tenant_id is not None and events_repo is not None and limitations:
        for lim in limitations:
            es.emit(events_repo, tenant_id, "observability.limitation", "runtime-scanner",
                    action={"limitation": lim}, severity="LOW")

    return {
        "server_id": server_id,
        "containers_seen": len(seen_ids),
        "error": None,
        "limitations": limitations,
    }


def record_agent_activity(
    events_repo,
    tenant_id: int,
    agent_identity: str,
    event_type: str,
    action: Optional[Dict[str, Any]] = None,
    *,
    severity: str = "INFO",
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Emit a higher-level agent-activity event (started, tool invoked, etc.)."""
    return es.emit(
        events_repo, tenant_id, event_type, "agent-activity",
        agent_id=agent_identity, action=action or {}, severity=severity,
        correlation_id=correlation_id,
    )


class RuntimeScanner:
    """Periodic scanner over the managed servers (serverless-worker style)."""

    def __init__(
        self,
        *,
        servers_loader: Callable[[], List[Dict[str, Any]]],
        collect: Callable[[Dict[str, Any]], Tuple[List[Dict[str, Any]], Optional[str]]],
        classify: Callable[[Dict[str, Any]], Dict[str, Any]],
        repo,
        interval: float = 30.0,
    ):
        self._servers_loader = servers_loader
        self._collect = collect
        self._classify = classify
        self._repo = repo
        self._interval = interval
        self.running = False

    def scan_once(self) -> List[Dict[str, Any]]:
        return [
            scan_server(s, self._collect, self._classify, self._repo)
            for s in (self._servers_loader() or [])
        ]

    def run(self) -> None:  # pragma: no cover - long-running loop
        self.running = True
        while self.running:
            try:
                self.scan_once()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(self._interval)

    def stop(self) -> None:  # pragma: no cover
        self.running = False
