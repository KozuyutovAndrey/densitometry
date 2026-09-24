const $ = (id) => document.getElementById(id);

const state = {
  jobs: [], job: null, image: null, filtered: [], health: null,
  bitmap: null, zoom: 1, panX: 0, panY: 0, dragging: false, lastX: 0, lastY: 0,
  view3d: { yaw: -0.6, pitch: 0.15, scale: 1, dragging: false, x: 0, y: 0 },
};

const regionNames = { spine: "Позвоночник", left_hip: "Левое бедро", right_hip: "Правое бедро", hip_unknown_side: "Бедро" };
const violationNames = {
  spine_positioning: "Нарушение укладки позвоночника",
  spine_axis: "Отклонение оси позвоночника",
  spine_artifact: "Артефакт или посторонний предмет",
  hip_positioning_rotation: "Позиционирование или ротация бедра",
  hip_roi: "Некорректная область интереса бедра",
};

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function showNotice(message, error = false) {
  const notice = $("notice");
  notice.textContent = message;
  notice.className = error ? "notice error" : "notice";
  notice.hidden = !message;
}

async function api(path, options) {
  const response = await fetch(path, options);
  let body = {};
  try { body = await response.json(); } catch { /* non-JSON response */ }
  if (!response.ok) throw new Error(body.error || `Ошибка сервера: ${response.status}`);
  return body;
}

function jobLabel(job) {
  const marker = ({ queued: "в очереди", running: "обработка", failed: "ошибка" }[job.status] || "готово");
  return `${job.name} · ${marker}`;
}

async function loadJobs(preserve = true) {
  const current = preserve && state.job ? state.job.id : null;
  state.jobs = await api("/api/jobs");
  state.job = state.jobs.find((job) => job.id === current) || state.jobs[0] || null;
  renderJobPicker();
  renderAll();
  if (state.jobs.some((job) => ["queued", "running"].includes(job.status))) setTimeout(() => loadJobs(), 1800);
}

function renderJobPicker() {
  const select = $("job-select");
  select.replaceChildren();
  for (const job of state.jobs) {
    const option = node("option", "", jobLabel(job));
    option.value = job.id;
    option.selected = job.id === state.job?.id;
    select.append(option);
  }
}

function statusText(job) {
  if (!job) return "Нет загруженных наборов";
  if (job.status === "queued") return "Ожидает запуска";
  if (job.status === "running") return "Выполняется полный анализ…";
  if (job.status === "failed") return job.error || "Обработка завершилась с ошибкой";
  return "Пакетная обработка завершена";
}

function matches(image) {
  const query = $("search").value.trim().toLowerCase();
  const quality = $("quality").value;
  return (!query || [image.filename, image.image_uid, image.study_uid].some((value) => (value || "").toLowerCase().includes(query)))
    && (!$("region").value || image.anatomical_region === $("region").value)
    && (!quality || (quality === "failed" ? image.processing_status !== "Success" : image.quality_class === quality));
}

function qualityInfo(image) {
  if (image.processing_status !== "Success") return { label: "Ошибка обработки", className: "failed" };
  if (image.quality_class === "1") return { label: "Требует внимания", className: "bad" };
  return { label: "Без нарушений", className: "" };
}

function renderAll() {
  const images = state.job?.images || [];
  state.filtered = images.filter(matches);
  if (!state.image || !images.some((image) => image.id === state.image.id)) state.image = images[0] || null;
  const good = images.filter((image) => image.processing_status === "Success" && image.quality_class === "0").length;
  const bad = images.filter((image) => image.processing_status === "Success" && image.quality_class === "1").length;
  $("stat-total").textContent = images.length || "—";
  $("stat-good").textContent = images.length ? good : "—";
  $("stat-bad").textContent = images.length ? bad : "—";
  $("stat-failed").textContent = images.length ? images.length - good - bad : "—";
  $("batch-status").textContent = statusText(state.job);
  $("batch-status").className = state.job?.status === "failed" ? "error" : "";
  for (const format of ["csv", "xlsx"]) {
    const link = $(`export-${format}`);
    link.hidden = state.job?.status !== "completed";
    if (state.job) link.href = `/api/jobs/${encodeURIComponent(state.job.id)}/export.${format}`;
  }
  renderList();
  renderTable();
  renderImageDetail();
}

function chooseImage(image) {
  state.image = image;
  state.bitmap = null;
  state.zoom = 1; state.panX = 0; state.panY = 0;
  renderAll();
  loadPreview();
}

