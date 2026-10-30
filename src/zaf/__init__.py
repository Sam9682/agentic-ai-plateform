"""Zero-trust Agent Firewall (ZAF) package.

Governance and enforcement subsystem sitting between agents and the resources
they can reach. Provides the policy decision point, human approval workflow,
governed MCP gateway, infrastructure API proxy, encrypted credential vault and
automated containment response. An agent is never trusted merely because it
runs in an approved container; every protected action is evaluated against
policy, and the firewall fails closed.
"""
