import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
from pathlib import Path


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
    assert "make build" in result.stdout
    assert "deploy/worker-kit/export.sh" in result.stdout
    assert "deploy/offline-bundle && ./scripts/export-images.sh" in result.stdout
    assert "deploy/offline-bundle && ./scripts/package-bundle.sh" in result.stdout


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
        (kit / "manifest.json").write_text(
            '{"schema_version":1,"kit_version":"0.1.0"}',
            encoding="utf-8",
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
                "CODIFY_KIT_VERSION=0.1.0",
                "--env",
                "CODIFY_RUNTIME_IMAGE=team/runtime:1",
                "--env",
                "CODIFY_CLAUDE_BIN=/usr/local/bin/claude",
                "team/runtime:1",
                "--verify",
                "--smoke",
                "java -version",
            ]


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
        (bundle_dir / "README.md").write_text("offline bundle", encoding="utf-8")
        (images_dir / "codify-offline-images.tar.gz").write_text("image archive", encoding="utf-8")
        kit_archive = kits_dir / "codify-worker-kit-0.1.0-linux-amd64.tar.gz"
        kit_archive.write_text("kit archive", encoding="utf-8")
        (kits_dir / f"{kit_archive.name}.sha256").write_text("checksum", encoding="utf-8")

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

        with tarfile.open(archive_path, "r:gz") as archive:
            names = archive.getnames()

        assert "offline-bundle/README.md" in names
        assert "offline-bundle/images/codify-offline-images.tar.gz" in names
        assert "offline-bundle/kits/codify-worker-kit-0.1.0-linux-amd64.tar.gz" in names
        assert "codify-offline-bundle.tar.gz" not in names


def test_worker_kit_installer_verifies_and_refuses_version_overwrite():
    repo_root = Path(__file__).resolve().parents[3]
    script_path = (
        repo_root / "deploy" / "offline-bundle" / "scripts" / "install-worker-kit.sh"
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        kit_name = "0.1.0-linux-amd64"
        source = root / kit_name
        (source / "nix" / "store").mkdir(parents=True)
        launcher = source / "launcher"
        launcher.write_text("launcher", encoding="utf-8")
        launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)
        (source / "manifest.json").write_text(
            '{"schema_version":1,"kit_version":"0.1.0"}', encoding="utf-8"
        )
        archive = root / f"codify-worker-kit-{kit_name}.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            bundle.add(source, arcname=kit_name)
        checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
        (root / f"{archive.name}.sha256").write_text(
            f"{checksum}  {archive.name}\n", encoding="utf-8"
        )
        install_root = root / "installed"

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
        assert second.returncode != 0
        assert "already installed" in second.stderr
