# Densitometry QC

Проект для задачи ЛЦТ 2026 по контролю качества денситометрических DICOM-снимков.

План работ: [PLAN.md](PLAN.md).

## Web-интерфейс и локальный API

Запустить интерфейс пакетной загрузки и просмотра результатов:

```bash
uv run python viewer/server.py
```

Открыть `http://127.0.0.1:8765`. Сервер принимает ZIP с DICOM, а для анализа
вызывает существующий `scripts/run_full_inference.py`; модельная логика в HTTP-роутах
не дублируется. Подробности по API и экспериментальной 3D-визуализации описаны в
[`viewer/README.md`](viewer/README.md).

## Full Inference / Submission CSV

Запустить весь текущий end-to-end пайплайн одной командой:

```bash
uv run python scripts/run_full_inference.py \
  --input data/Для\ теста.zip \
  --out-csv artifacts/submission.csv
```

Скрипт последовательно выполняет:

- `infer_pipeline.py`;
- `predict_landmarks_heatmap.py`;
- `predict_landmarks_knn.py`;
- `merge_landmark_predictions.py`;
- `predict_spine_classifiers.py`;
- `apply_quality_rules.py`;
- финальный экспорт минимального CSV под ТЗ.

Финальный CSV содержит колонки:

- `path_to_study`;
- `study_uid`;
- `image_uid`;
- `anatomical_region`;
- `quality_class`;
- `violation_type`;
- `processing_status`;
- `time_of_processing`.

Промежуточные и debug CSV по умолчанию пишутся в `artifacts/full_inference/`. Debug-таблица `quality_predictions_debug.csv` содержит вероятности классификаторов, geometry scores, canonical/duplicate flags и внутренние статусы.

Проверенный smoke-test:

```bash
uv run python scripts/run_full_inference.py \
  --input data/Для\ теста.zip \
  --out-csv artifacts/submission_test.csv \
  --work-dir artifacts/full_inference_test
```

Проверенный полный прогон на train archive:

```bash
uv run python scripts/run_full_inference.py \
  --input data/НД_для_обучения.zip \
  --out-csv artifacts/submission_train.csv \
  --work-dir artifacts/full_inference_train
```

Результат полного прогона: `499` DICOM -> `499` строк submission, все `processing_status=Success`.

## Подготовка первичных артефактов

```bash
uv run python scripts/prepare_artifacts.py
```

Скрипт читает архивы из `data/` без ручной распаковки и пишет в `artifacts/`:

- `dicom_index.csv` — индекс всех DICOM из train/test, метаданные, размер изображения и первичная подсказка области (`region_hint`).
- `labels.csv` — нормализованная разметка из Excel. Итоговые `*_quality_or` считаются как OR отдельных критериев; исходные итоговые колонки сохранены как `raw_*`.
- `study_summary.csv` — сводка по исследованиям: число DICOM и подсчёт областей.
- `manual_image_review.csv` — рабочая таблица для ручной валидации области, canonical-кадра и дублей.
- `contact_sheets/` — JPEG-листы по каждому train-исследованию для быстрого визуального просмотра.

Быстрый прогон без JPEG:

```bash
uv run python scripts/prepare_artifacts.py --no-contact-sheets
```

Сгенерировать только первые N contact sheets:

```bash
uv run python scripts/prepare_artifacts.py --max-contact-sheets 10
```

Автозаполнить рабочую таблицу ручной проверки:

```bash
uv run python scripts/prefill_manual_review.py
```

Скрипт сохраняет backup в `artifacts/manual_image_review.before_prefill.csv` и пишет shortlist для визуальной проверки в `artifacts/manual_prefill_report.csv`.

После ручной проверки собрать clean dataset:

```bash
uv run python scripts/build_clean_dataset.py
```

Скрипт читает подтверждённый `manual_image_review.csv`, оставляет только canonical-снимки `spine`, `right_hip`, `left_hip`, присоединяет разметку и пишет:

- `clean_image_index.csv` — чистая таблица `study x region` для обучения, landmarks и аналитики.
- `clean_dataset_report.csv` — счётчики по регионам, меткам и критериям.
- `clean_dataset_issues.csv` — потенциальные проблемы join/разметки.

