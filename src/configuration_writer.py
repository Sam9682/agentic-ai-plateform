"""Configuration_Writer for the Onboarding Setup Wizard (Requirement 6).

Persists validated wizard output to ``conf/deploy.ini`` safely:

* A timestamped backup of the existing file is taken before any write
  (Req 6.2). If the backup fails the write is aborted and the file is left
  byte-identical to its pre-write content (Req 6.3).
* Managed keys are merged over a preserved copy of the unmanaged keys, so
  keys not owned by the wizard keep their original value (Req 6.1).
* The new content is written atomically: a temp file in ``conf/`` is
  flushed and ``fsync``-ed, then ``os.replace``-d onto ``deploy.ini`` so the
  rename is atomic on POSIX. This mirrors the temp-file-then-rename pattern
  in ``src/nginx_manager.write_nginx_config`` (Req 6.1).
* If the write fails after a backup was created, the previous configuration
  is restored from the backup and a write failure is reported (Req 6.4).
* ``deploy.ini`` and any credential file are ``chmod 0600`` so only the
  service account can read/write them (Req 6.6).
* The Admin_User password is stored via ``werkzeug.security.generate_password_hash``
  into the ``users`` table and is never written in plaintext to any file
  (Req 6.5).

The ``deploy.ini`` format is a flat ``KEY=VALUE`` file (no INI sections),
interleaved with ``#`` comment lines and blank lines. The writer preserves
that layout: comments, blank lines, and unmanaged keys are kept verbatim and
in place; managed keys are updated in place, and any managed key that is not
already present is appended.
"""

import logging
import os
import shutil
import tempfile
from datetime import datetime

from werkzeug.security import generate_password_hash

from .database_postgres import db_manager

logger = logging.getLogger(__name__)

# Wizard-managed keys in conf/deploy.ini. Every other key found in an existing
# file is treated as unmanaged and preserved verbatim (Req 6.1).
MANAGED_KEYS = (
    "DOMAIN",
    "ADMIN_EMAIL",
    "GITEA_VERSION",
    "SSL_MODE",
)

# Keys that map to wizard input names -> deploy.ini keys. Wizard values are
# passed in under human-friendly names; this maps them onto the file keys.
_VALUE_KEY_ALIASES = {
    "domain": "DOMAIN",
    "email": "ADMIN_EMAIL",
    "admin_email": "ADMIN_EMAIL",
    "gitea_version": "GITEA_VERSION",
    "ssl_mode": "SSL_MODE",
}

# Owner read/write only (Req 6.6).
_OWNER_ONLY_MODE = 0o600


class WriteResult:
    """Outcome of a ConfigurationWriter.write call.

    ``failure_type`` is ``None`` on success, ``"backup"`` when the pre-write
    backup could not be created (Req 6.3), or ``"write"`` when writing the
    new configuration failed after a backup existed (Req 6.4).
    """

    def __init__(self, success, failure_type=None, message="", backup_path=None):
        self.success = success
        self.failure_type = failure_type  # None | "backup" | "write"
        self.message = message
        self.backup_path = backup_path

    def __repr__(self):
        return (
            f"WriteResult(success={self.success!r}, "
            f"failure_type={self.failure_type!r}, message={self.message!r}, "
            f"backup_path={self.backup_path!r})"
        )


