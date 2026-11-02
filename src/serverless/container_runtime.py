"""Container Runtime Abstraction for Serverless Docker Execution.

Provides an abstract base class for Docker and Podman container runtimes,
allowing the worker service to execute jobs using whichever runtime is available.
"""

import logging
import shutil
import subprocess
import uuid
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from src.aro.execution_manager import assert_image_pinned
from src.execution_policy import (
    BackoffParams,
    OutcomeStatus,
    run_with_policy,
    ssh_is_transient,
)
from src.ssh_utils import _redact

logger = logging.getLogger(__name__)

# Bounded wall-clock budget for a single image pull attempt and the number of
# attempts a transient pull failure is retried through the shared policy (R5.3).
PULL_TIMEOUT_DEFAULT = 300
PULL_MAX_ATTEMPTS = 3
# Bounded budget for a one-shot ``docker logs`` capture (R5.1).
LOGS_TIMEOUT_DEFAULT = 60


class ContainerRuntime(ABC):
    """Abstract interface for container runtimes (Docker/Podman).

    Subclasses implement the actual CLI interactions for pulling images,
    running containers with security constraints, and managing container lifecycle.
    """

    @staticmethod
    def detect() -> "ContainerRuntime":
        """Detect available container runtime on the system.

        Checks for Docker first, then Podman. Returns an instance of the
        appropriate runtime subclass. Uses both shutil.which() to check
        if the binary exists on PATH and subprocess.run() to verify it
        responds correctly.

        Returns:
            ContainerRuntime: An instance of DockerRuntime or PodmanRuntime.

        Raises:
            RuntimeError: If no supported container runtime is found.
        """
        # Check Docker first
        if shutil.which("docker"):
            try:
                result = subprocess.run(
                    ["docker", "--version"],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    return DockerRuntime()
            except (OSError, FileNotFoundError):
                pass

        # Fall back to Podman
        if shutil.which("podman"):
            try:
                result = subprocess.run(
                    ["podman", "--version"],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    return PodmanRuntime()
            except (OSError, FileNotFoundError):
                pass

        raise RuntimeError(
            "No supported container runtime found. Install Docker or Podman."
        )

    @abstractmethod
    def pull_image(self, image: str) -> None:
        """Pull a container image from a registry.

        Args:
            image: Full image reference (e.g. 'docker.io/library/python:3.11').

        Raises:
            RuntimeError: If the image pull fails.
        """
        ...

    @abstractmethod
    def run_container(
        self,
        image: str,
        command: List[str],
        env: Dict[str, str],
        timeout: int,
        **security_opts,
    ) -> str:
        """Run a container in detached mode with security constraints.

        Args:
            image: The container image to run.
            command: Command and arguments to execute inside the container.
            env: Environment variables to pass to the container.
            timeout: Maximum execution time in seconds.
            **security_opts: Additional security options such as:
                - memory_limit (str): Memory limit (e.g. '512m').
                - cpu_limit (str): CPU limit (e.g. '1').
                - network (str): Network mode (e.g. 'none').
                - read_only (bool): Mount root filesystem as read-only.
                - user (str): User to run the container as.
                - runtime_type (str): Container runtime to use ('runc' or
                  'kata'). When 'kata' (or any non-'runc' value), a
                  `--runtime <type>` flag is added so the container runs
                  inside a Kata MicroVM. Defaults to 'runc'.

        Returns:
            str: The container ID of the started container.

        Raises:
            RuntimeError: If the container fails to start.
        """
        ...

    @abstractmethod
    def stop_container(self, container_id: str, timeout: int = 10) -> None:
        """Stop a running container.

        Args:
            container_id: The ID of the container to stop.
            timeout: Seconds to wait before forcefully killing the container.

        Raises:
            RuntimeError: If the container cannot be stopped.
        """
        ...

    @abstractmethod
    def get_logs(self, container_id: str, stream: str) -> str:
        """Retrieve logs from a container.

        Args:
            container_id: The ID of the container.
            stream: Which log stream to retrieve ('stdout' or 'stderr').

        Returns:
            str: The log content for the requested stream.

        Raises:
            RuntimeError: If logs cannot be retrieved.
        """
        ...

    @abstractmethod
    def wait(self, container_id: str, timeout: int) -> int:
        """Wait for a container to finish execution.

        Args:
            container_id: The ID of the container to wait on.
            timeout: Maximum seconds to wait before raising TimeoutError.

        Returns:
            int: The container's exit code.

        Raises:
            TimeoutError: If the container does not finish within the timeout.
            RuntimeError: If waiting fails for another reason.
        """
        ...

    @abstractmethod
    def cleanup(self, container_id: str) -> None:
        """Remove a container and its associated resources.

        Should be called after a container has finished (or been stopped)
        to free up system resources.

        Args:
            container_id: The ID of the container to remove.
        """
        ...


class DockerRuntime(ContainerRuntime):
    """Docker Engine implementation of the container runtime.

    Executes containers via the Docker CLI with full security hardening:
    read-only filesystem, unprivileged user, all capabilities dropped,
    resource limits, no network access, and process restrictions.
    """

    _binary = "docker"

    def pull_image(self, image: str) -> None:
        """Pull a digest-pinned container image using docker pull.

        The image must be digest-pinned (``name@sha256:...``) before any pull
        runs: an unpinned reference is a deterministic policy failure that is
        rejected with no pull and no retry (R5.2). The pull itself is wrapped in
        the shared execution policy so a transient registry failure (5xx,
        connection reset, timeout) is retried with bounded backoff while a
        deterministic failure (unknown manifest, denied) fails immediately
        (R5.3). Log output carries only the redacted command summary so pull
        credentials embedded in the reference never reach the log (R5.8).

        Args:
            image: Full image reference, digest-pinned
                (e.g. 'docker.io/library/python@sha256:...').

        Raises:
            ExecutionPolicyError: If the image is not digest-pinned.
            RuntimeError: If the image pull fails after exhausting retries.
        """
        # Digest pin gate: deterministic failure, no pull, no retry (R5.2).
        assert_image_pinned(image)

        cmd = [self._binary, "pull", image]
        logger.info("Pulling image: %s", _redact(cmd))

        def _pull(_token):
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=PULL_TIMEOUT_DEFAULT,
            )
            if result.returncode != 0:
                # Raise an error whose text carries the registry stderr so the
                # transient classifier can route connect/timeout/reset failures
                # to a retry and leave deterministic failures terminal (R5.3).
                err = RuntimeError(
                    f"Failed to pull image '{image}': {result.stderr.strip()}"
                )
                err.stderr = result.stderr
                raise err
            return result

        outcome = run_with_policy(
            _pull,
            timeout=PULL_TIMEOUT_DEFAULT,
            max_attempts=PULL_MAX_ATTEMPTS,
            backoff=BackoffParams(),
            is_transient=ssh_is_transient,
        )
        if outcome.status is not OutcomeStatus.SUCCEEDED:
            if outcome.error is not None:
                raise outcome.error
            raise RuntimeError(
                f"Failed to pull image '{image}': {outcome.status.value}"
            )

    def run_container(
        self,
        image: str,
        command: List[str],
        env: Dict[str, str],
        timeout: int,
        **opts,
    ) -> str:
        """Run a container in detached mode with security constraints.

        Generates a unique container name using UUID and applies all security
        flags: --read-only, --user nobody, --cap-drop ALL, --memory, --cpus,
        --network none, --security-opt no-new-privileges, --pids-limit 256.

        Args:
            image: The container image to run.
            command: Command and arguments to execute inside the container.
            env: Environment variables to pass to the container.
            timeout: Maximum execution time in seconds (used by worker for wait).
            **opts: Additional options:
                - memory_limit (str): Memory limit (default '512m').
                - cpu_limit (str): CPU limit (default '1').
                - network (str): Network mode (default 'none').
                - runtime_type (str): Container runtime ('runc' or 'kata').
                  Adds `--runtime <type>` for non-'runc' values so the
                  container runs inside a Kata MicroVM. Default 'runc'.

        Returns:
            str: The container ID of the started container.

        Raises:
            RuntimeError: If the container fails to start.
        """
        container_name = f"job-{uuid.uuid4()}"
        cmd = [self._binary, "run", "-d", "--name", container_name]
        # Container runtime selection (e.g. 'kata' MicroVM isolation). 'runc' is
        # the default, so the flag is only emitted for non-default values.
        runtime_type = opts.get("runtime_type", "runc")
        if runtime_type and runtime_type != "runc":
            cmd += ["--runtime", runtime_type]
        # Security flags
        cmd += ["--read-only", "--user", "nobody"]
        cmd += ["--cap-drop", "ALL"]
        cmd += ["--memory", opts.get("memory_limit", "512m")]
        cmd += ["--cpus", opts.get("cpu_limit", "1")]
        cmd += ["--network", opts.get("network", "none")]
        cmd += ["--security-opt", "no-new-privileges"]
        cmd += ["--pids-limit", "256"]
        # Environment variables
        for k, v in env.items():
            cmd += ["-e", f"{k}={v}"]
        # Image and command
        cmd += [image] + command

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to start container: {result.stderr.strip()}"
            )
        return result.stdout.strip()

    def stop_container(self, container_id: str, timeout: int = 10) -> None:
        """Stop a running container using docker stop.

        Args:
            container_id: The ID or name of the container to stop.
            timeout: Seconds to wait before forcefully killing the container.

        Raises:
            RuntimeError: If the container cannot be stopped.
        """
        result = subprocess.run(
            [self._binary, "stop", "-t", str(timeout), container_id],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to stop container '{container_id}': {result.stderr.strip()}"
            )

    def get_logs(self, container_id: str, stream: str) -> str:
        """Retrieve logs from a container for a specific stream.

        Args:
            container_id: The ID or name of the container.
            stream: Which log stream to retrieve ('stdout' or 'stderr').

        Returns:
            str: The log content for the requested stream.

        Raises:
            RuntimeError: If logs cannot be retrieved.
        """
        # ``docker logs`` multiplexes the container's stdout onto the
        # subprocess's stdout and the container's stderr onto the subprocess's
        # stderr. There is no reliable ``--stdout``/``--stderr`` filter: the
        # old ``docker logs --stderr`` branch returned the docker CLI's own
        # error channel, not the container's stderr. Run the command once and
        # read the correct subprocess stream for the requested logical stream
        # (R5.1).
        result = subprocess.run(
            [self._binary, "logs", container_id],
            capture_output=True,
            text=True,
            timeout=LOGS_TIMEOUT_DEFAULT,
        )
        return result.stdout if stream == "stdout" else result.stderr

    def wait(self, container_id: str, timeout: int) -> int:
        """Wait for a container to finish execution using docker wait.

        Args:
            container_id: The ID or name of the container to wait on.
            timeout: Maximum seconds to wait before raising TimeoutError.

        Returns:
            int: The container's exit code.

        Raises:
            TimeoutError: If the container does not finish within the timeout.
            RuntimeError: If waiting fails for another reason.
        """
        try:
            result = subprocess.run(
                [self._binary, "wait", container_id],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise TimeoutError(
                f"Container '{container_id}' did not finish within {timeout} seconds"
            )

        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to wait on container '{container_id}': {result.stderr.strip()}"
            )
        return int(result.stdout.strip())

    def cleanup(self, container_id: str) -> None:
        """Remove a container forcefully using docker rm -f.

        Args:
            container_id: The ID or name of the container to remove.
        """
        subprocess.run(
            [self._binary, "rm", "-f", container_id],
            capture_output=True,
            text=True,
        )


class PodmanRuntime(DockerRuntime):
    """Podman implementation of the container runtime (CLI-compatible with Docker).

    Podman provides a Docker-compatible CLI interface. This class inherits all
    functionality from DockerRuntime and simply overrides the binary name to use
    'podman' instead of 'docker'.
    """

    _binary = "podman"