Собрать pilot-выборку для landmarks:

```bash
uv run python scripts/build_landmark_pilot.py
```

Скрипт пишет:

- `landmark_pilot.csv` — снимки для ручной простановки точек.
- `landmark_pilot_report.csv` — состав pilot-выборки.

Запустить отдельный UI для landmarks:

```bash
uv run python landmark_ui/app.py --host 0.0.0.0 --port 8766
```

После разметки посчитать pilot-метрики:

```bash
uv run python scripts/compute_landmark_metrics.py
```

Скрипт пишет `artifacts/landmark_metrics.csv`. Для малого вертела и ROI-отступов расстояния считаются в миллиметрах с учётом разного масштаба по осям: `X = 0.6 мм/px`, `Y = 1.05 мм/px`. Боковой ROI считается по стороне: для `right_hip` до левого края изображения, для `left_hip` до правого.

Собрать и проверить полную landmark-разметку:

```bash
uv run python scripts/build_landmark_all.py
uv run python landmark_ui/app.py --host 0.0.0.0 --port 8766 --pilot-csv artifacts/landmark_all.csv
uv run python scripts/compute_landmark_metrics.py --pilot-csv artifacts/landmark_all.csv --out-csv artifacts/landmark_all_metrics.csv
uv run python scripts/evaluate_landmark_rules.py --pilot-csv artifacts/landmark_all.csv --metrics-csv artifacts/landmark_all_metrics.csv --eval-csv artifacts/landmark_all_rule_eval.csv --errors-csv artifacts/landmark_all_rule_errors.csv
uv run python scripts/analyze_landmark_metrics.py --pilot-csv artifacts/landmark_all.csv --metrics-csv artifacts/landmark_all_metrics.csv --summary-csv artifacts/landmark_all_analysis_summary.csv --rows-csv artifacts/landmark_all_analysis_rows.csv
uv run python scripts/make_rule_error_sheets.py
uv run python scripts/export_keypoint_dataset.py
```

`make_rule_error_sheets.py` пишет JPEG-листы ошибок правил в `artifacts/rule_error_sheets/`. `export_keypoint_dataset.py` пишет PNG и `annotations.csv` в `artifacts/keypoint_dataset/`; split делается по `study_folder`.



Оценить и сохранить простую модель стороны бедра:

```bash
uv run python scripts/evaluate_laterality_baseline.py
```

На текущей ручной валидации template-baseline даёт `150/152` на canonical train-бёдрах при проверке внутри `infer_pipeline.py`; два спорных снимка записаны в `artifacts/laterality_inference_errors.csv`.



## KNN Landmarks And Baseline Quality

Оценить более сильный baseline landmarks по ближайшим похожим снимкам:

```bash
uv run python scripts/evaluate_landmark_knn.py --k 5
```

Текущий результат KNN на val: mean error около `15.7 мм`, median около `12.8 мм`. Это лучше mean-shape, но всё ещё baseline.

Получить KNN landmark-предсказания для результата инференса:

```bash
uv run python scripts/predict_landmarks_knn.py --input-csv artifacts/inference_skeleton.csv --dicom-input data/Для\ теста.zip --out-csv artifacts/inference_landmark_predictions_knn.csv
```

Применить геометрические правила качества к предсказанным landmarks:

```bash
uv run python scripts/apply_quality_rules.py --inference-csv artifacts/inference_skeleton.csv --landmarks-csv artifacts/inference_landmark_predictions_knn.csv --out-csv artifacts/quality_predictions_baseline.csv
```

`quality_predictions_baseline.csv` уже имеет строку на каждый DICOM и черновые `quality_class` / `violation_type`. Это baseline-вывод, не финальная модель.

## Spine Positioning Dataset

Собрать отдельный датасет для задачи укладки позвоночника: видны ли подвздошные кости внизу снимка.

```bash
uv run python scripts/build_spine_positioning_dataset.py
```

