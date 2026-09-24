"""Local UI adapter. The team's inference scripts remain the source of QC results."""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).parent / "web"
STORE = ROOT / "artifacts" / "viewer_jobs"
sys.path.insert(0, str(ROOT))

FIELDS = ["path_to_study", "study_uid", "image_uid", "anatomical_region", "quality_class", "violation_type", "processing_status", "time_of_processing"]
JOBS: dict[str, dict] = {}
LOCK = threading.RLock()
POOL = ThreadPoolExecutor(max_workers=1)
MAX_UPLOAD = 512 * 1024 * 1024


def rows(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def results(submission, work):
    debug = rows(work / "quality_predictions_debug.csv")
    skeleton = {r["member"]: r for r in rows(work / "inference_skeleton.csv")}
    landmarks = {r["member"]: r for r in rows(work / "inference_landmark_predictions_hybrid.csv")}
    output = []
    # Submission and debug preserve input order, including repeated image UIDs.
    final = rows(submission)
    if len(final) != len(debug):
        raise ValueError("Количество строк результата и debug не совпадает")
    for i, (row, detail) in enumerate(zip(final, debug)):
        if row["image_uid"] != detail["image_uid"]:
            raise ValueError("Порядок изображений в результате и debug не совпадает")
        member = detail["member"]
        point_row = landmarks.get(member, {})
        points = []
        for key, val in point_row.items():
            if key.endswith("_x") and point_row.get(key[:-2] + "_visible") == "1":
                x, y = number(val), number(point_row.get(key[:-2] + "_y"))
                if x is not None and y is not None:
                    points.append({"name": key[:-2], "x": x, "y": y})
        output.append({**row, "id": str(i), "member": member,
                       "filename": detail.get("filename", Path(member).name),
                       "width": number(skeleton.get(member, {}).get("columns")),
                       "height": number(skeleton.get(member, {}).get("rows")),
                       "landmarks": points, "landmark_model": point_row.get("landmark_model", ""),
                       "metrics": {k: number(detail.get(k)) for k in ["spine_axis_angle_deg", "hip_lesser_prominence_mm", "hip_top_margin_mm", "hip_bottom_margin_mm", "hip_lateral_margin_mm"]}})
    return output


def snapshot(job):
    with LOCK:
        return {k: v for k, v in job.items() if not k.startswith("_")}


def archive_label(header):
    name = Path(unquote(header or "")).name
    if name.lower().endswith(".zip"):
        name = name[:-4]
    return name[:100] or "Новый пакет исследований"


def run_job(job):
    with LOCK:
        job["status"] = "running"
    folder = job["_folder"]
    command = [os.environ.get("QC_PYTHON", sys.executable), str(ROOT / "scripts/run_full_inference.py"),
               "--input", str(job["_input"]), "--out-csv", str(folder / "submission.csv"), "--work-dir", str(folder / "work")]
    if os.environ.get("QC_DEVICE"):
        command += ["--device", os.environ["QC_DEVICE"]]
    try:
        with (folder / "inference.log").open("w") as log:
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=3600)
        images = results(folder / "submission.csv", folder / "work")
        with LOCK:
            job.update(status="completed", images=images)
    except Exception:
        with LOCK:
            job.update(status="failed", error="Анализ не завершён. Проверьте зависимости и журнал inference.log в папке задания.")


def image_bytes(job, item):
    # Keep DICOM/image dependencies out of API startup and lightweight tests.
    from scripts.prepare_artifacts import image_from_dicom

    with zipfile.ZipFile(job["_input"]) as z:
        info = z.getinfo(item["member"])
        if info.file_size > 64 * 1024 * 1024:
            raise ValueError("Изображение слишком большое для просмотра")
        image, _ = image_from_dicom(z.read(info))
    return image


def reconstruction_status():
    repo = Path(os.environ.get("DXA3D_REPO", ""))
    checkpoint = Path(os.environ.get("DXA3D_CHECKPOINT", ""))
    if not os.environ.get("DXA3D_REPO") or not os.environ.get("DXA3D_CHECKPOINT"):
        return False, "3D-реконструкция пока не подключена к серверной сборке"
    if not (repo / "inference.py").is_file() or not checkpoint.is_file():
        return False, "Не найден исходный код DXA-to-3D или checkpoint"
    model_path = repo / "model.py"
    if not model_path.is_file() or "def create_model" not in model_path.read_text(errors="ignore"):
        return False, "Версия DXA-to-3D несовместима с опубликованным inference API"
    return True, ""


def reconstruction_enabled():
    return reconstruction_status()[0]


