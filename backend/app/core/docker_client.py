"""Docker Engine HTTP API client with TLS support."""

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Any, BinaryIO
from urllib.parse import urlsplit, urlunsplit

import docker
from docker.constants import DEFAULT_TIMEOUT_SECONDS
from docker.models.containers import Container
from docker.utils import parse_host

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass(frozen=True)
class DockerConnectionConfig:
    """Connection details identifying one Docker daemon client."""

    host: str
    tls_ca: str | None = None
    tls_cert: str | None = None
    tls_key: str | None = None

    @classmethod
    def from_settings(cls, runtime_settings: Any) -> "DockerConnectionConfig":
        def optional_path(name: str) -> str | None:
            return str(getattr(runtime_settings, name, "") or "").strip() or None

        return cls(
            host=str(runtime_settings.docker_host).strip(),
            tls_ca=optional_path("docker_tls_ca"),
            tls_cert=optional_path("docker_tls_cert"),
            tls_key=optional_path("docker_tls_key"),
        )


def canonicalize_docker_host(host: str, *, tls_enabled: bool) -> str:
    """Return the endpoint identity Docker SDK uses for one daemon connection."""
    canonical = parse_host(host.strip(), tls=tls_enabled)
    parsed = urlsplit(canonical)
    if parsed.scheme == "http+unix":
        return canonical

    hostname = parsed.hostname
    if hostname is None:
        return canonical
    hostname = hostname.rstrip(".").lower()
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = hostname
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path, "", ""))


def resolve_docker_connection(
    runtime_settings: Any,
    *,
    docker_host: str | None = None,
    docker_tls_ca: str | None = None,
    docker_tls_cert: str | None = None,
    docker_tls_key: str | None = None,
) -> DockerConnectionConfig:
    """Resolve profile target fields, falling back to the complete global target."""
    host = (docker_host or "").strip()
    if not host:
        return DockerConnectionConfig.from_settings(runtime_settings)
    return DockerConnectionConfig(
        host=host,
        tls_ca=(docker_tls_ca or "").strip() or None,
        tls_cert=(docker_tls_cert or "").strip() or None,
        tls_key=(docker_tls_key or "").strip() or None,
    )


