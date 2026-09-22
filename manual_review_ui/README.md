# Manual Review UI

Небольшой локальный русскоязычный web UI для ручной проверки `artifacts/manual_image_review.csv`.

Папка изолирована: если UI больше не нужен, можно удалить `manual_review_ui/`.

## Запуск

Из корня проекта:

```bash
uv run python manual_review_ui/app.py
```

Открыть:

```text
http://127.0.0.1:8765
```

Если порт занят:

```bash
uv run python manual_review_ui/app.py --port 8766
```

## Что редактируется

UI читает и сохраняет:

```text
artifacts/manual_image_review.csv
```

При первом сохранении создаётся backup:

```text
artifacts/manual_image_review.webui_backup.csv
```

## Что можно разметить

- `manual_region`
- `manual_is_canonical`
- `manual_notes`

Для train-бёдер автопрефилл оставляет `hip_unknown_side`; в UI нужно глазами заменить на `right_hip` или `left_hip`.

## Что показывает UI

- текущий DICOM как PNG;
- строки того же исследования;
- contact sheet исследования, если он есть;
- фильтры по pending/unknown/canonical/train/test;
- поиск по study, имени файла, региону и заметкам.
