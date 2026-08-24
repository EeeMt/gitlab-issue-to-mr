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
import tarfile
import tempfile
from pathlib import Path

import pytest

_worker_kit_spec = importlib.util.spec_from_file_location(
    "worker_kit_fixture", Path(__file__).with_name("test_worker_kit.py")
)
_worker_kit_module = importlib.util.module_from_spec(_worker_kit_spec)
assert _worker_kit_spec.loader is not None
_worker_kit_spec.loader.exec_module(_worker_kit_module)
_runtime_verifier_fixture = _worker_kit_module._runtime_verifier_fixture


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


def test_worker_kit_export_omits_macos_appledouble_metadata():
    repo_root = Path(__file__).resolve().parents[3]
    export_script = (repo_root / "deploy" / "worker-kit" / "export.sh").read_text(
        encoding="utf-8"
    )

    assert 'COPYFILE_DISABLE=1 tar -C "${STAGING}" -czf "${ARCHIVE}"' in export_script


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
        (kit / "manifest.json").write_text(
            '{"schema_version":1,"kit_version":"0.3.5"}',
            encoding="utf-8",
        )
        shutil.copy2(repo_root / "deploy/worker-kit/verify-runtime.sh", kit / "verify-runtime.sh")
        (kit / "verify-runtime.sh").chmod(0o755)
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
                "CODIFY_CLAUDE_BIN=/usr/local/bin/claude",
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
        (scripts / "verify-worker-runtime.sh").chmod(0o755)
        archive = root / "offline-bundle.tar.gz"
        with tarfile.open(archive, "w:gz") as output:
            output.add(source, arcname="offline-bundle")
        extracted = root / "extracted"
        extracted.mkdir()
        with tarfile.open(archive, "r:gz") as input_archive:
            input_archive.extractall(extracted)
        wrapper = extracted / "offline-bundle/scripts/verify-worker-runtime.sh"

        def run(document=None, *, actual_sha="a" * 64, extra=None):
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
                    "IMAGE_INSPECT": json.dumps(image_inspect),
                },
                capture_output=True,
                text=True,
                check=False,
            )

        assert run(bundle).returncode == 0
        assert run(None).returncode != 0
        assert run(bundle, actual_sha="e" * 64).returncode != 0
        mismatched = json.loads(json.dumps(bundle))
        mismatched["adapters"]["pi"]["source"]["artifact_sha256"] = "f" * 64
        assert run(mismatched).returncode != 0


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
        for name in ("verify-runtime.sh", "validate-runtime-manifest.py"):
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
        kit_archive = kits_dir / "codify-worker-kit-0.1.0-linux-amd64.tar.gz"
        real_kit, fixture_manifest, artifact, fake_docker = _runtime_verifier_fixture(tmp_path / "source-kit")
        shutil.copy2(repo_root / "deploy/worker-kit/verify-runtime.sh", real_kit / "verify-runtime.sh")
        (real_kit / "verify-runtime.sh").chmod(0o755)
        with tarfile.open(kit_archive, "w:gz") as kit_output:
            kit_output.add(real_kit, arcname="0.1.0-linux-amd64")
        kit_digest = hashlib.sha256(kit_archive.read_bytes()).hexdigest()
        (kits_dir / f"{kit_archive.name}.sha256").write_text(
            f"{kit_digest}  {kit_archive.name}\n", encoding="utf-8"
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
        assert "offline-bundle/kits/codify-worker-kit-0.1.0-linux-amd64.tar.gz" in names
        assert "offline-bundle/scripts/verify-worker-runtime.sh" in names

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
        packaged_kit = extracted / "offline-bundle/kits/codify-worker-kit-0.1.0-linux-amd64.tar.gz"
        with tarfile.open(packaged_kit, "r:gz") as kit_input:
            kit_input.extractall(installed)
        kit = installed / "0.1.0-linux-amd64"
        runtime_path = tmp_path / "packaged-runtime.json"
        runtime_path.write_text(json.dumps(fixture_manifest), encoding="utf-8")
        run_result = subprocess.run(
            [str(wrapper), "--kit", str(kit), "--image", "fake:image", "--runtime-manifest", str(runtime_path), "--all-harnesses"],
            cwd=extracted,
            env={
                **os.environ,
                "PATH": f"{fake_docker.parent}{os.pathsep}{os.environ['PATH']}",
                "ARTIFACT_PATH": str(artifact),
                "ACTUAL_CLI_SHA": "a" * 64,
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
        ("0.1.0-linux-amd64/../sentinel", None, None),
        ("/tmp/codify-kit-escape", None, None),
        ("wrong-root/file", None, None),
        ("0.1.0-linux-amd64/link", "../../sentinel", tarfile.SYMTYPE),
        ("0.1.0-linux-amd64/hardlink", "../../sentinel", tarfile.LNKTYPE),
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
    for name in ("verify-runtime.sh", "validate-runtime-manifest.py"):
        shutil.copy2(repo_root / f"deploy/worker-kit/{name}", worker_kit_dir / name)
    (worker_kit_dir / "verify-runtime.sh").chmod(0o755)
    shutil.copy2(repo_root / "deploy/offline-bundle/scripts/package-bundle.sh", scripts_dir)
    shutil.copy2(repo_root / "deploy/offline-bundle/scripts/validate-kit-archive.py", scripts_dir)
    (scripts_dir / "package-bundle.sh").chmod(0o755)
    (bundle_dir / "images/codify-offline-images.tar.gz").write_text("image", encoding="utf-8")
    archive = kits_dir / "codify-worker-kit-0.1.0-linux-amd64.tar.gz"
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