class DockerClientWrapper:
    """Wrapper around Docker SDK for container management."""

    def __init__(
        self,
        connection: DockerConnectionConfig | None = None,
        *,
        connect_timeout: int = 10,
        operation_timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Initialize Docker client with TLS configuration."""
        connection = connection or DockerConnectionConfig.from_settings(settings)
        docker_kwargs: dict[str, Any] = {
            "base_url": connection.host,
            "version": "auto",
            "timeout": connect_timeout,
        }

        # Add TLS configuration if provided
        if connection.tls_ca:
            docker_kwargs["tls"] = docker.tls.TLSConfig(
                ca_cert=connection.tls_ca,
                client_cert=(connection.tls_cert, connection.tls_key),
                verify=True,
            )

        self.client = docker.DockerClient(**docker_kwargs)
        # ``version=auto`` performs I/O during construction. Keep that handshake short,
        # then restore the normal Docker SDK timeout for image pulls and task execution.
        self.client.api.timeout = operation_timeout
        self.connection = connection
        logger.info("Docker client initialized: %s", connection.host)

    def inspect_server(self) -> dict[str, Any]:
        """Verify connectivity and return the small server identity used by admins."""
        self.client.ping()
        version = self.client.version()
        info = self.client.info()
        return {
            "server_version": version.get("Version") or info.get("ServerVersion"),
            "architecture": info.get("Architecture") or version.get("Arch"),
            "operating_system": info.get("OperatingSystem") or version.get("Os"),
        }

    def pull_image(self, image: str, force: bool = False) -> None:
        """Pull Docker image from registry if not exists locally.

        Args:
            image: Image name (e.g., 'nginx:latest')
            force: Force pull even if image exists locally (default: False)
        """
        # Check if image exists locally first
        if not force:
            try:
                self.client.images.get(image)
                logger.info(f"Image already exists locally: {image}")
                return
            except docker.errors.NotFound:
                pass

        # Pull image (force pull or if not exists)
        logger.info(f"Pulling image: {image}")
        try:
            self.client.images.pull(image)
            logger.info(f"Image pulled: {image}")
        except Exception:
            # If pull fails (e.g., local image, no registry), try to use existing
            try:
                self.client.images.get(image)
                logger.info(f"Pull failed but using existing local image: {image}")
            except docker.errors.NotFound:
                logger.warning(f"Image not found locally or in registry: {image}")
                raise

    def create_container(
        self,
        image: str,
        command: str | list[str],
        environment: dict[str, str] | None = None,
        volumes: dict[str, dict[str, str]] | None = None,
        working_dir: str | None = None,
        network: str | None = None,
        name: str | None = None,
        entrypoint: str | list[str] | None = None,
        user: str | None = None,
        labels: dict[str, str] | None = None,
        tmpfs: dict[str, str] | None = None,
    ) -> Container:
        """Create and start a Docker container.

        Args:
            image: Docker image to use
            command: Command to run in container
            environment: Environment variables
            volumes: Volume mounts (host_path: container_path)
            working_dir: Working directory in container
            network: Network to attach
            name: Container name
            entrypoint: Optional image entrypoint override
            user: Optional container user override
            labels: Optional container labels
            tmpfs: Optional tmpfs mounts keyed by container path

        Returns:
            Container object
        """
        logger.info(f"Creating container with image: {image}, name: {name}")

        if name:
            try:
                existing = self.client.containers.get(name)
                logger.info(f"Removing stale container {name} (status: {existing.status})")
                existing.remove(force=True)
            except docker.errors.NotFound:
                pass

        container = self.client.containers.run(
            image,
            command,
            detach=True,
            environment=environment,
            volumes=volumes,
            working_dir=working_dir,
            network=network,
            remove=False,
            name=name,
            entrypoint=entrypoint,
            user=user,
            labels=labels,
            tmpfs=tmpfs,
        )

        logger.info(f"Container created: {container.id}")
        return container

    def wait_for_container(
        self, container: Container, timeout: int = 600
    ) -> tuple[int, str]:
        """Wait for container to complete execution.

        Args:
            container: Container object
            timeout: Timeout in seconds

        Returns:
            Tuple of (exit_code, logs)

        Raises:
            TimeoutError: If container execution times out
            ContainerError: If container exits with non-zero code
        """
        logger.info(f"Waiting for container: {container.id}, timeout: {timeout}s")

        try:
            # Wait for container to finish
            result = container.wait(timeout=timeout)
            exit_code = result.get("StatusCode", 1)
        except Exception as e:
            logger.error(f"Container wait failed: {e}")
            # Try to get logs even if wait failed
            try:
                logs = container.logs(stdout=True, stderr=True).decode("utf-8")
            except Exception as inner_e:
                logs = f"Failed to get logs: {inner_e}"
            return -1, logs

        # Get logs
        try:
            logs = container.logs(stdout=True, stderr=True).decode("utf-8")
        except Exception as e:
            logger.warning(f"Failed to get container logs: {e}")
            logs = f"Failed to decode logs: {e}"

        # Log exit code and status
        if exit_code == 0:
            logger.info(f"Container {container.id} completed successfully")
        else:
            logger.warning(f"Container {container.id} exited with code: {exit_code}")

        return exit_code, logs

    def get_container_logs(self, container: Any, follow: bool = False) -> BinaryIO:
        """Get container logs.

        Args:
            container: Container object
            follow: Whether to follow logs

        Returns:
            Log output
        """
        return container.logs(stdout=True, stderr=True, follow=follow)

    def read_file_from_container(self, container: Any, container_path: str) -> bytes | None:
        """Read a single file from a (possibly stopped) container via the Docker API.

        Uses container.get_archive() which works with both local and remote Docker daemons,
        avoiding any reliance on shared volume mounts between the scheduler and the Docker host.

        Args:
            container: Container object
            container_path: Absolute path to the file inside the container

        Returns:
            File contents as bytes, or None if the file cannot be retrieved.
        """
        import io
        import tarfile

        try:
            bits, _stat = container.get_archive(container_path)
            buf = io.BytesIO()
            for chunk in bits:
                buf.write(chunk)
            buf.seek(0)
            with tarfile.open(fileobj=buf) as tar:
                members = tar.getmembers()
                if not members:
                    return None
                extracted = tar.extractfile(members[0])
                if extracted is None:
                    return None
                return extracted.read()
        except Exception as exc:
            logger.info(f"Could not read {container_path!r} from container {container.id}: {exc}")
            return None

    def remove_container(self, container: Any, force: bool = False) -> None:
        """Remove a container.

        Args:
            container: Container object
            force: Force removal
        """
        logger.info(f"Removing container: {container.id}")
        container.remove(force=force)
        logger.info(f"Container removed: {container.id}")

    def close(self) -> None:
        """Close Docker client connection."""
        self.client.close()
        logger.info("Docker client closed")


# Connection-keyed process cache. The legacy singleton name remains for tests and callers
# that use only the global Docker target.
_docker_client: DockerClientWrapper | None = None
_docker_clients: dict[DockerConnectionConfig, DockerClientWrapper] = {}
_docker_clients_lock = threading.Lock()
_docker_client_creation_locks: dict[DockerConnectionConfig, threading.Lock] = {}


def get_docker_client(
    connection: DockerConnectionConfig | None = None,
) -> DockerClientWrapper:
    """Get a cached Docker client for one target connection."""
    global _docker_client
    if connection is None and _docker_client is not None:
        return _docker_client

    resolved = connection or DockerConnectionConfig.from_settings(settings)
    with _docker_clients_lock:
        client = _docker_clients.get(resolved)
        if client is not None:
            if connection is None:
                _docker_client = client
            return client
        creation_lock = _docker_client_creation_locks.setdefault(
            resolved,
            threading.Lock(),
        )

    # Client construction negotiates the API version over the network. Serialize only
    # callers for the same daemon so an unavailable target cannot block other targets.
    with creation_lock:
        with _docker_clients_lock:
            client = _docker_clients.get(resolved)
        if client is None:
            client = (
                DockerClientWrapper(resolved)
                if connection is not None
                else DockerClientWrapper()
            )
            with _docker_clients_lock:
                _docker_clients[resolved] = client
        if connection is None:
            _docker_client = client
        return client


async def get_docker_client_async(
    connection: DockerConnectionConfig | None = None,
) -> DockerClientWrapper:
    """Get a cached client without blocking the event loop during negotiation."""
    return await asyncio.to_thread(get_docker_client, connection)


def close_docker_clients() -> None:
    """Close all cached clients, primarily for process shutdown and tests."""
    global _docker_client
    with _docker_clients_lock:
        clients = list({id(client): client for client in _docker_clients.values()}.values())
        _docker_clients.clear()
        _docker_client_creation_locks.clear()
        _docker_client = None
    for client in clients:
        client.close()
