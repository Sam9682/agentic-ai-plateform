"""Deploy Template catalog for the Onboarding Experience.

Loads Deploy Templates from the seeded ``deploy_templates`` table, validates each
against the field bounds, and exposes the valid subset. Invalid templates are
excluded and recorded rather than being fatal (Req 7.4); an all-invalid load
yields an empty catalog with a "no valid templates" indicator (Req 7.5).

The catalog is the single source of truth consumed by the Sandbox, CLI, MCP,
REST, and dashboard surfaces (Req 7, 8, 9, 10).
"""

import json
import logging
from numbers import Number
from typing import List, Dict, Optional, Tuple

from .database_postgres import db_manager

logger = logging.getLogger(__name__)

# Field bounds (Req 7.2 / 7.3).
MIN_PORT = 1
MAX_PORT = 65535
MIN_MEMORY_MB = 64
MAX_MEMORY_MB = 65536
MIN_CPU_CORES = 0.1
MAX_CPU_CORES = 64

# Indicator surfaced by ``load`` when no template validates (Req 7.5).
NO_VALID_TEMPLATES = "no valid templates"


class TemplateValidationError(Exception):
    """Raised per-template with the failing field.

    Caught by the loader and recorded; never propagated out of ``load`` so a
    single bad row cannot crash catalog loading (Req 7.4).
    """

    def __init__(self, template_id: str, failing_fields: List[str]):
        self.template_id = template_id
        self.failing_fields = failing_fields
        super().__init__(
            f"template '{template_id}' failed validation: {', '.join(failing_fields)}"
        )


def _coerce_json(value):
    """Return a parsed JSON structure for a JSONB column value.

    psycopg2 usually decodes JSONB to native Python objects, but a hand-edited or
    externally seeded row may arrive as a string. Anything unparseable is left
    as-is so validation can reject it.
    """
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8")
        except (UnicodeDecodeError, AttributeError):
            return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