Он не заменяет landmark dataset. Он содержит оригинальные spine-снимки и только train-аугментации:

- synthetic bad `spine_positioning`: обрезка низа у нормальных spine-снимков.

Validation остаётся только из настоящих снимков.

Артефакты:

- `artifacts/spine_positioning_dataset/annotations.csv`;
- `artifacts/spine_positioning_dataset/images/`.

Имена PNG содержат номер изображения и pilot id, например `img402_pilot0150_..._bottom_crop_25.png`.

## Spine Artifact Dataset

Собрать отдельный датасет для задачи артефактов позвоночника:

```bash
uv run python scripts/build_spine_artifact_dataset.py
```

Он содержит оригинальные spine-снимки и только train-аугментации:

- synthetic positive `spine_artifact`: зеркалирование artifact-positive снимков по вертикальной оси.

Validation остаётся только из настоящих снимков.

Артефакты:

- `artifacts/spine_artifact_dataset/annotations.csv`;
- `artifacts/spine_artifact_dataset/images/`.

Имена PNG содержат номер изображения, pilot id и метку `artifact`/`clean`, например `img422_pilot0154_artifact_hflip.png`.

Старый смешанный `artifacts/spine_classifier_dataset/` удалён: он объединял две разные задачи и не должен пересоздаваться.

## Spine Classifiers

Обучить независимые бинарные классификаторы позвоночника:

```bash
uv run python scripts/train_spine_classifier.py --task positioning --epochs 60 --batch-size 16
uv run python scripts/train_spine_classifier.py --task artifact --epochs 80 --batch-size 16
```

Артефакты:

- `artifacts/spine_classifiers/positioning/best.pt`;
- `artifacts/spine_classifiers/positioning/report.json`;
- `artifacts/spine_classifiers/positioning/val_predictions.csv`;
- `artifacts/spine_classifiers/artifact/best.pt`;
- `artifacts/spine_classifiers/artifact/report.json`;
- `artifacts/spine_classifiers/artifact/val_predictions.csv`.

Текущий sanity-check на val:

- positioning: `TP=1`, `FP=0`, `FN=1`, `TN=18`, balanced accuracy `0.75`; единственный FN - спорный `img492`, где экспертная метка bad, но подвздошные гребни размечены как видимые;
- artifact: `TP=5`, `FP=1`, `FN=1`, `TN=13`, balanced accuracy `0.881`.

## PyTorch Heatmap Landmarks

Обучить heatmap-модель для landmarks:

```bash
uv run python scripts/train_landmark_heatmap.py --region hip --epochs 80 --batch-size 8
uv run python scripts/train_landmark_heatmap.py --region spine --epochs 80 --batch-size 8
```

Финальное переобучение перед сдачей на прежних train+val данных:

```bash
uv run python scripts/train_landmark_heatmap.py --region hip --epochs 80 --batch-size 8 --geometry-loss-weight 0 --geometry-loss-start-epoch 9999 --train-all
uv run python scripts/train_landmark_heatmap.py --region spine --epochs 80 --batch-size 8 --train-all
uv run python scripts/train_spine_classifier.py --task positioning --epochs 60 --batch-size 16 --train-all
uv run python scripts/train_spine_classifier.py --task artifact --epochs 80 --batch-size 16 --train-all
uv run python scripts/evaluate_landmark_knn.py --train-all
uv run python scripts/evaluate_laterality_baseline.py --train-all
```

Текущий результат на прежнем val до финального train-all:

- hip heatmap: mean error `4.36 мм`, median `1.99 мм`, p90 `6.32 мм`;
- spine heatmap: mean error `58.97 мм`, хуже KNN, поэтому пока не используем в гибриде.

Финальный train-all sanity-check по объединенному train+val:

- hip heatmap: mean error `1.51 мм`, median `1.02 мм`, p90 `2.81 мм`;
- spine heatmap: mean error `16.36 мм`, median `2.05 мм`, p90 `56.13 мм`;
- spine positioning classifier: train-all weights, inference threshold `0.289507` from old validation;
- spine artifact classifier: train-all weights, inference threshold `0.235047` from old validation.

