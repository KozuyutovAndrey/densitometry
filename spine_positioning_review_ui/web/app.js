let items = [];
let filtered = [];
let currentIndex = 0;
let currentFilter = 'all';
let selectedLabel = null;
let selectedUseForTraining = '1';

const els = {
  stats: document.getElementById('stats'),
  list: document.getElementById('list'),
  search: document.getElementById('search'),
  counter: document.getElementById('counter'),
  title: document.getElementById('title'),
  image: document.getElementById('image'),
  meta: document.getElementById('meta'),
  notes: document.getElementById('notes'),
  saveBtn: document.getElementById('saveBtn'),
  saveNextBtn: document.getElementById('saveNextBtn'),
  prevBtn: document.getElementById('prevBtn'),
  nextBtn: document.getElementById('nextBtn'),
};

function labelText(value) {
  if (value === '1') return 'Видны';
  if (value === '0') return 'Не видны';
  return 'Сомнительно';
}

function labelClass(value) {
  if (value === '1') return 'good';
  if (value === '0') return 'bad';
  return 'unknown';
}

function positioningText(value) {
  if (value === '1') return 'Нарушение укладки';
  if (value === '0') return 'Без нарушения укладки';
  return 'Не указано';
}

function trainingText(value) {
  return value === '0' ? 'не использовать' : 'в обучение';
}

function renderStats(summary) {
  const cards = [
    ['Всего', summary.total],
    ['Проверено', summary.reviewed],
    ['Осталось', summary.unreviewed],
    ['Изменено', summary.changed],
    ['Исходно видны', summary.visible_original],
    ['Исходно не видны', summary.missing_original],
    ['Оригиналы', summary.real_total],
    ['Синтетика', summary.synthetic_total],
    ['В обучение', summary.training_included],
    ['Исключено', summary.training_excluded],
  ];
  els.stats.innerHTML = cards.map(([label, value]) => `<div class="stat"><b>${value}</b><span>${label}</span></div>`).join('');
}

function applyFilters() {
  const q = els.search.value.trim().toLowerCase();
  filtered = items.filter((item) => {
    if (currentFilter === 'unreviewed' && item.reviewed) return false;
    if (currentFilter === 'changed' && !item.changed) return false;
    if (currentFilter === 'real' && item.synthetic !== '0') return false;
    if (currentFilter === 'synthetic' && item.synthetic !== '1') return false;
    if (currentFilter === 'visible' && item.review_iliac_visible !== '1') return false;
    if (currentFilter === 'missing' && item.review_iliac_visible !== '0') return false;
    if (currentFilter === 'training' && item.review_use_for_training !== '1') return false;
    if (currentFilter === 'excluded' && item.review_use_for_training !== '0') return false;
    if (!q) return true;
    return [item.image_number, item.pilot_id, item.study_folder, item.filename, item.review_id]
      .join(' ')
      .toLowerCase()
      .includes(q);
  });
  if (currentIndex >= filtered.length) currentIndex = Math.max(0, filtered.length - 1);
  renderList();
  renderCurrent();
}

function renderList() {
  els.list.innerHTML = filtered.map((item, idx) => {
    const active = idx === currentIndex ? ' active' : '';
    const changed = item.changed ? ' · исправлено' : '';
    const reviewed = item.reviewed ? 'проверено' : 'не проверено';
    const kind = item.synthetic === '1' ? `синтетика: ${item.augmentation}` : 'оригинал';
    const training = trainingText(item.review_use_for_training);
    return `<button class="item${active}" data-idx="${idx}">
      <div class="item-title">
        <span>#${item.image_number} · ${item.filename}</span>
        <span class="badge ${labelClass(item.review_iliac_visible)}">${labelText(item.review_iliac_visible)}</span>
      </div>
      <div class="item-sub">${reviewed}${changed} · было: ${labelText(item.original_iliac_visible)} · ${positioningText(item.original_positioning_bad)} · ${kind} · ${training} · ${item.split}</div>
      <div class="item-sub">${item.study_folder}</div>
    </button>`;
  }).join('');
  document.querySelectorAll('.item').forEach((node) => {
    node.addEventListener('click', () => {
      currentIndex = Number(node.dataset.idx);
      renderList();
      renderCurrent();
    });
  });
}