class TemplateCatalog:
    """Loads, validates, and exposes Deploy Templates (Req 7)."""

    def __init__(self, db=None):
        self._db = db or db_manager
        self._templates: Dict[str, dict] = {}
        self._errors: List[Tuple[str, str]] = []
        self._loaded = False

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def load(self) -> "TemplateCatalog":
        """Load all templates, validate each, keep the valid ones.

        Records ``(template_id, failing_field)`` for every rejected template
        without raising (Req 7.3, 7.4). An all-invalid load leaves the catalog
        empty with the "no valid templates" indicator available via
        :meth:`is_empty` / :meth:`indicator` (Req 7.5).
        """
        self._templates = {}
        self._errors = []
        self._loaded = True

        rows = self._fetch_rows()
        for row in rows:
            template = self._row_to_template(row)
            template_id = template.get("template_id") or ""
            failing_fields = self.validate(template)
            if failing_fields:
                # Record the (template_id, failing_field) for the first failing
                # field so the reject is traceable, and log the full set.
                self._errors.append((template_id, failing_fields[0]))
                logger.warning(
                    "Deploy template '%s' rejected; failing fields: %s",
                    template_id,
                    ", ".join(failing_fields),
                )
                continue
            self._templates[template_id] = template

        if not self._templates:
            logger.warning("Template catalog loaded with %s", NO_VALID_TEMPLATES)

        return self

    def _fetch_rows(self) -> List[tuple]:
        """Read enabled template rows from ``deploy_templates``."""
        query = (
            "SELECT template_id, app_type, display_name, source_image, ports, "
            "environment, memory_mb, cpu_cores, timeout_seconds "
            "FROM deploy_templates WHERE enabled = true ORDER BY template_id"
        )
        try:
            rows = self._db.execute_query(query, fetch_all=True)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to read deploy_templates: %s", exc)
            return []
        return rows or []

    @staticmethod
    def _row_to_template(row) -> dict:
        """Map a DB row (tuple or mapping) to the validated template shape."""
        if isinstance(row, dict):
            template = {
                "template_id": row.get("template_id"),
                "app_type": row.get("app_type"),
                "display_name": row.get("display_name"),
                "source_image": row.get("source_image"),
                "ports": _coerce_json(row.get("ports")),
                "environment": _coerce_json(row.get("environment")),
                "memory_mb": row.get("memory_mb"),
                "cpu_cores": row.get("cpu_cores"),
                "timeout_seconds": row.get("timeout_seconds"),
            }
        else:
            (
                template_id,
                app_type,
                display_name,
                source_image,
                ports,
                environment,
                memory_mb,
                cpu_cores,
                timeout_seconds,
            ) = row
            template = {
                "template_id": template_id,
                "app_type": app_type,
                "display_name": display_name,
                "source_image": source_image,
                "ports": _coerce_json(ports),
                "environment": _coerce_json(environment),
                "memory_mb": memory_mb,
                "cpu_cores": cpu_cores,
                "timeout_seconds": timeout_seconds,
            }
        # cpu_cores may arrive as Decimal from NUMERIC columns; normalize.
        if template["cpu_cores"] is not None:
            try:
                template["cpu_cores"] = float(template["cpu_cores"])
            except (TypeError, ValueError):
                pass
        return template

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------
    def list(self) -> List[dict]:
        """Return validated catalog entries; empty list when none valid.

        Each entry exposes: identifier, app_type, image, ports, env, memory_mb,
        cpu_cores (Req 7.5, 10.1).
        """
        entries = []
        for template in self._templates.values():
            entries.append(
                {
                    "identifier": template.get("template_id"),
                    "app_type": template.get("app_type"),
                    "image": template.get("source_image"),
                    "ports": template.get("ports"),
                    "env": template.get("environment"),
                    "memory_mb": template.get("memory_mb"),
                    "cpu_cores": template.get("cpu_cores"),
                }
            )
        return entries

    def get(self, template_id: str) -> Optional[dict]:
        """Return one validated template, or ``None`` if absent (Req 9.3/9.4, 10.4)."""
        return self._templates.get(template_id)

    @property
    def errors(self) -> List[Tuple[str, str]]:
        """Recorded ``(template_id, failing_field)`` pairs for rejected rows."""
        return list(self._errors)

    def is_empty(self) -> bool:
        """True when the loaded catalog has no valid templates (Req 7.5)."""
        return len(self._templates) == 0

    def indicator(self) -> Optional[str]:
        """Return the "no valid templates" indicator when empty, else None (Req 7.5)."""
        return NO_VALID_TEMPLATES if self.is_empty() else None

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    @staticmethod
    def validate(template: dict) -> List[str]:
        """Return the list of failing field names ([] means valid).

        Checks (Req 7.2, 7.3):
          - ``source_image`` present (non-empty)
          - ``ports``: at least one port, each an integer in 1..65535
          - ``environment``: every entry is a name-value pair
          - ``memory_mb``: 64..65536
          - ``cpu_cores``: 0.1..64
        """
        failing: List[str] = []

        if not isinstance(template, dict):
            # Nothing usable; report every checkable field as failing.
            return ["source_image", "ports", "environment", "memory_mb", "cpu_cores"]

        # source/image present (Req 7.2)
        source = template.get("source_image", template.get("source"))
        if not isinstance(source, str) or not source.strip():
            failing.append("source_image")

        # >=1 port, each in 1..65535 (Req 7.2)
        if not TemplateCatalog._ports_valid(template.get("ports")):
            failing.append("ports")

        # env vars are name-value pairs (Req 7.2)
        if not TemplateCatalog._env_valid(template.get("environment")):
            failing.append("environment")

        # 64 <= memory_mb <= 65536 (Req 7.2)
        if not TemplateCatalog._in_bounds(
            template.get("memory_mb"), MIN_MEMORY_MB, MAX_MEMORY_MB, integer=True
        ):
            failing.append("memory_mb")

        # 0.1 <= cpu_cores <= 64 (Req 7.2)
        if not TemplateCatalog._in_bounds(
            template.get("cpu_cores"), MIN_CPU_CORES, MAX_CPU_CORES
        ):
            failing.append("cpu_cores")

        return failing

    @staticmethod
    def _ports_valid(ports) -> bool:
        if not isinstance(ports, list) or len(ports) < 1:
            return False
        for port in ports:
            number = TemplateCatalog._port_number(port)
            if number is None:
                return False
            if not (MIN_PORT <= number <= MAX_PORT):
                return False
        return True

    @staticmethod
    def _port_number(port):
        """Extract an integer port number from a port entry.

        Accepts either a bare integer or a mapping with a ``container`` key
        (the seeded schema shape). Booleans and floats are rejected.
        """
        if isinstance(port, dict):
            port = port.get("container", port.get("port"))
        if isinstance(port, bool):
            return None
        if isinstance(port, int):
            return port
        return None

    @staticmethod
    def _env_valid(environment) -> bool:
        if environment is None:
            return False
        if not isinstance(environment, list):
            return False
        for entry in environment:
            if not isinstance(entry, dict):
                return False
            if "name" not in entry or "value" not in entry:
                return False
            if not isinstance(entry.get("name"), str) or not entry.get("name"):
                return False
        return True

    @staticmethod
    def _in_bounds(value, low, high, integer: bool = False) -> bool:
        if isinstance(value, bool):
            return False
        if integer and not isinstance(value, int):
            return False
        if not isinstance(value, Number):
            return False
        return low <= value <= high
