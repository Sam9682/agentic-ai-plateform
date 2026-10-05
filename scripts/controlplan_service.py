#!/usr/bin/env python3
"""Systemd unit rendering for the control-plan service.

Single source of truth for the ``swautomorph-controlplan.service`` content so
the install command (``controller_cli.py install-as-systemctl-service``)
and the committed fallback artifact never diverge. The install user and all
``/home/<user>/<folder>`` paths are derived from ``LINUX_USER_INSTALLATION``
and ``PLTF_FOLDER`` in ``conf/deploy.ini``; the canonical fallbacks (``psmc``
and ``agentic-ai-plateform``) match config_postgres.py, gunicorn.conf.py,
deployControlPlan.sh and the shell scripts.

Dependency-free (stdlib only) so it is trivially importable and testable.

Regenerate the committed artifact with:

    python3 scripts/controlplan_service.py
"""

import os

# Canonical fallbacks, identical to every other entry point.
DEFAULT_LINUX_USER = 'psmc'
DEFAULT_PLTF_FOLDER = 'agentic-ai-plateform'

SERVICE_FILENAME = 'swautomorph-controlplan.service'


def _read_ini_value(config_path, key, default):
    try:
        with open(config_path, 'r') as f:
            for line in f:
                if line.strip().startswith(key):
                    value = line.split('=', 1)[1].strip().strip("'\"")
                    if value:
                        return value
    except Exception:
        pass
    return default


def resolve_service_identity(config_path=None):
    """Return (linux_user, pltf_folder) resolved from deploy.ini with the
    canonical fallbacks."""
    if config_path is None:
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(repo_root, 'conf', 'deploy.ini')
    linux_user = _read_ini_value(config_path, 'LINUX_USER_INSTALLATION', DEFAULT_LINUX_USER)
    pltf_folder = _read_ini_value(config_path, 'PLTF_FOLDER', DEFAULT_PLTF_FOLDER)
    return linux_user, pltf_folder


def render_controlplan_unit(linux_user, pltf_folder):
    """Render the systemd unit content for the given install identity."""
    base_path = f'/home/{linux_user}/{pltf_folder}'
    return f"""[Unit]
Description=SWAutomorph Control Plan
After=network.target

[Service]
Type=forking
# GENERATED ARTIFACT - regenerate with 'python3 scripts/controlplan_service.py'
# or at install time via 'controller_cli.py install-as-systemctl-service'.
# User= and the /home/<user>/<folder> paths are derived from
# LINUX_USER_INSTALLATION and PLTF_FOLDER in conf/deploy.ini.
ExecStart={base_path}/scripts/start_swautomorph_controlplan.sh
ExecStop={base_path}/scripts/stop_swautomorph_controlplan.sh
WorkingDirectory={base_path}
User={linux_user}

[Install]
WantedBy=multi-user.target
"""


def write_committed_artifact():
    """Regenerate scripts/swautomorph-controlplan.service from deploy.ini."""
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    linux_user, pltf_folder = resolve_service_identity()
    content = render_controlplan_unit(linux_user, pltf_folder)
    out_path = os.path.join(scripts_dir, SERVICE_FILENAME)
    with open(out_path, 'w') as f:
        f.write(content)
    return out_path, linux_user, pltf_folder


if __name__ == '__main__':
    path, user, folder = write_committed_artifact()
    print(f'Regenerated {path} (User={user}, PLTF_FOLDER={folder})')