function renderCurrent() {
  if (!filtered.length) {
    els.counter.textContent = 'Нет снимков';
    els.title.textContent = 'Ничего не найдено';
    els.image.removeAttribute('src');
    els.meta.innerHTML = '';
    els.notes.value = '';
    selectedLabel = null;
    selectedUseForTraining = '1';
    updateDecisionButtons();
    updateUseButtons();
    return;
  }
  const item = filtered[currentIndex];
  const globalIndex = items.findIndex((x) => x.review_id === item.review_id) + 1;
  els.counter.textContent = `Снимок ${globalIndex} из ${items.length}`;
  els.title.textContent = `#${item.image_number} · ${item.filename}`;
  els.image.src = `${item.image_url}?t=${encodeURIComponent(item.updated_at || '')}`;
  els.meta.innerHTML = [
    ['Метка организаторов', labelText(item.original_iliac_visible)],
    ['Текущая метка', labelText(item.review_iliac_visible)],
    ['Укладка по Excel', positioningText(item.original_positioning_bad)],
    ['Study UID', item.study_folder],
    ['Pilot ID', item.pilot_id],
    ['Файл', item.filename],
    ['Тип снимка', item.synthetic === '1' ? `Синтетика: ${item.augmentation}` : 'Оригинал'],
    ['Обучение', trainingText(item.review_use_for_training)],
  ].map(([label, value]) => `<div class="meta-card"><span>${label}</span><b title="${value}">${value}</b></div>`).join('');
  els.notes.value = item.review_notes || '';
  selectedLabel = item.review_iliac_visible;
  selectedUseForTraining = item.review_use_for_training || '1';
  updateDecisionButtons();
  updateUseButtons();
  const active = els.list.querySelector('.item.active');
  if (active) active.scrollIntoView({ block: 'nearest' });
}

function updateDecisionButtons() {
  document.querySelectorAll('.decision-btn').forEach((btn) => {
    btn.classList.toggle('selected', btn.dataset.label === selectedLabel);
  });
}

function updateUseButtons() {
  document.querySelectorAll('.use-btn').forEach((btn) => {
    btn.classList.toggle('selected', btn.dataset.use === selectedUseForTraining);
  });
}

async function loadItems() {
  const res = await fetch('/api/items');
  const data = await res.json();
  items = data.items;
  renderStats(data.summary);
  applyFilters();
}

async function saveCurrent(goNext = false) {
  if (!filtered.length || selectedLabel == null) return;
  const item = filtered[currentIndex];
  const res = await fetch('/api/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      review_id: item.review_id,
      review_iliac_visible: selectedLabel,
      review_status: 'done',
      review_use_for_training: selectedUseForTraining,
      review_notes: els.notes.value,
    }),
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.error || 'Ошибка сохранения');
    return;
  }
  await loadItems();
  const idx = filtered.findIndex((x) => x.review_id === item.review_id);
  currentIndex = Math.max(0, idx);
  if (goNext) currentIndex = Math.min(filtered.length - 1, currentIndex + 1);
  renderList();
  renderCurrent();
}

function move(delta) {
  if (!filtered.length) return;
  currentIndex = Math.min(filtered.length - 1, Math.max(0, currentIndex + delta));
  renderList();
  renderCurrent();
}

document.querySelectorAll('.filter').forEach((btn) => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.filter').forEach((x) => x.classList.remove('active'));
    btn.classList.add('active');
    currentFilter = btn.dataset.filter;
    currentIndex = 0;
    applyFilters();
  });
});

document.querySelectorAll('.decision-btn').forEach((btn) => {
  btn.addEventListener('click', () => {
    selectedLabel = btn.dataset.label;
    updateDecisionButtons();
  });
});

document.querySelectorAll('.use-btn').forEach((btn) => {
  btn.addEventListener('click', () => {
    selectedUseForTraining = btn.dataset.use;
    updateUseButtons();
  });
});

els.search.addEventListener('input', () => { currentIndex = 0; applyFilters(); });
els.prevBtn.addEventListener('click', () => move(-1));
els.nextBtn.addEventListener('click', () => move(1));
els.saveBtn.addEventListener('click', () => saveCurrent(false));
els.saveNextBtn.addEventListener('click', () => saveCurrent(true));

document.addEventListener('keydown', (event) => {
  if (event.target && ['TEXTAREA', 'INPUT'].includes(event.target.tagName)) return;
  if (event.key === '1') { selectedLabel = '1'; updateDecisionButtons(); }
  if (event.key === '0') { selectedLabel = '0'; updateDecisionButtons(); }
  if (event.key === '?') { selectedLabel = '?'; updateDecisionButtons(); }
  if (event.code === 'KeyT' || event.key.toLowerCase() === 't') { selectedUseForTraining = '1'; updateUseButtons(); }
  if (event.code === 'KeyE' || event.key.toLowerCase() === 'e') { selectedUseForTraining = '0'; updateUseButtons(); }
  if (event.key.toLowerCase() === 's') saveCurrent(false);
  if (event.key.toLowerCase() === 'n' || event.key === 'ArrowRight') move(1);
  if (event.key.toLowerCase() === 'p' || event.key === 'ArrowLeft') move(-1);
});

loadItems();
