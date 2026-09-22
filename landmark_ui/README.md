# Landmark UI

Отдельный временный web UI для pilot-разметки landmarks. Папку можно удалить, если инструмент больше не нужен.

Перед запуском соберите pilot CSV:

```bash
uv run python scripts/build_landmark_pilot.py
```

Запуск локально:

```bash
uv run python landmark_ui/app.py --host 127.0.0.1 --port 8766
```

Запуск для доступа из локальной сети:

```bash
uv run python landmark_ui/app.py --host 0.0.0.0 --port 8766
```

Разметка сохраняется в `artifacts/landmark_pilot.csv`. При первом сохранении создаётся backup `artifacts/landmark_pilot.webui_backup.csv`.
