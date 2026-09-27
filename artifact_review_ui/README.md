# Artifact Review UI

Небольшой временный UI для перепроверки разметки `spine_artifact` только на оригинальных изображениях без synthetic/hflip.

## Запуск

```bash
uv run python artifact_review_ui/server.py --host 0.0.0.0 --port 8770
```

Открыть локально:

```text
http://127.0.0.1:8770
```

Из локальной сети/Tailscale открывать по IP сервера и тому же порту.

## Что размечается

Источник:

```text
artifacts/spine_artifact_dataset/annotations.csv
```

В UI попадают только строки:

```text
augmentation == original
synthetic == 0
```

Результат сохраняется отдельно:

```text
artifacts/spine_artifact_dataset/manual_artifact_review.csv
```

Исходный `annotations.csv` не изменяется.

## Горячие клавиши

- `1` - артефакт есть
- `0` - артефакта нет
- `?` - сомнительно
- `S` - сохранить
- `N` / стрелка вправо - следующий
- `P` / стрелка влево - предыдущий
