"""Docker Engine HTTP API client with TLS support."""

import base64
import logging
from typing import Any, BinaryIO, Optional

import docker
from docker.client import DockerClient

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

    def pull_image(self, image: str) -> None:
        """Pull Docker image from registry.

        Args:
            image: Image name (e.g., 'nginx:latest')
        """
        logger.info(f"Pulling image: {image}")
        self.client.images.pull(image)
        logger.info(f"Image pulled: {image}")

    def create_container(
        self,
        image: str,
        command: str,
        environment: Optional[dict[str, str]] = None,
        volumes: Optional[dict[str, dict[str, str]]] = None,
        working_dir: Optional[str] = None,
        network: Optional[str] = None,
        name: Optional[str] = None,
    ) -> Any:
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
        self, container: Any, timeout: int = 600
    ) -> tuple[int, str]:
        """Wait for container to complete execution.

        Args:
            container: Container object
            timeout: Timeout in seconds

        Returns:
            Tuple of (exit_code, logs)
        """
        logger.info(f"Waiting for container: {container.id}")

        # Wait for container to finish
        result = container.wait(timeout=timeout)
        exit_code = result.get("StatusCode", 1)

        # Get logs
        logs = container.logs(stdout=True, stderr=True).decode("utf-8")

        logger.info(f"Container {container.id} exited with code: {exit_code}")
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
_docker_client: Optional[DockerClientWrapper] = None


def get_docker_client() -> DockerClientWrapper:
    """Get singleton Docker client instance."""
    global _docker_client
    if _docker_client is None:
        _docker_client = DockerClientWrapper()
    return _docker_client