function renderList() {
  const list = $("image-list");
  list.replaceChildren();
  $("list-count").textContent = state.filtered.length ? state.filtered.length : "";
  if (!state.filtered.length) {
    list.append(node("div", "empty-list", state.job?.status === "completed" ? "По фильтрам ничего не найдено" : "Результаты появятся после обработки"));
    return;
  }
  for (const image of state.filtered) {
    const button = node("button", `image-card${image.id === state.image?.id ? " selected" : ""}`);
    button.type = "button";
    const thumb = node("img", "thumb");
    thumb.alt = "";
    thumb.loading = "lazy";
    thumb.src = `/api/jobs/${encodeURIComponent(state.job.id)}/images/${encodeURIComponent(image.id)}/preview.png`;
    const text = node("span", "card-text");
    text.append(node("strong", "", regionNames[image.anatomical_region] || image.anatomical_region || "Область не определена"));
    text.append(node("small", "", image.filename || image.image_uid));
    const q = qualityInfo(image);
    text.append(node("span", `card-status ${q.className}`, q.label));
    button.append(thumb, text);
    button.addEventListener("click", () => chooseImage(image));
    list.append(button);
  }
}

function renderTable() {
  const body = $("results-body");
  body.replaceChildren();
  if (!state.filtered.length) {
    const row = node("tr");
    const cell = node("td", "", state.job?.status === "completed" ? "Нет строк, соответствующих фильтрам" : "Таблица будет заполнена после обработки");
    cell.colSpan = 6;
    row.append(cell); body.append(row); return;
  }
  for (const image of state.filtered) {
    const row = node("tr", image.id === state.image?.id ? "selected" : "");
    row.tabIndex = 0;
    const q = qualityInfo(image);
    const qualityCell = node("td");
    qualityCell.append(node("span", `table-quality ${q.className}`, q.label));
    const values = [
      image.filename || "—", regionNames[image.anatomical_region] || image.anatomical_region || "—",
      qualityCell, violationLabels(image).join(", ") || "—", image.processing_status || "—", image.time_of_processing || "—",
    ];
    for (const value of values) row.append(value instanceof HTMLElement ? value : node("td", "", value));
    row.addEventListener("click", () => chooseImage(image));
    row.addEventListener("keydown", (event) => { if (["Enter", " "].includes(event.key)) chooseImage(image); });
    body.append(row);
  }
}

function violationLabels(image) {
  return (image?.violation_type || "").split(/[;,|]+/).map((v) => v.trim()).filter(Boolean).map((v) => violationNames[v] || v);
}

function renderImageDetail() {
  const image = state.image;
  $("image-empty").hidden = Boolean(image);
  $("image-title").textContent = image ? (regionNames[image.anatomical_region] || image.anatomical_region || "Область не определена") : "Выберите снимок";
  $("image-number").textContent = image ? `СНИМОК ${Number(image.id) + 1} ИЗ ${state.job.images.length}` : "ПРОСМОТР СНИМКА";
  const badge = $("quality-badge");
  if (image) {
    const q = qualityInfo(image); badge.textContent = q.label; badge.className = `badge ${q.className}`; badge.hidden = false;
  } else badge.hidden = true;
  $("meta-file").textContent = image?.filename || "—";
  $("meta-study").textContent = image?.study_uid || "—";
  $("meta-image").textContent = image?.image_uid || "—";
  $("image-size").textContent = image?.width && image?.height ? `${image.width} × ${image.height} px` : "—";
  renderFindings();
  update3dPanel();
  if (image && !state.bitmap) loadPreview(); else drawImage();
}

function renderFindings() {
  const container = $("findings");
  const measurements = $("measurements");
  container.replaceChildren(); measurements.replaceChildren();
  const image = state.image;
  if (!image) {
    container.append(node("div", "empty-list", "Результат ещё не выбран")); return;
  }
  const labels = violationLabels(image);
  if (image.processing_status !== "Success") {
    addFinding(container, "Ошибка обработки", "Снимок сохранён в отчёте со статусом Failure.", true);
  } else if (!labels.length) {
    addFinding(container, "Критерии соблюдены", "Алгоритм не обнаружил нарушений из поддерживаемого перечня.", false);
  } else {
    labels.forEach((label) => addFinding(container, label, findingExplanation(label), true));
  }
  const metricNames = {
    spine_axis_angle_deg: ["Наклон оси", "°"], hip_lesser_prominence_mm: ["Выступание малого вертела", " мм"],
    hip_top_margin_mm: ["Верхний отступ", " мм"], hip_bottom_margin_mm: ["Нижний отступ", " мм"],
    hip_lateral_margin_mm: ["Боковой отступ", " мм"],
  };
  let count = 0;
  for (const [key, value] of Object.entries(image.metrics || {})) {
    if (value === null || value === undefined) continue;
    const row = node("div", "metric");
    row.append(node("span", "", metricNames[key]?.[0] || key), node("strong", "", `${Number(value).toFixed(1)}${metricNames[key]?.[1] || ""}`));
    measurements.append(row); count++;
  }
  if (!count) measurements.append(node("div", "metric", "Числовые измерения недоступны"));
  $("source-note").textContent = `Результат локальной пакетной обработки. Landmarks: ${image.landmark_model || "нет данных"}.`;
}

