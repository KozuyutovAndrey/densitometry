import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from viewer import reconstruct, server


class ViewerAdapterTests(unittest.TestCase):
    def test_server_starts_without_demo_jobs(self):
        self.assertEqual({}, server.JOBS)

    def test_result_parser_matches_submission_rows(self):
        images = server.results(
            server.ROOT / "artifacts/submission_test.csv",
            server.ROOT / "artifacts/full_inference_test",
        )
        self.assertEqual(3, len(images))
        self.assertEqual({"spine", "left_hip", "right_hip"}, {row["anatomical_region"] for row in images})
        self.assertTrue(all(row["processing_status"] == "Success" for row in images))
        self.assertTrue(any(row["landmarks"] for row in images))

    def test_snapshot_does_not_expose_local_paths(self):
        public = server.snapshot({"id": "job", "status": "queued", "_input": Path("private.zip")})
        self.assertEqual({"id": "job", "status": "queued"}, public)

    def test_archive_label_is_safe_and_human_readable(self):
        self.assertEqual("batch 01", server.archive_label("batch%2001.zip"))
        self.assertEqual("secret", server.archive_label("../../secret.zip"))
        self.assertEqual("Новый пакет исследований", server.archive_label(""))

    def test_qc_job_delegates_to_existing_full_inference_script(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            job = {
                "id": "job",
                "status": "queued",
                "_folder": folder,
                "_input": folder / "input.zip",
            }
            with patch.object(server.subprocess, "run") as run, patch.object(server, "results", return_value=[]):
                server.run_job(job)
            command = run.call_args.args[0]
            self.assertEqual("completed", job["status"])
            self.assertIn(str(server.ROOT / "scripts/run_full_inference.py"), command)
            self.assertIn("--input", command)
            self.assertIn("--out-csv", command)
            self.assertIn("--work-dir", command)

    def test_3d_is_enabled_only_with_existing_repo_and_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            (repo / "inference.py").write_text("# upstream entrypoint\n")
            (repo / "model.py").write_text("def create_model():\n    pass\n")
            checkpoint = root / "model.pt"
            checkpoint.write_bytes(b"checkpoint")
            with patch.dict(os.environ, {"DXA3D_REPO": str(repo), "DXA3D_CHECKPOINT": str(checkpoint)}, clear=False):
                self.assertTrue(server.reconstruction_enabled())

    def test_missing_3d_configuration_has_user_facing_message(self):
        with patch.dict(os.environ, {}, clear=True):
            enabled, reason = server.reconstruction_status()
        self.assertFalse(enabled)
        self.assertNotIn("DXA3D_", reason)
        self.assertIn("не подключена", reason)

    def test_pinned_upstream_is_reported_as_incompatible(self):
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "model.pt"
            checkpoint.write_bytes(b"checkpoint")
            repo = server.ROOT / "third_party/DXA-to-3D"
            with patch.dict(os.environ, {"DXA3D_REPO": str(repo), "DXA3D_CHECKPOINT": str(checkpoint)}, clear=False):
                enabled, reason = server.reconstruction_status()
            self.assertFalse(enabled)
            self.assertIn("несовместима", reason)

    def test_3d_points_validation_rejects_invalid_values(self):
        self.assertEqual([[0.0, 1.0, 2.0], [3.0, 4.0, 5.0]], reconstruct.validate_points([[0.0, 1.0, 2.0], [3.0, 4.0, 5.0]]))
        with self.assertRaises(ValueError):
            reconstruct.validate_points([[0.0, 1.0, float("nan")], [3.0, 4.0, 5.0]])


if __name__ == "__main__":
    unittest.main()
