"""Infrastructure providers behind the ZAF infra proxy.

Each provider maps a provider-native operation to a canonical ZAF action string
(e.g. ``openstack.server.delete``) so the PDP can evaluate infrastructure
operations independently of whatever an agent reports. A mock provider gives
deterministic, side-effect-free behavior for CI; the real OpenStack provider is
credential-gated and must never perform destructive mutations in automated runs.
"""