function addFinding(container, title, description, bad) {
  const item = node("div", `finding${bad ? " bad" : ""}`);
  const heading = node("h3"); heading.append(node("span", "symbol", bad ? "!" : "✓"), document.createTextNode(title));
  item.append(heading, node("p", "", description)); container.append(item);
}

function findingExplanation(label) {
  if (label.includes("оси")) return "Оценка центральной линии вышла за заданный критерий.";
  if (label.includes("Артефакт")) return "На изображении обнаружены признаки постороннего объекта или выраженного наложения.";
  if (label.includes("область интереса")) return "Один или несколько необходимых отступов от области интереса недостаточны.";
  if (label.includes("бедра")) return "Геометрия ориентиров указывает на возможную ошибку позиционирования или ротации.";
  return "Нарушение определено существующим пайплайном контроля качества.";
}

async function loadPreview() {
  if (!state.image || !state.job) return;
  const source = new Image();
  source.onload = () => { if (state.image) { state.bitmap = source; drawImage(); } };
  source.onerror = () => { state.bitmap = null; showNotice("Не удалось загрузить изображение для просмотра", true); };
  source.src = `/api/jobs/${encodeURIComponent(state.job.id)}/images/${encodeURIComponent(state.image.id)}/preview.png`;
}

function canvasSize(canvas) {
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(1, Math.round(rect.width * ratio));
  const height = Math.max(1, Math.round(rect.height * ratio));
  if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
  return { width, height, ratio };
}

function drawImage() {
  const canvas = $("image-canvas");
  const { width, height } = canvasSize(canvas);
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, width, height);
  if (!state.bitmap || !state.image) return;
  const fit = Math.min(width / state.bitmap.width, height / state.bitmap.height) * .88;
  const scale = fit * state.zoom;
  const x = (width - state.bitmap.width * scale) / 2 + state.panX;
  const y = (height - state.bitmap.height * scale) / 2 + state.panY;
  ctx.filter = `brightness(${$("brightness").value}%) contrast(${$("contrast").value}%)`;
  ctx.imageSmoothingEnabled = true;
  ctx.drawImage(state.bitmap, x, y, state.bitmap.width * scale, state.bitmap.height * scale);
  ctx.filter = "none";
  if ($("landmarks").checked) {
    for (const point of state.image.landmarks || []) {
      const px = x + point.x * scale, py = y + point.y * scale;
      ctx.beginPath(); ctx.arc(px, py, 4 * (window.devicePixelRatio || 1), 0, Math.PI * 2);
      ctx.fillStyle = "#62d0b0"; ctx.fill(); ctx.lineWidth = 1.5 * (window.devicePixelRatio || 1); ctx.strokeStyle = "#102b2a"; ctx.stroke();
    }
  }
  $("zoom-label").textContent = `${Math.round(state.zoom * 100)}%`;
}

function reconstruction() { return state.job?.reconstructions?.[state.image?.id]; }

function update3dPanel() {
  const enabled = state.image?.anatomical_region === "spine";
  $("tab-3d").disabled = !enabled;
  const current = reconstruction();
  $("reconstruct").disabled = !state.health?.reconstruction || current?.status === "queued";
  if (!enabled) $("three-description").textContent = "3D-функция предназначена для снимков позвоночника.";
  else if (!state.health?.reconstruction) $("three-description").textContent = state.health?.reconstruction_reason || "3D-реконструкция пока недоступна в этой сборке.";
  else if (current?.status === "queued") $("three-description").textContent = "Выполняется реконструкция…";
  else if (current?.status === "failed") $("three-description").textContent = current.error;
  else $("three-description").textContent = "Модель оценивает фронтальную и сагиттальную центральные линии и объединяет их в пространственную ось.";
  $("three-empty").hidden = current?.status === "completed";
  draw3d();
}

