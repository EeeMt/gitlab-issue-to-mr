"""Tests for DockerClientWrapper."""

from unittest.mock import MagicMock, patch


class MockContainer:
    """Mock container object for testing."""

    def __init__(self, exit_code: int = 0, logs: bytes = b"test logs"):
        self.id = "test-container-123"
        self._exit_code = exit_code
        self._logs = logs
        self._wait_exception = None
        self._logs_exception = None

    def wait(self, timeout: int = 600):
        if self._wait_exception:
            raise self._wait_exception
        return {"StatusCode": self._exit_code}

    def logs(self, stdout=True, stderr=True, follow=False):
        if self._logs_exception:
            raise self._logs_exception
        return self._logs

    def remove(self, force=False):
        pass


class TestWaitForContainer:
    """Tests for wait_for_container method."""

    def test_wait_for_container_success(self):
        """Test successful container execution."""
        from app.core.docker_client import DockerClientWrapper

        mock_container = MockContainer(exit_code=0, logs=b"Success output")

        wrapper = DockerClientWrapper.__new__(DockerClientWrapper)
        wrapper.client = MagicMock()

        exit_code, logs = wrapper.wait_for_container(mock_container)

        assert exit_code == 0
        assert logs == "Success output"

    def test_wait_for_container_failure(self):
        """Test container exits with non-zero code."""
        from app.core.docker_client import DockerClientWrapper

        mock_container = MockContainer(exit_code=1, logs=b"Error output")

        wrapper = DockerClientWrapper.__new__(DockerClientWrapper)
        wrapper.client = MagicMock()

        exit_code, logs = wrapper.wait_for_container(mock_container)

        assert exit_code == 1
        assert logs == "Error output"

    def test_wait_for_container_wait_exception_with_logs_success(self):
        """Test container.wait() fails but logs retrieval succeeds."""
        from app.core.docker_client import DockerClientWrapper

        mock_container = MockContainer()
        mock_container._wait_exception = Exception("Connection refused")
        mock_container._logs = b"Partial logs before failure"

        wrapper = DockerClientWrapper.__new__(DockerClientWrapper)
        wrapper.client = MagicMock()

        exit_code, logs = wrapper.wait_for_container(mock_container)

        assert exit_code == -1
        assert logs == "Partial logs before failure"

    def test_wait_for_container_wait_exception_with_logs_failure(self):
        """Test container.wait() fails and logs retrieval also fails.

        This tests the fix for the bare except bug where inner_e
        was not properly capturing the inner exception.
        """
        from app.core.docker_client import DockerClientWrapper

        mock_container = MockContainer()
        mock_container._wait_exception = Exception("Connection refused")
        mock_container._logs_exception = Exception("Logs unavailable")

        wrapper = DockerClientWrapper.__new__(DockerClientWrapper)
        wrapper.client = MagicMock()

        exit_code, logs = wrapper.wait_for_container(mock_container)

        assert exit_code == -1
        assert "Logs unavailable" in logs
        # Verify it's using inner_e, not outer e
        assert "Connection refused" not in logs

    def test_wait_for_container_logs_decode_error(self):
        """Test logs decoding failure returns error message."""
        from app.core.docker_client import DockerClientWrapper

        mock_container = MockContainer()
        mock_container._logs_exception = UnicodeDecodeError(
            "utf-8", b"\xff\xfe", 0, 1, "invalid"
        )

        wrapper = DockerClientWrapper.__new__(DockerClientWrapper)
        wrapper.client = MagicMock()

        exit_code, logs = wrapper.wait_for_container(mock_container)

        assert exit_code == 0  # wait succeeded
        assert "Failed to decode logs" in logs

    def test_wait_for_container_timeout(self):
        """Test container wait timeout."""
        from app.core.docker_client import DockerClientWrapper

        mock_container = MockContainer()
        mock_container._wait_exception = Exception("Timeout")

        wrapper = DockerClientWrapper.__new__(DockerClientWrapper)
        wrapper.client = MagicMock()

        exit_code, logs = wrapper.wait_for_container(mock_container, timeout=30)

        assert exit_code == -1


