import io
import os
import tarfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.core.worker_results import _stream_runtime_archive_from_container


def _docker_outer_tar(name: str, payload: bytes, *, extra: bool = False) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        info = tarfile.TarInfo(name)
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
        if extra:
            other = tarfile.TarInfo("unexpected")
            other.size = 1
            archive.addfile(other, io.BytesIO(b"x"))
    return buffer.getvalue()


def _chunks(content: bytes):
    for index in range(0, len(content), 37):
        yield content[index : index + 37]


def test_streams_inner_archive_to_atomic_file(tmp_path):
    archive_name = "task-1-runtime-archive.tar.gz"
    payload = os.urandom(64 * 1024)
    container = SimpleNamespace(
        get_archive=lambda _path: (_chunks(_docker_outer_tar(archive_name, payload)), {})
    )

    final_path, size = _stream_runtime_archive_from_container(
        container,
        container_path=f"/tmp/codify-runtime/{archive_name}",
        archive_name=archive_name,
        archive_store=str(tmp_path),
    )

    assert Path(final_path).read_bytes() == payload
    assert size == len(payload)
    assert not list(tmp_path.glob("*.part"))


def test_rejects_extra_outer_tar_members_and_removes_partial_file(tmp_path):
    archive_name = "task-2-runtime-archive.tar.gz"
    outer = _docker_outer_tar(archive_name, b"archive", extra=True)
    container = SimpleNamespace(get_archive=lambda _path: (_chunks(outer), {}))

    with pytest.raises(RuntimeError, match="extra members"):
        _stream_runtime_archive_from_container(
            container,
            container_path=f"/tmp/codify-runtime/{archive_name}",
            archive_name=archive_name,
            archive_store=str(tmp_path),
        )

    assert not list(tmp_path.iterdir())


def test_rejects_declared_archive_above_hard_limit_before_copy(tmp_path):
    archive_name = "task-3-runtime-archive.tar.gz"
    outer = _docker_outer_tar(archive_name, b"12345")
    container = SimpleNamespace(get_archive=lambda _path: (_chunks(outer), {}))

    with patch("app.core.worker_results.WORKER_RUNTIME_ARCHIVE_MAX_BYTES", 4):
        with pytest.raises(RuntimeError, match="hard limit"):
            _stream_runtime_archive_from_container(
                container,
                container_path=f"/tmp/codify-runtime/{archive_name}",
                archive_name=archive_name,
                archive_store=str(tmp_path),
            )

    assert not list(tmp_path.iterdir())