function draw3d() {
  const canvas = $("spine-canvas");
  const { width, height } = canvasSize(canvas);
  const ctx = canvas.getContext("2d"); ctx.clearRect(0, 0, width, height);
  const points = reconstruction()?.points;
  if (!points?.length) return;
  const xs = points.map((p) => p[0]), ys = points.map((p) => p[1]), zs = points.map((p) => p[2]);
  const center = [(Math.min(...xs) + Math.max(...xs))/2, (Math.min(...ys) + Math.max(...ys))/2, (Math.min(...zs) + Math.max(...zs))/2];
  const span = Math.max(Math.max(...xs)-Math.min(...xs), Math.max(...ys)-Math.min(...ys), Math.max(...zs)-Math.min(...zs), 1);
  const c1 = Math.cos(state.view3d.yaw), s1 = Math.sin(state.view3d.yaw), c2 = Math.cos(state.view3d.pitch), s2 = Math.sin(state.view3d.pitch);
  const projected = points.map((p) => {
    const x0=(p[0]-center[0])/span, y0=(p[1]-center[1])/span, z0=(p[2]-center[2])/span;
    const x1=x0*c1-z0*s1, z1=x0*s1+z0*c1, y1=y0*c2-z1*s2, depth=y0*s2+z1*c2;
    const perspective=1/(1.8+depth*.35), size=Math.min(width,height)*1.35*state.view3d.scale;
    return [width/2+x1*size*perspective,height/2-y1*size*perspective,depth];
  });
  const gradient=ctx.createLinearGradient(0,0,width,height); gradient.addColorStop(0,"#8dd6c0"); gradient.addColorStop(1,"#287e75");
  ctx.lineWidth=4*(window.devicePixelRatio||1); ctx.strokeStyle=gradient; ctx.beginPath(); projected.forEach((p,i)=>i?ctx.lineTo(p[0],p[1]):ctx.moveTo(p[0],p[1])); ctx.stroke();
  projected.forEach((p) => { ctx.beginPath();ctx.arc(p[0],p[1],4*(window.devicePixelRatio||1),0,Math.PI*2);ctx.fillStyle="#a7e0ce";ctx.fill();ctx.strokeStyle="#153f3d";ctx.lineWidth=1.5;ctx.stroke(); });
}

async function request3d() {
  if (!state.job || !state.image) return;
  try {
    await api(`/api/jobs/${encodeURIComponent(state.job.id)}/images/${encodeURIComponent(state.image.id)}/reconstruct`, { method: "POST" });
    await refreshCurrentUntil3d();
  } catch (error) { showNotice(error.message, true); }
}

async function refreshCurrentUntil3d() {
  const updated = await api(`/api/jobs/${encodeURIComponent(state.job.id)}`);
  state.jobs = state.jobs.map((job) => job.id === updated.id ? updated : job); state.job = updated;
  state.image = updated.images.find((image) => image.id === state.image.id); renderAll();
  if (reconstruction()?.status === "queued") setTimeout(refreshCurrentUntil3d, 1500);
}

function setupViewerEvents() {
  const canvas = $("image-canvas");
  canvas.addEventListener("pointerdown", (event) => { state.dragging=true;state.lastX=event.clientX;state.lastY=event.clientY;canvas.setPointerCapture(event.pointerId); });
  canvas.addEventListener("pointermove", (event) => { if(!state.dragging)return; const r=window.devicePixelRatio||1;state.panX+=(event.clientX-state.lastX)*r;state.panY+=(event.clientY-state.lastY)*r;state.lastX=event.clientX;state.lastY=event.clientY;drawImage(); });
  canvas.addEventListener("pointerup", () => state.dragging=false);
  canvas.addEventListener("wheel", (event) => { event.preventDefault(); state.zoom=Math.max(.5,Math.min(4,state.zoom*(event.deltaY<0?1.1:.9)));drawImage(); }, {passive:false});
  const c3=$("spine-canvas");
  c3.addEventListener("pointerdown",e=>{state.view3d.dragging=true;state.view3d.x=e.clientX;state.view3d.y=e.clientY;c3.setPointerCapture(e.pointerId)});
  c3.addEventListener("pointermove",e=>{if(!state.view3d.dragging)return;state.view3d.yaw+=(e.clientX-state.view3d.x)*.01;state.view3d.pitch+=(e.clientY-state.view3d.y)*.01;state.view3d.x=e.clientX;state.view3d.y=e.clientY;draw3d()});
  c3.addEventListener("pointerup",()=>state.view3d.dragging=false);
  c3.addEventListener("wheel",e=>{e.preventDefault();state.view3d.scale=Math.max(.5,Math.min(3,state.view3d.scale*(e.deltaY<0?1.1:.9)));draw3d()},{passive:false});
  c3.addEventListener("keydown",e=>{if(e.key==="ArrowLeft")state.view3d.yaw-=.1;if(e.key==="ArrowRight")state.view3d.yaw+=.1;if(e.key==="ArrowUp")state.view3d.pitch-=.1;if(e.key==="ArrowDown")state.view3d.pitch+=.1;if(e.key==="+")state.view3d.scale*=1.1;if(e.key==="-")state.view3d.scale*=.9;draw3d()});
}

