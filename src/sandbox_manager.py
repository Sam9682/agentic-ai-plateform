"""Sandbox / Demo Mode provisioning for the Onboarding Experience.

:class:`SandboxManager` provisions a working demo environment so a new operator
observes value within minutes: it creates a single :data:`Demo_User` labeled
``account_type='sandbox demo'`` and seeds between 3 and 10 Sample Applications
selected from the shared Deploy Template catalog (Req 1, 3).

Design decisions (annotated against the acceptance criteria):

- The catalog is the single source of truth for blueprints; every seeded app is
  deployed through the shared :class:`~src.template_deploy.TemplateDeployService`
  with ``sandbox_label=True`` so its deployment row is marked ``is_sandbox`` and
  reset/teardown can scope destructive operations (Req 2.4, 3.2).
- Port allocation (12 consecutive ports per app) is handled inside
  ``TemplateDeployService`` via ``calculate_app_ports`` (Req 3.4); the sandbox
  layer does not compute ports itself.
- Provisioning is atomic at the sandbox level: if any app fails to deploy, OR
  fewer than 3 apps can be seeded, every already-seeded app is rolled back
  (orchestrator ``delete_service`` + nginx ``remove_location_block`` + DB record
  removal) and the ``Demo_User`` and its partial records are removed, leaving no
  partial sandbox behind (Req 1.5, 3.5).

``reset`` and ``teardown`` scope every destructive operation to sandbox-labeled
resources (``account_type='sandbox demo'`` / ``is_sandbox=true``) so non-sandbox
users and applications are never touched (Req 2.4); per-app removal failures are
isolated and reported while the remaining apps are still processed (Req 2.6).
"""

import logging
import secrets
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

from werkzeug.security import generate_password_hash

from . import nginx_manager
from .database_postgres import db_manager as default_db_manager
from .database_postgres import DOMAIN
from .template_catalog import TemplateCatalog
from .template_deploy import TemplateDeployService

logger = logging.getLogger(__name__)

# Account-type attribute that distinguishes the demo account from non-demo
# accounts (Req 3.1). Reset/teardown scope destructive queries on this value
# (Req 2.4).
SANDBOX_ACCOUNT_TYPE = "sandbox demo"

# The Demo_User display/login name (Req 3.1).
DEMO_USER_NAME = "Demo_User"

# Seed-count bounds (Req 1.1, 3.2, 3.5).
MIN_SEED_APPS = 3
MAX_SEED_APPS = 10


@dataclass
class SandboxReport:
    """Outcome of a :class:`SandboxManager` operation.

    On a successful provision, ``success`` is ``True``, ``credentials`` holds the
    Demo_User login details, and ``apps`` holds one entry per seeded app, each
    including exactly one ``access_url`` (Req 1.3). On failure, ``success`` is
    ``False``, ``failed`` lists the applications that could not be deployed, and
    ``apps`` is empty because the partial sandbox was rolled back (Req 1.5, 3.5).
    """

    success: bool
    message: Optional[str] = None
    error_code: Optional[str] = None
    credentials: Optional[Dict[str, Any]] = None
    apps: List[Dict[str, Any]] = field(default_factory=list)
    failed: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def failure(
        cls,
        message: str,
        error_code: Optional[str] = None,
        failed: Optional[List[Dict[str, Any]]] = None,
    ) -> "SandboxReport":
        return cls(
            success=False,
            message=message,
            error_code=error_code,
            failed=list(failed or []),
        )


# Symbolic error codes surfaces can map to messages/statuses.
ERROR_SANDBOX_EXISTS = "sandbox_exists"        # a sandbox is already present (Req 1.4)
ERROR_SEED_FAILED = "seed_failed"              # could not seed >=3 apps / an app failed (Req 1.5, 3.5)


