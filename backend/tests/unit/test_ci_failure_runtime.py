import tempfile
import unittest
from pathlib import Path

from app.models import CIFailureRun, Task


class CIFailureWorkerRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_materializes_ci_failure_bundle_for_repair_task(self):
        from app.core.worker_runtime import materialize_ci_failure_bundle

        source = self.root / "ci-failures" / "91"
        (source / "jobs").mkdir(parents=True)
        (source / "pipeline.json").write_text("{}", encoding="utf-8")
        (source / "failed-jobs.json").write_text("{}", encoding="utf-8")
        (source / "jobs" / "12345-build.log").write_text("failed", encoding="utf-8")

        runtime_path = self.root / "runtime"
        task = Task(id=314, issue_id=1, project_id=42, user_prompt="repair")
        task.trigger_source = "ci_auto_repair"
        task.ci_failure_run = CIFailureRun(id=91, project_id=42, pipeline_id=678, pipeline_sha="abc", pipeline_status="failed", bundle_path=str(source))

        materialize_ci_failure_bundle(task, runtime_path)

        copied = runtime_path / "ci-failure"
        self.assertTrue((copied / "pipeline.json").exists())
        self.assertEqual((copied / "jobs" / "12345-build.log").read_text(encoding="utf-8"), "failed")

    def test_materializes_ci_failure_bundle_for_manual_retry(self):
        from app.core.worker_runtime import materialize_ci_failure_bundle

        source = self.root / "ci-failures" / "91"
        source.mkdir(parents=True)
        (source / "pipeline.json").write_text("{}", encoding="utf-8")

        runtime_path = self.root / "runtime"
        task = Task(id=315, issue_id=1, project_id=42, user_prompt="retry repair")
        task.trigger_source = "retry"
        task.ci_failure_run_id = 91
        task.ci_failure_run = CIFailureRun(
            id=91,
            project_id=42,
            pipeline_id=678,
            pipeline_sha="abc",
            pipeline_status="failed",
            bundle_path=str(source),
        )

        materialize_ci_failure_bundle(task, runtime_path)

        self.assertTrue((runtime_path / "ci-failure" / "pipeline.json").exists())

    def test_missing_bundle_for_repair_task_raises_clear_error(self):
        from app.core.worker_runtime import materialize_ci_failure_bundle

        task = Task(id=314, issue_id=1, project_id=42, user_prompt="repair")
        task.trigger_source = "ci_auto_repair"
        task.ci_failure_run = CIFailureRun(id=91, project_id=42, pipeline_id=678, pipeline_sha="abc", pipeline_status="failed", bundle_path=str(self.root / "missing"))

        with self.assertRaisesRegex(RuntimeError, "CI failure bundle is not available"):
            materialize_ci_failure_bundle(task, self.root / "runtime")