class TestPullImage:
    """Tests for pull_image method."""

    @patch("app.core.docker_client.get_settings")
    def test_pull_image_already_exists(self, mock_get_settings):
        """Test pull_image skips pull when image exists."""
        mock_settings = MagicMock()
        mock_settings.docker_host = "unix:///var/run/docker.sock"
        mock_settings.docker_tls_ca = None
        mock_get_settings.return_value = mock_settings

        from app.core.docker_client import DockerClientWrapper

        wrapper = DockerClientWrapper.__new__(DockerClientWrapper)
        wrapper.client = MagicMock()

        mock_image = MagicMock()
        wrapper.client.images.get.return_value = mock_image

        wrapper.pull_image("nginx:latest")

        wrapper.client.images.get.assert_called_once_with("nginx:latest")
        wrapper.client.images.pull.assert_not_called()

    @patch("app.core.docker_client.get_settings")
    def test_pull_image_force_pull(self, mock_get_settings):
        """Test force pull ignores local image check."""
        mock_settings = MagicMock()
        mock_settings.docker_host = "unix:///var/run/docker.sock"
        mock_settings.docker_tls_ca = None
        mock_get_settings.return_value = mock_settings

        from app.core.docker_client import DockerClientWrapper

        wrapper = DockerClientWrapper.__new__(DockerClientWrapper)
        wrapper.client = MagicMock()

        wrapper.pull_image("nginx:latest", force=True)

        wrapper.client.images.get.assert_not_called()
        wrapper.client.images.pull.assert_called_once_with("nginx:latest")


class TestCreateContainer:
    """Tests for create_container method."""

    @patch("app.core.docker_client.get_settings")
    def test_create_container_basic(self, mock_get_settings):
        """Test basic container creation."""
        mock_settings = MagicMock()
        mock_settings.docker_host = "unix:///var/run/docker.sock"
        mock_settings.docker_tls_ca = None
        mock_get_settings.return_value = mock_settings

        from app.core.docker_client import DockerClientWrapper

        wrapper = DockerClientWrapper.__new__(DockerClientWrapper)
        wrapper.client = MagicMock()

        mock_container = MagicMock()
        mock_container.id = "abc123"
        wrapper.client.containers.run.return_value = mock_container

        result = wrapper.create_container(
            image="codify-worker/java21-maven:2026.07",
            command="python run.py",
        )

        assert result.id == "abc123"
        wrapper.client.containers.run.assert_called_once()


class TestRemoveContainer:
    """Tests for remove_container method."""

    def test_remove_container_normal(self):
        """Test normal container removal."""
        from app.core.docker_client import DockerClientWrapper

        wrapper = DockerClientWrapper.__new__(DockerClientWrapper)
        wrapper.client = MagicMock()

        mock_container = MagicMock()
        mock_container.id = "test-123"

        wrapper.remove_container(mock_container)

        mock_container.remove.assert_called_once_with(force=False)

    def test_remove_container_force(self):
        """Test forced container removal."""
        from app.core.docker_client import DockerClientWrapper

        wrapper = DockerClientWrapper.__new__(DockerClientWrapper)
        wrapper.client = MagicMock()

        mock_container = MagicMock()
        mock_container.id = "test-123"

        wrapper.remove_container(mock_container, force=True)

        mock_container.remove.assert_called_once_with(force=True)


class TestGetContainerLogs:
    """Tests for get_container_logs method."""

    def test_get_container_logs_basic(self):
        """Test basic logs retrieval."""
        from app.core.docker_client import DockerClientWrapper

        wrapper = DockerClientWrapper.__new__(DockerClientWrapper)
        wrapper.client = MagicMock()

        mock_container = MagicMock()
        mock_container.logs.return_value = b"line1\nline2\n"

        result = wrapper.get_container_logs(mock_container)

        mock_container.logs.assert_called_once_with(
            stdout=True, stderr=True, follow=False
        )
        assert result == b"line1\nline2\n"