После возврата validation-порогов all-DICOM audit на `248` размеченных изображениях: quality `BA=0.690`, `F1=0.558`; `spine_artifact BA=0.588`, поэтому порог артефактов остается отдельным риском калибровки.

Получить heatmap landmarks, spine-classifier predictions и собрать гибрид `hip=PyTorch`, `spine=KNN + classifiers` вручную для отладки. Для обычного end-to-end запуска используйте `scripts/run_full_inference.py` из раздела выше.

```bash
uv run python scripts/predict_landmarks_heatmap.py --input-csv artifacts/inference_skeleton.csv --dicom-input data/Для\ теста.zip --out-csv artifacts/inference_landmark_predictions_heatmap.csv
uv run python scripts/merge_landmark_predictions.py --primary-csv artifacts/inference_landmark_predictions_heatmap.csv --fallback-csv artifacts/inference_landmark_predictions_knn.csv --out-csv artifacts/inference_landmark_predictions_hybrid.csv
uv run python scripts/predict_spine_classifiers.py --input-csv artifacts/inference_skeleton.csv --dicom-input data/Для\ теста.zip --out-csv artifacts/inference_spine_classifier_predictions.csv
uv run python scripts/apply_quality_rules.py --inference-csv artifacts/inference_skeleton.csv --landmarks-csv artifacts/inference_landmark_predictions_hybrid.csv --spine-classifiers-csv artifacts/inference_spine_classifier_predictions.csv --out-csv artifacts/quality_predictions_hybrid.csv --model-name hybrid
```

В этом режиме `spine_positioning` и `spine_artifact` берутся из spine-классификаторов, а `spine_axis`, hip rotation/positioning и hip ROI остаются на landmark-правилах.

## Landmark Baseline

Оценить простейший baseline автоматических landmarks:

```bash
uv run python scripts/evaluate_landmark_baseline.py
```

Он обучает среднюю нормированную форму по `spine`, `left_hip`, `right_hip` и пишет:

- `artifacts/landmark_mean_model.json`;
- `artifacts/landmark_baseline_eval.csv`;
- `artifacts/landmark_baseline_report.csv`.

Текущий результат mean-shape baseline на val: mean error около `20 мм`, median около `19 мм`. Это не финальная точность, а нижняя планка и контракт модели.

Получить landmark-предсказания для результата инференса:

```bash
uv run python scripts/predict_landmarks_baseline.py --input-csv artifacts/inference_skeleton.csv --out-csv artifacts/inference_landmark_predictions.csv
```

## Каркас инференса

Проверить end-to-end поток на архиве или папке DICOM:

```bash
uv run python scripts/infer_pipeline.py --input data/Для\ теста.zip --out-csv artifacts/inference_skeleton.csv
```

Скрипт пишет строку на каждый DICOM и заполняет:

- `anatomical_region` — `spine`, `right_hip`, `left_hip`, `hip_unknown_side` или `unknown`;
- `is_canonical_for_region` — основной снимок региона внутри исследования;
- `is_duplicate_or_derived` — debug-флаг дубля/derived; финальное качество все равно считается для этого DICOM;
- `processing_status` — что произошло с изображением.

Текущий `infer_pipeline.py` решает region/laterality/canonical. Качество считается отдельными шагами через landmark-predictions, `predict_spine_classifiers.py` и `apply_quality_rules.py`; canonical не используется для копирования quality на другие DICOM.


## Важные договорённости

- На финальном инференсе нужна строка на каждый DICOM/изображение, и каждое изображение оценивается отдельно.
- Для обучения нельзя считать дубли/derived-версии независимыми объектами: split делаем по `study_folder/study_key`, а canonical image используем только для train/leakage контроля, не для финального копирования quality.
- Пустые ячейки в Excel — это отсутствующая зона или неприменимый критерий, а не отрицательная метка.
- Для ROI бедра используем масштаб из ответа организаторов: `Y = 1.05 мм/px`, `X = 0.6 мм/px`; значит 3 см по вертикали это примерно `28.6 px`, 2 см по горизонтали — `33.3 px`.
