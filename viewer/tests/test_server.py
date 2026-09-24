import os
import csv
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from viewer import reconstruct, server
from viewer.xlsx_export import workbook_bytes
from scripts.run_full_inference import export_submission


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

    def test_3d_is_enabled_with_existing_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint = root / "model.pt"
            checkpoint.write_bytes(b"checkpoint")
            with patch.dict(os.environ, {"DXA3D_CHECKPOINT": str(checkpoint)}, clear=False):
                self.assertTrue(server.reconstruction_enabled())

    def test_missing_3d_configuration_has_user_facing_message(self):
        with patch.dict(os.environ, {}, clear=True):
            enabled, reason = server.reconstruction_status()
        self.assertFalse(enabled)
        self.assertNotIn("DXA3D_", reason)
        self.assertIn("не загружена", reason)

    def test_3d_points_validation_rejects_invalid_values(self):
        self.assertEqual([[0.0, 1.0, 2.0], [3.0, 4.0, 5.0]], reconstruct.validate_points([[0.0, 1.0, 2.0], [3.0, 4.0, 5.0]]))
        with self.assertRaises(ValueError):
            reconstruct.validate_points([[0.0, 1.0, float("nan")], [3.0, 4.0, 5.0]])

    def test_published_curves_are_converted_to_3d_centerline(self):
        curves = [[0.0] * 6 for _ in range(209)]
        curves[0][1], curves[0][4] = 0.25, 0.75
        points = reconstruct.curves_to_points(curves)
        self.assertEqual(209, len(points))
        self.assertEqual([0.25, 0.0, 0.75], points[0])
        self.assertEqual(1.0, points[-1][1])

    def test_submission_uses_measured_time_for_each_dicom(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            debug = root / "debug.csv"
            timing = root / "timing.csv"
            output = root / "submission.csv"
            with debug.open("w", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=["member", "path_to_study", "dicom_study_uid", "image_uid", "anatomical_region", "quality_class", "violation_type", "processing_status"])
                writer.writeheader()
                writer.writerows([
                    {"member": "a.dcm", "image_uid": "a", "quality_class": "0", "processing_status": "quality_predicted"},
                    {"member": "b.dcm", "image_uid": "b", "quality_class": "1", "processing_status": "quality_predicted"},
                ])
            with timing.open("w", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=["member", "processing_seconds"])
                writer.writeheader()
                writer.writerows([{"member": "a.dcm", "processing_seconds": "0.125"}, {"member": "b.dcm", "processing_seconds": "0.875"}])
            export_submission(debug, output, 10.0, [timing])
            with output.open() as file:
                values = list(csv.DictReader(file))
            self.assertEqual(["0.125000", "0.875000"], [row["time_of_processing"] for row in values])

    def test_xlsx_export_is_a_valid_office_archive(self):
        content = workbook_bytes([{"image_uid": "1&2", "quality_class": "1", "time_of_processing": "0.25"}], server.FIELDS)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertEqual("PK", content[:2].decode())
            sheet = archive.read("xl/worksheets/sheet1.xml").decode()
            self.assertIn("1&amp;2", sheet)
            self.assertIn("<v>0.25</v>", sheet)


if __name__ == "__main__":
    unittest.main()
