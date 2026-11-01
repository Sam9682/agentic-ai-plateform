"""Credential-free Gitea/URL utilities.

This module hosts the Gitea URL helpers that must never embed credentials.
``redact_credential_url`` is a pure helper applied on read so historical
stored URLs that still contain an embedded ``user:pass@`` authority are
masked before they are returned or displayed.

Both ``src/routes/api_routes.py`` and ``src/routes/orchestrator_routes.py``
import from here (e.g. ``from ..gitea_auth import redact_credential_url``).
"""

import os
from urllib.parse import urlsplit, urlunsplit

from .zaf.credential_vault import SecretWrapper

__all__ = [
    "redact_credential_url",
    "gitea_clone_url",
    "gitea_credentials",
    "GiteaAuthError",
]

_REDACTED_USERINFO = "***"

# Environment variable holding the Gitea access token / credential.
_GITEA_TOKEN_ENV = "GITEA_TOKEN"


class GiteaAuthError(Exception):
    """Raised when no Gitea credential can be sourced.

    This is the fail-closed signal for :func:`gitea_credentials`: rather than
    falling back to a static literal credential, the caller is forced to
    configure a real secret (env/secret store or a short-lived token).
    """


def redact_credential_url(value):
    """Mask any ``userinfo`` component in a URL.

    ``scheme://user:pass@host/path?q#f`` becomes ``scheme://***@host/path?q#f``,
    leaving the remaining URL structure (scheme, host, port, path, query,
    fragment) intact.

    This is a pure function: it does not mutate its argument and has no side
    effects.

    - A URL with no ``userinfo`` is returned unchanged.
    - Non-string input (e.g. ``None``) is returned unchanged.
    - A value that does not parse as a URL with a network authority is
      returned unchanged.
    """
    if not isinstance(value, str):
        return value

    try:
        parts = urlsplit(value)
    except ValueError:
        return value

    # No network location (authority) means there is no userinfo to mask.
    if not parts.netloc:
        return value

    # ``@`` separates userinfo from host[:port]; absence means no credential.
    if "@" not in parts.netloc:
        return value

    host_part = parts.netloc.rsplit("@", 1)[1]
    redacted_netloc = f"{_REDACTED_USERINFO}@{host_part}"

    return urlunsplit(
        (parts.scheme, redacted_netloc, parts.path, parts.query, parts.fragment)
    )


def gitea_clone_url(host, path):
    """Build a credential-free Gitea URL: ``http://<host>/<path>``.

    The returned URL never carries a ``user:pass@`` authority (R3.2).
    Authentication is supplied out-of-band to git (credential helper,
    ``GIT_ASKPASS``, or an ``Authorization: token ...`` header) so the URL
    embedded anywhere — including values persisted to
    ``deployments.gitea_branch_url`` / ``modification_history`` or streamed in a
    Server-Sent Events ``data:`` chunk — is always clean.

    - ``host`` is the host[:port] authority with no userinfo. Any accidental
      ``user:pass@`` prefix is stripped so the result is guaranteed clean.
    - ``path`` is the repository path; a single leading ``/`` is normalized so
      the join never produces a double slash.
    """
    host = "" if host is None else str(host)
    path = "" if path is None else str(path)

    # Strip any scheme a caller may have included in ``host``.
    if "://" in host:
        host = host.split("://", 1)[1]

    # Defensively strip any embedded ``user:pass@`` authority from the host so
    # a credential can never sneak into the constructed URL.
    if "@" in host:
        host = host.rsplit("@", 1)[1]

    host = host.strip("/")
    path = path.lstrip("/")

    return f"http://{host}/{path}"


def gitea_credentials():
    """Return Gitea auth from env/secret store, failing closed.

    The credential is read from the ``GITEA_TOKEN`` environment variable (or,
    in a deployment, an injected secret) and returned inside a
    :class:`SecretWrapper` so it cannot leak through logging, f-strings, or
    serialization (R3.1, R4.5, R12.1).

    This function never returns a static literal credential. When no credential
    is configured it raises :class:`GiteaAuthError` (fail closed) rather than
    handing back a default.
    """
    token = os.environ.get(_GITEA_TOKEN_ENV)
    if token:
        return SecretWrapper(token)

    # No credential configured: fail closed. Do NOT fall back to any static
    # literal — the caller must configure a real secret or short-lived token.
    raise GiteaAuthError("no Gitea credential configured")
