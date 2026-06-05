"""Additional coverage tests for DockerClientWrapper.

Targets missed lines: 29, 36, 51-52, 59-66, 95-100, 188-189, 201.
"""

from unittest.mock import MagicMock, patch

import docker
import docker.errors
import docker.tls
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_wrapper():
    """Create a DockerClientWrapper without running __init__."""
    from app.core.docker_client import DockerClientWrapper

    wrapper = DockerClientWrapper.__new__(DockerClientWrapper)
    wrapper.client = MagicMock()
    return wrapper


# ---------------------------------------------------------------------------
# __init__ – TLS and non-TLS paths  (lines 28-36)
# ---------------------------------------------------------------------------

class TestDockerClientInit:
    """Tests for DockerClientWrapper.__init__."""

    @patch("app.core.docker_client.docker.DockerClient")
    @patch("app.core.docker_client.docker.tls.TLSConfig")
    @patch("app.core.docker_client.settings")
    def test_init_with_tls_config(self, mock_settings, mock_tls_cls, mock_docker_cls):
        """__init__ passes TLS configuration when docker_tls_ca is set (line 29)."""
        mock_settings.docker_host = "tcp://docker-host:2376"
        mock_settings.docker_tls_ca = "/certs/ca.pem"
        mock_settings.docker_tls_cert = "/certs/cert.pem"
        mock_settings.docker_tls_key = "/certs/key.pem"

        mock_tls_obj = MagicMock()
        mock_tls_cls.return_value = mock_tls_obj

        from app.core.docker_client import DockerClientWrapper

        wrapper = DockerClientWrapper()

        mock_tls_cls.assert_called_once_with(
            ca_cert="/certs/ca.pem",
            client_cert=("/certs/cert.pem", "/certs/key.pem"),
            verify=True,
        )
        mock_docker_cls.assert_called_once_with(
            base_url="tcp://docker-host:2376",
            version="auto",
            tls=mock_tls_obj,
        )
        # line 36: logger.info is called (implicitly tests line 36 is reached)
        assert wrapper.client is mock_docker_cls.return_value

    @patch("app.core.docker_client.docker.DockerClient")
    @patch("app.core.docker_client.settings")
    def test_init_without_tls_config(self, mock_settings, mock_docker_cls):
        """__init__ skips TLS when docker_tls_ca is falsy (line 28 else, line 35-36)."""
        mock_settings.docker_host = "unix:///var/run/docker.sock"
        mock_settings.docker_tls_ca = None

        from app.core.docker_client import DockerClientWrapper

        wrapper = DockerClientWrapper()

        mock_docker_cls.assert_called_once_with(
            base_url="unix:///var/run/docker.sock",
            version="auto",
        )
        assert wrapper.client is mock_docker_cls.return_value


# ---------------------------------------------------------------------------
# pull_image – image-not-found-locally and pull-failure paths (lines 51-66)
# ---------------------------------------------------------------------------

class TestPullImageCoverage:
    """Cover pull_image branches not exercised by existing tests."""

    def test_pull_image_not_found_locally_triggers_pull(self):
        """Image doesn't exist locally → NotFound raised → image is pulled (lines 51-52)."""
        wrapper = _make_wrapper()
        wrapper.client.images.get.side_effect = docker.errors.NotFound("not found")
        wrapper.client.images.pull.return_value = MagicMock()

        wrapper.pull_image("myimage:v1")

        wrapper.client.images.get.assert_called_once_with("myimage:v1")
        wrapper.client.images.pull.assert_called_once_with("myimage:v1")

    def test_pull_fails_but_local_image_exists(self):
        """Pull fails with generic error; fallback image.get succeeds (lines 59-63)."""
        wrapper = _make_wrapper()

        # First call: image not found (trigger pull)
        # Second call (inside except): image found locally
        wrapper.client.images.get.side_effect = [
            docker.errors.NotFound("not found"),  # line 48
            MagicMock(),  # line 62 — fallback succeeds
        ]
        wrapper.client.images.pull.side_effect = RuntimeError("registry timeout")

        # Should NOT raise
        wrapper.pull_image("myimage:v1")

        assert wrapper.client.images.get.call_count == 2
        wrapper.client.images.pull.assert_called_once_with("myimage:v1")

    def test_pull_fails_and_image_not_found_raises(self):
        """Pull fails and fallback image.get also fails → raises (lines 64-66)."""
        wrapper = _make_wrapper()

        wrapper.client.images.get.side_effect = docker.errors.NotFound("not found")
        wrapper.client.images.pull.side_effect = RuntimeError("registry timeout")

        with pytest.raises(docker.errors.NotFound):
            wrapper.pull_image("missing:latest")

        # images.get called twice: initial check + fallback
        assert wrapper.client.images.get.call_count == 2
        wrapper.client.images.pull.assert_called_once_with("missing:latest")


