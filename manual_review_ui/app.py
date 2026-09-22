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


DEFAULT_REVIEW_CSV = ROOT / "artifacts" / "manual_image_review.csv"
DEFAULT_INDEX_CSV = ROOT / "artifacts" / "dicom_index.csv"
DEFAULT_TRAIN_ZIP = ROOT / "data" / "НД_для_обучения.zip"
DEFAULT_TEST_ZIP = ROOT / "data" / "Для теста.zip"
DEFAULT_CONTACT_SHEETS = ROOT / "artifacts" / "contact_sheets"

REGION_CHOICES = [
    "spine",
    "hip_unknown_side",
    "right_hip",
    "left_hip",
    "duplicate",
    "derived",
    "unknown",
]


INDEX_HTML = r"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Ручная разметка денситометрии</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f7f8;
      --panel: #ffffff;
      --line: #d7dee2;
      --text: #1b252b;
      --muted: #62707a;
      --accent: #0f766e;
      --accent-weak: #d9f3ef;
      --bad: #a33a2e;
      --warn: #a16207;
      --shadow: 0 1px 3px rgba(15, 23, 42, 0.12);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.35 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    header {
      height: 56px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 18px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      position: sticky;
      top: 0;
      z-index: 10;
    }
    h1 {
      font-size: 17px;
      margin: 0;
      font-weight: 650;
    }
    main {
      display: grid;
      grid-template-columns: minmax(340px, 1fr) 430px;
      gap: 14px;
      padding: 14px;
      max-width: 1640px;
      margin: 0 auto;
    }
    button, select, input, textarea {
      font: inherit;
    }
    button {
      border: 1px solid var(--line);
      background: #fff;
      color: var(--text);
      border-radius: 7px;
      min-height: 34px;
      padding: 6px 10px;
      cursor: pointer;
    }
    button:hover { border-color: #9fb0b8; }
    button.primary {
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }
    button.ghost {
      background: transparent;
    }
    button:disabled {
      opacity: 0.5;
      cursor: default;
    }
    select, input, textarea {
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fff;
      color: var(--text);
      padding: 7px 9px;
      width: 100%;
    }
    textarea {
      min-height: 96px;
      resize: vertical;
    }
    .toolbar {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .stat {
      color: var(--muted);
      white-space: nowrap;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      min-width: 0;
    }
    .viewer {
      padding: 14px;
    }
    .image-wrap {
      min-height: 420px;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #111;
      border-radius: 8px;
      overflow: hidden;
    }
    .image-wrap img {
      max-width: 100%;
      max-height: calc(100vh - 190px);
      object-fit: contain;
      image-rendering: pixelated;
    }
    .meta-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
      margin-top: 12px;
    }
    .meta {
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 8px;
      min-width: 0;
    }
    .meta b {
      display: block;
      font-size: 11px;
      color: var(--muted);
      font-weight: 600;
      margin-bottom: 3px;
    }
    .meta span {
      display: block;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .side {
      padding: 14px;
      align-self: start;
      position: sticky;
      top: 70px;
      max-height: calc(100vh - 84px);
      overflow: auto;
    }
    .field {
      margin-bottom: 12px;
    }
    .field label {
      display: block;
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
      margin-bottom: 5px;
    }
    .checkline {
      display: flex;
      align-items: center;
      gap: 8px;
      margin: 10px 0 14px;
    }
    .checkline input {
      width: auto;
      transform: scale(1.15);
    }
    .quick {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 7px;
      margin-bottom: 12px;
    }
    .quick button.active {
      background: var(--accent-weak);
      border-color: var(--accent);
    }
    .actions {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      margin: 12px 0;
    }
    .study-table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 12px;
      font-size: 12px;
    }
    .study-table th, .study-table td {
      border-bottom: 1px solid var(--line);
      padding: 6px 5px;
      text-align: left;
      vertical-align: top;
    }
    .study-table tr.current {
      background: var(--accent-weak);
    }
    .study-table button {
      min-height: 26px;
      padding: 3px 7px;
      border-radius: 5px;
    }
    .tag {
      display: inline-block;
      padding: 2px 6px;
      border-radius: 999px;
      background: #edf2f4;
      color: var(--muted);
      margin: 0 4px 4px 0;
      font-size: 12px;
    }
    .tag.warn { color: var(--warn); background: #fef3c7; }
    .tag.bad { color: var(--bad); background: #fee2e2; }
    .sheet {
      margin-top: 14px;
      padding-top: 12px;
      border-top: 1px solid var(--line);
    }
    .sheet img {
      display: block;
      width: 100%;
      max-height: 460px;
      object-fit: contain;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fff;
    }
    .status {
      min-height: 20px;
      color: var(--muted);
    }
    .status.error { color: var(--bad); }
    .status.ok { color: var(--accent); }
    .mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      overflow-wrap: anywhere;
    }
    @media (max-width: 980px) {
      main { grid-template-columns: 1fr; }
      .side { position: static; max-height: none; }
      .meta-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      header { height: auto; min-height: 56px; align-items: flex-start; padding: 10px 14px; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Ручная разметка снимков</h1>
    <div class="toolbar">
      <button id="prevBtn">←</button>
      <button id="nextBtn">→</button>
      <input id="jumpInput" type="number" min="1" value="1" style="width:82px">
      <button id="jumpBtn">Перейти</button>
      <select id="filterSelect" style="width:190px">
        <option value="all">все строки</option>
        <option value="needs_review">требуют проверки</option>
        <option value="hip_unknown_side">бедро без стороны</option>
        <option value="unknown">неизвестные</option>
        <option value="canonical">основные снимки</option>
        <option value="noncanonical">не основные</option>
        <option value="train">обучение</option>
        <option value="test">тест</option>
      </select>
      <input id="searchInput" type="search" placeholder="исследование / файл / заметки" style="width:210px">
      <span id="counter" class="stat"></span>
    </div>
  </header>

  <main>
    <section class="panel viewer">
      <div class="image-wrap">
        <img id="dicomImage" alt="Снимок">
      </div>
      <div class="meta-grid">
        <div class="meta"><b>набор</b><span id="mSplit"></span></div>
        <div class="meta"><b>файл</b><span id="mFile"></span></div>
        <div class="meta"><b>размер</b><span id="mSize"></span></div>
        <div class="meta"><b>подсказка</b><span id="mHint"></span></div>
      </div>
      <div class="meta" style="margin-top:8px">
        <b>путь внутри архива</b>
        <span id="mMember" class="mono"></span>
      </div>
      <div class="sheet" id="sheetBox">
        <div class="field"><label>лист исследования</label></div>
        <img id="sheetImage" alt="Лист исследования">
      </div>
    </section>

    <aside class="panel side">
      <div class="field">
        <label>исследование</label>
        <div id="studyId" class="mono"></div>
      </div>

      <div id="noteTags"></div>

      <div class="field">
        <label>область / тип снимка</label>
        <select id="regionSelect"></select>
      </div>

      <div class="quick" id="quickButtons"></div>

      <label class="checkline">
        <input id="canonicalCheck" type="checkbox">
        <span>основной снимок региона</span>
      </label>

      <div class="field">
        <label>заметки</label>
        <textarea id="notesInput"></textarea>
      </div>

      <div class="actions">
        <button id="saveBtn" class="primary">Сохранить</button>
        <button id="saveNextBtn" class="primary">Сохранить и дальше</button>
        <button id="copyHintBtn">Взять подсказку</button>
        <button id="clearNotesBtn">Очистить заметки</button>
      </div>

      <div id="status" class="status"></div>

      <table class="study-table">
        <thead>
          <tr>
            <th>#</th>
            <th>файл</th>
            <th>размер</th>
            <th>область</th>
            <th>осн.</th>
          </tr>
        </thead>
        <tbody id="studyRows"></tbody>
      </table>
    </aside>
  </main>

  <script>
    const regions = ["spine", "hip_unknown_side", "right_hip", "left_hip", "duplicate", "derived", "unknown"];
    const regionLabels = {
      spine: "позвоночник",
      hip_unknown_side: "бедро, сторону проверить",
      right_hip: "правое бедро",
      left_hip: "левое бедро",
      duplicate: "дубль",
      derived: "derived/обработка",
      unknown: "неизвестно",
    };
    const splitLabels = {train: "обучение", test: "тест"};
    const state = { rows: [], filtered: [], pos: 0, current: null, dirty: false };

    function $(id) { return document.getElementById(id); }

    function setStatus(text, kind="") {
      const el = $("status");
      el.textContent = text || "";
      el.className = "status " + kind;
    }

    function rowSearchText(row) {
      return [row.study_folder, row.member, row.filename, row.manual_region, row.manual_notes, row.region_hint].join(" ").toLowerCase();
    }

    function applyFilter() {
      const filter = $("filterSelect").value;
      const query = $("searchInput").value.trim().toLowerCase();
      state.filtered = state.rows.filter(row => {
        let ok = true;
        if (filter === "needs_review") ok = row.manual_notes || row.manual_region === "hip_unknown_side" || row.manual_region === "unknown";
        if (filter === "hip_unknown_side") ok = row.manual_region === "hip_unknown_side";
        if (filter === "unknown") ok = row.manual_region === "unknown";
        if (filter === "canonical") ok = row.manual_is_canonical === "1";
        if (filter === "noncanonical") ok = row.manual_is_canonical !== "1";
        if (filter === "train") ok = row.split === "train";
        if (filter === "test") ok = row.split === "test";
        if (ok && query) ok = rowSearchText(row).includes(query);
        return ok;
      });
      state.pos = Math.min(state.pos, Math.max(0, state.filtered.length - 1));
      renderCounter();
    }

    function renderCounter() {
      $("counter").textContent = state.filtered.length ? `${state.pos + 1} / ${state.filtered.length} (${state.rows.length} rows)` : `0 / 0 (${state.rows.length} rows)`;
      $("jumpInput").value = state.filtered.length ? state.pos + 1 : 0;
      $("prevBtn").disabled = state.pos <= 0;
      $("nextBtn").disabled = state.pos >= state.filtered.length - 1;
    }

    function tagsFromNotes(notes) {
      const box = $("noteTags");
      box.innerHTML = "";
      if (!notes) return;
      for (const raw of notes.split(";")) {
        const text = raw.trim();
        if (!text) continue;
        const span = document.createElement("span");
        span.textContent = text;
        span.className = "tag";
        if (text.includes("review")) span.classList.add("warn");
        if (text.includes("duplicate")) span.classList.add("bad");
        box.appendChild(span);
      }
    }

    function renderStudyTable(row, studyRows) {
      const body = $("studyRows");
      body.innerHTML = "";
      for (const item of studyRows) {
        const tr = document.createElement("tr");
        if (item.index === row.index) tr.className = "current";
        tr.innerHTML = `
          <td><button data-index="${item.index}">${item.index + 1}</button></td>
          <td>${item.filename}</td>
          <td>${item.columns}x${item.rows}</td>
          <td title="${item.manual_region}">${regionLabels[item.manual_region] || item.manual_region}</td>
          <td>${item.manual_is_canonical === "1" ? "да" : "нет"}</td>
        `;
        tr.querySelector("button").addEventListener("click", () => goToAbsolute(item.index));
        body.appendChild(tr);
      }
    }

    function updateForm(row) {
      $("mSplit").textContent = splitLabels[row.split] || row.split;
      $("mFile").textContent = row.filename;
      $("mSize").textContent = `${row.columns} x ${row.rows}`;
      $("mHint").textContent = `${regionLabels[row.region_hint] || row.region_hint} / ранг ${row.candidate_rank_in_region || ""}`;
      $("mMember").textContent = row.member;
      $("studyId").textContent = row.study_folder;
      $("regionSelect").value = row.manual_region || "unknown";
      $("canonicalCheck").checked = row.manual_is_canonical === "1";
      $("notesInput").value = row.manual_notes || "";
      tagsFromNotes(row.manual_notes || "");
      $("dicomImage").src = `/api/image/${row.index}.png?ts=${Date.now()}`;
      if (row.has_contact_sheet) {
        $("sheetBox").style.display = "";
        $("sheetImage").src = `/api/sheet/${encodeURIComponent(row.study_folder)}.jpg?ts=${Date.now()}`;
      } else {
        $("sheetBox").style.display = "none";
        $("sheetImage").removeAttribute("src");
      }
    }

    async function loadCurrent() {
      if (!state.filtered.length) {
        setStatus("Нет строк для выбранного фильтра", "error");
        return;
      }
      const row = state.filtered[state.pos];
      const res = await fetch(`/api/row/${row.index}`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      state.current = data.row;
      const known = state.rows.find(r => r.index === data.row.index);
      if (known) Object.assign(known, data.row);
      updateForm(data.row);
      renderStudyTable(data.row, data.study_rows);
      renderCounter();
      setStatus("");
      state.dirty = false;
    }

    async function saveCurrent() {
      if (!state.current) return;
      const payload = {
        manual_region: $("regionSelect").value,
        manual_is_canonical: $("canonicalCheck").checked ? "1" : "0",
        manual_notes: $("notesInput").value.trim(),
      };
      const res = await fetch(`/api/row/${state.current.index}`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const known = state.rows.find(r => r.index === data.row.index);
      if (known) Object.assign(known, data.row);
      Object.assign(state.current, data.row);
      applyFilter();
      tagsFromNotes(data.row.manual_notes || "");
      setStatus("Сохранено", "ok");
      state.dirty = false;
    }

    async function go(delta) {
      if (!state.filtered.length) return;
      state.pos = Math.max(0, Math.min(state.filtered.length - 1, state.pos + delta));
      await loadCurrent();
    }

    async function goToAbsolute(index) {
      applyFilter();
      const pos = state.filtered.findIndex(r => r.index === index);
      if (pos >= 0) {
        state.pos = pos;
      } else {
        $("filterSelect").value = "all";
        $("searchInput").value = "";
        applyFilter();
        state.pos = state.filtered.findIndex(r => r.index === index);
      }
      await loadCurrent();
    }

    function initControls(summary) {
      const select = $("regionSelect");
      select.innerHTML = "";
      for (const region of regions) {
        const option = document.createElement("option");
        option.value = region;
        option.textContent = regionLabels[region] || region;
        option.title = region;
        select.appendChild(option);
      }
      const quick = $("quickButtons");
      quick.innerHTML = "";
      for (const region of regions) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = regionLabels[region] || region;
        button.dataset.region = region;
        button.title = region;
        button.addEventListener("click", () => {
          $("regionSelect").value = region;
          for (const b of quick.querySelectorAll("button")) b.classList.toggle("active", b.dataset.region === region);
          state.dirty = true;
        });
        quick.appendChild(button);
      }

      $("prevBtn").addEventListener("click", () => go(-1).catch(err => setStatus(err.message, "error")));
      $("nextBtn").addEventListener("click", () => go(1).catch(err => setStatus(err.message, "error")));
      $("jumpBtn").addEventListener("click", () => {
        const value = Number($("jumpInput").value || 1);
        state.pos = Math.max(0, Math.min(state.filtered.length - 1, value - 1));
        loadCurrent().catch(err => setStatus(err.message, "error"));
      });
      $("filterSelect").addEventListener("change", () => { state.pos = 0; applyFilter(); loadCurrent().catch(err => setStatus(err.message, "error")); });
      $("searchInput").addEventListener("input", () => { state.pos = 0; applyFilter(); loadCurrent().catch(err => setStatus(err.message, "error")); });
      $("saveBtn").addEventListener("click", () => saveCurrent().catch(err => setStatus(err.message, "error")));
      $("saveNextBtn").addEventListener("click", async () => {
        try {
          await saveCurrent();
          await go(1);
        } catch (err) {
          setStatus(err.message, "error");
        }
      });
      $("copyHintBtn").addEventListener("click", () => {
        if (!state.current) return;
        $("regionSelect").value = state.current.region_hint || "unknown";
        $("canonicalCheck").checked = state.current.candidate_is_canonical === "1";
        state.dirty = true;
      });
      $("clearNotesBtn").addEventListener("click", () => {
        $("notesInput").value = "";
        state.dirty = true;
      });
      for (const id of ["regionSelect", "canonicalCheck", "notesInput"]) {
        $(id).addEventListener("change", () => { state.dirty = true; });
        $(id).addEventListener("input", () => { state.dirty = true; });
      }
      document.addEventListener("keydown", (event) => {
        if (event.target.matches("input, textarea, select")) return;
        if (event.key === "ArrowLeft") go(-1).catch(err => setStatus(err.message, "error"));
        if (event.key === "ArrowRight") go(1).catch(err => setStatus(err.message, "error"));
      });
    }

    async function init() {
      const res = await fetch("/api/rows");
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      state.rows = data.rows;
      initControls(data.summary);
      applyFilter();
      await loadCurrent();
    }

    init().catch(err => setStatus(err.message, "error"));
  </script>
</body>
</html>
"""


class ReviewStore:
    def __init__(
        self,
        review_csv: Path,
        index_csv: Path,
        train_zip: Path,
        test_zip: Path,
        contact_sheets_dir: Path,
    ) -> None:
        self.review_csv = review_csv
        self.index_csv = index_csv
        self.train_zip = train_zip
        self.test_zip = test_zip
        self.contact_sheets_dir = contact_sheets_dir
        self.lock = threading.Lock()
        self.backup_written = False
        self.rows, self.fieldnames = self._load_review()
        self.index_rows = self._load_csv(self.index_csv)
        self.index_by_member = {row["member"]: row for row in self.index_rows}
        self.sheet_by_study = self._build_sheet_map()
        self._attach_indices()

    def _load_csv(self, path: Path) -> list[dict[str, str]]:
        with path.open("r", encoding="utf-8", newline="") as fp:
            return list(csv.DictReader(fp))

    def _load_review(self) -> tuple[list[dict[str, str]], list[str]]:
        with self.review_csv.open("r", encoding="utf-8", newline="") as fp:
            reader = csv.DictReader(fp)
            rows = list(reader)
            return rows, list(reader.fieldnames or [])

    def _attach_indices(self) -> None:
        for index, row in enumerate(self.rows):
            row["index"] = str(index)

    def _build_sheet_map(self) -> dict[str, Path]:
        sheets: dict[str, Path] = {}
        if not self.contact_sheets_dir.exists():
            return sheets
        for path in self.contact_sheets_dir.glob("*.jpg"):
            stem = path.stem
            if "_" in stem:
                sheets[stem.split("_", 1)[1]] = path
        return sheets

    def public_row(self, row: dict[str, str]) -> dict[str, Any]:
        data = dict(row)
        data["index"] = int(row["index"])
        data["has_contact_sheet"] = row["study_folder"] in self.sheet_by_study
        return data

    def rows_payload(self) -> dict[str, Any]:
        with self.lock:
            rows = [self.public_row(row) for row in self.rows]
        summary = {
            "total": len(rows),
            "regions": {},
        }
        for row in rows:
            region = row.get("manual_region", "")
            summary["regions"][region] = summary["regions"].get(region, 0) + 1
        return {"rows": rows, "summary": summary}

    def row_payload(self, index: int) -> dict[str, Any]:
        with self.lock:
            row = self.rows[index]
            study = row["study_folder"]
            study_rows = [self.public_row(r) for r in self.rows if r["study_folder"] == study]
            return {"row": self.public_row(row), "study_rows": study_rows}

    def save_row(self, index: int, payload: dict[str, Any]) -> dict[str, Any]:
        region = str(payload.get("manual_region", "")).strip()
        canonical = str(payload.get("manual_is_canonical", "")).strip()
        notes = str(payload.get("manual_notes", "")).strip()

        if region not in REGION_CHOICES:
            raise ValueError(f"Неизвестное значение manual_region: {region}")
        if canonical not in {"0", "1"}:
            raise ValueError("manual_is_canonical должен быть 0 или 1")

        with self.lock:
            row = self.rows[index]
            row["manual_region"] = region
            row["manual_is_canonical"] = canonical
            row["manual_notes"] = notes
            self._write_review_locked()
            return self.public_row(row)

    def _write_review_locked(self) -> None:
        if not self.backup_written:
            backup = self.review_csv.with_suffix(".webui_backup.csv")
            if not backup.exists():
                shutil.copy2(self.review_csv, backup)
            self.backup_written = True

        tmp = self.review_csv.with_suffix(".tmp")
        rows = []
        for row in self.rows:
            clean = {field: row.get(field, "") for field in self.fieldnames}
            rows.append(clean)
        with tmp.open("w", encoding="utf-8", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=self.fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        tmp.replace(self.review_csv)

    def image_bytes(self, index: int) -> bytes:
        with self.lock:
            row = dict(self.rows[index])
        idx = self.index_by_member.get(row["member"], {})
        archive = idx.get("archive", "")
        zip_path = self.train_zip if archive == self.train_zip.name else self.test_zip
        with zipfile.ZipFile(zip_path) as zf:
            image, _meta = image_from_dicom(zf.read(row["member"]))
        scale = min(3.0, max(1.0, 760 / max(1, image.width)))
        if scale > 1.01:
            image = image.resize((round(image.width * scale), round(image.height * scale)))
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()

    def sheet_bytes(self, study: str) -> bytes | None:
        path = self.sheet_by_study.get(study)
        if path is None or not path.exists():
            return None
        return path.read_bytes()


class Handler(BaseHTTPRequestHandler):
    store: ReviewStore

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

    def parse_path(self) -> tuple[str, dict[str, list[str]]]:
        parsed = urllib.parse.urlparse(self.path)
        return parsed.path, urllib.parse.parse_qs(parsed.query)

    def do_GET(self) -> None:
        try:
            path, _query = self.parse_path()
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
            if path.startswith("/api/sheet/") and path.endswith(".jpg"):
                study = urllib.parse.unquote(path.rsplit("/", 1)[1].removesuffix(".jpg"))
                body = self.store.sheet_bytes(study)
                if body is None:
                    self.send_error_text(HTTPStatus.NOT_FOUND, "Лист исследования не найден")
                    return
                self.send_bytes(body, "image/jpeg")
                return
            self.send_error_text(HTTPStatus.NOT_FOUND, "Не найдено")
        except IndexError:
            self.send_error_text(HTTPStatus.NOT_FOUND, "Строка не найдена")
        except Exception as exc:
            self.send_error_text(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_POST(self) -> None:
        try:
            path, _query = self.parse_path()
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
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--review-csv", type=Path, default=DEFAULT_REVIEW_CSV)
    parser.add_argument("--index-csv", type=Path, default=DEFAULT_INDEX_CSV)
    parser.add_argument("--train-zip", type=Path, default=DEFAULT_TRAIN_ZIP)
    parser.add_argument("--test-zip", type=Path, default=DEFAULT_TEST_ZIP)
    parser.add_argument("--contact-sheets-dir", type=Path, default=DEFAULT_CONTACT_SHEETS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    store = ReviewStore(
        review_csv=args.review_csv,
        index_csv=args.index_csv,
        train_zip=args.train_zip,
        test_zip=args.test_zip,
        contact_sheets_dir=args.contact_sheets_dir,
    )
    Handler.store = store
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"
    print(f"Web UI для ручной разметки: {url}", flush=True)
    print("Нажмите Ctrl+C для остановки.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановка.", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
