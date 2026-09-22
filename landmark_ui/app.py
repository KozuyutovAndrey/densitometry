from __future__ import annotations

import argparse
import csv
import io
import json
import shutil
import sys
import threading
import urllib.parse
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.prepare_artifacts import image_from_dicom  # noqa: E402


DEFAULT_PILOT_CSV = ROOT / "artifacts" / "landmark_pilot.csv"
DEFAULT_TRAIN_ZIP = ROOT / "data" / "НД_для_обучения.zip"
DEFAULT_TEST_ZIP = ROOT / "data" / "Для теста.zip"

STATUS_CHOICES = {"new", "in_progress", "done", "skip"}

SPINE_POINTS = [
    ("spine_th12_center", "Th12 центр"),
    ("spine_l1_center", "L1 центр"),
    ("spine_l2_center", "L2 центр"),
    ("spine_l3_center", "L3 центр"),
    ("spine_l4_center", "L4 центр"),
    ("spine_l5_center", "L5 центр"),
    ("spine_left_iliac_crest", "левый гребень подвздошной"),
    ("spine_right_iliac_crest", "правый гребень подвздошной"),
]

HIP_POINTS = [
    ("hip_greater_trochanter_top_edge", "верхний край большого вертела"),
    ("hip_greater_trochanter_lateral_edge", "боковой край большого вертела"),
    ("hip_lesser_trochanter_upper", "верх малого вертела"),
    ("hip_lesser_trochanter_tip", "кончик малого вертела"),
    ("hip_lesser_trochanter_lower", "низ малого вертела"),
    ("hip_ischium_edge", "край седалищной кости"),
]

ALL_POINT_KEYS = [key for key, _label in [*SPINE_POINTS, *HIP_POINTS]]

