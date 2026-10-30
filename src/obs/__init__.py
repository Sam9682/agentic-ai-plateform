"""Observability subsystem for ARO/ZAF.

Rule-based anomaly detection and explainable risk scoring over the agent event
and runtime-observation streams. Scoring is deterministic and auditable — an LLM
is never the sole mechanism for a security decision (SRS §5.5).
"""
