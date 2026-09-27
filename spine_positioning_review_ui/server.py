from __future__ import annotations

import argparse
import csv
import json
import mimetypes
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = ROOT / "artifacts" / "spine_positioning_dataset"
ANNOTATIONS_CSV = DATASET_DIR / "annotations.csv"
REVIEW_CSV = DATASET_DIR / "manual_iliac_review.csv"
WEB_DIR = Path(__file__).resolve().parent / "web"

REVIEW_FIELDNAMES = [
    "review_id",
    "image_number",
    "pilot_id",
    "split",
    "study_folder",
    "filename",
    "image_path",
    "source_image_path",
    "augmentation",
    "synthetic",
    "original_iliac_visible",
    "original_positioning_bad",
    "review_iliac_visible",
    "review_positioning_bad",
    "review_status",
    "review_use_for_training",
    "review_notes",
    "updated_at",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fp:
        return list(csv.DictReader(fp))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def review_id(row: dict[str, str]) -> str:
    base = f"img{int(row['image_number']):03d}_pilot{int(row['pilot_id']):04d}_{row['filename']}"
    if row.get("synthetic") == "1":
        return f"{base}_{row.get('augmentation', 'synthetic')}"
    return base


def load_review_items() -> list[dict[str, str]]:
    rows = read_csv(ANNOTATIONS_CSV)
    rows.sort(key=lambda r: (r.get("synthetic") == "1", int(r["image_number"]), r.get("augmentation", "")))
    return rows


def load_review_rows() -> dict[str, dict[str, str]]:
    if not REVIEW_CSV.exists():
        return {}
    return {row["review_id"]: row for row in read_csv(REVIEW_CSV)}


def positioning_bad_to_iliac_visible(value: str) -> str:
    if value == "1":
        return "0"
    if value == "0":
        return "1"
    return "?"


def iliac_visible_to_positioning_bad(value: str) -> str:
    if value == "1":
        return "0"
    if value == "0":
        return "1"
    return "?"


def build_items() -> list[dict[str, Any]]:
    reviews = load_review_rows()
    items: list[dict[str, Any]] = []
    for row in load_review_items():
        rid = review_id(row)
        original_positioning_bad = row.get("positioning_bad") or row.get("spine_positioning", "")
        original_iliac_visible = row.get("iliac_visible") or positioning_bad_to_iliac_visible(original_positioning_bad)
        review = reviews.get(rid, {})
        review_iliac_visible = review.get("review_iliac_visible", original_iliac_visible)
        review_positioning_bad = review.get(
            "review_positioning_bad",
            iliac_visible_to_positioning_bad(review_iliac_visible),
        )
        item = {
            "review_id": rid,
            "image_number": row.get("image_number", ""),
            "pilot_id": row.get("pilot_id", ""),
            "split": row.get("split", ""),
            "study_folder": row.get("study_folder", ""),
            "filename": row.get("filename", ""),
            "image_path": row.get("image_path", ""),
            "source_image_path": row.get("source_image_path", ""),
            "augmentation": row.get("augmentation", ""),
            "synthetic": row.get("synthetic", ""),
            "original_iliac_visible": original_iliac_visible,
            "original_positioning_bad": original_positioning_bad,
            "review_iliac_visible": review_iliac_visible,
            "review_positioning_bad": review_positioning_bad,
            "review_status": review.get("review_status", ""),
            "review_use_for_training": review.get("review_use_for_training", "1"),
            "review_notes": review.get("review_notes", ""),
            "updated_at": review.get("updated_at", ""),
        }
        item["image_url"] = f"/image/{rid}"
        item["changed"] = bool(item["review_status"] == "done" and item["review_iliac_visible"] != item["original_iliac_visible"])
        item["reviewed"] = item["review_status"] == "done"
        items.append(item)
    return items


def save_review(payload: dict[str, Any]) -> dict[str, Any]:
    rid = str(payload.get("review_id", ""))
    label = str(payload.get("review_iliac_visible", ""))
    status = str(payload.get("review_status", "done")) or "done"
    notes = str(payload.get("review_notes", ""))
    use_for_training = str(payload.get("review_use_for_training", "1"))
    if label not in {"0", "1", "?"}:
        raise ValueError("review_iliac_visible must be 0, 1, or ?")
    if use_for_training not in {"0", "1"}:
        raise ValueError("review_use_for_training must be 0 or 1")
    items = {item["review_id"]: item for item in build_items()}
    if rid not in items:
        raise KeyError(f"Unknown review_id: {rid}")
    reviews = load_review_rows()
    base = items[rid]
    positioning_bad = iliac_visible_to_positioning_bad(label)
    reviews[rid] = {
        "review_id": rid,
        "image_number": base["image_number"],
        "pilot_id": base["pilot_id"],
        "split": base["split"],
        "study_folder": base["study_folder"],
        "filename": base["filename"],
        "image_path": base["image_path"],
        "source_image_path": base.get("source_image_path", ""),
        "augmentation": base.get("augmentation", ""),
        "synthetic": base.get("synthetic", ""),
        "original_iliac_visible": base["original_iliac_visible"],
        "original_positioning_bad": base["original_positioning_bad"],
        "review_iliac_visible": label,
        "review_positioning_bad": positioning_bad,
        "review_status": status,
        "review_use_for_training": use_for_training,
        "review_notes": notes,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    ordered = [reviews[item["review_id"]] for item in build_items() if item["review_id"] in reviews]
    write_csv(REVIEW_CSV, ordered, REVIEW_FIELDNAMES)
    return reviews[rid]


def summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    reviewed = [item for item in items if item["reviewed"]]
    changed = [item for item in items if item["changed"]]
    return {
        "total": len(items),
        "reviewed": len(reviewed),
        "unreviewed": len(items) - len(reviewed),
        "changed": len(changed),
        "visible_original": sum(1 for item in items if item["original_iliac_visible"] == "1"),
        "missing_original": sum(1 for item in items if item["original_iliac_visible"] == "0"),
        "real_total": sum(1 for item in items if item.get("synthetic") == "0"),
        "synthetic_total": sum(1 for item in items if item.get("synthetic") == "1"),
        "visible_reviewed": sum(1 for item in reviewed if item["review_iliac_visible"] == "1"),
        "missing_reviewed": sum(1 for item in reviewed if item["review_iliac_visible"] == "0"),
        "uncertain_reviewed": sum(1 for item in reviewed if item["review_iliac_visible"] == "?"),
        "training_included": sum(1 for item in reviewed if item.get("review_use_for_training", "1") == "1"),
        "training_excluded": sum(1 for item in reviewed if item.get("review_use_for_training", "1") == "0"),
        "training_bad_included": sum(1 for item in reviewed if item.get("review_use_for_training", "1") == "1" and item["review_positioning_bad"] == "1"),
        "training_good_included": sum(1 for item in reviewed if item.get("review_use_for_training", "1") == "1" and item["review_positioning_bad"] == "0"),
        "review_csv": str(REVIEW_CSV.relative_to(ROOT)),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "IliacReviewUI/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def send_json(self, data: Any, status: int = 200) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        raw = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path in {"/", "/index.html"}:
            self.send_file(WEB_DIR / "index.html")
            return
        if path == "/app.js":
            self.send_file(WEB_DIR / "app.js")
            return
        if path == "/style.css":
            self.send_file(WEB_DIR / "style.css")
            return
        if path == "/api/items":
            items = build_items()
            self.send_json({"items": items, "summary": summary(items)})
            return
        if path.startswith("/image/"):
            rid = path.removeprefix("/image/")
            item_by_id = {item["review_id"]: item for item in build_items()}
            item = item_by_id.get(rid)
            if not item:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_file(DATASET_DIR / item["image_path"])
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/save":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            saved = save_review(payload)
            items = build_items()
            self.send_json({"saved": saved, "summary": summary(items)})
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=400)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8771)
    return parser.parse_args()


def main() -> None:
    if not ANNOTATIONS_CSV.exists():
        raise FileNotFoundError(ANNOTATIONS_CSV)
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Iliac review UI: http://127.0.0.1:{args.port}")
    if args.host not in {"127.0.0.1", "localhost"}:
        print(f"Listening on {args.host}:{args.port}")
    print(f"Review CSV: {REVIEW_CSV}")
    server.serve_forever()


if __name__ == "__main__":
    main()