INDEX_HTML = r'''<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Landmarks DXA</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f6f7;
      --panel: #fff;
      --line: #d8e0e4;
      --text: #19242a;
      --muted: #64727c;
      --accent: #0f766e;
      --accent-soft: #dff5f1;
      --bad: #a33a2e;
      --warn: #a16207;
      --blue: #1d4ed8;
      --shadow: 0 1px 3px rgba(15, 23, 42, 0.12);
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg); color: var(--text); font: 14px/1.35 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    header { min-height: 58px; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 16px; border-bottom: 1px solid var(--line); background: var(--panel); position: sticky; top: 0; z-index: 20; }
    h1 { margin: 0; font-size: 17px; font-weight: 680; }
    main { display: grid; grid-template-columns: minmax(380px, 1fr) 440px; gap: 14px; padding: 14px; max-width: 1680px; margin: 0 auto; }
    button, select, input, textarea { font: inherit; }
    button { border: 1px solid var(--line); background: #fff; color: var(--text); border-radius: 7px; min-height: 34px; padding: 6px 10px; cursor: pointer; }
    button:hover { border-color: #9eb0b8; }
    button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
    button.active { background: var(--accent-soft); border-color: var(--accent); }
    button.danger { color: var(--bad); }
    button:disabled { opacity: .5; cursor: default; }
    select, input, textarea { border: 1px solid var(--line); border-radius: 7px; background: #fff; color: var(--text); padding: 7px 9px; width: 100%; }
    textarea { resize: vertical; min-height: 78px; }
    .toolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .stat { color: var(--muted); white-space: nowrap; }
    .panel { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; box-shadow: var(--shadow); min-width: 0; }
    .viewer { padding: 14px; }
    .stage-wrap { min-height: 520px; display: flex; align-items: center; justify-content: center; background: #111; border-radius: 8px; overflow: auto; padding: 12px; }
    #stage { position: relative; display: inline-block; line-height: 0; }
    #dicomImage { display: block; max-width: min(100%, 1040px); max-height: calc(100vh - 178px); object-fit: contain; image-rendering: pixelated; user-select: none; }
    #overlay { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; overflow: visible; }
    .meta-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin-top: 12px; }
    .meta { border: 1px solid var(--line); border-radius: 7px; padding: 8px; min-width: 0; }
    .meta b { display: block; font-size: 11px; color: var(--muted); margin-bottom: 3px; }
    .meta span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .side { padding: 14px; align-self: start; position: sticky; top: 72px; max-height: calc(100vh - 88px); overflow: auto; }
    .field { margin-bottom: 12px; }
    .field label { display: block; color: var(--muted); font-size: 12px; font-weight: 650; margin-bottom: 5px; }
    .point-list { display: grid; grid-template-columns: 1fr; gap: 6px; margin-bottom: 12px; }
    .point-btn { display: grid; grid-template-columns: 18px 1fr auto; align-items: center; gap: 8px; text-align: left; }
    .dot { width: 11px; height: 11px; border-radius: 999px; border: 2px solid var(--line); }
    .point-btn.set .dot { background: var(--accent); border-color: var(--accent); }
    .point-btn.current { border-color: var(--blue); box-shadow: 0 0 0 2px rgba(29,78,216,.12); }
    .coord { color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }
    .actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 12px 0; }
    .tag { display: inline-block; padding: 2px 7px; border-radius: 999px; background: #edf2f4; color: var(--muted); margin: 0 4px 5px 0; font-size: 12px; }
    .tag.bad { background: #fee2e2; color: var(--bad); }
    .tag.warn { background: #fef3c7; color: var(--warn); }
    .status { min-height: 20px; color: var(--muted); }
    .status.ok { color: var(--accent); }
    .status.error { color: var(--bad); }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; overflow-wrap: anywhere; }
    @media (max-width: 1020px) { main { grid-template-columns: 1fr; } .side { position: static; max-height: none; } .meta-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } header { align-items: flex-start; } }
  </style>
</head>
<body>
  <header>
    <h1>Разметка landmarks</h1>
    <div class="toolbar">
      <button id="prevBtn">←</button>
      <button id="nextBtn">→</button>
      <input id="jumpInput" type="number" min="1" value="1" style="width:82px">
      <button id="jumpBtn">Перейти</button>
      <select id="filterSelect" style="width:190px">
        <option value="all">все</option>
        <option value="todo">не готово</option>
        <option value="spine">позвоночник</option>
        <option value="hip">бедро</option>
        <option value="bad">плохие</option>
        <option value="good">хорошие контроли</option>
        <option value="done">готово</option>
        <option value="skip">пропущено</option>
      </select>
      <input id="searchInput" type="search" placeholder="study / файл / нарушение" style="width:220px">
      <span id="counter" class="stat"></span>
    </div>
  </header>

  <main>
    <section class="panel viewer">
      <div class="stage-wrap"><div id="stage"><img id="dicomImage" alt="DICOM"><svg id="overlay"></svg></div></div>
      <div class="meta-grid">
        <div class="meta"><b>pilot</b><span id="mPilot"></span></div>
        <div class="meta"><b>область</b><span id="mRegion"></span></div>
        <div class="meta"><b>качество</b><span id="mQuality"></span></div>
        <div class="meta"><b>размер</b><span id="mSize"></span></div>
      </div>
      <div class="meta" style="margin-top:8px"><b>путь</b><span id="mMember" class="mono"></span></div>
    </section>

    <aside class="panel side">
      <div class="field"><label>исследование</label><div id="studyId" class="mono"></div></div>
      <div id="tags"></div>
      <div class="field"><label>текущая точка</label><div id="currentPointName" class="mono"></div></div>
      <div class="point-list" id="pointList"></div>
      <div class="actions"><button id="clearPointBtn" class="danger">Очистить точку</button><button id="clearAllBtn" class="danger">Очистить все</button></div>
      <div class="field"><label>статус</label><select id="statusSelect"><option value="new">новая</option><option value="in_progress">в работе</option><option value="done">готово</option><option value="skip">пропустить</option></select></div>
      <div class="field"><label>заметки</label><textarea id="notesInput"></textarea></div>
      <div class="actions"><button id="saveBtn" class="primary">Сохранить</button><button id="saveNextBtn" class="primary">Сохранить и дальше</button></div>
      <div id="status" class="status"></div>
    </aside>
  </main>

  <script>
    const pointDefs = {
      spine: [["spine_th12_center", "Th12 центр"], ["spine_l1_center", "L1 центр"], ["spine_l2_center", "L2 центр"], ["spine_l3_center", "L3 центр"], ["spine_l4_center", "L4 центр"], ["spine_l5_center", "L5 центр"], ["spine_left_iliac_crest", "левый гребень подвздошной"], ["spine_right_iliac_crest", "правый гребень подвздошной"]],
      hip: [["hip_greater_trochanter_top_edge", "верхний край большого вертела"], ["hip_greater_trochanter_lateral_edge", "боковой край большого вертела"], ["hip_lesser_trochanter_upper", "верх малого вертела"], ["hip_lesser_trochanter_tip", "кончик малого вертела"], ["hip_lesser_trochanter_lower", "низ малого вертела"], ["hip_ischium_edge", "край седалищной кости"]],
    };
    const state = { rows: [], filtered: [], pos: 0, current: null, currentPoint: null };
    const $ = id => document.getElementById(id);
    function setStatus(text, kind="") { const el = $("status"); el.textContent = text || ""; el.className = "status " + kind; }
    function groupOf(row) { return row.pilot_group || (row.anatomical_region === "spine" ? "spine" : "hip"); }
    function defsFor(row) { return pointDefs[groupOf(row)] || []; }
    function getPoint(row, key) { const x = row[key + "_x"], y = row[key + "_y"]; if (x === undefined || y === undefined || x === "" || y === "") return null; return {x: Number(x), y: Number(y)}; }
    function setPoint(row, key, x, y) { row[key + "_x"] = String(Math.round(x * 10) / 10); row[key + "_y"] = String(Math.round(y * 10) / 10); }
    function clearPoint(row, key) { row[key + "_x"] = ""; row[key + "_y"] = ""; }
    function rowSearchText(row) { return [row.study_folder, row.filename, row.anatomical_region, row.violation_type, row.manual_notes, row.annotation_notes].join(" ").toLowerCase(); }
    function applyFilter() {
      const filter = $("filterSelect").value; const query = $("searchInput").value.trim().toLowerCase();
      state.filtered = state.rows.filter(row => {
        let ok = true;
        if (filter === "todo") ok = row.annotation_status !== "done" && row.annotation_status !== "skip";
        if (filter === "spine") ok = groupOf(row) === "spine";
        if (filter === "hip") ok = groupOf(row) === "hip";
        if (filter === "bad") ok = row.selected_reason === "bad_label";
        if (filter === "good") ok = row.selected_reason === "good_control";
        if (filter === "done") ok = row.annotation_status === "done";
        if (filter === "skip") ok = row.annotation_status === "skip";
        if (ok && query) ok = rowSearchText(row).includes(query);
        return ok;
      });
      state.pos = Math.min(state.pos, Math.max(0, state.filtered.length - 1)); renderCounter();
    }
    function renderCounter() { $("counter").textContent = state.filtered.length ? `${state.pos + 1} / ${state.filtered.length} (${state.rows.length})` : `0 / 0 (${state.rows.length})`; $("jumpInput").value = state.filtered.length ? state.pos + 1 : 0; $("prevBtn").disabled = state.pos <= 0; $("nextBtn").disabled = state.pos >= state.filtered.length - 1; }
    function renderTags(row) { const tags = $("tags"); tags.innerHTML = ""; for (const value of [row.selected_reason, row.violation_type || "без нарушения", row.manual_notes].filter(Boolean)) { const span = document.createElement("span"); span.className = "tag"; if (value === "bad_label" || row.quality_class === "1") span.classList.add("bad"); if (value === "good_control") span.classList.add("warn"); span.textContent = value; tags.appendChild(span); } }
    function renderPointList(row) {
      const list = $("pointList"); list.innerHTML = ""; const defs = defsFor(row);
      if (!state.currentPoint && defs.length) state.currentPoint = defs[0][0];
      if (!defs.some(([key]) => key === state.currentPoint) && defs.length) state.currentPoint = defs[0][0];
      for (const [key, label] of defs) {
        const point = getPoint(row, key); const btn = document.createElement("button");
        btn.type = "button"; btn.className = "point-btn" + (point ? " set" : "") + (state.currentPoint === key ? " current" : "");
        btn.innerHTML = `<span class="dot"></span><span>${label}</span><span class="coord">${point ? `${point.x}, ${point.y}` : "-"}</span>`;
        btn.addEventListener("click", () => { state.currentPoint = key; renderPointList(row); renderOverlay(); }); list.appendChild(btn);
      }
      const active = defs.find(([key]) => key === state.currentPoint); $("currentPointName").textContent = active ? active[1] : "";
    }
    function renderOverlay() {
      const row = state.current; const img = $("dicomImage"); const svg = $("overlay"); svg.innerHTML = "";
      if (!row || !img.naturalWidth || !img.clientWidth) return;
      svg.setAttribute("viewBox", `0 0 ${img.clientWidth} ${img.clientHeight}`);
      const scaleX = img.clientWidth / img.naturalWidth; const scaleY = img.clientHeight / img.naturalHeight;
      for (const [key, label] of defsFor(row)) {
        const point = getPoint(row, key); if (!point) continue;
        const x = point.x * scaleX; const y = point.y * scaleY;
        const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
        const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        circle.setAttribute("cx", x); circle.setAttribute("cy", y); circle.setAttribute("r", key === state.currentPoint ? 6 : 4.5); circle.setAttribute("fill", key === state.currentPoint ? "#1d4ed8" : "#0f766e"); circle.setAttribute("stroke", "white"); circle.setAttribute("stroke-width", "1.5");
        const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
        text.setAttribute("x", x + 8); text.setAttribute("y", y - 8); text.setAttribute("fill", "white"); text.setAttribute("stroke", "#111"); text.setAttribute("stroke-width", "3"); text.setAttribute("paint-order", "stroke"); text.setAttribute("font-size", "12"); text.textContent = label;
        g.appendChild(circle); g.appendChild(text); svg.appendChild(g);
      }
    }
    function updateForm(row) {
      $("mPilot").textContent = `${row.pilot_id} / ${row.selected_reason}`; $("mRegion").textContent = row.anatomical_region; $("mQuality").textContent = row.quality_class === "1" ? `плохое: ${row.violation_type}` : "хорошее"; $("mSize").textContent = `${row.columns} x ${row.rows}`; $("mMember").textContent = row.member; $("studyId").textContent = row.study_folder; $("statusSelect").value = row.annotation_status || "new"; $("notesInput").value = row.annotation_notes || "";
      renderTags(row); renderPointList(row); $("dicomImage").src = `/api/image/${row.index}.png?ts=${Date.now()}`;
    }
    async function loadCurrent() {
      if (!state.filtered.length) { setStatus("Нет строк", "error"); return; }
      const row = state.filtered[state.pos]; const res = await fetch(`/api/row/${row.index}`); if (!res.ok) throw new Error(await res.text());
      const data = await res.json(); state.current = data.row; const known = state.rows.find(r => r.index === data.row.index); if (known) Object.assign(known, data.row); state.currentPoint = null; updateForm(data.row); renderCounter(); setStatus("");
    }
    async function saveCurrent() {
      if (!state.current) return; state.current.annotation_status = $("statusSelect").value; state.current.annotation_notes = $("notesInput").value.trim();
      const payload = {annotation_status: state.current.annotation_status, annotation_notes: state.current.annotation_notes, points: {}};
      for (const [key] of defsFor(state.current)) payload.points[key] = getPoint(state.current, key) || null;
      const res = await fetch(`/api/row/${state.current.index}`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)}); if (!res.ok) throw new Error(await res.text());
      const data = await res.json(); const known = state.rows.find(r => r.index === data.row.index); if (known) Object.assign(known, data.row); Object.assign(state.current, data.row); applyFilter(); setStatus("Сохранено", "ok");
    }
    async function go(delta) { if (!state.filtered.length) return; state.pos = Math.max(0, Math.min(state.filtered.length - 1, state.pos + delta)); await loadCurrent(); }
    function imageClick(event) {
      if (!state.current || !state.currentPoint) return; const img = $("dicomImage"); const rect = img.getBoundingClientRect();
      const x = (event.clientX - rect.left) * img.naturalWidth / rect.width; const y = (event.clientY - rect.top) * img.naturalHeight / rect.height;
      if (x < 0 || y < 0 || x > img.naturalWidth || y > img.naturalHeight) return;
      setPoint(state.current, state.currentPoint, x, y); renderPointList(state.current); renderOverlay(); setStatus("Точка поставлена");
    }
    function initControls() {
      $("prevBtn").addEventListener("click", () => go(-1).catch(err => setStatus(err.message, "error")));
      $("nextBtn").addEventListener("click", () => go(1).catch(err => setStatus(err.message, "error")));
      $("jumpBtn").addEventListener("click", () => { state.pos = Math.max(0, Math.min(state.filtered.length - 1, Number($("jumpInput").value || 1) - 1)); loadCurrent().catch(err => setStatus(err.message, "error")); });
      $("filterSelect").addEventListener("change", () => { state.pos = 0; applyFilter(); loadCurrent().catch(err => setStatus(err.message, "error")); });
      $("searchInput").addEventListener("input", () => { state.pos = 0; applyFilter(); loadCurrent().catch(err => setStatus(err.message, "error")); });
      $("saveBtn").addEventListener("click", () => saveCurrent().catch(err => setStatus(err.message, "error")));
      $("saveNextBtn").addEventListener("click", async () => { try { await saveCurrent(); await go(1); } catch (err) { setStatus(err.message, "error"); } });
      $("clearPointBtn").addEventListener("click", () => { if (!state.current || !state.currentPoint) return; clearPoint(state.current, state.currentPoint); renderPointList(state.current); renderOverlay(); });
      $("clearAllBtn").addEventListener("click", () => { if (!state.current) return; for (const [key] of defsFor(state.current)) clearPoint(state.current, key); renderPointList(state.current); renderOverlay(); });
      $("dicomImage").addEventListener("click", imageClick); $("dicomImage").addEventListener("load", renderOverlay); window.addEventListener("resize", renderOverlay);
      document.addEventListener("keydown", (event) => { if (event.target.matches("input, textarea, select")) return; if (event.key === "ArrowLeft") go(-1).catch(err => setStatus(err.message, "error")); if (event.key === "ArrowRight") go(1).catch(err => setStatus(err.message, "error")); });
    }
    async function init() { const res = await fetch("/api/rows"); if (!res.ok) throw new Error(await res.text()); const data = await res.json(); state.rows = data.rows; initControls(); applyFilter(); await loadCurrent(); }
    init().catch(err => setStatus(err.message, "error"));
  </script>
</body>
</html>
'''


