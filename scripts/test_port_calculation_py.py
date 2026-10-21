#!/usr/bin/env python3
"""Tests for calculate_app_ports layout vs the canonical deployApp.sh.

Verifies that the Python port allocator matches the authoritative
``shared/deployApp.sh`` ``PORT_NAMES`` layout, where the main HTTPS web port
sits at the per-application base (offset 0) and HTTP at base+1, followed by
HTTPS/HTTP pairs.

Run:  .venv/bin/python scripts/test_port_calculation_py.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database_postgres import (
    calculate_app_ports,
    APP_PORT_COLUMNS,
    RANGE_START,
    RANGE_RESERVED,
    RANGE_PORTS_PER_APPLICATION,
)

# Canonical deployApp.sh PORT_NAMES order (offset 0 = base). The main web
# interface (HTTPS_PORT) is first. Mapped to the DB column names used by
# calculate_app_ports: HTTPS_PORT -> https_port, HTTP_PORT -> http_port,
# HTTPS_PORTn -> https_port{n+1}, HTTP_PORTn -> http_port{n+1}.
CANONICAL_COLUMN_BY_OFFSET = [
    'https_port', 'http_port',       # base+0, base+1
    'https_port2', 'http_port2',     # base+2, base+3
    'https_port3', 'http_port3',     # base+4, base+5
    'https_port4', 'http_port4',     # base+6, base+7
    'https_port5', 'http_port5',     # base+8, base+9
    'https_port6', 'http_port6',     # base+10, base+11
]

PASS = 0
FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


def ports_dict(user_id, app_id):
    """Return {column_name: port} from calculate_app_ports."""
    values = calculate_app_ports(user_id, app_id)
    return dict(zip(APP_PORT_COLUMNS, values))


def test_reported_case():
    """user=1, identity=2 -> main HTTPS (https_port) == 6124."""
    print("== reported case (user=1, identity=2) ==")
    d = ports_dict(1, 2)
    check(d['https_port'] == 6124, f"https_port main expected 6124 got {d['https_port']}")
    check(d['http_port'] == 6125, f"http_port expected 6125 got {d['http_port']}")
    # The dashboard URL is built from index 1 of the tuple (https_port).
    values = calculate_app_ports(1, 2)
    check(values[1] == 6124, f"tuple[1] (URL port) expected 6124 got {values[1]}")


def test_layout_matches_deployapp():
    """Across many inputs, the layout matches the canonical offset order."""
    print("== canonical layout (interleaved, HTTPS main at base+0) ==")
    import random
    for _ in range(200):
        user_id = random.randint(0, 500)
        identity = random.randint(0, 50)
        base = RANGE_START + user_id * RANGE_RESERVED + identity * RANGE_PORTS_PER_APPLICATION
        d = ports_dict(user_id, identity)
        for offset, col in enumerate(CANONICAL_COLUMN_BY_OFFSET):
            expected = base + offset
            if d[col] != expected:
                check(False, f"u={user_id} id={identity} {col} expected {expected} got {d[col]}")
                break
        else:
            # all 12 offsets matched; also assert they are exactly base..base+11
            vals = sorted(d.values())
            check(vals == list(range(base, base + 12)),
                  f"u={user_id} id={identity} not contiguous: {vals}")


def test_https_is_lower_of_pair():
    """HTTPS main is base+0 (below HTTP), matching deployApp.sh convention."""
    print("== HTTPS main below HTTP in the main pair ==")
    d = ports_dict(3, 7)
    check(d['https_port'] + 1 == d['http_port'],
          f"expected http_port == https_port+1, got https={d['https_port']} http={d['http_port']}")


if __name__ == '__main__':
    test_reported_case()
    test_layout_matches_deployapp()
    test_https_is_lower_of_pair()
    print(f"\nPASSED={PASS} FAILED={FAIL}")
    sys.exit(0 if FAIL == 0 else 1)