# ---------------------------------------------------------------------------
# create_container – stale container removal paths (lines 94-100)
# ---------------------------------------------------------------------------

class TestCreateContainerCoverage:
    """Cover create_container branches for named containers."""

    def test_create_container_removes_stale_container_by_name(self):
        """Existing container with same name is force-removed (lines 95-98)."""
        wrapper = _make_wrapper()

        stale = MagicMock()
        stale.status = "exited"
        wrapper.client.containers.get.return_value = stale

        new_container = MagicMock()
        new_container.id = "new-456"
        wrapper.client.containers.run.return_value = new_container

        result = wrapper.create_container(
            image="worker:latest",
            command="echo hi",
            name="my-worker",
        )

        wrapper.client.containers.get.assert_called_once_with("my-worker")
        stale.remove.assert_called_once_with(force=True)
        assert result.id == "new-456"

    def test_create_container_name_not_found(self):
        """Container name doesn't exist → NotFound caught, proceeds (lines 99-100)."""
        wrapper = _make_wrapper()

        wrapper.client.containers.get.side_effect = docker.errors.NotFound("not found")

        new_container = MagicMock()
        new_container.id = "new-789"
        wrapper.client.containers.run.return_value = new_container

        result = wrapper.create_container(
            image="worker:latest",
            command="echo hi",
            name="fresh-worker",
        )

        wrapper.client.containers.get.assert_called_once_with("fresh-worker")
        assert result.id == "new-789"

    def test_create_container_without_name_skips_stale_check(self):
        """No name provided → stale container check is skipped entirely."""
        wrapper = _make_wrapper()

        new_container = MagicMock()
        new_container.id = "anon-111"
        wrapper.client.containers.run.return_value = new_container

        result = wrapper.create_container(
            image="worker:latest",
            command="echo hi",
        )

        wrapper.client.containers.get.assert_not_called()
        assert result.id == "anon-111"


# ---------------------------------------------------------------------------
# close  (lines 188-189)
# ---------------------------------------------------------------------------

class TestCloseCoverage:
    """Cover DockerClientWrapper.close method."""

    def test_close_calls_client_close(self):
        """close() delegates to the underlying Docker client (lines 188-189)."""
        wrapper = _make_wrapper()

        wrapper.close()

        wrapper.client.close.assert_called_once()


# ---------------------------------------------------------------------------
# get_docker_client singleton  (line 201)
# ---------------------------------------------------------------------------

class TestGetDockerClientSingleton:
    """Cover the module-level get_docker_client singleton factory."""

    @patch("app.core.docker_client.DockerClientWrapper")
    def test_get_docker_client_creates_singleton(self, mock_cls):
        """First call creates the instance; second call returns the same one (line 201)."""
        import app.core.docker_client as mod

        # Reset the module-level singleton
        mod._docker_client = None

        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance

        first = mod.get_docker_client()
        second = mod.get_docker_client()

        assert first is mock_instance
        assert second is mock_instance
        mock_cls.assert_called_once()

        # Clean up: reset so other tests aren't affected
        mod._docker_client = None

    @patch("app.core.docker_client.DockerClientWrapper")
    def test_get_docker_client_returns_existing(self, mock_cls):
        """When _docker_client is already set, no new instance is created."""
        import app.core.docker_client as mod

        sentinel = MagicMock()
        mod._docker_client = sentinel

        result = mod.get_docker_client()

        assert result is sentinel
        mock_cls.assert_not_called()

        # Clean up
        mod._docker_client = None
