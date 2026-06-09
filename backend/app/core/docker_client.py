"""Docker Engine HTTP API client with TLS support."""

import logging
from typing import Any, BinaryIO

import docker
from docker.models.containers import Container

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class DockerClientWrapper:
    """Wrapper around Docker SDK for container management."""

    def __init__(self) -> None:
        """Initialize Docker client with TLS configuration."""
        docker_kwargs: dict[str, Any] = {
            "base_url": settings.docker_host,
            "version": "auto",
        }

        # Add TLS configuration if provided
        if settings.docker_tls_ca:
            docker_kwargs["tls"] = docker.tls.TLSConfig(
                ca_cert=settings.docker_tls_ca,
                client_cert=(settings.docker_tls_cert, settings.docker_tls_key),
                verify=True,
            )

        self.client = docker.DockerClient(**docker_kwargs)
        logger.info(f"Docker client initialized: {settings.docker_host}")

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
        command: str,
        environment: dict[str, str] | None = None,
        volumes: dict[str, dict[str, str]] | None = None,
        working_dir: str | None = None,
        network: str | None = None,
        name: str | None = None,
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


# Singleton instance
_docker_client: DockerClientWrapper | None = None


def get_docker_client() -> DockerClientWrapper:
    """Get singleton Docker client instance."""
    global _docker_client
    if _docker_client is None:
        _docker_client = DockerClientWrapper()
    return _docker_client
