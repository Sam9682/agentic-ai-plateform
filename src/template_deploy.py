"""Shared template deploy path for the Onboarding Experience.

Every surface (Dashboard, CLI, MCP, REST, Sandbox) deploys through the single,
surface-agnostic :class:`TemplateDeployService` so behavior is identical
everywhere (Req 8, 9, 10).

The service orchestrates the existing platform building blocks rather than
reinventing them:

- :class:`~src.template_catalog.TemplateCatalog` is the single source of truth
  for blueprint definitions (Req 7).
- ``LightOrchestrator`` (``src/orchestrator.py``) creates the service/containers.
- ``nginx_manager`` (``src/nginx_manager.py``) exposes the app at
  ``https://{domain}/{USER_ID}/{APPLICATION_NAME}``.
- ``db_manager`` and ``calculate_app_ports`` (``src/database_postgres.py``)
  provide transactional PostgreSQL access and the 12-consecutive-port
  allocation (Req 3.4).

Deploy guard order (each maps to an error code so surfaces can return
400/404/409/502):

  1. ``validate_app_name(app_name)``       -> 400 invalid name          (Req 10.6, 10.2)
  2. ``catalog.get(template_id)``          -> 404 template not found    (Req 10.4, 9.3/9.4)
  3. name unique for ``user_id``           -> 409 name in use           (Req 10.5)
  4. allocate ``application_id`` + ports via ``calculate_app_ports``    (Req 3.4)
  5. ``orchestrator.create_service(...)``  -> 502 on failure            (Req 10.7, 8.4)
  6. ``nginx_manager.insert_location_block(...)``                       (Req 8.3)
  7. record deployment (status running)

On any failure after allocation (step 4), the partial records are rolled back
in a single transaction and the nginx location block is removed best-effort so
no partial resources remain (Req 8.4, 10.7).
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

from . import nginx_manager
from .database_postgres import db_manager as default_db_manager
from .database_postgres import (
    calculate_app_ports,
    APP_PORT_COLUMNS_SQL,
    APP_PORT_PLACEHOLDERS_SQL,
    DOMAIN,
)

logger = logging.getLogger(__name__)

# Application name rules (Req 10.6, 10.2). DNS-label-safe and matches the nginx
# location + URL path usage: 1..63 chars, permitted set [a-z0-9-].
APP_NAME_MIN_LEN = 1
APP_NAME_MAX_LEN = 63
_APP_NAME_RE = re.compile(r"^[a-z0-9-]+$")

# Deployment status recorded on success (Req 8.1 / step 7).
DEPLOYMENT_STATUS_RUNNING = "running"

# Symbolic error codes surfaces map to HTTP status codes. Keeping the mapping
# here means every surface (REST/CLI/MCP/dashboard) reports the same outcome
# for the same failure.
ERROR_INVALID_NAME = "invalid_name"        # -> 400 (Req 10.6, 10.2)
ERROR_TEMPLATE_NOT_FOUND = "not_found"     # -> 404 (Req 10.4, 9.3/9.4)
ERROR_NAME_CONFLICT = "name_conflict"      # -> 409 (Req 10.5)
ERROR_ORCHESTRATOR_FAILED = "deploy_failed"  # -> 502 (Req 10.7, 8.4)

# error code -> HTTP status, for convenience of REST/other surfaces.
STATUS_CODES = {
    ERROR_INVALID_NAME: 400,
    ERROR_TEMPLATE_NOT_FOUND: 404,
    ERROR_NAME_CONFLICT: 409,
    ERROR_ORCHESTRATOR_FAILED: 502,
}


@dataclass
class DeployResult:
    """Outcome of a :meth:`TemplateDeployService.deploy` call.

    ``success`` distinguishes the happy path from any guard/rollback failure.
    On success ``application_id`` and ``access_url`` are populated. On failure
    ``error_code`` is one of the ``ERROR_*`` constants and ``status_code`` is
    the corresponding HTTP status so surfaces can map outcomes to 400/404/409/502.
    """

    success: bool
    error_code: Optional[str] = None
    status_code: Optional[int] = None
    message: Optional[str] = None
    application_id: Optional[int] = None
    application_name: Optional[str] = None
    access_url: Optional[str] = None
    template_id: Optional[str] = None
    ports: List[int] = field(default_factory=list)

    @classmethod
    def failure(cls, error_code: str, message: str, **kwargs) -> "DeployResult":
        """Build a failed result, deriving the HTTP status from ``error_code``."""
        return cls(
            success=False,
            error_code=error_code,
            status_code=STATUS_CODES.get(error_code, 500),
            message=message,
            **kwargs,
        )

    @classmethod
    def ok(
        cls,
        application_id: int,
        application_name: str,
        access_url: str,
        template_id: str,
        ports: List[int],
    ) -> "DeployResult":
        """Build a successful result."""
        return cls(
            success=True,
            status_code=200,
            application_id=application_id,
            application_name=application_name,
            access_url=access_url,
            template_id=template_id,
            ports=list(ports),
        )


class TemplateDeployService:
    """Single, surface-agnostic template deploy path (Req 8, 9, 10)."""

    def __init__(self, catalog, orchestrator, db_manager=None, nginx=None):
        """
        :param catalog: a loaded :class:`TemplateCatalog` (single source of truth).
        :param orchestrator: the ``LightOrchestrator`` instance.
        :param db_manager: PostgreSQL manager; defaults to the shared singleton.
        :param nginx: nginx manager module/object; defaults to ``src.nginx_manager``
            (injectable so tests can supply a stub).
        """
        self.catalog = catalog
        self.orchestrator = orchestrator
        self.db_manager = db_manager or default_db_manager
        self.nginx = nginx or nginx_manager

    # ------------------------------------------------------------------
    # Name validation (Req 10.6, 10.2)
    # ------------------------------------------------------------------
    @staticmethod
    def validate_app_name(name: Any) -> bool:
        """Return ``True`` iff ``name`` is a valid application name.

        Valid iff length 1..63 and every character is in the permitted set
        ``[a-z0-9-]``. Empty, missing (``None``/non-string) and oversized names
        are rejected (Req 10.6, 10.2).
        """
        if not isinstance(name, str):
            return False
        if not (APP_NAME_MIN_LEN <= len(name) <= APP_NAME_MAX_LEN):
            return False
        return bool(_APP_NAME_RE.match(name))

    # ------------------------------------------------------------------
    # Deploy (guard order in the module docstring)
    # ------------------------------------------------------------------
    def deploy(
        self,
        template_id: str,
        app_name: str,
        user_id: int,
        sandbox_label: bool = False,
    ) -> DeployResult:
        """Deploy ``template_id`` as ``app_name`` for ``user_id``.

        Executes the guard order and, on any failure after port allocation,
        rolls back the partial records in one transaction and best-effort removes
        the nginx location block so no partial resources remain (Req 8.4, 10.7).
        """
        # Step 1: validate the application name (Req 10.6, 10.2) -> 400.
        if not self.validate_app_name(app_name):
            return DeployResult.failure(
                ERROR_INVALID_NAME,
                "invalid application name",
                application_name=app_name if isinstance(app_name, str) else None,
                template_id=template_id,
            )

        # Step 2: resolve the template (Req 10.4, 9.3/9.4) -> 404. The
        # orchestrator is never invoked when the template is unknown.
        template = self.catalog.get(template_id)
        if template is None:
            return DeployResult.failure(
                ERROR_TEMPLATE_NOT_FOUND,
                "template not found",
                application_name=app_name,
                template_id=template_id,
            )

        # Step 3: name must be unique for this user (Req 10.5) -> 409. The
        # orchestrator is never invoked on a conflict.
        if self._name_in_use(user_id, app_name):
            return DeployResult.failure(
                ERROR_NAME_CONFLICT,
                "application name already in use",
                application_name=app_name,
                template_id=template_id,
            )

        image = template.get("source_image") or template.get("source") or template.get("image")
        environment = template.get("environment") or []
        ports_spec = template.get("ports") or []
        memory_mb = template.get("memory_mb")
        cpu_cores = template.get("cpu_cores")
        timeout_seconds = template.get("timeout_seconds")

        user_name = self._get_user_name(user_id)

        # Step 4: allocate an application_id and its 12 consecutive ports
        # (6 HTTP + 6 HTTPS) via calculate_app_ports (Req 3.4). This is the
        # first mutating step; everything below is rolled back on failure.
        application_id = None
        try:
            application_id = self._allocate_application(app_name)
            app_ports = calculate_app_ports(user_id, application_id)
            access_url = self._build_access_url(user_id, app_name)
            self._record_user_application(user_id, application_id, access_url, app_ports)
        except Exception as exc:
            logger.error("Port/record allocation failed for '%s': %s", app_name, exc)
            self._rollback(user_id, application_id, app_name, user_name)
            return DeployResult.failure(
                ERROR_ORCHESTRATOR_FAILED,
                "failed to allocate deployment resources",
                application_name=app_name,
                template_id=template_id,
            )

        # Step 5: create the service via the orchestrator (Req 8.1). Any failure
        # is treated as "orchestrator failed to initiate" -> 502 (Req 10.7, 8.4).
        orchestrator_ports = self._build_orchestrator_ports(ports_spec, app_ports)
        try:
            self._create_service(
                name=app_name,
                image=image,
                user_id=user_id,
                ports=orchestrator_ports,
                environment=environment,
                memory_mb=memory_mb,
                cpu_cores=cpu_cores,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            logger.error("Orchestrator failed to initiate '%s': %s", app_name, exc)
            self._rollback(user_id, application_id, app_name, user_name)
            return DeployResult.failure(
                ERROR_ORCHESTRATOR_FAILED,
                "orchestrator failed to initiate deployment",
                application_name=app_name,
                template_id=template_id,
            )

        # Step 6: expose the app via nginx (Req 8.3).
        try:
            self.nginx.insert_location_block(user_name, app_name, access_url, access_url)
        except Exception as exc:
            logger.error("nginx insert_location_block failed for '%s': %s", app_name, exc)
            # Roll back orchestrator + records so no partial resources remain
            # (Req 8.4, 10.7).
            self._rollback(user_id, application_id, app_name, user_name)
            return DeployResult.failure(
                ERROR_ORCHESTRATOR_FAILED,
                "failed to publish nginx location",
                application_name=app_name,
                template_id=template_id,
            )

        # Step 7: record the deployment with status "running".
        try:
            self._record_deployment(
                user_id, application_id, app_name, sandbox_label
            )
        except Exception as exc:
            logger.error("Failed to record deployment for '%s': %s", app_name, exc)
            self._rollback(user_id, application_id, app_name, user_name)
            return DeployResult.failure(
                ERROR_ORCHESTRATOR_FAILED,
                "failed to record deployment",
                application_name=app_name,
                template_id=template_id,
            )

        logger.info(
            "Deployed template '%s' as '%s' for user %s -> %s",
            template_id,
            app_name,
            user_id,
            access_url,
        )
        return DeployResult.ok(
            application_id=application_id,
            application_name=app_name,
            access_url=access_url,
            template_id=template_id,
            ports=list(app_ports),
        )

    # ------------------------------------------------------------------
    # Access URL (Req 8.3, 10.2)
    # ------------------------------------------------------------------
    @staticmethod
    def _build_access_url(user_id: int, app_name: str) -> str:
        """Canonical access URL ``https://{domain}/{USER_ID}/{APPLICATION_NAME}`` (Req 8.3)."""
        return f"https://{DOMAIN}/{user_id}/{app_name}"

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------
    def _name_in_use(self, user_id: int, app_name: str) -> bool:
        """True iff ``user_id`` already owns an application named ``app_name`` (Req 10.5).

        A name is considered "in use" for the user if there is a deployment the
        user owns with that application name, or a user_applications row that
        joins to an application of that name.
        """
        row = self.db_manager.execute_query(
            "SELECT 1 FROM deployments WHERE user_id = %s AND application_name = %s LIMIT 1",
            (user_id, app_name),
            fetch_one=True,
        )
        if row:
            return True
        row = self.db_manager.execute_query(
            """
            SELECT 1 FROM user_applications ua
            JOIN applications a ON a.id = ua.application_id
            WHERE ua.user_id = %s AND a.name = %s LIMIT 1
            """,
            (user_id, app_name),
            fetch_one=True,
        )
        return bool(row)

    def _get_user_name(self, user_id: int) -> str:
        """Return the username for ``user_id`` (falls back to ``user_{id}``)."""
        try:
            row = self.db_manager.execute_query(
                "SELECT username FROM users WHERE id = %s",
                (user_id,),
                fetch_one=True,
            )
            if row and row[0]:
                return row[0]
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to resolve username for user %s: %s", user_id, exc)
        return f"user_{user_id}"

    def _allocate_application(self, app_name: str) -> int:
        """Create (or fetch) the global ``applications`` row and return its id.

        ``applications.name`` is UNIQUE, so an existing row is reused; a new one
        is inserted otherwise. Returns the application id used for port
        allocation (Req 3.4).
        """
        row = self.db_manager.execute_query(
            "SELECT id FROM applications WHERE name = %s",
            (app_name,),
            fetch_one=True,
        )
        if row and row[0]:
            return int(row[0])

        new_id = self.db_manager.execute_query(
            "INSERT INTO applications (name, description) VALUES (%s, %s) RETURNING id",
            (app_name, "Deployed from template"),
            fetch_one=True,
        )
        if new_id and new_id[0]:
            return int(new_id[0])
        # Fallback: race where another writer inserted between our SELECT and
        # INSERT (ON name UNIQUE). Re-read.
        row = self.db_manager.execute_query(
            "SELECT id FROM applications WHERE name = %s",
            (app_name,),
            fetch_one=True,
        )
        if row and row[0]:
            return int(row[0])
        raise RuntimeError(f"could not allocate application id for '{app_name}'")

    def _record_user_application(self, user_id, application_id, access_url, app_ports):
        """Insert the user_applications row with the 12 allocated ports (Req 3.4)."""
        self.db_manager.execute_query(
            f"INSERT INTO user_applications (user_id, application_id, url, {APP_PORT_COLUMNS_SQL}) "
            f"VALUES (%s, %s, %s, {APP_PORT_PLACEHOLDERS_SQL}) "
            f"ON CONFLICT (user_id, application_id) DO NOTHING",
            (user_id, application_id, access_url, *app_ports),
        )

    def _record_deployment(self, user_id, application_id, app_name, sandbox_label):
        """Record the deployment row with status running (step 7).

        ``is_sandbox`` labels sandbox-seeded deployments so reset/teardown can
        scope destructive operations (Req 2.4, 3.2).
        """
        self.db_manager.execute_query(
            "INSERT INTO deployments (user_id, application_id, application_name, status, is_sandbox) "
            "VALUES (%s, %s, %s, %s, %s)",
            (user_id, application_id, app_name, DEPLOYMENT_STATUS_RUNNING, bool(sandbox_label)),
        )

    def _rollback(self, user_id, application_id, app_name, user_name):
        """Roll back partial records in one transaction + best-effort nginx removal.

        Removes any deployment and user_applications rows created for this
        (user, application) so no partial resources remain (Req 8.4, 10.7). The
        global ``applications`` row is left intact when it is shared, but the
        per-user linkage and deployment are removed. Best-effort orchestrator
        service deletion and nginx removal follow.
        """
        # DB rollback in a single transaction.
        if application_id is not None:
            try:
                with self.db_manager.get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "DELETE FROM deployments WHERE user_id = %s AND application_id = %s",
                        (user_id, application_id),
                    )
                    cursor.execute(
                        "DELETE FROM user_applications WHERE user_id = %s AND application_id = %s",
                        (user_id, application_id),
                    )
                    conn.commit()
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("Rollback of DB records failed for '%s': %s", app_name, exc)

        # Best-effort orchestrator service removal (stops instances too).
        try:
            self.orchestrator.delete_service(app_name, user_id)
        except Exception as exc:
            logger.warning("Best-effort orchestrator cleanup failed for '%s': %s", app_name, exc)

        # Best-effort nginx location removal.
        try:
            self.nginx.remove_location_block(user_name, app_name)
        except Exception as exc:
            logger.warning("Best-effort nginx cleanup failed for '%s': %s", app_name, exc)

    # ------------------------------------------------------------------
    # Orchestrator helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _build_orchestrator_ports(ports_spec, app_ports) -> Dict[str, int]:
        """Map the template's container ports to the allocated host ports.

        The template ``ports`` list looks like ``[{"container": 80, ...}, ...]``.
        ``app_ports`` are the 12 allocated ports (HTTP/HTTPS interleaved). We map
        each declared container port to the next allocated HTTP host port so the
        orchestrator publishes ``container -> host``.
        """
        mapping: Dict[str, int] = {}
        http_ports = list(app_ports[0::2])  # HTTP ports are at even indices.
        for idx, entry in enumerate(ports_spec or []):
            if isinstance(entry, dict):
                container = entry.get("container", entry.get("port"))
            else:
                container = entry
            if container is None:
                continue
            host = http_ports[idx] if idx < len(http_ports) else None
            if host is None:
                break
            mapping[str(container)] = host
        return mapping

    def _create_service(
        self,
        name,
        image,
        user_id,
        ports,
        environment,
        memory_mb=None,
        cpu_cores=None,
        timeout_seconds=None,
    ):
        """Invoke ``orchestrator.create_service`` forwarding image/ports/env and,
        when the orchestrator accepts them, the resource hints (memory/cpu/timeout)
        (Req 8.1).

        The resource hints are forwarded only if the orchestrator's
        ``create_service`` signature accepts them, keeping this compatible with
        the current signature while honoring the design intent.
        """
        kwargs = {
            "name": name,
            "image": image,
            "user_id": user_id,
            "ports": ports,
            "environment": environment,
        }
        for hint_name, hint_value in (
            ("memory_mb", memory_mb),
            ("cpu_cores", cpu_cores),
            ("timeout_seconds", timeout_seconds),
        ):
            if hint_value is not None and self._orchestrator_accepts(hint_name):
                kwargs[hint_name] = hint_value
        return self.orchestrator.create_service(**kwargs)

    def _orchestrator_accepts(self, param_name: str) -> bool:
        """True iff the orchestrator's ``create_service`` accepts ``param_name``."""
        try:
            import inspect

            sig = inspect.signature(self.orchestrator.create_service)
        except (TypeError, ValueError):  # pragma: no cover - defensive
            return False
        params = sig.parameters
        if param_name in params:
            return True
        # Accept if the callable takes **kwargs.
        return any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
        )
