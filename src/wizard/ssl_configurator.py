"""SSL certificate configuration for the Setup Wizard (Requirement 5).

``SslConfigurator`` implements the two SSL sub-flows of the wizard's SSL step:

* :meth:`generate` wraps the existing ``scripts/generate_ssl.sh`` script,
  kicking it off and polling for progress with a hard 120s cap. On failure or
  timeout the previously configured certificate state is kept unchanged and the
  caller may retry generation or switch to upload (Req 5.1, 5.2, 5.6). The
  actual subprocess invocation is isolated in :meth:`_spawn` so the timing and
  polling logic can be unit-tested without launching a real 120s process.

* :meth:`upload` accepts exactly one PEM certificate and one PEM private key,
  each no larger than 1 MB, validates that the certificate matches the
  configured domain (SAN/CN) and that the key matches the certificate. On ANY
  mismatch or rejection the previously configured certificate state is left
  unchanged (Req 5.3, 5.4, 5.5).

PEM parsing/validation uses the ``cryptography`` library when it is available
(it is a project dependency). If it is not installed, a documented best-effort
fallback performs structural PEM checks only; :attr:`SslResult.best_effort`
flags that the strong domain/key-match guarantees could not be enforced.
"""

import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Upload limits (Req 5.3).
MAX_PEM_BYTES = 1 * 1024 * 1024  # 1 MB per file.

# Generation timing cap (Req 5.6): fail if generation does not finish in 120s.
GENERATION_TIMEOUT_SECONDS = 120
# Progress poll cadence while generation is in progress (Req 5.2).
POLL_INTERVAL_SECONDS = 1.0

# Job states surfaced to the wizard while generation runs (Req 5.2, 5.6).
JOB_PENDING = "pending"
JOB_RUNNING = "running"
JOB_SUCCEEDED = "succeeded"
JOB_FAILED = "failed"
JOB_TIMEOUT = "timeout"

# Detect the cryptography library once at import (Req 5.4, 5.5).
try:  # pragma: no cover - import guard
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa, ec, dsa
    from cryptography.x509.oid import NameOID, ExtensionOID

    _HAS_CRYPTOGRAPHY = True
except Exception:  # pragma: no cover - cryptography not installed
    _HAS_CRYPTOGRAPHY = False


@dataclass
class SslResult:
    """Outcome of an :meth:`SslConfigurator.upload` call.

    ``accepted`` is True only when every check passes. ``reason`` explains a
    rejection (or confirms acceptance). ``best_effort`` is True when the
    ``cryptography`` library was unavailable and only structural PEM checks
    were possible, so the domain-match and key-match guarantees were not fully
    enforced.
    """

    accepted: bool
    reason: str = ""
    best_effort: bool = False


@dataclass
class SslJob:
    """A generation job returned by :meth:`SslConfigurator.generate`.

    The job carries its current ``status`` (one of the ``JOB_*`` constants),
    an optional ``reason`` on failure/timeout, and the ``domain``/``email`` it
    was started for. ``prior_state_preserved`` records that a failed or
    timed-out generation left the previously configured certificate untouched
    (Req 5.6).
    """

    domain: str
    email: str
    status: str = JOB_PENDING
    reason: str = ""
    returncode: Optional[int] = None
    prior_state_preserved: bool = True
    _proc: object = field(default=None, repr=False)

    @property
    def in_progress(self) -> bool:
        return self.status in (JOB_PENDING, JOB_RUNNING)

    @property
    def succeeded(self) -> bool:
        return self.status == JOB_SUCCEEDED

    @property
    def can_retry(self) -> bool:
        """Failure/timeout allows retry or switching to upload (Req 5.6)."""
        return self.status in (JOB_FAILED, JOB_TIMEOUT)