def reconstruct(job, item):
    folder = STORE / job["id"] / ("3d-" + item["id"])
    folder.mkdir(parents=True, exist_ok=True)
    try:
        image_bytes(job, item).save(folder / "input.png")
        with (folder / "reconstruction.log").open("w") as log:
            subprocess.run([os.environ.get("DXA3D_PYTHON", sys.executable), str(Path(__file__).parent / "reconstruct.py"),
                            "--input", str(folder / "input.png"), "--output", str(folder / "result.json")],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
        value = json.loads((folder / "result.json").read_text())
        with LOCK:
            job["reconstructions"][item["id"]] = {"status": "completed", **value}
    except Exception:
        with LOCK:
            job["reconstructions"][item["id"]] = {"status": "failed", "error": "Реконструкция не выполнена. Проверьте веса, зависимости и журнал reconstruction.log."}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *_):
        pass

    def send_data(self, value, status=200, content_type="application/json; charset=utf-8"):
        data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode() if not isinstance(value, bytes) else value
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        if parts[0] != "api":
            return super().do_GET()
        try:
            if parts == ["api", "health"]:
                enabled, reason = reconstruction_status()
                return self.send_data({"status": "ok", "reconstruction": enabled,
                                       "reconstruction_reason": reason})
            if parts == ["api", "jobs"]:
                return self.send_data([snapshot(j) for j in list(JOBS.values())])
            if len(parts) < 3 or parts[1] != "jobs" or parts[2] not in JOBS:
                return self.send_data({"error": "Задание не найдено"}, 404)
            job = JOBS[parts[2]]
            if len(parts) == 3:
                return self.send_data(snapshot(job))
            if parts[3:] == ["export.csv"]:
                out = io.StringIO(newline="")
                writer = csv.DictWriter(out, FIELDS, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(job.get("images", []))
                return self.send_data(out.getvalue().encode("utf-8-sig"), content_type="text/csv; charset=utf-8")
            if len(parts) == 6 and parts[3] == "images" and parts[5] == "preview.png":
                item = next(r for r in job["images"] if r["id"] == parts[4])
                out = io.BytesIO()
                image_bytes(job, item).save(out, format="PNG")
                return self.send_data(out.getvalue(), content_type="image/png")
            return self.send_data({"error": "Маршрут не найден"}, 404)
        except (ValueError, KeyError, StopIteration, OSError, zipfile.BadZipFile):
            return self.send_data({"error": "Не удалось прочитать данные изображения"}, 422)

    def do_POST(self):
        # Local-only server; reject browser requests from foreign origins.
        if self.headers.get("Origin") and urlparse(self.headers["Origin"]).netloc != self.headers.get("Host"):
            return self.send_data({"error": "Недопустимый источник запроса"}, 403)
        parts = urlparse(self.path).path.strip("/").split("/")
        if parts == ["api", "jobs"]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_UPLOAD:
                    return self.send_data({"error": "Допустим ZIP размером до 512 МБ"}, 413)
                with LOCK:
                    if sum(j["status"] in {"queued", "running"} for j in JOBS.values()) >= 4:
                        return self.send_data({"error": "Очередь заполнена. Дождитесь завершения анализа."}, 429)
                payload = self.rfile.read(length)
                if len(payload) != length:
                    raise ValueError()
                with zipfile.ZipFile(io.BytesIO(payload)) as z:
                    if not any(n.lower().endswith(".dcm") for n in z.namelist()):
                        raise ValueError()
                    if len(z.infolist()) > 10000 or sum(i.file_size for i in z.infolist()) > 2 * 1024**3:
                        raise ValueError()
                key = uuid.uuid4().hex
                folder = STORE / key
                folder.mkdir(parents=True)
                source = folder / "input.zip"
                source.write_bytes(payload)
                job = {"id": key, "name": archive_label(self.headers.get("X-Archive-Name")),
                       "created": time.time(), "status": "queued",
                       "archived": False, "images": [], "reconstructions": {}, "_input": source, "_folder": folder}
                with LOCK:
                    JOBS[key] = job
                POOL.submit(run_job, job)
                return self.send_data(snapshot(job), 202)
            except (ValueError, zipfile.BadZipFile):
                return self.send_data({"error": "Нужен корректный ZIP с файлами .dcm, до 10 000 файлов и 2 ГБ после распаковки"}, 400)
        if len(parts) == 6 and parts[:2] == ["api", "jobs"] and parts[3] == "images" and parts[5] == "reconstruct":
            if not reconstruction_enabled():
                return self.send_data({"error": reconstruction_status()[1]}, 503)
            job = JOBS.get(parts[2])
            item = next((r for r in (job or {}).get("images", []) if r["id"] == parts[4]), None)
            if not item or item["anatomical_region"] != "spine":
                return self.send_data({"error": "Реконструкция доступна только для позвоночника"}, 422)
            with LOCK:
                previous = job["reconstructions"].get(item["id"], {})
                if previous.get("status") not in {"queued", "completed"}:
                    job["reconstructions"][item["id"]] = {"status": "queued"}
                    POOL.submit(reconstruct, job, item)
            return self.send_data(snapshot(job), 202)
        self.send_data({"error": "Маршрут не найден"}, 404)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    display_host = "127.0.0.1" if args.host == "0.0.0.0" else args.host
    print(f"Densitometry viewer: http://{display_host}:{args.port}", flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