function setupUpload() {
  const dialog=$("upload-dialog"), file=$("file"), zone=$("drop-zone");
  $("upload-open").addEventListener("click",()=>dialog.showModal()); $("upload-close").addEventListener("click",()=>dialog.close());
  file.addEventListener("change",()=>$("file-name").textContent=file.files[0]?.name||"");
  ["dragenter","dragover"].forEach(name=>zone.addEventListener(name,e=>{e.preventDefault();zone.classList.add("drag")}));
  ["dragleave","drop"].forEach(name=>zone.addEventListener(name,e=>{e.preventDefault();zone.classList.remove("drag")}));
  zone.addEventListener("drop",e=>{if(e.dataTransfer.files[0]){file.files=e.dataTransfer.files;$("file-name").textContent=file.files[0].name}});
  $("upload-form").addEventListener("submit",event=>{
    event.preventDefault(); const selected=file.files[0]; if(!selected)return;
    $("upload-error").textContent=""; $("upload-progress").hidden=false; $("upload-submit").disabled=true;
    const xhr=new XMLHttpRequest(); xhr.open("POST","/api/jobs"); xhr.setRequestHeader("Content-Type","application/zip");xhr.setRequestHeader("X-Archive-Name",encodeURIComponent(selected.name));
    xhr.upload.onprogress=e=>{if(e.lengthComputable)$("upload-progress").value=e.loaded/e.total*100};
    xhr.onload=async()=>{ $("upload-submit").disabled=false; try{const result=JSON.parse(xhr.responseText);if(xhr.status>=400)throw new Error(result.error||"Ошибка загрузки");dialog.close();file.value="";$("file-name").textContent="";state.job=result;await loadJobs(false);showNotice("Архив принят. Пакетная обработка поставлена в очередь.")}catch(error){$("upload-error").textContent=error.message} };
    xhr.onerror=()=>{$("upload-submit").disabled=false;$("upload-error").textContent="Не удалось подключиться к локальному серверу"}; xhr.send(selected);
  });
}

async function init() {
  setupViewerEvents(); setupUpload();
  $("job-select").addEventListener("change",event=>{state.job=state.jobs.find(j=>j.id===event.target.value);state.image=null;state.bitmap=null;renderAll()});
  ["search","region","quality"].forEach(id=>$(id).addEventListener(id==="search"?"input":"change",renderAll));
  $("refresh").addEventListener("click",()=>loadJobs()); $("landmarks").addEventListener("change",drawImage);
  ["brightness","contrast"].forEach(id=>$(id).addEventListener("input",drawImage));
  $("zoom-in").addEventListener("click",()=>{state.zoom=Math.min(4,state.zoom*1.15);drawImage()}); $("zoom-out").addEventListener("click",()=>{state.zoom=Math.max(.5,state.zoom/1.15);drawImage()});
  $("reset").addEventListener("click",()=>{state.zoom=1;state.panX=0;state.panY=0;$("brightness").value=100;$("contrast").value=100;drawImage()});
  $("reset-3d").addEventListener("click",()=>{state.view3d={yaw:-.6,pitch:.15,scale:1,dragging:false,x:0,y:0};draw3d()}); $("reconstruct").addEventListener("click",request3d);
  $("tab-2d").addEventListener("click",()=>switchTab(false)); $("tab-3d").addEventListener("click",()=>switchTab(true));
  window.addEventListener("resize",()=>{drawImage();draw3d()});
  try { state.health=await api("/api/health"); $("connection").textContent="Локальный сервер подключён";$("connection-dot").classList.add("online");await loadJobs(false); }
  catch(error){$("connection").textContent="Сервер недоступен";showNotice(error.message,true)}
}

function switchTab(three) {
  if(three && $("tab-3d").disabled)return;
  $("panel-2d").hidden=three;$("panel-3d").hidden=!three;$("tab-2d").classList.toggle("active",!three);$("tab-3d").classList.toggle("active",three);$("tab-2d").setAttribute("aria-selected",String(!three));$("tab-3d").setAttribute("aria-selected",String(three));if(three)draw3d();else drawImage();
}

init();
