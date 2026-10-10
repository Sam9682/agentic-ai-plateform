#!/usr/bin/env python3
"""
Backfill/correct the per-application ports stored in ``user_applications``.

Historically ``calculate_app_ports`` laid the 12 per-application ports out with
HTTP at the base offset and HTTPS at base+1, and it always used the platform
``applications.id`` as the identity number. The canonical deployment script
(``agentic-ai-plateform--skills/deployApp.sh``) instead puts the **main HTTPS** port at the base
offset (base+0) and derives the per-application base from each app's
``conf/deploy.ini`` ``APPLICATION_IDENTITY_NUMBER``.

The mismatch meant the dashboard showed a port that was both one above the real
HTTPS port and, when the deployed identity number differed from
``applications.id``, in the wrong per-application block entirely (e.g. the
dashboard link read ``:6137`` while the container actually served ``:6124``).

This script recomputes every ``user_applications`` row with the corrected
``calculate_app_ports`` and the authoritative identity number (the deployed
app's ``conf/deploy.ini`` value when present, otherwise ``applications.id``),
rewrites the 12 port columns, and rebuilds the stored URL while preserving its
host. Run with ``--dry-run`` to preview changes without writing.
"""

import argparse
import os
import sys
from urllib.parse import urlparse

# Allow running from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database_postgres import (  # noqa: E402
    db_manager,
    calculate_app_ports,
    resolve_app_identity_number,
    APP_PORT_COLUMNS,
    APP_PORT_UPDATE_SQL,
    DOMAIN,
)

# Index of ``https_port`` (the main web port) within APP_PORT_COLUMNS and the
# tuple returned by calculate_app_ports().
HTTPS_MAIN_INDEX = APP_PORT_COLUMNS.index('https_port')


def _host_from_url(url):
    """Return the hostname from a stored URL, defaulting to DOMAIN."""
    if not url:
        return DOMAIN
    raw = url if '://' in url else f'https://{url}'
    try:
        host = urlparse(raw).hostname
    except ValueError:
        host = None
    return host or DOMAIN


def fix_ports(dry_run=False):
    rows = db_manager.execute_query(
        """
        SELECT ua.id, ua.user_id, ua.application_id, ua.url,
               ua.http_port, ua.https_port,
               u.username, a.name
        FROM user_applications ua
        JOIN users u ON ua.user_id = u.id
        JOIN applications a ON ua.application_id = a.id
        ORDER BY ua.id
        """,
        fetch_all=True,
    )

    if not rows:
        print('No user_applications rows found.')
        return 0

    print(f"{'ID':<5} {'User':<12} {'App':<28} {'identity':<9} "
          f"{'old https':<10} {'new https':<10} {'status'}")
    print('-' * 90)

    changed = 0
    for row in rows:
        ua_id, user_id, app_id, url, old_http, old_https, username, app_name = row

        identity = resolve_app_identity_number(username, app_name, app_id)
        app_ports = calculate_app_ports(user_id, identity)
        new_https = app_ports[HTTPS_MAIN_INDEX]

        host = _host_from_url(url)
        new_url = f'https://{host}:{new_https}'

        needs_update = (old_https != new_https) or (url != new_url)
        status = 'update' if needs_update else 'ok'
        src = 'ini' if identity != app_id else 'app_id'
        print(f"{ua_id:<5} {username:<12} {app_name[:28]:<28} "
              f"{identity}({src})".ljust(9 + 7) +
              f"{str(old_https):<10} {str(new_https):<10} {status}")

        if needs_update and not dry_run:
            db_manager.execute_query(
                f"UPDATE user_applications SET {APP_PORT_UPDATE_SQL}, url = %s WHERE id = %s",
                (*app_ports, new_url, ua_id),
            )
            changed += 1
        elif needs_update:
            changed += 1

    print('-' * 90)
    if dry_run:
        print(f"[DRY-RUN] {changed} row(s) would be updated.")
    else:
        print(f"Updated {changed} row(s).")
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Preview the changes without writing to the database.',
    )
    args = parser.parse_args()
    try:
        fix_ports(dry_run=args.dry_run)
    except Exception as e:  # pragma: no cover - operational safety
        print(f'Error: {e}')
        sys.exit(1)


if __name__ == '__main__':
    main()