class SslConfigurator:
    """Automatic-generation + manual-upload SSL configuration (Req 5)."""

    def __init__(self, ssl_dir: Optional[str] = None, script_path: Optional[str] = None):
        """
        :param ssl_dir: directory where certificates live; used to snapshot the
            prior certificate state so a failed operation can be shown to have
            left it unchanged. Defaults to ``<repo>/ssl``.
        :param script_path: path to ``generate_ssl.sh``. Defaults to
            ``<repo>/scripts/generate_ssl.sh``.
        """
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.ssl_dir = ssl_dir or os.path.join(base_dir, "ssl")
        self.script_path = script_path or os.path.join(base_dir, "scripts", "generate_ssl.sh")
        self._base_dir = base_dir

    # ------------------------------------------------------------------
    # Automatic generation (Req 5.1, 5.2, 5.6)
    # ------------------------------------------------------------------
    def generate(
        self,
        domain: str,
        email: str,
        timeout: int = GENERATION_TIMEOUT_SECONDS,
        poll_interval: float = POLL_INTERVAL_SECONDS,
    ) -> SslJob:
        """Run ``generate_ssl.sh`` for ``domain``/``email`` and poll to completion.

        The subprocess is launched via :meth:`_spawn` (isolated for testing) and
        polled at ``poll_interval`` until it exits or ``timeout`` seconds elapse
        (default 120s, Req 5.6). On non-zero exit, spawn failure, or timeout the
        job is marked failed/timeout, the prior certificate state is left
        unchanged, and the caller may retry or switch to upload (Req 5.6).

        This does not block for the full 120s in the success path: it returns as
        soon as the process finishes. The cap only bounds the worst case.
        """
        job = SslJob(domain=domain, email=email, status=JOB_PENDING)

        try:
            proc = self._spawn(domain, email)
        except Exception as exc:
            logger.error("Failed to start SSL generation for %s: %s", domain, exc)
            job.status = JOB_FAILED
            job.reason = f"could not start certificate generation: {exc}"
            job.prior_state_preserved = True
            return job

        job._proc = proc
        job.status = JOB_RUNNING

        deadline = time.monotonic() + max(0, timeout)
        while True:
            returncode = self._poll(proc)
            if returncode is not None:
                job.returncode = returncode
                if returncode == 0:
                    job.status = JOB_SUCCEEDED
                    job.reason = "certificate generated"
                    job.prior_state_preserved = False  # new cert is now in place
                else:
                    job.status = JOB_FAILED
                    job.reason = f"generation script exited with code {returncode}"
                    job.prior_state_preserved = True
                return job

            if time.monotonic() >= deadline:
                # Cap reached: terminate and keep the prior cert state (Req 5.6).
                self._terminate(proc)
                job.status = JOB_TIMEOUT
                job.reason = f"certificate generation did not complete within {timeout}s"
                job.prior_state_preserved = True
                return job

            time.sleep(poll_interval)

    # -- subprocess isolation (overridable / patchable in tests) -----------
    def _spawn(self, domain: str, email: str):
        """Launch ``generate_ssl.sh`` as a subprocess and return the handle.

        Isolated so tests can patch it with a fake process (no real 120s wait).
        The script reads ``DOMAIN`` from the environment; ``email`` is forwarded
        as ``ADMIN_EMAIL`` for scripts that consume it.
        """
        env = dict(os.environ)
        env["DOMAIN"] = domain
        env["ADMIN_EMAIL"] = email
        return subprocess.Popen(
            ["bash", self.script_path],
            cwd=self._base_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

    @staticmethod
    def _poll(proc):
        """Return the process exit code, or None if still running."""
        return proc.poll()

    @staticmethod
    def _terminate(proc):
        """Best-effort terminate of a timed-out generation process."""
        try:
            proc.terminate()
        except Exception:  # pragma: no cover - defensive
            pass

    # ------------------------------------------------------------------
    # Manual upload (Req 5.3, 5.4, 5.5)
    # ------------------------------------------------------------------
    def upload(self, cert_pem, key_pem, domain: str) -> SslResult:
        """Validate and (conceptually) accept an uploaded cert + key pair.

        Accepted iff:
          * exactly one PEM certificate and one PEM key are supplied,
          * each is <= 1 MB (Req 5.3),
          * the certificate matches ``domain`` via SAN or CN (Req 5.4),
          * the private key matches the certificate (Req 5.5).

        On ANY rejection the previously configured certificate state is left
        unchanged (this method performs no writes; acceptance is signalled to
        the caller which is responsible for persistence) (Req 5.4, 5.5).
        """
        cert_bytes = self._as_bytes(cert_pem)
        key_bytes = self._as_bytes(key_pem)

        # Presence: exactly one cert + one key.
        if not cert_bytes or not key_bytes:
            return SslResult(False, "a certificate file and a private key file are both required")

        # Size cap (Req 5.3).
        if len(cert_bytes) > MAX_PEM_BYTES:
            return SslResult(False, "certificate file exceeds the 1 MB limit")
        if len(key_bytes) > MAX_PEM_BYTES:
            return SslResult(False, "private key file exceeds the 1 MB limit")

        if not _HAS_CRYPTOGRAPHY:
            return self._upload_best_effort(cert_bytes, key_bytes, domain)

        # Parse the certificate (must be a single PEM cert) (Req 5.3).
        try:
            cert = x509.load_pem_x509_certificate(cert_bytes)
        except Exception as exc:
            return SslResult(False, f"certificate is not valid PEM: {exc}")

        # Reject bundles that contain more than one certificate (exactly one).
        if cert_bytes.count(b"-----BEGIN CERTIFICATE-----") != 1:
            return SslResult(False, "exactly one certificate is required")

        # Parse the private key (must be a single PEM key) (Req 5.3).
        try:
            key = serialization.load_pem_private_key(key_bytes, password=None)
        except Exception as exc:
            return SslResult(False, f"private key is not valid PEM: {exc}")

        # Certificate must match the configured domain via SAN or CN (Req 5.4).
        if not self._cert_matches_domain(cert, domain):
            return SslResult(False, "certificate does not match the configured domain")

        # Private key must match the certificate (Req 5.5).
        if not self._key_matches_cert(cert, key):
            return SslResult(False, "private key does not match the certificate")

        return SslResult(True, "certificate accepted")

    # -- cryptography-backed checks ----------------------------------------
    @staticmethod
    def _cert_matches_domain(cert, domain: str) -> bool:
        """True iff ``domain`` is covered by the cert's SAN dNSNames or CN (Req 5.4)."""
        if not domain:
            return False
        names = []
        # Subject Alternative Names (preferred).
        try:
            san = cert.extensions.get_extension_for_oid(
                ExtensionOID.SUBJECT_ALTERNATIVE_NAME
            ).value
            names.extend(san.get_values_for_type(x509.DNSName))
        except Exception:
            pass
        # Common Name (fallback).
        try:
            for attr in cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME):
                names.append(attr.value)
        except Exception:
            pass
        return any(SslConfigurator._name_matches(name, domain) for name in names)

    @staticmethod
    def _name_matches(cert_name: str, domain: str) -> bool:
        """Match a certificate name against a domain, honoring a leading wildcard."""
        if not cert_name:
            return False
        cert_name = cert_name.strip().lower().rstrip(".")
        domain = domain.strip().lower().rstrip(".")
        if cert_name == domain:
            return True
        if cert_name.startswith("*."):
            # Wildcard matches exactly one left-most label.
            suffix = cert_name[1:]  # ".example.com"
            if not domain.endswith(suffix):
                return False
            left = domain[: -len(suffix)]
            return bool(left) and "." not in left
        return False

    @staticmethod
    def _key_matches_cert(cert, key) -> bool:
        """True iff ``key``'s public key equals the certificate's public key (Req 5.5)."""
        try:
            cert_pub = cert.public_key().public_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            key_pub = key.public_key().public_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            return cert_pub == key_pub
        except Exception:
            return False

    # -- best-effort fallback (cryptography unavailable) -------------------
    @staticmethod
    def _upload_best_effort(cert_bytes: bytes, key_bytes: bytes, domain: str) -> SslResult:
        """Structural-only validation when ``cryptography`` is not installed.

        Without the library the strong domain-match / key-match guarantees
        (Req 5.4, 5.5) cannot be enforced. This verifies only that each input
        looks like a single PEM block of the expected type; the result is
        flagged ``best_effort`` so the caller/UI can require the library for a
        strict acceptance. On any structural rejection prior state is unchanged.
        """
        if cert_bytes.count(b"-----BEGIN CERTIFICATE-----") != 1:
            return SslResult(False, "exactly one PEM certificate is required", best_effort=True)
        has_key = (
            b"-----BEGIN PRIVATE KEY-----" in key_bytes
            or b"-----BEGIN RSA PRIVATE KEY-----" in key_bytes
            or b"-----BEGIN EC PRIVATE KEY-----" in key_bytes
        )
        if not has_key:
            return SslResult(False, "a PEM private key is required", best_effort=True)
        logger.warning(
            "cryptography library unavailable; SSL upload validated best-effort only "
            "(domain match and key match NOT verified)."
        )
        return SslResult(
            True,
            "certificate accepted (best-effort: install 'cryptography' for full validation)",
            best_effort=True,
        )

    # -- input coercion ----------------------------------------------------
    @staticmethod
    def _as_bytes(value) -> bytes:
        """Coerce a PEM input (bytes/str/None) to bytes; None/empty -> b""."""
        if value is None:
            return b""
        if isinstance(value, bytes):
            return value
        if isinstance(value, bytearray):
            return bytes(value)
        if isinstance(value, str):
            return value.encode("utf-8")
        return b""
