import shutil
import stat
import subprocess
import tarfile
import tempfile
from pathlib import Path


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
    assert "deploy/offline-bundle && ./scripts/export-images.sh" in result.stdout
    assert "deploy/offline-bundle && ./scripts/package-bundle.sh" in result.stdout


def test_package_bundle_script_creates_archive_under_deploy_directory():
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "deploy" / "offline-bundle" / "scripts" / "package-bundle.sh"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        deploy_dir = tmp_path / "deploy"
        bundle_dir = deploy_dir / "offline-bundle"
        scripts_dir = bundle_dir / "scripts"
        images_dir = bundle_dir / "images"

        scripts_dir.mkdir(parents=True)
        images_dir.mkdir(parents=True)
        (bundle_dir / "README.md").write_text("offline bundle", encoding="utf-8")
        (images_dir / "codify-offline-images.tar.gz").write_text("image archive", encoding="utf-8")

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
        assert "codify-offline-bundle.tar.gz" not in names
