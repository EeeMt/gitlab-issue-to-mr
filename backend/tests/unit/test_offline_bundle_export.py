import gzip
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pytest

_worker_kit_spec = importlib.util.spec_from_file_location(
    "worker_kit_fixture", Path(__file__).with_name("test_worker_kit.py")
)
_worker_kit_module = importlib.util.module_from_spec(_worker_kit_spec)
assert _worker_kit_spec.loader is not None
_worker_kit_spec.loader.exec_module(_worker_kit_module)
_runtime_verifier_fixture = _worker_kit_module._runtime_verifier_fixture


@contextmanager
def _secure_install_root():
    if os.geteuid() != 0:
        pytest.skip("Worker Kit installation requires root")
    with tempfile.TemporaryDirectory(prefix="codify-test-worker-kits-", dir="/opt") as path:
        yield Path(path)


def _fake_uid_env(root: Path, uid: int) -> dict[str, str]:
    fake_bin = root / "fake-id-bin"
    fake_bin.mkdir()
    fake_id = fake_bin / "id"
    fake_id.write_text(
        "#!/bin/sh\n"
        f"if [ \"${{1:-}}\" = \"-u\" ]; then printf '%s\\n' '{uid}'; else exit 1; fi\n",
        encoding="utf-8",
    )
    fake_id.chmod(0o755)
    return {**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"}


def test_worker_kit_uses_content_addressed_nixpkgs_lock():
    repo_root = Path(__file__).resolve().parents[3]
    lock = json.loads(
        (repo_root / "deploy" / "worker-kit" / "nixpkgs.json").read_text(
            encoding="utf-8"
        )
    )
    dockerfile = (repo_root / "deploy" / "Dockerfile.worker-kit").read_text(
        encoding="utf-8"
    )
    nix_expression = (repo_root / "deploy" / "worker-kit" / "default.nix").read_text(
        encoding="utf-8"
    )

    assert re.fullmatch(r"[0-9a-f]{40}", lock["rev"])
    assert lock["rev"] in lock["url"]
    assert re.fullmatch(r"[0-9a-df-np-sv-z0-9]{52}", lock["sha256"])
    assert "nix-channel" not in dockerfile
    assert "COPY deploy/worker-kit/nixpkgs.json ./nixpkgs.json" in dockerfile
    assert 'ENV NIX_CONFIG="filter-syscalls = false"' in dockerfile
    assert "builtins.fetchTarball" in nix_expression
    assert "inherit (nixpkgsLock) url sha256" in nix_expression
    assert "nixpkgs_revision" in dockerfile
    assert "claude.ai/install.sh" not in dockerfile
    assert "CLAUDE_VERSION" not in dockerfile
    assert (
        "components: {nixpkgs: $nixpkgs_version, nixpkgs_revision: $nixpkgs_revision}"
        in dockerfile
    )
    assert "claude-code-cli" not in nix_expression
    assert "src = ./claude" not in nix_expression


def test_make_offline_bundle_export_target_builds_exports_and_packages():
    repo_root = Path(__file__).resolve().parents[3]

    result = subprocess.run(
        ["make", "-n", "offline-bundle-export"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "docker-compose --env-file .env.test build" in result.stdout
    assert "Dockerfile.worker-java21-maven" not in result.stdout
    assert "codify-worker/java21-maven:2026.07" not in result.stdout
    assert "deploy/worker-kit/export.sh" in result.stdout
    assert "deploy/offline-bundle && ./scripts/export-images.sh" in result.stdout
    assert "deploy/offline-bundle && ./scripts/package-bundle.sh" in result.stdout


def test_offline_artifacts_are_excluded_from_docker_build_contexts():
    repo_root = Path(__file__).resolve().parents[3]
    root_ignore = (repo_root / ".dockerignore").read_text(encoding="utf-8")

    assert "deploy/offline-bundle/" in root_ignore
    assert "deploy/codify-offline-bundle*.tar.gz" in root_ignore


def test_worker_kit_export_does_not_materialize_linux_tree_on_host():
    repo_root = Path(__file__).resolve().parents[3]
    export_script = (repo_root / "deploy" / "worker-kit" / "export.sh").read_text(
        encoding="utf-8"
    )

    assert "export-archive.py" in export_script
    assert 'tar -C "${STAGING}/build/worker-kit/" -xf -' not in export_script


def test_worker_kit_export_none_selection_stages_placeholder_and_passes_sentinel():
    repo_root = Path(__file__).resolve().parents[3]

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        worker_kit_dir = root / "deploy" / "worker-kit"
        worker_kit_dir.mkdir(parents=True)
        shutil.copy2(repo_root / "deploy/worker-kit/export.sh", worker_kit_dir / "export.sh")
        shutil.copy2(
            repo_root / "deploy/worker-kit/export-archive.py",
            worker_kit_dir / "export-archive.py",
        )
        (root / "deploy" / "Dockerfile.worker-kit").write_text("FROM scratch\n", encoding="utf-8")
        (root / "deploy" / "worker-cli").mkdir()

        manifest = root / "fake-manifest.json"
        manifest.write_text('{"harness_inventory":{}}\n', encoding="utf-8")
        fake_kit = root / "fake-kit"
        fake_kit.mkdir()
        shutil.copy2(manifest, fake_kit / "manifest.json")
        (fake_kit / ".keep").write_text("", encoding="utf-8")

        fake_bin = root / "bin"
        fake_bin.mkdir()
        docker_args_log = root / "docker-args.log"
        docker = fake_bin / "docker"
        docker.write_text(
            "#!/bin/sh\n"
            "set -eu\n"
            "printf '%s\\n' \"$@\" >> \"$FAKE_DOCKER_ARGS_LOG\"\n"
            "case \"${1:-}\" in\n"
            "  buildx) exit 0 ;;\n"
            "  build)\n"
            "    test -f \"$FAKE_DOCKER_ROOT/deploy/worker-cli/kit-staging/.keep\"\n"
            "    exit 0\n"
            "    ;;\n"
            "  create) printf '%s\\n' fake-cid ;;\n"
            "  run) cat \"$FAKE_DOCKER_MANIFEST\" ;;\n"
            "  cp) tar -C \"$FAKE_DOCKER_KIT\" -cf - . ;;\n"
            "  rm) exit 0 ;;\n"
            "  *) exit 2 ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        docker.chmod(0o755)

        output_dir = root / "out"
        env = {
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "FAKE_DOCKER_ARGS_LOG": str(docker_args_log),
            "FAKE_DOCKER_ROOT": str(root),
            "FAKE_DOCKER_MANIFEST": str(manifest),
            "FAKE_DOCKER_KIT": str(fake_kit),
            "WORKER_KIT_VERSION": "test-none",
            "WORKER_KIT_PLATFORM": "linux/amd64",
            "WORKER_KIT_CLI_SELECTION": "none",
            "WORKER_KIT_OUTPUT_DIR": str(output_dir),
        }

        result = subprocess.run(
            [str(worker_kit_dir / "export.sh")],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        docker_args = docker_args_log.read_text(encoding="utf-8").splitlines()
        assert "KIT_CLI_SELECTION=none" in docker_args
        archives = list(output_dir.glob("codify-worker-kit-*.tar.gz"))
        assert len(archives) == 1
        with tarfile.open(archives[0], mode="r:gz") as archive:
            names = archive.getnames()
        assert any(name.endswith("/.keep") for name in names)
        assert any(name.endswith("/manifest.json") for name in names)


def test_export_images_script_creates_missing_output_directory():
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "deploy" / "offline-bundle" / "scripts" / "export-images.sh"

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        scripts_dir = root / "offline-bundle" / "scripts"
        scripts_dir.mkdir(parents=True)

        script_copy = scripts_dir / "export-images.sh"
        shutil.copy2(script_path, script_copy)
        script_copy.chmod(script_copy.stat().st_mode | stat.S_IEXEC)

        fake_bin = root / "bin"
        fake_bin.mkdir()
        docker_args_log = root / "docker-args.log"
        docker = fake_bin / "docker"
        docker.write_text(
            "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$DOCKER_ARGS_LOG\"\n"
            "printf 'fake image archive'\n",
            encoding="utf-8",
        )
        docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
        env = {
            **os.environ,
            "DOCKER_ARGS_LOG": str(docker_args_log),
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        }

        result = subprocess.run(
            [str(script_copy)],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        images_dir = root / "offline-bundle" / "images"
        archive = images_dir / "codify-offline-images.tar.gz"
        assert gzip.decompress(archive.read_bytes()) == b"fake image archive"
        assert (images_dir / "SHA256SUMS").is_file()
        assert docker_args_log.read_text(encoding="utf-8").splitlines() == [
            "save",
            "codify-backend:latest",
            "codify-nginx:latest",
            "postgres:16-alpine",
        ]

        config_dir = root / "offline-bundle" / "config"
        config_dir.mkdir()
        (config_dir / "worker-images.txt").write_text(
            "# Explicit project runtimes\n"
            "codify-worker/java21-maven:2026.07\n"
            "team/node22-pnpm:2026.07  # frontend runtime\n",
            encoding="utf-8",
        )

        result = subprocess.run(
            [str(script_copy)],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert docker_args_log.read_text(encoding="utf-8").splitlines() == [
            "save",
            "codify-backend:latest",
            "codify-nginx:latest",
            "postgres:16-alpine",
            "codify-worker/java21-maven:2026.07",
            "team/node22-pnpm:2026.07",
        ]


def test_verify_runtime_scripts_mount_claude_without_breaking_docker_args():
    repo_root = Path(__file__).resolve().parents[3]
    scripts = (
        repo_root / "deploy" / "worker-kit" / "verify-runtime.sh",
        repo_root / "deploy" / "offline-bundle" / "scripts" / "verify-worker-runtime.sh",
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        kit = root / "kit"
        (kit / "nix" / "store").mkdir(parents=True)
        launcher = kit / "launcher"
        launcher.write_text("#!/bin/sh\n", encoding="utf-8")
        launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)
        (kit / "bridge-selfcheck-claude").write_text("#!/bin/sh\n", encoding="utf-8")
        (kit / "bridge-selfcheck-claude").chmod(0o755)
        (kit / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "manifest_kind": "codify.worker.kit-manifest/v1",
                    "kit_version": "0.3.5",
                    "platform": "linux/amd64",
                    "harness_inventory": {
                        key: {"availability": "absent", "reason_code": "not_selected"}
                        for key in ("pi", "opencode", "claude", "codex")
                    },
                }
            ),
            encoding="utf-8",
        )
        shutil.copy2(repo_root / "deploy/worker-kit/verify-runtime.sh", kit / "verify-runtime.sh")
        (kit / "verify-runtime.sh").chmod(0o755)
        shutil.copy2(repo_root / "deploy/worker-kit/verify-kit-content.py", kit / "verify-kit-content.py")
        subprocess.run(
            [
                sys.executable,
                str(repo_root / "deploy/worker-kit/verify-kit-content.py"),
                "--root",
                str(kit),
                "--write-manifest",
            ],
            check=True,
            capture_output=True,
        )
        claude = root / "claude"
        claude.write_text("#!/bin/sh\n", encoding="utf-8")
        claude.chmod(claude.stat().st_mode | stat.S_IEXEC)

        fake_bin = root / "bin"
        fake_bin.mkdir()
        log_path = root / "docker-args.log"
        docker = fake_bin / "docker"
        docker.write_text(
            "#!/usr/bin/env bash\n"
            "{ printf '__CALL__\\n'; printf '%s\\n' \"$@\"; } >> \"$DOCKER_ARGS_LOG\"\n",
            encoding="utf-8",
        )
        docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
        env = {
            **os.environ,
            "DOCKER_ARGS_LOG": str(log_path),
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        }

        for script in scripts:
            log_path.write_text("", encoding="utf-8")
            result = subprocess.run(
                [
                    str(script),
                    "--kit",
                    str(kit),
                    "--claude-host-path",
                    str(claude),
                    "--image",
                    "team/runtime:1",
                    "--smoke",
                    "java -version",
                ],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            assert result.returncode == 0, result.stderr
            calls: list[list[str]] = []
            current: list[str] | None = None
            for line in log_path.read_text(encoding="utf-8").splitlines():
                if line == "__CALL__":
                    current = []
                    calls.append(current)
                elif current is not None:
                    current.append(line)
            assert calls[-1] == [
                "run",
                "--rm",
                "--user",
                "0:0",
                "--tmpfs",
                "/workspace:rw,exec,mode=1777",
                "--volume",
                f"{kit}:/opt/codify-kit:ro",
                "--volume",
                f"{kit}/nix/store:/nix/store:ro",
                "--volume",
                f"{claude}:/usr/local/bin/claude:ro",
                "--entrypoint",
                "/opt/codify-kit/launcher",
                "--env",
                "CODIFY_KIT_VERSION=0.3.5",
                "--env",
                "CODIFY_RUNTIME_IMAGE=team/runtime:1",
                "--env",
                "CODIFY_HARNESS_KEY=claude",
                "--env",
                                "CODIFY_HARNESS_CLI_BIN=/usr/local/bin/claude",
                "team/runtime:1",
                "--verify",
                "--require-skill-support",
                "--smoke",
                "java -version",
            ]


def test_extracted_offline_bundle_runs_portable_v2_verifier_without_checkout():
    repo_root = Path(__file__).resolve().parents[3]
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        kit, bundle, artifact, fake_docker = _runtime_verifier_fixture(root / "fixture")
        shutil.copy2(repo_root / "deploy/worker-kit/verify-runtime.sh", kit / "verify-runtime.sh")
        (kit / "verify-runtime.sh").chmod(0o755)
        source = root / "offline-bundle"
        scripts = source / "scripts"
        scripts.mkdir(parents=True)
        shutil.copy2(repo_root / "deploy/offline-bundle/scripts/verify-worker-runtime.sh", scripts / "verify-worker-runtime.sh")
        shutil.copy2(repo_root / "deploy/worker-kit/verify-kit-content.py", scripts / "verify-kit-content.py")
        (scripts / "verify-worker-runtime.sh").chmod(0o755)
        archive = root / "offline-bundle.tar.gz"
        with tarfile.open(archive, "w:gz") as output:
            output.add(source, arcname="offline-bundle")
        extracted = root / "extracted"
        extracted.mkdir()
        with tarfile.open(archive, "r:gz") as input_archive:
            input_archive.extractall(extracted)
        wrapper = extracted / "offline-bundle/scripts/verify-worker-runtime.sh"

        def run(document=None, *, actual_sha=None, extra=None):
            if actual_sha is None:
                actual_sha = hashlib.sha256(b"#!/bin/sh\n").hexdigest()
            runtime = root / "runtime.json"
            image_identity = bundle.get("worker_image_identity") or {}
            image_inspect = {
                "RepoDigests": [image_identity.get("image_reference", "")],
                "Id": image_identity.get("image_id", ""),
                "Os": "linux",
                "Architecture": "amd64",
            }
            args = [str(wrapper), "--kit", str(kit), "--image", "fake:image"]
            if document is not None:
                runtime.write_text(json.dumps(document), encoding="utf-8")
                args += ["--runtime-manifest", str(runtime)]
            args += extra or ["--all-harnesses"]
            return subprocess.run(
                args,
                cwd=extracted,
                env={
                    **os.environ,
                    "PATH": f"{fake_docker.parent}{os.pathsep}{os.environ['PATH']}",
                    "ARTIFACT_PATH": str(artifact),
                    "ACTUAL_CLI_SHA": actual_sha,
                    "PAYLOAD_SHA": hashlib.sha256(b"#!/bin/sh\n").hexdigest(),
                    "PAYLOAD_SIZE": str(len(b"#!/bin/sh\n")),
                    "IMAGE_INSPECT": json.dumps(image_inspect),
                },
                capture_output=True,
                text=True,
                check=False,
            )

        assert run(bundle).returncode == 0
        assert run(None).returncode != 0
        assert run(bundle, actual_sha="e" * 64).returncode != 0
        # Adapter baseline differences are advisory: the verifier continues
        # with a sanitized warning and does not fail (§11.2).
        mismatched = json.loads(json.dumps(bundle))
        mismatched["adapters"]["pi"]["source"]["artifact_sha256"] = "f" * 64
        baseline_run = run(mismatched)
        assert baseline_run.returncode == 0, baseline_run.stderr


def test_offline_runtime_wrapper_verifies_content_before_running_kit_verifier():
    repo_root = Path(__file__).resolve().parents[3]
    wrapper = repo_root / "deploy/offline-bundle/scripts/verify-worker-runtime.sh"

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        kit, _, _, _ = _runtime_verifier_fixture(root / "fixture")
        marker = root / "kit-runtime-verifier-executed"
        runtime_verifier = kit / "verify-runtime.sh"
        runtime_verifier.write_text(
            "#!/usr/bin/env bash\n" f"touch {str(marker)!r}\n", encoding="utf-8"
        )
        runtime_verifier.chmod(0o755)

        result = subprocess.run(
            [str(wrapper), "--kit", str(kit), "--image", "unused:image"],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode != 0
        assert not marker.exists()
        assert "content inventory" in result.stderr


def test_package_bundle_script_creates_archive_under_deploy_directory():
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "deploy" / "offline-bundle" / "scripts" / "package-bundle.sh"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        deploy_dir = tmp_path / "deploy"
        bundle_dir = deploy_dir / "offline-bundle"
        scripts_dir = bundle_dir / "scripts"
        images_dir = bundle_dir / "images"
        kits_dir = bundle_dir / "kits"

        scripts_dir.mkdir(parents=True)
        images_dir.mkdir(parents=True)
        kits_dir.mkdir(parents=True)
        worker_kit_dir = deploy_dir / "worker-kit"
        worker_kit_dir.mkdir(parents=True)
        for name in ("verify-runtime.sh", "validate-runtime-manifest.py", "verify-kit-content.py"):
            shutil.copy2(repo_root / f"deploy/worker-kit/{name}", worker_kit_dir / name)
        (worker_kit_dir / "verify-runtime.sh").chmod(0o755)
        shutil.copy2(
            repo_root / "deploy/offline-bundle/scripts/verify-worker-runtime.sh",
            scripts_dir / "verify-worker-runtime.sh",
        )
        shutil.copy2(
            repo_root / "deploy/offline-bundle/scripts/validate-kit-archive.py",
            scripts_dir / "validate-kit-archive.py",
        )
        (scripts_dir / "verify-worker-runtime.sh").chmod(0o755)
        (bundle_dir / "README.md").write_text("offline bundle", encoding="utf-8")
        (images_dir / "codify-offline-images.tar.gz").write_text("image archive", encoding="utf-8")
        real_kit, fixture_manifest, artifact, fake_docker = _runtime_verifier_fixture(tmp_path / "source-kit")
        shutil.copy2(repo_root / "deploy/worker-kit/verify-runtime.sh", real_kit / "verify-runtime.sh")
        (real_kit / "verify-runtime.sh").chmod(0o755)
        kit_root_name = (
            f"0.3.15-linux-amd64-"
            f"{fixture_manifest['worker_kit_identity']['manifest_sha256'][:12]}"
        )
        kit_archive = kits_dir / f"codify-worker-kit-{kit_root_name}.tar.gz"
        with tarfile.open(kit_archive, "w:gz") as kit_output:
            kit_output.add(real_kit, arcname=kit_root_name)
        kit_digest = hashlib.sha256(kit_archive.read_bytes()).hexdigest()
        (kits_dir / f"{kit_archive.name}.sha256").write_text(
            f"{kit_digest}  {kit_archive.name}\n", encoding="utf-8"
        )
        legacy_archive = kits_dir / "codify-worker-kit-0.3.14-linux-amd64.tar.gz"
        legacy_archive.write_bytes(b"legacy kit archive")
        (kits_dir / f"{legacy_archive.name}.sha256").write_text(
            f"{'0' * 64}  {legacy_archive.name}\n", encoding="utf-8"
        )

        script_copy = scripts_dir / "package-bundle.sh"
        shutil.copy2(script_path, script_copy)
        script_copy.chmod(script_copy.stat().st_mode | stat.S_IEXEC)

        result = subprocess.run(
            [str(script_copy)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr

        archive_path = deploy_dir / "codify-offline-bundle.tar.gz"
        assert archive_path.exists()
        checksum_path = Path(f"{archive_path}.sha256")
        assert checksum_path.exists()
        checksum = checksum_path.read_text(encoding="utf-8").split()[0]
        assert checksum == hashlib.sha256(archive_path.read_bytes()).hexdigest()

        with tarfile.open(archive_path, "r:gz") as archive:
            names = archive.getnames()

        assert "offline-bundle/README.md" in names
        assert "offline-bundle/images/codify-offline-images.tar.gz" in names
        assert f"offline-bundle/kits/{kit_archive.name}" in names
        assert f"offline-bundle/kits/{legacy_archive.name}" not in names
        assert "offline-bundle/scripts/verify-worker-runtime.sh" in names
        assert "offline-bundle/scripts/verify-kit-content.py" in names

        checksum_result = subprocess.run(
            ["sha256sum", "-c", str(archive_path) + ".sha256"],
            cwd=deploy_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        assert checksum_result.returncode == 0, checksum_result.stderr
        extracted = tmp_path / "packaged-extracted"
        extracted.mkdir()
        with tarfile.open(archive_path, "r:gz") as packaged:
            packaged.extractall(extracted)
        wrapper = extracted / "offline-bundle/scripts/verify-worker-runtime.sh"
        installed = tmp_path / "installed-kit"
        installed.mkdir()
        packaged_kit = extracted / f"offline-bundle/kits/{kit_archive.name}"
        with tarfile.open(packaged_kit, "r:gz") as kit_input:
            kit_input.extractall(installed)
        kit = installed / kit_root_name
        runtime_path = tmp_path / "packaged-runtime.json"
        runtime_path.write_text(json.dumps(fixture_manifest), encoding="utf-8")
        run_result = subprocess.run(
            [str(wrapper), "--kit", str(kit), "--image", "fake:image", "--runtime-manifest", str(runtime_path), "--all-harnesses"],
            cwd=extracted,
            env={
                **os.environ,
                "PATH": f"{fake_docker.parent}{os.pathsep}{os.environ['PATH']}",
                "ARTIFACT_PATH": str(artifact),
                "PAYLOAD_SHA": hashlib.sha256(b"#!/bin/sh\n").hexdigest(),
                "PAYLOAD_SIZE": str(len(b"#!/bin/sh\n")),
                "IMAGE_INSPECT": json.dumps(
                    {
                        "RepoDigests": [fixture_manifest["worker_image_identity"]["image_reference"]],
                        "Id": fixture_manifest["worker_image_identity"]["image_id"],
                        "Os": "linux",
                        "Architecture": "amd64",
                    }
                ),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert run_result.returncode == 0, run_result.stderr

        tampered = deploy_dir / "tampered-offline-bundle.tar.gz"
        tampered.write_bytes(archive_path.read_bytes() + b"tampered")
        tampered_checksum = Path(f"{tampered}.sha256")
        tampered_checksum.write_text(
            checksum_path.read_text(encoding="utf-8").replace(
                archive_path.name, tampered.name
            ),
            encoding="utf-8",
        )
        tampered_result = subprocess.run(
            ["sha256sum", "-c", str(tampered_checksum)],
            cwd=deploy_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        assert tampered_result.returncode != 0
        assert "codify-offline-bundle.tar.gz" not in names


@pytest.mark.parametrize(
    "member_name,link_name,link_type",
    [
        ("0.1.0-linux-amd64-000000000000/../sentinel", None, None),
        ("/tmp/codify-kit-escape", None, None),
        ("wrong-root/file", None, None),
        ("0.1.0-linux-amd64-000000000000/link", "../../sentinel", tarfile.SYMTYPE),
        ("0.1.0-linux-amd64-000000000000/hardlink", "../../sentinel", tarfile.LNKTYPE),
    ],
)
def test_package_bundle_rejects_unsafe_kit_tar_members(
    tmp_path, member_name, link_name, link_type
):
    repo_root = Path(__file__).resolve().parents[3]
    deploy_dir = tmp_path / "deploy"
    bundle_dir = deploy_dir / "offline-bundle"
    scripts_dir = bundle_dir / "scripts"
    (bundle_dir / "images").mkdir(parents=True)
    kits_dir = bundle_dir / "kits"
    kits_dir.mkdir()
    worker_kit_dir = deploy_dir / "worker-kit"
    worker_kit_dir.mkdir()
    scripts_dir.mkdir()
    for name in ("verify-runtime.sh", "validate-runtime-manifest.py", "verify-kit-content.py"):
        shutil.copy2(repo_root / f"deploy/worker-kit/{name}", worker_kit_dir / name)
    (worker_kit_dir / "verify-runtime.sh").chmod(0o755)
    shutil.copy2(repo_root / "deploy/offline-bundle/scripts/package-bundle.sh", scripts_dir)
    shutil.copy2(repo_root / "deploy/offline-bundle/scripts/validate-kit-archive.py", scripts_dir)
    (scripts_dir / "package-bundle.sh").chmod(0o755)
    (bundle_dir / "images/codify-offline-images.tar.gz").write_text("image", encoding="utf-8")
    archive = kits_dir / "codify-worker-kit-0.1.0-linux-amd64-000000000000.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        member = tarfile.TarInfo(member_name)
        if link_name is None:
            member.size = 1
            output.addfile(member, io.BytesIO(b"x"))
        else:
            member.type = link_type
            member.linkname = link_name
            output.addfile(member)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (kits_dir / f"{archive.name}.sha256").write_text(
        f"{digest}  {archive.name}\n", encoding="utf-8"
    )
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("untouched", encoding="utf-8")

    result = subprocess.run(
        [str(scripts_dir / "package-bundle.sh")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert not (deploy_dir / "codify-offline-bundle.tar.gz").exists()
    assert sentinel.read_text(encoding="utf-8") == "untouched"


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("safe", 0),
        ("nix-store-absolute", 0),
        ("nested-symlink", 0),
        ("root-relative-escape", 1),
        ("relative-escape", 1),
        ("missing", 1),
        ("cycle", 1),
    ],
)
def test_validate_kit_archive_resolves_links_safely(tmp_path, kind, expected):
    repo_root = Path(__file__).resolve().parents[3]
    helper = repo_root / "deploy/offline-bundle/scripts/validate-kit-archive.py"
    archive = tmp_path / "kit.tar.gz"
    root = "0.1.0-linux-amd64"
    with tarfile.open(archive, "w:gz") as output:
        root_member = tarfile.TarInfo(root)
        root_member.type = tarfile.DIRTYPE
        output.addfile(root_member)
        file_member = tarfile.TarInfo(f"{root}/a")
        file_member.size = 1
        output.addfile(file_member, io.BytesIO(b"a"))
        if kind == "safe":
            link = tarfile.TarInfo(f"{root}/b")
            link.type = tarfile.LNKTYPE
            link.linkname = f"{root}/a"
            output.addfile(link)
            symlink = tarfile.TarInfo(f"{root}/sub/link")
            symlink.type = tarfile.SYMTYPE
            symlink.linkname = "../a"
            output.addfile(symlink)
        elif kind == "nix-store-absolute":
            store_dir = tarfile.TarInfo(f"{root}/nix/store")
            store_dir.type = tarfile.DIRTYPE
            output.addfile(store_dir)
            target = tarfile.TarInfo(f"{root}/nix/store/target")
            target.size = 1
            output.addfile(target, io.BytesIO(b"t"))
            link = tarfile.TarInfo(f"{root}/nix/store/link")
            link.type = tarfile.SYMTYPE
            link.linkname = "/nix/store/target"
            output.addfile(link)
        elif kind == "nested-symlink":
            for name in (f"{root}/sub", f"{root}/sub/target"):
                directory = tarfile.TarInfo(name)
                directory.type = tarfile.DIRTYPE
                output.addfile(directory)
            target = tarfile.TarInfo(f"{root}/sub/target/file")
            target.size = 1
            output.addfile(target, io.BytesIO(b"t"))
            directory_link = tarfile.TarInfo(f"{root}/sub/current")
            directory_link.type = tarfile.SYMTYPE
            directory_link.linkname = "target"
            output.addfile(directory_link)
            link = tarfile.TarInfo(f"{root}/sub/link")
            link.type = tarfile.SYMTYPE
            link.linkname = "current/file"
            output.addfile(link)
        elif kind == "root-relative-escape":
            link = tarfile.TarInfo(f"{root}/b")
            link.type = tarfile.LNKTYPE
            link.linkname = f"{root}/../escape"
            output.addfile(link)
        elif kind == "relative-escape":
            link = tarfile.TarInfo(f"{root}/sub/link")
            link.type = tarfile.SYMTYPE
            link.linkname = "../../escape"
            output.addfile(link)
        elif kind == "missing":
            link = tarfile.TarInfo(f"{root}/b")
            link.type = tarfile.LNKTYPE
            link.linkname = f"{root}/missing"
            output.addfile(link)
        else:
            for name, target in (("x", "y"), ("y", "x")):
                link = tarfile.TarInfo(f"{root}/{name}")
                link.type = tarfile.SYMTYPE
                link.linkname = f"{root}/{target}"
                output.addfile(link)

    result = subprocess.run(
        ["python3", str(helper), str(archive), root],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected, result.stderr


def test_worker_kit_export_archive_stream_preserves_case_distinct_paths(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[3]
    exporter = repo_root / "deploy/worker-kit/export-archive.py"
    validator = repo_root / "deploy/offline-bundle/scripts/validate-kit-archive.py"
    source = tmp_path / "docker-copy.tar"
    root_name = "0.6.0-linux-amd64-aaaaaaaaaaaa"
    long_path = (
        "./nix/store/"
        "m6zl58rra824v4wjmy4fpr7524303d2b-codify-worker-kit-runtime/"
        "etc/ssl/certs/ca-no-trust-rules-bundle.crt"
    )
    with tarfile.open(source, "w") as output:
        for name in (
            "nix",
            "nix/store",
            "nix/store/terminfo",
            "nix/store/terminfo/P",
            "nix/store/terminfo/p",
            "nix/store/terminfo/w",
        ):
            directory = tarfile.TarInfo(name)
            directory.type = tarfile.DIRTYPE
            output.addfile(directory)
        for name in ("nix/store/terminfo/P/pt100w", "nix/store/terminfo/p/pt100w"):
            member = tarfile.TarInfo(name)
            member.size = 1
            output.addfile(member, io.BytesIO(b"t"))
        long_member = tarfile.TarInfo(long_path)
        long_member.size = 1
        output.addfile(long_member, io.BytesIO(b"c"))
        symlink = tarfile.TarInfo("nix/store/terminfo/w/wrenw")
        symlink.type = tarfile.SYMTYPE
        symlink.linkname = "../p/pt100w"
        output.addfile(symlink)

    archive = tmp_path / "kit.tar.gz"
    with source.open("rb") as stream:
        result = subprocess.run(
            [sys.executable, str(exporter), str(archive), root_name],
            stdin=stream,
            capture_output=True,
            text=True,
            check=False,
        )
    assert result.returncode == 0, result.stderr
    with tarfile.open(archive, "r:gz") as output:
        names = set(output.getnames())
        assert f"{root_name}/nix/store/terminfo/P/pt100w" in names
        assert f"{root_name}/nix/store/terminfo/p/pt100w" in names
        assert f"{root_name}/{long_path[2:]}" in names
        assert not any(name.startswith("./") for name in names)
        wrenw = output.getmember(f"{root_name}/nix/store/terminfo/w/wrenw")
        assert wrenw.linkname == "../p/pt100w"

    result = subprocess.run(
        ["python3", str(validator), str(archive), root_name],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("forward", [False, True])
def test_content_verifier_accepts_hard_link_archive_members(tmp_path: Path, forward: bool):
    repo_root = Path(__file__).resolve().parents[3]
    verifier = repo_root / "deploy/worker-kit/verify-kit-content.py"
    source = tmp_path / "source-kit"
    source.mkdir()
    payload = source / "payload"
    payload.write_bytes(b"payload\n")
    payload_link = source / "payload-link"
    payload_link.hardlink_to(payload)
    (source / "manifest.json").write_text(
        '{"schema_version":2,"kit_version":"0.1.0","platform":"linux/amd64"}',
        encoding="utf-8",
    )
    subprocess.run(
        [sys.executable, str(verifier), "--root", str(source), "--write-manifest"],
        check=True,
        capture_output=True,
    )
    manifest_bytes = (source / "manifest.json").read_bytes()
    root_name = f"0.1.0-linux-amd64-{hashlib.sha256(manifest_bytes).hexdigest()[:12]}"
    archive = tmp_path / "kit.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        root_member = tarfile.TarInfo(root_name)
        root_member.type = tarfile.DIRTYPE
        output.addfile(root_member)
        link_member = tarfile.TarInfo(f"{root_name}/payload-link")
        link_member.type = tarfile.LNKTYPE
        link_member.linkname = f"{root_name}/payload"
        payload_member = tarfile.TarInfo(f"{root_name}/payload")
        payload_member.size = len(b"payload\n")
        if forward:
            output.addfile(link_member)
            output.addfile(payload_member, io.BytesIO(b"payload\n"))
        else:
            output.addfile(payload_member, io.BytesIO(b"payload\n"))
            output.addfile(link_member)
        manifest_member = tarfile.TarInfo(f"{root_name}/manifest.json")
        manifest_member.size = len(manifest_bytes)
        output.addfile(manifest_member, io.BytesIO(manifest_bytes))

    result = subprocess.run(
        [
            sys.executable,
            str(verifier),
            "--archive",
            str(archive),
            "--root-name",
            root_name,
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_worker_kit_installer_verifies_and_refuses_version_overwrite():
    repo_root = Path(__file__).resolve().parents[3]
    script_path = (
        repo_root / "deploy" / "offline-bundle" / "scripts" / "install-worker-kit.sh"
    )

    with tempfile.TemporaryDirectory() as tmpdir, _secure_install_root() as install_root:
        root = Path(tmpdir)
        source_name = "0.1.0-linux-amd64"
        source = root / source_name
        (source / "nix" / "store").mkdir(parents=True)
        launcher = source / "launcher"
        launcher.write_text("launcher", encoding="utf-8")
        launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)
        shutil.copy2(repo_root / "deploy/worker-kit/verify-kit-content.py", source / "verify-kit-content.py")
        (source / "manifest.json").write_text(
            '{"schema_version":2,"kit_version":"0.1.0","platform":"linux/amd64"}',
            encoding="utf-8",
        )
        subprocess.run(
            [
                sys.executable,
                str(repo_root / "deploy/worker-kit/verify-kit-content.py"),
                "--root",
                str(source),
                "--write-manifest",
            ],
            check=True,
            capture_output=True,
        )
        manifest_sha256 = hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest()
        kit_name = f"{source_name}-{manifest_sha256[:12]}"
        archive = root / f"codify-worker-kit-{kit_name}.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            bundle.add(source, arcname=kit_name)
        checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
        (root / f"{archive.name}.sha256").write_text(
            f"{checksum}  {archive.name}\n", encoding="utf-8"
        )
        first = subprocess.run(
            [str(script_path), str(archive), str(install_root)],
            capture_output=True,
            text=True,
            check=False,
        )
        second = subprocess.run(
            [str(script_path), str(archive), str(install_root)],
            capture_output=True,
            text=True,
            check=False,
        )

        assert first.returncode == 0, first.stderr
        assert (install_root / kit_name / "launcher").is_file()
        receipt = json.loads((install_root / kit_name / ".install-receipt.json").read_text())
        assert receipt["manifest_sha256"] == manifest_sha256
        assert receipt["content_inventory_sha256"]
        assert (install_root.stat().st_uid, install_root.stat().st_mode & 0o022) == (0, 0)
        assert (install_root / kit_name).stat().st_uid == 0
        assert (install_root / kit_name / ".install-receipt.json").stat().st_mode & 0o022 == 0
        assert second.returncode != 0
        assert "already installed" in second.stderr


@pytest.mark.parametrize(
    "script_relative_path",
    [
        "deploy/worker-kit/install.sh",
        "deploy/offline-bundle/scripts/install-worker-kit.sh",
    ],
)
def test_worker_kit_installers_reject_target_appearing_before_atomic_publish(
    script_relative_path: str,
):
    """A target created after the preflight check cannot receive nested Kit bytes."""
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / script_relative_path

    with tempfile.TemporaryDirectory() as tmpdir, _secure_install_root() as install_root:
        root = Path(tmpdir)
        source_name = "0.1.0-linux-amd64"
        source = root / source_name
        (source / "nix" / "store").mkdir(parents=True)
        launcher = source / "launcher"
        launcher.write_text("launcher", encoding="utf-8")
        launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)
        shutil.copy2(
            repo_root / "deploy/worker-kit/verify-kit-content.py",
            source / "verify-kit-content.py",
        )
        (source / "manifest.json").write_text(
            '{"schema_version":2,"kit_version":"0.1.0","platform":"linux/amd64"}',
            encoding="utf-8",
        )
        subprocess.run(
            [
                sys.executable,
                str(repo_root / "deploy/worker-kit/verify-kit-content.py"),
                "--root",
                str(source),
                "--write-manifest",
            ],
            check=True,
            capture_output=True,
        )
        manifest_sha256 = hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest()
        kit_name = f"{source_name}-{manifest_sha256[:12]}"
        archive = root / f"codify-worker-kit-{kit_name}.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            bundle.add(source, arcname=kit_name)
        checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
        (root / f"{archive.name}.sha256").write_text(
            f"{checksum}  {archive.name}\n", encoding="utf-8"
        )

        fake_bin = root / "fake-bin"
        fake_bin.mkdir()
        fake_python = fake_bin / "python3"
        fake_python.write_text(
            "#!/bin/sh\n"
            "if [ \"${1:-}\" = \"-\" ] && [ -n \"${4:-}\" ]; then\n"
            "    case \"$4\" in\n"
            "        *.worker-kit-install-*.lock) mkdir -p \"$3/occupied-by-race\" ;;\n"
            "    esac\n"
            "fi\n"
            f"exec {sys.executable} \"$@\"\n",
            encoding="utf-8",
        )
        fake_python.chmod(0o755)
        env = {**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"}

        result = subprocess.run(
            [str(script_path), str(archive), str(install_root)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        target = install_root / kit_name
        assert result.returncode != 0
        assert "atomic publish" in result.stderr
        assert (target / "occupied-by-race").is_dir()
        assert not (target / kit_name).exists()


def test_worker_kit_installer_never_executes_kit_supplied_content_verifier():
    repo_root = Path(__file__).resolve().parents[3]
    script_path = (
        repo_root / "deploy" / "offline-bundle" / "scripts" / "install-worker-kit.sh"
    )

    with tempfile.TemporaryDirectory() as tmpdir, _secure_install_root() as install_root:
        root = Path(tmpdir)
        source_name = "0.1.0-linux-amd64"
        source = root / source_name
        (source / "nix" / "store").mkdir(parents=True)
        launcher = source / "launcher"
        launcher.write_text("launcher", encoding="utf-8")
        launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)
        marker = root / "kit-verifier-executed"
        (source / "verify-kit-content.py").write_text(
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).touch()\n",
            encoding="utf-8",
        )
        (source / "manifest.json").write_text(
            '{"schema_version":2,"kit_version":"0.1.0","platform":"linux/amd64"}',
            encoding="utf-8",
        )
        subprocess.run(
            [
                sys.executable,
                str(repo_root / "deploy/worker-kit/verify-kit-content.py"),
                "--root",
                str(source),
                "--write-manifest",
            ],
            check=True,
            capture_output=True,
        )
        manifest_sha256 = hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest()
        kit_name = f"{source_name}-{manifest_sha256[:12]}"
        archive = root / f"codify-worker-kit-{kit_name}.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            bundle.add(source, arcname=kit_name)
        checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
        (root / f"{archive.name}.sha256").write_text(
            f"{checksum}  {archive.name}\n", encoding="utf-8"
        )

        result = subprocess.run(
            [str(script_path), str(archive), str(install_root)],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert not marker.exists()


def test_worker_kit_installer_rejects_non_root_before_preparing_install_root(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "deploy/offline-bundle/scripts/install-worker-kit.sh"
    install_root = tmp_path / "should-not-be-created"

    result = subprocess.run(
        [str(script_path), str(tmp_path / "missing.tar.gz"), str(install_root)],
        env=_fake_uid_env(tmp_path, 501),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "must run as root" in result.stderr
    assert not install_root.exists()


def test_direct_worker_kit_installer_rejects_user_writable_parent(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "deploy/worker-kit/install.sh"
    archive = tmp_path / "kit.tar.gz"
    archive.write_bytes(b"not a real archive")
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_name(f"{archive.name}.sha256").write_text(
        f"{checksum}  {archive.name}\n", encoding="utf-8"
    )
    install_root = tmp_path / "user-writable" / "worker-kits"

    result = subprocess.run(
        [str(script_path), str(archive), str(install_root)],
        env=_fake_uid_env(tmp_path, 0),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "install root is not a root-owned" in result.stderr
    assert not install_root.exists()
