import os
import csv
import io
import tempfile
import unittest
import zipfile
import struct
import sys
from pathlib import Path
from unittest.mock import patch

from viewer import gradcam, reconstruct, server
from viewer.xlsx_export import workbook_bytes
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from scripts import predict_landmarks_heatmap as heatmap_landmarks
from scripts.run_full_inference import export_submission
from scripts.prepare_artifacts import is_dicom_member


class ViewerAdapterTests(unittest.TestCase):
    @staticmethod
    def extensionless_dicom_bytes():
        raw = bytearray(132)
        raw[128:132] = b"DICM"
        raw.extend(struct.pack("<HH2sH", 0x0028, 0x0010, b"US", 2))
        raw.extend(struct.pack("<H", 300))
        raw.extend(struct.pack("<HH2sH", 0x0028, 0x0011, b"US", 2))
        raw.extend(struct.pack("<H", 280))
        return bytes(raw)

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

    def test_violation_description_explains_spine_and_hip_details(self):
        spine = server.violation_description(
            {"anatomical_region": "spine", "violation_type": "spine_positioning;spine_artifact"},
            {"spine_axis_angle_deg": ""},
            {},
        )
        self.assertIn("Не обнаружены подвздошные кости", spine)
        self.assertIn("артефакта", spine)

        hip_points = {
            "hip_greater_trochanter_top_edge_visible": "1",
            "hip_greater_trochanter_top_edge_x": "100",
            "hip_greater_trochanter_top_edge_y": "100",
            "hip_greater_trochanter_lateral_edge_visible": "1",
            "hip_greater_trochanter_lateral_edge_x": "120",
            "hip_greater_trochanter_lateral_edge_y": "80",
            "hip_lesser_trochanter_upper_visible": "1",
            "hip_lesser_trochanter_upper_x": "140",
            "hip_lesser_trochanter_upper_y": "90",
            "hip_lesser_trochanter_lower_visible": "1",
            "hip_lesser_trochanter_lower_x": "160",
            "hip_lesser_trochanter_lower_y": "120",
        }
        hip = server.violation_description(
            {"anatomical_region": "right_hip", "violation_type": "hip_positioning_rotation;hip_roi"},
            {
                "hip_lesser_prominence_mm": "7.0",
                "hip_top_margin_mm": "20",
                "hip_bottom_margin_mm": "40",
                "hip_lateral_margin_mm": "10",
            },
            hip_points,
        )
        self.assertIn("Некорректное позиционирование", hip)
        self.assertIn("Ротация бедра (недостаточная)", hip)
        self.assertIn("Недостаточный верхний захват", hip)
        self.assertIn("Недостаточный латеральный захват", hip)

    def test_hip_lesser_lower_respects_laterality_anchor(self):
        right_points = {
            "hip_greater_trochanter_top_edge": (30.0, 10.0),
            "hip_lesser_trochanter_lower": (20.0, 50.0),
        }
        heatmap_landmarks.enforce_hip_side_order(right_points, "right_hip")
        self.assertGreaterEqual(
            right_points["hip_lesser_trochanter_lower"][0],
            right_points["hip_greater_trochanter_top_edge"][0],
        )

        left_points = {
            "hip_greater_trochanter_top_edge": (30.0, 10.0),
            "hip_lesser_trochanter_lower": (45.0, 50.0),
        }
        heatmap_landmarks.enforce_hip_side_order(left_points, "left_hip")
        self.assertLessEqual(
            left_points["hip_lesser_trochanter_lower"][0],
            left_points["hip_greater_trochanter_top_edge"][0],
        )

    def test_spine_positioning_bad_hides_iliac_landmarks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / "work"
            work.mkdir()
            with (root / "submission.csv").open("w", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=server.FIELDS)
                writer.writeheader()
                writer.writerow({
                    "path_to_study": "study",
                    "study_uid": "study",
                    "image_uid": "image",
                    "anatomical_region": "spine",
                    "quality_class": "1",
                    "violation_type": "spine_positioning",
                    "processing_status": "Success",
                    "time_of_processing": "0.1",
                })
            with (work / "quality_predictions_debug.csv").open("w", newline="") as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=["member", "filename", "image_uid", "anatomical_region", "spine_positioning_pred_bad"],
                )
                writer.writeheader()
                writer.writerow({
                    "member": "spine.dcm",
                    "filename": "spine.dcm",
                    "image_uid": "image",
                    "anatomical_region": "spine",
                    "spine_positioning_pred_bad": "1",
                })
            with (work / "inference_skeleton.csv").open("w", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=["member", "columns", "rows"])
                writer.writeheader()
                writer.writerow({"member": "spine.dcm", "columns": "300", "rows": "400"})
            with (work / "inference_landmark_predictions_hybrid.csv").open("w", newline="") as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=[
                        "member",
                        "landmark_model",
                        "spine_l1_center_x",
                        "spine_l1_center_y",
                        "spine_l1_center_visible",
                        "spine_left_iliac_crest_x",
                        "spine_left_iliac_crest_y",
                        "spine_left_iliac_crest_visible",
                        "spine_right_iliac_crest_x",
                        "spine_right_iliac_crest_y",
                        "spine_right_iliac_crest_visible",
                    ],
                )
                writer.writeheader()
                writer.writerow({
                    "member": "spine.dcm",
                    "landmark_model": "hybrid:test",
                    "spine_l1_center_x": "100",
                    "spine_l1_center_y": "120",
                    "spine_l1_center_visible": "1",
                    "spine_left_iliac_crest_x": "80",
                    "spine_left_iliac_crest_y": "360",
                    "spine_left_iliac_crest_visible": "1",
                    "spine_right_iliac_crest_x": "220",
                    "spine_right_iliac_crest_y": "360",
                    "spine_right_iliac_crest_visible": "1",
                })

            images = server.results(root / "submission.csv", work)

        names = {point["name"] for point in images[0]["landmarks"]}
        self.assertIn("spine_l1_center", names)
        self.assertNotIn("spine_left_iliac_crest", names)
        self.assertNotIn("spine_right_iliac_crest", names)

    def test_archive_label_is_safe_and_human_readable(self):
        self.assertEqual("batch 01", server.archive_label("batch%2001.zip"))
        self.assertEqual("secret", server.archive_label("../../secret.zip"))
        self.assertEqual("Новый пакет исследований", server.archive_label(""))

    def test_extensionless_dicom_is_accepted_by_upload_and_pipeline(self):
        raw = self.extensionless_dicom_bytes()
        self.assertTrue(is_dicom_member("study/IM000001", raw))
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("study/IM000001", raw)
        with zipfile.ZipFile(io.BytesIO(archive_bytes.getvalue())) as archive:
            self.assertTrue(server.archive_contains_dicom(archive))

    def test_upload_body_is_streamed_to_disk_without_size_cap(self):
        payload = b"x" * (server.UPLOAD_CHUNK * 2 + 17)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "large.zip"
            server.save_request_body(io.BytesIO(payload), target, len(payload))
            self.assertEqual(payload, target.read_bytes())

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

    def test_docker_image_does_not_force_cuda(self):
        dockerfile = (server.ROOT / "Dockerfile").read_text()
        self.assertNotIn("QC_DEVICE=cuda", dockerfile)

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

    def test_3d_worker_runs_reconstruction_as_importable_module(self):
        command = server.reconstruction_command(Path("input.png"), Path("result.json"))
        self.assertEqual(["-m", "viewer.reconstruct"], command[1:3])

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
        content = workbook_bytes([{"image_uid": "1&2", "quality_class": "1", "violation_description": "Недостаточный верхний захват", "time_of_processing": "0.25"}], server.FIELDS)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertEqual("PK", content[:2].decode())
            sheet = archive.read("xl/worksheets/sheet1.xml").decode()
            self.assertIn("1&amp;2", sheet)
            self.assertIn("Недостаточный верхний захват", sheet)
            self.assertIn("<v>0.25</v>", sheet)

    def test_ui_has_blocking_processing_status(self):
        html = (server.STATIC / "index.html").read_text()
        script = (server.STATIC / "app.js").read_text()
        self.assertIn('id="processing-overlay"', html)
        self.assertIn("Идёт обработка исследований", script)
        self.assertIn("updateProcessingOverlay", script)

    def test_ui_has_explainability_overlay_toggle(self):
        html = (server.STATIC / "index.html").read_text()
        script = (server.STATIC / "app.js").read_text()
        self.assertIn('id="explain"', html)
        self.assertIn("Объяснение", html)
        self.assertIn("drawExplanationOverlay", script)
        self.assertIn("Описание нарушения", html)
        self.assertIn("card-reason", script)
        self.assertIn("hip_lateral_margin_mm", script)
        self.assertIn("spine_axis_angle_deg", script)

    def test_ui_has_gradcam_overlay_controls(self):
        html = (server.STATIC / "index.html").read_text()
        script = (server.STATIC / "app.js").read_text()
        self.assertIn('id="gradcam"', html)
        self.assertIn("Тепловая карта артефактов", html)
        self.assertNotIn("Grad-CAM: артефакты", script)
        self.assertIn("loadGradcam", script)
        self.assertIn("drawGradcam", script)

    def test_gradcam_rejects_non_spine_images(self):
        with self.assertRaises(ValueError):
            server.gradcam_bytes({"id": "job"}, {"id": "1", "anatomical_region": "left_hip"}, "artifact")

    def test_gradcam_heatmap_colorizer_returns_transparent_png_layer(self):
        layer = gradcam.colorize_heatmap(gradcam.normalize_heatmap(__import__("numpy").array([[0.0, 2.0], [1.0, 4.0]])), "artifact")
        self.assertEqual("RGBA", layer.mode)
        self.assertEqual((2, 2), layer.size)
        self.assertGreater(__import__("numpy").asarray(layer.getchannel("A")).max(), 0)

    def test_artifact_gradcam_png_is_empty_below_threshold(self):
        with patch.object(gradcam, "gradcam_overlay") as overlay:
            overlay.return_value = (__import__("PIL").Image.new("RGBA", (2, 2), (255, 120, 20, 180)), 0.1, 0.2)
            data = gradcam.gradcam_png_bytes(__import__("PIL").Image.new("L", (2, 2)), "artifact")
        image = __import__("PIL").Image.open(io.BytesIO(data))
        self.assertEqual(0, __import__("numpy").asarray(image.getchannel("A")).max())


if __name__ == "__main__":
    unittest.main()
