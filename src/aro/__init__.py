"""Agent Runtime Orchestrator (ARO) package.

Control-plane subsystem that manages the lifecycle of heterogeneous AI agent
runtimes (Kiro via ACP, SHAI via CLI and HTTP/SSE) on managed servers, drives
their task execution through a durable queue, and feeds the unified event and
observability stream. Governance/enforcement lives in the sibling ``src.zaf``
package; shared event schema is defined here in :mod:`src.aro.event_service`.
"""
