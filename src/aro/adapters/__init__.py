"""Runtime adapters for the Agent Runtime Orchestrator.

Each supported agent runtime (Kiro via ACP, SHAI via CLI and HTTP/SSE, generic
CLI/MCP) implements the common :class:`~src.aro.adapters.base.AgentRuntimeAdapter`
interface. ACP, CLI and HTTP/SSE are distinct protocols, so each has its own
adapter — an MCP connection alone does not provide visibility into every action
an agent performs. Adapters declare their real capabilities via
:meth:`get_capabilities`; the platform documents unsupported capabilities rather
than pretending every runtime is identical.
"""