class LandmarkStore:
    def __init__(self, pilot_csv: Path, train_zip: Path, test_zip: Path) -> None:
        self.pilot_csv = pilot_csv
        self.train_zip = train_zip
        self.test_zip = test_zip
        self.lock = threading.Lock()
        self.backup_written = False
        self.rows, self.fieldnames = self._load_pilot()
        self._attach_indices()

    def _load_pilot(self) -> tuple[list[dict[str, str]], list[str]]:
        with self.pilot_csv.open("r", encoding="utf-8", newline="") as fp:
            reader = csv.DictReader(fp)
            rows = list(reader)
            return rows, list(reader.fieldnames or [])

    def _attach_indices(self) -> None:
        for index, row in enumerate(self.rows):
            row["index"] = str(index)

    def public_row(self, row: dict[str, str]) -> dict[str, Any]:
        data = dict(row)
        data["index"] = int(row["index"])
        return data

    def rows_payload(self) -> dict[str, Any]:
        with self.lock:
            rows = [self.public_row(row) for row in self.rows]
        return {"rows": rows, "total": len(rows)}

    def row_payload(self, index: int) -> dict[str, Any]:
        with self.lock:
            return {"row": self.public_row(self.rows[index])}

    def save_row(self, index: int, payload: dict[str, Any]) -> dict[str, Any]:
        status = str(payload.get("annotation_status", "new")).strip()
        notes = str(payload.get("annotation_notes", "")).strip()
        points = payload.get("points", {})
        if status not in STATUS_CHOICES:
            raise ValueError(f"Неизвестный статус: {status}")
        if not isinstance(points, dict):
            raise ValueError("points должен быть объектом")

        with self.lock:
            row = self.rows[index]
            row["annotation_status"] = status
            row["annotation_notes"] = notes
            for key in ALL_POINT_KEYS:
                item = points.get(key, None)
                x_field = f"{key}_x"
                y_field = f"{key}_y"
                if x_field not in self.fieldnames or y_field not in self.fieldnames:
                    continue
                if item is None:
                    row[x_field] = ""
                    row[y_field] = ""
                    continue
                try:
                    x = float(item["x"])
                    y = float(item["y"])
                except (KeyError, TypeError, ValueError):
                    raise ValueError(f"Некорректная точка: {key}") from None
                row[x_field] = f"{x:.1f}"
                row[y_field] = f"{y:.1f}"
            self._write_locked()
            return self.public_row(row)

    def _write_locked(self) -> None:
        if not self.backup_written:
            backup = self.pilot_csv.with_suffix(".webui_backup.csv")
            if not backup.exists():
                shutil.copy2(self.pilot_csv, backup)
            self.backup_written = True
        tmp = self.pilot_csv.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=self.fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in self.rows:
                writer.writerow({field: row.get(field, "") for field in self.fieldnames})
        tmp.replace(self.pilot_csv)

    def image_bytes(self, index: int) -> bytes:
        with self.lock:
            row = dict(self.rows[index])
        zip_path = self.train_zip if row.get("split") == "train" else self.test_zip
        with zipfile.ZipFile(zip_path) as zf:
            image, _meta = image_from_dicom(zf.read(row["member"]))
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    store: LandmarkStore

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.client_address[0], self.log_date_time_string(), fmt % args))

    def send_bytes(self, body: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_bytes(json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

    def send_error_text(self, status: HTTPStatus, message: str) -> None:
        self.send_bytes(message.encode("utf-8"), "text/plain; charset=utf-8", status)

    def do_GET(self) -> None:
        try:
            path = urllib.parse.urlparse(self.path).path
            if path == "/":
                self.send_bytes(INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
                return
            if path == "/api/rows":
                self.send_json(self.store.rows_payload())
                return
            if path.startswith("/api/row/"):
                index = int(path.rsplit("/", 1)[1])
                self.send_json(self.store.row_payload(index))
                return
            if path.startswith("/api/image/") and path.endswith(".png"):
                index_text = path.rsplit("/", 1)[1].removesuffix(".png")
                self.send_bytes(self.store.image_bytes(int(index_text)), "image/png")
                return
            self.send_error_text(HTTPStatus.NOT_FOUND, "Не найдено")
        except IndexError:
            self.send_error_text(HTTPStatus.NOT_FOUND, "Строка не найдена")
        except Exception as exc:
            self.send_error_text(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_POST(self) -> None:
        try:
            path = urllib.parse.urlparse(self.path).path
            if path.startswith("/api/row/"):
                index = int(path.rsplit("/", 1)[1])
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                row = self.store.save_row(index, payload)
                self.send_json({"ok": True, "row": row})
                return
            self.send_error_text(HTTPStatus.NOT_FOUND, "Не найдено")
        except IndexError:
            self.send_error_text(HTTPStatus.NOT_FOUND, "Строка не найдена")
        except ValueError as exc:
            self.send_error_text(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self.send_error_text(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--pilot-csv", type=Path, default=DEFAULT_PILOT_CSV)
    parser.add_argument("--train-zip", type=Path, default=DEFAULT_TRAIN_ZIP)
    parser.add_argument("--test-zip", type=Path, default=DEFAULT_TEST_ZIP)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    store = LandmarkStore(args.pilot_csv, args.train_zip, args.test_zip)
    Handler.store = store
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Web UI для landmarks: http://{args.host}:{args.port}", flush=True)
    print("Нажмите Ctrl+C для остановки.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановка.", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
