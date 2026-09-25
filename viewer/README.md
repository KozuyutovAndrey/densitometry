# Web-интерфейс контроля качества DXA

Локальный интерфейс покрывает пользовательскую часть ТЗ:

- пакетная загрузка ZIP с DICOM;
- один ZIP может содержать несколько исследований, каждое входное изображение
  становится отдельной строкой результата;
- одна строка общей таблицы на каждый входной DICOM, включая ошибки обработки;
- фильтрация по области и результату контроля;
- просмотр снимка, предсказанных landmarks, измерений и найденных нарушений;
- выгрузка итогового CSV с обязательными колонками;
- выгрузка той же итоговой таблицы в XLSX;
- экспериментальная 3D-визуализация формы позвоночника.

## Запуск

```bash
uv sync
uv run python viewer/server.py
```

Интерфейс будет доступен по адресу <http://127.0.0.1:8765>. Для запуска в
контейнере или во внутренней сети можно явно разрешить внешний bind:

```bash
uv run python viewer/server.py --host 0.0.0.0 --port 8765
```

Задания выполняются последовательно, чтобы несколько параллельных запросов не
исчерпали память GPU. Загруженные архивы, логи и результаты сохраняются локально
в `artifacts/viewer_jobs/` и не отправляются во внешние сервисы.

Контейнерный запуск основного QC и интерфейса:

```bash
./scripts/restart_viewer.sh
```

Скрипт при первом запуске скачивает официальный DXA-to-3D checkpoint, проверяет
его SHA-256, пересобирает образ и заменяет контейнер. Результаты, журналы и веса
сохраняются между перезапусками. Порт можно изменить через `VIEWER_PORT`, каталог
заданий — через `VIEWER_JOBS_DIR`, каталог весов — через `DXA3D_MODEL_DIR`.
По умолчанию контейнер доступен только на `127.0.0.1`; для прямого внешнего
доступа без reverse proxy можно задать `VIEWER_BIND=0.0.0.0`.

Для серверного стенда интерфейс следует публиковать через Nginx. Готовая
конфигурация находится в `deploy/nginx/densitometry.conf` и включает лимит
загрузки 512 МБ и таймауты для обработки:

```bash
sudo apt-get update
sudo apt-get install -y nginx
sudo install -m 644 deploy/nginx/densitometry.conf /etc/nginx/sites-available/densitometry
sudo ln -sfn /etc/nginx/sites-available/densitometry /etc/nginx/sites-enabled/densitometry
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
```

После этого приложение доступно на порту 80. Для публичного домена поверх этой
конфигурации нужно выпустить TLS-сертификат, например через Certbot.

## HTTP API

| Метод | Маршрут | Назначение |
|---|---|---|
| `GET` | `/api/health` | Доступность сервера и модуля 3D |
| `GET` | `/api/jobs` | Список пакетных заданий |
| `GET` | `/api/jobs/{job_id}` | Состояние и строки результата |
| `POST` | `/api/jobs` | Загрузить ZIP как тело запроса |
| `GET` | `/api/jobs/{job_id}/export.csv` | Скачать итоговую таблицу |
| `GET` | `/api/jobs/{job_id}/export.xlsx` | Скачать итоговую таблицу в Excel |
| `GET` | `/api/jobs/{job_id}/images/{image_id}/preview.png` | Получить PNG-превью DICOM |
| `POST` | `/api/jobs/{job_id}/images/{image_id}/reconstruct` | Запустить 3D для spine-снимка |

`POST /api/jobs` принимает `application/zip` без multipart-обёртки. Максимальный
размер запроса — 512 МБ, после распаковки — 2 ГБ и не более 10 000 файлов.

Роут пакетного анализа запускает существующую команду:

```bash
python scripts/run_full_inference.py \
  --input <input.zip> \
  --out-csv <job>/submission.csv \
  --work-dir <job>/work
```

Интерпретатор можно задать через `QC_PYTHON`, устройство — через `QC_DEVICE`.
Таким образом, HTTP-слой отвечает за очередь, файлы и представление результата,
а классификация, landmarks и правила остаются в командных скриптах команды.
`time_of_processing` измеряется отдельно для каждого DICOM на этапах landmark
inference и классификации; общая однократная загрузка моделей в это поле не
включается.

## DXA-to-3D

Адаптер `viewer/reconstruct.py` изолирован в отдельном процессе. Совместимый
загрузчик в `viewer/dxa3d_published.py` воспроизводит исходную опубликованную
архитектуру ResNet50 + Bottleneck Transformer и загружает официальный checkpoint.
Исходный проект закреплён как git submodule в `third_party/DXA-to-3D`; после
обычного клонирования его можно получить командой:

```bash
git submodule update --init --recursive
```

Веса в Git не добавляются. При запуске без Docker укажите только путь к уже
скачанному checkpoint:

```bash
export DXA3D_CHECKPOINT="$PWD/artifacts/dxa3d/best_model.pt"
```

Upstream: <https://github.com/EmmanuelleB985/DXA-to-3D>, лицензия MIT.

После запуска контейнера 3D доступно для снимков позвоночника. Результат —
экспериментальная пространственная ось, а не сегментация позвонков или
диагностическая объёмная модель; он не участвует в `quality_class`. Совместимый
загрузчик нужен потому, что текущий upstream `inference.py` ссылается на
отсутствующую новую архитектуру, тогда как опубликованный checkpoint содержит
веса исходной модели с шестью кривыми по 209 точек.

## Проверки

```bash
uv run python -m unittest discover -s viewer/tests -v
```
