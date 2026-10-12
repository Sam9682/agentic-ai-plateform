"""Explainable heuristic classifier for agentic workloads.

:func:`classify` takes a normalized container observation (the dict produced by
``runtime_collector.normalize_container``) and returns a classification, a
confidence score in ``[0.0, 1.0]``, and a list of human-readable evidence lines
that justify the score.

The classifier is intentionally pure (no I/O, no ML): every signal is a
weighted, named rule so an operator can see exactly why a container was flagged.
A pluggable ML scorer can be layered on later without changing this contract.
"""

import re
from typing import Any, Dict, List, Tuple

# Classification labels (match the DB CHECK constraint).
PROBABLE_AGENT = "probable_agent"
UNCLASSIFIED = "unclassified"

# Score at or above this threshold -> probable_agent.
AGENT_THRESHOLD = 0.5

# Image/name tokens that strongly suggest an agent runtime.
_AGENT_NAME_TOKENS = (
    "agent", "kiro", "shai", "autogpt", "autogen", "crewai",
    "langchain", "llamaindex", "copilot", "devin", "aider",
)

# Known LLM / inference API hosts an agent is likely to call.
_LLM_API_HOSTS = (
    "api.openai.com", "api.anthropic.com", "generativelanguage.googleapis.com",
    "api.mistral.ai", "api.cohere.ai", "api.groq.com", "api.together.xyz",
    "bedrock", "openai.azure.com", "api.perplexity.ai",
)

# Env var names that hint at LLM/agent configuration.
_LLM_ENV_HINTS = (
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY",
    "MISTRAL_API_KEY", "COHERE_API_KEY", "GROQ_API_KEY", "HUGGINGFACE",
    "LLM_", "AGENT_", "MODEL_NAME", "OLLAMA_",
)

# Python/node LLM client modules commonly seen in agent process args.
_LLM_PROCESS_HINTS = (
    "openai", "anthropic", "langchain", "llama_index", "llamaindex",
    "autogen", "crewai", "ollama", "transformers", "vllm", "litellm",
)

# Weights per signal. Scores are summed then clamped to [0, 1].
_W_IMAGE_NAME = 0.35
_W_CONTAINER_NAME = 0.25
_W_ENV_HINT = 0.25
_W_PROCESS_HINT = 0.30
_W_NETWORK_LLM = 0.35
_W_LONG_LIVED_LOOP = 0.15


def classify(observation: Dict[str, Any]) -> Dict[str, Any]:
    """Classify a container observation as a probable agent or unclassified.

    Args:
        observation: Normalized container dict (see runtime_collector).

    Returns:
        ``{"classification": str, "score": float, "evidence": [str, ...]}``.
        ``score`` is clamped to [0.0, 1.0]. ``evidence`` is empty when no signal
        fired.
    """
    score = 0.0
    evidence: List[str] = []

    image = (observation.get("image") or "").lower()
    name = (observation.get("name") or "").lower()
    env = observation.get("env") or {}
    processes = observation.get("processes") or []
    network = observation.get("network_summary") or {}
    status = (observation.get("status") or "").lower()

    # 1. Image name tokens.
    token = _first_token(image, _AGENT_NAME_TOKENS)
    if token:
        score += _W_IMAGE_NAME
        evidence.append(f"image '{observation.get('image')}' contains agent token '{token}'")

    # 2. Container name tokens.
    token = _first_token(name, _AGENT_NAME_TOKENS)
    if token:
        score += _W_CONTAINER_NAME
        evidence.append(f"container name '{observation.get('name')}' contains agent token '{token}'")

    # 3. Env var hints.
    env_hits = _env_hits(env)
    if env_hits:
        score += _W_ENV_HINT
        shown = ", ".join(env_hits[:3])
        evidence.append(f"environment hints at LLM/agent config: {shown}")

    # 4. In-container process hints.
    proc_hits = _process_hits(processes)
    if proc_hits:
        score += _W_PROCESS_HINT
        shown = ", ".join(sorted(proc_hits)[:3])
        evidence.append(f"process args reference LLM client libs: {shown}")

    # 5. Outbound connections to known LLM API hosts.
    net_hits = _network_hits(network)
    if net_hits:
        score += _W_NETWORK_LLM
        shown = ", ".join(net_hits[:3])
        evidence.append(f"outbound connections to LLM API hosts: {shown}")

    # 6. Long-lived looping behavior (weak signal; only meaningful with others).
    if _looks_long_lived(status) and (proc_hits or env_hits or token):
        score += _W_LONG_LIVED_LOOP
        evidence.append("long-lived container with agent-like workload characteristics")

    score = max(0.0, min(1.0, round(score, 4)))
    classification = PROBABLE_AGENT if score >= AGENT_THRESHOLD else UNCLASSIFIED
    return {"classification": classification, "score": score, "evidence": evidence}


def _first_token(haystack: str, tokens: Tuple[str, ...]):
    """Return the first token found as a word-ish substring, or None."""
    for t in tokens:
        if re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", haystack):
            return t
    # Fall back to plain substring for compound image tags like 'kiro-runtime'.
    for t in tokens:
        if t in haystack:
            return t
    return None


def _env_hits(env: Dict[str, Any]) -> List[str]:
    """Return env var names that match LLM/agent hints."""
    hits = []
    for key in env.keys():
        up = key.upper()
        for hint in _LLM_ENV_HINTS:
            if up == hint or up.startswith(hint) or hint in up:
                hits.append(key)
                break
    return hits


def _process_hits(processes: List[Dict[str, str]]) -> List[str]:
    """Return LLM client lib tokens referenced in process args."""
    hits = set()
    for proc in processes:
        args = (proc.get("args") or proc.get("comm") or "").lower()
        for hint in _LLM_PROCESS_HINTS:
            if hint in args:
                hits.add(hint)
    return list(hits)


def _network_hits(network: Dict[str, Any]) -> List[str]:
    """Return known LLM API hosts found in a network summary.

    Accepts either ``{"egress": [host, ...]}`` or a flat list under common keys.
    """
    hosts: List[str] = []
    if isinstance(network, dict):
        for key in ("egress", "connections", "hosts"):
            value = network.get(key)
            if isinstance(value, list):
                hosts.extend(str(h) for h in value)
    elif isinstance(network, list):
        hosts = [str(h) for h in network]

    hits = []
    for host in hosts:
        low = host.lower()
        for known in _LLM_API_HOSTS:
            if known in low:
                hits.append(host)
                break
    return hits


def _looks_long_lived(status: str) -> bool:
    """Heuristic: docker 'Up <n> hours/days' suggests a long-lived process."""
    if not status.startswith("up"):
        return False
    return any(unit in status for unit in ("hour", "day", "week", "month"))