class ConfigurationWriter:
    """Atomic, backup-protected writer for ``conf/deploy.ini`` (Req 6)."""

    def __init__(self, config_path=None, db=None):
        if config_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_path = os.path.join(base_dir, "conf", "deploy.ini")
        self.config_path = config_path
        self.conf_dir = os.path.dirname(self.config_path)
        self._db = db if db is not None else db_manager

    # -- public API ---------------------------------------------------------

    def write(self, values):
        """Persist wizard-managed ``values`` to ``conf/deploy.ini``.

        ``values`` is a flat dict of wizard inputs. Keys map onto managed
        deploy.ini keys via ``_VALUE_KEY_ALIASES`` (or are used verbatim if
        they already match a managed key). The special key
        ``admin_password`` (with optional ``admin_username``/``admin_email``)
        is stored as a password hash in the ``users`` table and is never
        written to a file (Req 6.5).

        Returns a :class:`WriteResult`.
        """
        managed = self._resolve_managed_values(values)

        existing_content = None
        backup_path = None
        file_exists = os.path.exists(self.config_path)

        # Step 1: back up an existing file before touching it (Req 6.2, 6.3).
        if file_exists:
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    existing_content = f.read()
                backup_path = self._backup_path()
                shutil.copy2(self.config_path, backup_path)
                # Confirm the backup content matches the pre-write content.
                with open(backup_path, "r", encoding="utf-8") as f:
                    if f.read() != existing_content:
                        raise IOError("backup content mismatch")
            except Exception as e:  # backup failed -> abort, leave file intact
                logger.error("Configuration backup failed: %s", e)
                # Best-effort cleanup of a partial backup so the file dir is clean.
                if backup_path and os.path.exists(backup_path):
                    try:
                        os.remove(backup_path)
                    except OSError:
                        pass
                return WriteResult(
                    success=False,
                    failure_type="backup",
                    message=f"Failed to create configuration backup: {e}",
                )

        # Step 2: merge managed keys over the preserved unmanaged content (Req 6.1).
        new_content = self._merge(existing_content, managed)

        # Step 3: atomic write (temp file -> fsync -> os.replace) (Req 6.1).
        try:
            self._atomic_write(new_content)
            os.chmod(self.config_path, _OWNER_ONLY_MODE)  # Req 6.6
        except Exception as e:
            logger.error("Configuration write failed: %s", e)
            # Step 4: restore from backup if we had one (Req 6.4).
            if backup_path is not None:
                try:
                    shutil.copy2(backup_path, self.config_path)
                    os.chmod(self.config_path, _OWNER_ONLY_MODE)
                except Exception as restore_err:
                    logger.error(
                        "Failed to restore configuration from backup %s: %s",
                        backup_path,
                        restore_err,
                    )
            elif os.path.exists(self.config_path):
                # No prior file existed; remove any partial artifact we created.
                try:
                    os.remove(self.config_path)
                except OSError:
                    pass
            return WriteResult(
                success=False,
                failure_type="write",
                message=f"Failed to write configuration: {e}",
                backup_path=backup_path,
            )

        # Step 5: store the Admin_User password as a hash, never plaintext (Req 6.5).
        if values.get("admin_password"):
            try:
                self._store_admin_user(values)
            except Exception as e:
                logger.error("Failed to store Admin_User credentials: %s", e)
                return WriteResult(
                    success=False,
                    failure_type="write",
                    message=f"Configuration written but Admin_User store failed: {e}",
                    backup_path=backup_path,
                )

        return WriteResult(success=True, message="Configuration written", backup_path=backup_path)

    # -- helpers ------------------------------------------------------------

    def _resolve_managed_values(self, values):
        """Map wizard input names onto managed deploy.ini keys."""
        managed = {}
        for raw_key, raw_value in values.items():
            if raw_key in ("admin_password", "admin_username", "admin_first_name", "admin_last_name"):
                # Never persisted to the file (Req 6.5).
                continue
            file_key = _VALUE_KEY_ALIASES.get(raw_key, raw_key)
            if file_key in MANAGED_KEYS:
                managed[file_key] = "" if raw_value is None else str(raw_value)
        return managed

    def _backup_path(self):
        """Second-precision timestamped backup path (Req 6.2)."""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"{self.config_path}.bak.{timestamp}"

    def _merge(self, existing_content, managed):
        """Merge managed keys over the preserved unmanaged content (Req 6.1).

        Preserves comments, blank lines, and unmanaged keys verbatim and in
        place. Managed keys already present are updated in place; managed keys
        not present are appended.
        """
        remaining = dict(managed)
        out_lines = []

        if existing_content is not None:
            # Split preserving the fact that content may or may not end with \n.
            lines = existing_content.split("\n")
            for line in lines:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in line:
                    key = line.split("=", 1)[0].strip()
                    if key in remaining:
                        out_lines.append(f"{key}={remaining.pop(key)}")
                        continue
                out_lines.append(line)

        # Append any managed keys that were not already present.
        if remaining:
            # Ensure separation from prior content.
            if out_lines and out_lines[-1].strip() != "":
                out_lines.append("")
            for key in MANAGED_KEYS:
                if key in remaining:
                    out_lines.append(f"{key}={remaining[key]}")

        content = "\n".join(out_lines)
        if not content.endswith("\n"):
            content += "\n"
        return content

    def _atomic_write(self, content):
        """Write ``content`` to a temp file in ``conf/`` then ``os.replace``.

        The temp file is flushed and ``fsync``-ed before the rename so the
        replacement is durable and atomic on POSIX (Req 6.1).
        """
        os.makedirs(self.conf_dir, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=self.conf_dir, prefix=".deploy.ini.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            # Owner-only before it becomes the live file (Req 6.6).
            os.chmod(tmp_path, _OWNER_ONLY_MODE)
            os.replace(tmp_path, self.config_path)
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise

    def _store_admin_user(self, values):
        """Insert/update the Admin_User with a hashed password (Req 6.5).

        The plaintext password is only used to produce the hash and is never
        written to any file.
        """
        username = values.get("admin_username", "admin")
        email = values.get("admin_email") or values.get("email") or f"admin@{values.get('domain', 'localhost')}"
        first_name = values.get("admin_first_name", "System")
        last_name = values.get("admin_last_name", "Administrator")
        password_hash = generate_password_hash(values["admin_password"])

        existing = self._db.execute_query(
            "SELECT id FROM users WHERE username = %s",
            (username,),
            fetch_one=True,
        )
        if existing:
            self._db.execute_query(
                "UPDATE users SET password_hash = %s, email = %s WHERE username = %s",
                (password_hash, email, username),
            )
        else:
            self._db.execute_query(
                """
                INSERT INTO users (username, email, password_hash, first_name, last_name, suspended)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (username, email, password_hash, first_name, last_name, False),
            )