class SandboxManager:
    """Provision, reset, and teardown the sandbox environment (Req 1, 2, 3)."""

    def __init__(
        self,
        catalog=None,
        orchestrator=None,
        deploy_service=None,
        db_manager=None,
        nginx=None,
    ):
        """All collaborators are injectable so tests can supply stubs.

        :param catalog: a :class:`TemplateCatalog`. Defaults to a freshly loaded
            catalog when not supplied.
        :param orchestrator: the ``LightOrchestrator`` used for rollback
            (``delete_service``) and forwarded to the deploy service.
        :param deploy_service: the shared :class:`TemplateDeployService`. When
            omitted one is constructed from ``catalog``/``orchestrator``.
        :param db_manager: PostgreSQL manager; defaults to the shared singleton.
        :param nginx: nginx manager module/object; defaults to ``src.nginx_manager``.
        """
        self.db_manager = db_manager or default_db_manager
        self.nginx = nginx or nginx_manager
        self.orchestrator = orchestrator

        if catalog is None:
            catalog = TemplateCatalog(db=self.db_manager).load()
        self.catalog = catalog

        if deploy_service is None:
            deploy_service = TemplateDeployService(
                catalog=self.catalog,
                orchestrator=self.orchestrator,
                db_manager=self.db_manager,
                nginx=self.nginx,
            )
        self.deploy_service = deploy_service

    # ------------------------------------------------------------------
    # Provisioning (Req 1, 3)
    # ------------------------------------------------------------------
    def provision(self) -> SandboxReport:
        """Provision the sandbox: create the Demo_User and seed 3..10 apps.

        Guard order:
          1. Reject when a sandbox already exists, changing nothing (Req 1.4).
          2. Verify at least 3 seedable templates exist; otherwise report a seed
             failure without creating anything (Req 3.5).
          3. Create the Demo_User with ``account_type='sandbox demo'`` and a
             hashed password (Req 3.1).
          4. Deploy each selected template through the shared deploy service with
             ``sandbox_label=True`` (Req 3.2, 3.4).
          5. On any app failure, roll back every seeded app and the Demo_User so
             no partial sandbox remains, and report the failed set (Req 1.5, 3.5).
          6. Return the demo credentials + exactly one access URL per app (Req 1.3).
        """
        # Step 1: reject if a sandbox already exists; change nothing (Req 1.4).
        if self._sandbox_exists():
            logger.info("provision() rejected: a sandbox already exists")
            return SandboxReport.failure(
                "A sandbox environment already exists. Run the reset or teardown "
                "action before provisioning again.",
                error_code=ERROR_SANDBOX_EXISTS,
            )

        # Step 2: determine the templates to seed. We need at least 3 seedable
        # templates; if fewer are available we fail without side effects (Req 3.5).
        templates = self._select_seed_templates()
        if len(templates) < MIN_SEED_APPS:
            logger.warning(
                "provision() cannot seed: only %d seedable template(s), need >= %d",
                len(templates),
                MIN_SEED_APPS,
            )
            return SandboxReport.failure(
                f"Demo seeding failed: only {len(templates)} deployable template(s) "
                f"available, at least {MIN_SEED_APPS} required.",
                error_code=ERROR_SEED_FAILED,
                failed=[{"template_id": t.get("template_id")} for t in templates],
            )

        # Step 3: create the Demo_User (Req 3.1). The plaintext password is
        # generated here and returned in the report's credentials (Req 1.3); only
        # the hash is persisted.
        password = self._generate_demo_password()
        try:
            user_id = self._create_demo_user(password)
        except Exception as exc:
            logger.error("Failed to create Demo_User: %s", exc)
            return SandboxReport.failure(
                "Demo seeding failed: could not create the demo user.",
                error_code=ERROR_SEED_FAILED,
            )

        # Step 4: seed each selected template through the shared deploy path.
        seeded: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []
        for template in templates:
            template_id = template.get("template_id")
            app_name = self._sample_app_name(template)
            result = self.deploy_service.deploy(
                template_id=template_id,
                app_name=app_name,
                user_id=user_id,
                sandbox_label=True,
            )
            if result.success:
                seeded.append(
                    {
                        "template_id": template_id,
                        "application_id": result.application_id,
                        "application_name": result.application_name,
                        "access_url": result.access_url,
                        "status": "running",
                    }
                )
            else:
                failed.append(
                    {
                        "template_id": template_id,
                        "application_name": app_name,
                        "error_code": result.error_code,
                        "message": result.message,
                    }
                )
                # Stop seeding on the first failure; the whole sandbox is rolled
                # back below (Req 1.5, 3.5).
                break

        # Step 5: any failure OR fewer than 3 seeded apps -> roll everything back
        # so no partial sandbox remains, and report the failed set (Req 1.5, 3.5).
        if failed or len(seeded) < MIN_SEED_APPS:
            logger.warning(
                "provision() rolling back: %d seeded, %d failed",
                len(seeded),
                len(failed),
            )
            self._rollback_provision(user_id, seeded)
            return SandboxReport.failure(
                "Demo seeding failed; the partial sandbox was rolled back.",
                error_code=ERROR_SEED_FAILED,
                failed=failed or [{"reason": "fewer than 3 apps could be seeded"}],
            )

        # Step 6: success -> return credentials + one access URL per app (Req 1.3).
        logger.info("provision() succeeded: seeded %d apps for Demo_User", len(seeded))
        return SandboxReport(
            success=True,
            message=f"Sandbox provisioned with {len(seeded)} sample applications.",
            credentials={
                "username": DEMO_USER_NAME,
                "password": password,
                "user_id": user_id,
                "account_type": SANDBOX_ACCOUNT_TYPE,
            },
            apps=seeded,
        )

    # ------------------------------------------------------------------
    # Reset (Req 2.1, 2.3, 2.4, 2.5, 2.6)
    # ------------------------------------------------------------------
    def reset(self) -> SandboxReport:
        """Reset the sandbox to its predefined seed baseline (Req 2.1).

        Guard order:
          1. If no sandbox exists, do nothing and return an informational
             message (Req 2.5).
          2. Otherwise stop + remove every sandbox-labeled sample app (Req 2.1,
             2.3, 2.4), continuing past per-app removal failures and recording
             each one (Req 2.6).
          3. Re-seed the predefined baseline (3..10 apps) for the Demo_User via
             the shared deploy service (Req 2.1, 3.2).

        Destructive queries are scoped to ``account_type='sandbox demo'`` /
        ``is_sandbox=true`` so non-sandbox users and apps are never touched
        (Req 2.4).
        """
        # Step 1: no sandbox -> informational, do nothing (Req 2.5).
        if not self._sandbox_exists():
            logger.info("reset() no-op: no sandbox environment is present")
            return SandboxReport(
                success=True,
                message="No sandbox environment is present.",
            )

        user_id = self._get_sandbox_user_id()

        # Step 2: stop + remove all sandbox-labeled apps, continuing on
        # per-app failures and recording each (Req 2.3, 2.4, 2.6).
        apps = self._list_sandbox_apps(user_id)
        removed, failed = self._remove_sandbox_apps(user_id, apps)

        # Step 3: re-seed the predefined baseline (3..10 apps) for the Demo_User
        # via the shared deploy path (Req 2.1, 3.2).
        templates = self._select_seed_templates()
        seeded: List[Dict[str, Any]] = []
        for template in templates:
            template_id = template.get("template_id")
            app_name = self._sample_app_name(template)
            result = self.deploy_service.deploy(
                template_id=template_id,
                app_name=app_name,
                user_id=user_id,
                sandbox_label=True,
            )
            if result.success:
                seeded.append(
                    {
                        "template_id": template_id,
                        "application_id": result.application_id,
                        "application_name": result.application_name,
                        "access_url": result.access_url,
                        "status": "running",
                    }
                )
            else:
                failed.append(
                    {
                        "template_id": template_id,
                        "application_name": app_name,
                        "error_code": result.error_code,
                        "message": result.message,
                    }
                )

        logger.info(
            "reset() done: removed %d, re-seeded %d, %d failure(s)",
            len(removed),
            len(seeded),
            len(failed),
        )
        return SandboxReport(
            success=not failed,
            message=(
                f"Sandbox reset: removed {len(removed)} app(s), "
                f"re-seeded {len(seeded)} sample application(s)."
            ),
            credentials={
                "username": DEMO_USER_NAME,
                "user_id": user_id,
                "account_type": SANDBOX_ACCOUNT_TYPE,
            },
            apps=seeded,
            failed=failed,
        )

    # ------------------------------------------------------------------
    # Teardown (Req 2.2, 2.3, 2.4, 2.5, 2.6)
    # ------------------------------------------------------------------
    def teardown(self) -> SandboxReport:
        """Tear down the sandbox and remove all demo resources (Req 2.2).

        Guard order:
          1. If no sandbox exists, do nothing and return an informational
             message (Req 2.5).
          2. Otherwise, in order (Req 2.2):
               a. stop all sample apps,
               b. remove all sample apps,
               c. remove the Demo_User,
               d. remove sandbox-specific database records.
             Steps (a) and (b) are performed together per app by
             :meth:`_remove_sandbox_apps` (``delete_service`` stops instances and
             removes the service; nginx location + DB records are removed too),
             continuing past per-app failures and recording each (Req 2.3, 2.6).

        All destructive queries are scoped to ``account_type='sandbox demo'`` /
        ``is_sandbox=true`` so non-sandbox users and apps are never touched
        (Req 2.4).
        """
        # Step 1: no sandbox -> informational, do nothing (Req 2.5).
        if not self._sandbox_exists():
            logger.info("teardown() no-op: no sandbox environment is present")
            return SandboxReport(
                success=True,
                message="No sandbox environment is present.",
            )

        user_id = self._get_sandbox_user_id()

        # Step 2a+2b: stop and remove all sandbox-labeled apps, continuing on
        # per-app failures and recording each (Req 2.3, 2.4, 2.6).
        apps = self._list_sandbox_apps(user_id)
        removed, failed = self._remove_sandbox_apps(user_id, apps)

        # Step 2c+2d: remove the Demo_User and any remaining sandbox-specific DB
        # records. Scoped to the sandbox account / is_sandbox rows (Req 2.2, 2.4).
        self._remove_sandbox_user_records(user_id)

        logger.info(
            "teardown() done: removed %d app(s), %d failure(s), Demo_User removed",
            len(removed),
            len(failed),
        )
        return SandboxReport(
            success=not failed,
            message=(
                f"Sandbox torn down: removed {len(removed)} app(s) and the demo user."
            ),
            apps=[],
            failed=failed,
        )

    # ------------------------------------------------------------------
    # Sandbox app removal shared by reset/teardown (Req 2.3, 2.4, 2.6)
    # ------------------------------------------------------------------
    def _remove_sandbox_apps(
        self, user_id: int, apps: List[Dict[str, Any]]
    ) -> tuple:
        """Stop + remove each sandbox app, isolating per-app failures (Req 2.3, 2.6).

        For every app, invoke ``orchestrator.delete_service`` (stops instances)
        AND ``nginx.remove_location_block`` (Req 2.3), then delete its
        ``deployments`` / ``user_applications`` records. Any per-app failure is
        caught, recorded in the ``failed`` list, and iteration continues so the
        remaining apps are still processed (Req 2.6).

        Returns a ``(removed, failed)`` tuple of app-descriptor lists.
        """
        removed: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []
        for app in apps:
            app_name = app.get("application_name")
            application_id = app.get("application_id")
            try:
                # Orchestrator stop/delete (removes the service + instances) (Req 2.3).
                if self.orchestrator is not None:
                    self.orchestrator.delete_service(app_name, user_id)

                # Remove the nginx dynamic location for the app (Req 2.3).
                self.nginx.remove_location_block(DEMO_USER_NAME, app_name)

                # Remove the sandbox-labeled DB records for this app. Scoped to
                # is_sandbox=true so non-sandbox deployments are never touched
                # (Req 2.4).
                if application_id is not None:
                    with self.db_manager.get_db_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            "DELETE FROM deployments WHERE user_id = %s "
                            "AND application_id = %s AND is_sandbox = true",
                            (user_id, application_id),
                        )
                        cursor.execute(
                            "DELETE FROM user_applications WHERE user_id = %s "
                            "AND application_id = %s",
                            (user_id, application_id),
                        )
                        conn.commit()
                removed.append(app)
            except Exception as exc:
                # Isolate the failure and keep processing the rest (Req 2.6).
                logger.warning(
                    "Failed to remove sandbox app '%s': %s", app_name, exc
                )
                failed.append(
                    {
                        "application_id": application_id,
                        "application_name": app_name,
                        "message": str(exc),
                    }
                )
        return removed, failed

    def _remove_sandbox_user_records(self, user_id: int) -> None:
        """Remove the Demo_User and remaining sandbox-specific records (Req 2.2, 2.4).

        Scoped to ``is_sandbox=true`` deployments and the
        ``account_type='sandbox demo'`` user so non-sandbox rows are structurally
        out of scope (Req 2.4).
        """
        try:
            with self.db_manager.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM deployments WHERE user_id = %s AND is_sandbox = true",
                    (user_id,),
                )
                cursor.execute(
                    "DELETE FROM user_applications WHERE user_id = %s",
                    (user_id,),
                )
                cursor.execute(
                    "DELETE FROM users WHERE id = %s AND account_type = %s",
                    (user_id, SANDBOX_ACCOUNT_TYPE),
                )
                conn.commit()
        except Exception as exc:
            logger.error(
                "teardown: failed to remove Demo_User %s records: %s", user_id, exc
            )

    # ------------------------------------------------------------------
    # Sandbox user + app enumeration (scoped to sandbox label, Req 2.4)
    # ------------------------------------------------------------------
    def _get_sandbox_user_id(self) -> Optional[int]:
        """Return the Demo_User id (``account_type='sandbox demo'``) or ``None`` (Req 2.4)."""
        row = self.db_manager.execute_query(
            "SELECT id FROM users WHERE account_type = %s LIMIT 1",
            (SANDBOX_ACCOUNT_TYPE,),
            fetch_one=True,
        )
        if row and row[0] is not None:
            return int(row[0])
        return None

    def _list_sandbox_apps(self, user_id: Optional[int]) -> List[Dict[str, Any]]:
        """Enumerate the Demo_User's sandbox-labeled apps to remove (Req 2.4).

        Queries the sandbox user's ``deployments`` where ``is_sandbox=true`` so
        only sandbox-labeled apps are returned; non-sandbox deployments are
        structurally out of scope (Req 2.4). Each returned descriptor carries the
        ``application_id`` and ``application_name`` needed for orchestrator/nginx
        removal.
        """
        if user_id is None:
            return []
        rows = self.db_manager.execute_query(
            "SELECT DISTINCT application_id, application_name FROM deployments "
            "WHERE user_id = %s AND is_sandbox = true",
            (user_id,),
            fetch_all=True,
        )
        apps: List[Dict[str, Any]] = []
        for row in rows or []:
            application_id = row[0]
            apps.append(
                {
                    "application_id": int(application_id)
                    if application_id is not None
                    else None,
                    "application_name": row[1],
                }
            )
        return apps

    # ------------------------------------------------------------------
    # Sandbox detection (Req 1.4)
    # ------------------------------------------------------------------
    def _sandbox_exists(self) -> bool:
        """True iff a Demo_User (``account_type='sandbox demo'``) already exists (Req 1.4)."""
        row = self.db_manager.execute_query(
            "SELECT 1 FROM users WHERE account_type = %s LIMIT 1",
            (SANDBOX_ACCOUNT_TYPE,),
            fetch_one=True,
        )
        return bool(row)

    # ------------------------------------------------------------------
    # Template selection (Req 3.2)
    # ------------------------------------------------------------------
    def _select_seed_templates(self) -> List[dict]:
        """Return the templates to seed: 3..10 valid catalog templates (Req 3.2).

        Selection is the catalog's validated set capped at :data:`MAX_SEED_APPS`.
        The full template dicts are returned so the deploy service can resolve
        each ``template_id``.
        """
        templates: List[dict] = []
        for entry in self.catalog.list():
            template_id = entry.get("identifier")
            if not template_id:
                continue
            template = self.catalog.get(template_id)
            if template is not None:
                templates.append(template)
            if len(templates) >= MAX_SEED_APPS:
                break
        return templates

    @staticmethod
    def _sample_app_name(template: dict) -> str:
        """Derive a DNS-label-safe sample app name from the template id.

        The deploy service validates names against ``[a-z0-9-]`` (1..63 chars),
        so we prefix the template id (already a slug in the catalog) with
        ``demo-`` to keep sample names distinguishable.
        """
        template_id = (template.get("template_id") or "app").lower()
        name = f"demo-{template_id}"
        return name[:63]

    # ------------------------------------------------------------------
    # Demo_User creation (Req 3.1)
    # ------------------------------------------------------------------
    @staticmethod
    def _generate_demo_password() -> str:
        """Generate a strong random password for the Demo_User.

        Returned in the report credentials (Req 1.3); only the hash is stored.
        """
        return secrets.token_urlsafe(16)

    def _create_demo_user(self, password: str) -> int:
        """Insert the Demo_User with ``account_type='sandbox demo'`` and a hash (Req 3.1).

        Returns the new user's id. The password is hashed with
        ``werkzeug.security.generate_password_hash``; the plaintext is never
        persisted.
        """
        password_hash = generate_password_hash(password)
        row = self.db_manager.execute_query(
            "INSERT INTO users (username, email, password_hash, first_name, last_name, "
            "suspended, account_type) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                DEMO_USER_NAME,
                f"demo@{DOMAIN}",
                password_hash,
                "Sandbox",
                "Demo",
                False,
                SANDBOX_ACCOUNT_TYPE,
            ),
            fetch_one=True,
        )
        if not row or not row[0]:
            raise RuntimeError("failed to insert Demo_User")
        return int(row[0])

    # ------------------------------------------------------------------
    # Rollback (Req 1.5, 3.5)
    # ------------------------------------------------------------------
    def _rollback_provision(self, user_id: int, seeded: List[Dict[str, Any]]) -> None:
        """Roll back a partial provision: remove all seeded apps + the Demo_User.

        For every already-seeded app: best-effort orchestrator ``delete_service``
        (stops instances) and nginx ``remove_location_block``, then delete its
        deployment and user_applications records. Finally remove the Demo_User and
        any remaining sandbox records so no partial sandbox remains (Req 1.5, 3.5).
        """
        for app in seeded:
            app_name = app.get("application_name")
            application_id = app.get("application_id")

            # Best-effort orchestrator service removal (stops instances too).
            try:
                if self.orchestrator is not None:
                    self.orchestrator.delete_service(app_name, user_id)
            except Exception as exc:
                logger.warning(
                    "Rollback: orchestrator delete_service failed for '%s': %s",
                    app_name,
                    exc,
                )

            # Best-effort nginx location removal.
            try:
                self.nginx.remove_location_block(DEMO_USER_NAME, app_name)
            except Exception as exc:
                logger.warning(
                    "Rollback: nginx remove_location_block failed for '%s': %s",
                    app_name,
                    exc,
                )

            # Remove the deployment + user_applications records for this app.
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
                except Exception as exc:
                    logger.error(
                        "Rollback: failed to delete records for '%s': %s", app_name, exc
                    )

        # Remove the Demo_User and any remaining sandbox-owned records so the
        # account is left with no partially seeded applications (Req 3.5).
        try:
            with self.db_manager.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM deployments WHERE user_id = %s AND is_sandbox = true",
                    (user_id,),
                )
                cursor.execute(
                    "DELETE FROM user_applications WHERE user_id = %s",
                    (user_id,),
                )
                cursor.execute(
                    "DELETE FROM users WHERE id = %s AND account_type = %s",
                    (user_id, SANDBOX_ACCOUNT_TYPE),
                )
                conn.commit()
        except Exception as exc:
            logger.error("Rollback: failed to remove Demo_User %s: %s", user_id, exc)
