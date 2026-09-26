# План работ

## Цель

Собрать локальное решение для оценки качества денситометрических DICOM-снимков:

- позвоночник: укладка, ось, артефакты/наложения;
- бедро: позиционирование/ротация, ROI;
- на выходе: строка на каждый DICOM/изображение с итоговым качеством и типами нарушений.

## Главная стратегия

Не начинать с большого классификатора на всех DICOM.

Данных мало, а часть классов имеет единицы плохих примеров. Поэтому базовый путь:

1. Построить индекс DICOM и нормализованную разметку.
2. Для обучения выбрать canonical image для каждого `study x region`, но финальный inference считать для каждого DICOM.
3. Собрать clean dataset с join к экспертной разметке.
4. Проверить геометрические правила на ручных landmarks.
5. Только после этого обучать landmark-модель, embedding-классификатор или небольшой ensemble.

## Важные договорённости

- Финальный inference должен выдавать строку на каждый DICOM.
- Для обучения дубли и derived-версии одного исследования нельзя считать независимыми объектами.
- Split делать строго по `study_folder/study_key`.
- Для обучения и контроля leakage использовать canonical image на `study x region`; для финального inference качество считать для каждого DICOM отдельно.
- Пустые ячейки в Excel означают отсутствующую зону или неприменимый критерий, а не отрицательную метку.
- Итоговое качество считаем как OR отдельных критериев, а исходные итоговые колонки сохраняем только для аудита.
- Для ROI бедра используем масштаб организаторов:
  - вертикаль: `1.05 мм/px`;
  - горизонталь: `0.6 мм/px`;
  - 3 см по вертикали: `28.6 px`;
  - 2 см по горизонтали: `33.3 px`.


## Демо / Explainability Overlay

Статус: в работе.

Цель: сделать врачебно понятный и демонстрационный режим объяснения решения в web UI. Не просто показывать `quality_class`, а визуально объяснять, почему снимок отмечен как bad.

Первый этап реализации:

- добавить переключатель `Объяснение` рядом с отображением анатомических точек;
- для позвоночника рисовать:
  - вертикальную эталонную линию;
  - предсказанную ось по крайним видимым центрам позвонков;
  - подпись угла оси;
  - нижнюю предупреждающую зону, если `spine_positioning_pred_bad=1`;
- для бедра рисовать:
  - ROI-отступ сверху от верхнего края большого вертела;
  - ROI-отступ сбоку от бокового края большого вертела;
  - ROI-отступ снизу от края седалищной кости;
  - базовую линию малого вертела и выступание кончика;
- использовать красно-янтарный цвет для нарушенных критериев и зелёный для нормальных измерений;
- Grad-CAM реализовать отдельным слоем для classifier-based причин (`spine_artifact`, `spine_positioning`), потому что геометрические критерии лучше объясняются линиями и расстояниями.


Второй этап реализации Grad-CAM:

- добавить backend-маршрут, который строит PNG Grad-CAM для spine-снимка и задачи `positioning`/`artifact`;
- использовать сохранённые `SmallSpineCNN` модели из `artifacts/spine_classifiers/*/best.pt`;
- в UI добавить переключатель `Тепловая карта артефактов` без выбора причины: укладка уже объясняется нижней зоной и подписью про подвздошные кости;
- показывать Grad-CAM только для артефактов позвоночника, не смешивать с ROI/landmark-геометрией бедра и укладкой;
- визуально проверить несколько десятков примеров, потому что Grad-CAM красивый, но не всегда клинически интерпретируемый.

Ограничения:

- overlay не должен менять inference и итоговый CSV;
- overlay работает только как визуальное объяснение уже рассчитанных landmarks/metrics/violations;
- если модель укладки позвоночника считает подвздошные кости отсутствующими, landmarks подвздошных костей в UI не показывать.

## Этап 1. Подготовка артефактов

Статус: сделано.

Команда:

```bash
uv run python scripts/prepare_artifacts.py
```

Артефакты:

- `artifacts/dicom_index.csv`
- `artifacts/labels.csv`
- `artifacts/study_summary.csv`
- `artifacts/manual_image_review.csv`
- `artifacts/contact_sheets/`

Проверки:

- train DICOM: `499`;
- test DICOM: `3`;
- всего DICOM: `502`;
- train studies: `100`;
- расхождение raw spine final с OR: `3`;
- расхождение raw hip final с OR: `0`.

## Этап 2. Ручная валидация изображений

Статус: сделано.

Автопрефилл:

```bash
uv run python scripts/prefill_manual_review.py
```

Скрипт заполняет пустые `manual_*` поля, сохраняет backup и пишет `artifacts/manual_prefill_report.csv`.

Нужно проверить и доразметить `artifacts/manual_image_review.csv`.

Колонки:

- `manual_region`: `spine`, `hip_unknown_side`, `right_hip`, `left_hip`, `duplicate`, `derived`, `unknown`;
- `manual_is_canonical`: `1` для основного снимка региона, `0` для дубля/derived;
- `manual_notes`: короткий комментарий, если кадр странный.

Как делать:

1. Открывать JPEG из `artifacts/contact_sheets/`.
2. Для каждого исследования определить, какие DICOM соответствуют позвоночнику, правому бедру, левому бедру.
3. Для каждого `study x region` выбрать один canonical image.
4. Отдельно отметить дубли, derived-версии и два изображения с шириной `248 px`.

Результат этапа:

- подтверждённая таблица `manual_image_review.csv`;
- готовая основа для clean train set.

## Этап 3. Clean dataset

Статус: сделано.

Цель: превратить ручную проверку в таблицу canonical-снимков с присоединённой экспертной разметкой.

Команда:

```bash
uv run python scripts/build_clean_dataset.py
```

Результат:

- `artifacts/clean_image_index.csv`;
- `artifacts/clean_dataset_report.csv`;
- `artifacts/clean_dataset_issues.csv`.

## Этап 4. Landmarks без ML

Статус: сделано для всех canonical train-снимков.

Была pilot-выборка `91` снимок: все bad-примеры по геометрическим критериям плюс good controls. После пилота размечены все canonical train-снимки:

- всего: `248 / 248`;
- бедро: `149 / 149`;
- позвоночник: `99 / 99`.

Команды:

```bash
uv run python scripts/build_landmark_pilot.py
uv run python scripts/build_landmark_all.py
uv run python landmark_ui/app.py --host 0.0.0.0 --port 8766 --pilot-csv artifacts/landmark_all.csv
uv run python scripts/compute_landmark_metrics.py --pilot-csv artifacts/landmark_all.csv --out-csv artifacts/landmark_all_metrics.csv
uv run python scripts/evaluate_landmark_rules.py --pilot-csv artifacts/landmark_all.csv --metrics-csv artifacts/landmark_all_metrics.csv --eval-csv artifacts/landmark_all_rule_eval.csv --errors-csv artifacts/landmark_all_rule_errors.csv
uv run python scripts/analyze_landmark_metrics.py --pilot-csv artifacts/landmark_all.csv --metrics-csv artifacts/landmark_all_metrics.csv --summary-csv artifacts/landmark_all_analysis_summary.csv --rows-csv artifacts/landmark_all_analysis_rows.csv
uv run python scripts/make_rule_error_sheets.py
uv run python scripts/export_keypoint_dataset.py
```

Артефакты:

- `artifacts/landmark_pilot.csv`;
- `artifacts/landmark_pilot_report.csv`;
- `artifacts/landmark_all.csv`;
- `artifacts/landmark_all_metrics.csv`;
- `artifacts/landmark_all_rule_eval.csv`;
- `artifacts/landmark_all_rule_errors.csv`;
- `artifacts/landmark_all_analysis_summary.csv`;
- `artifacts/landmark_all_analysis_rows.csv`;
- `artifacts/rule_error_sheets/`;
- `landmark_ui/` — временный web UI для кликовой разметки точек.

### Позвоночник

Размечено:

- центры уверенно видимых тел позвонков: `Th12`, `L1`, `L2`, `L3`, `L4`, `L5`;
- верхние края подвздошных костей.

Метрики:

- ось от верхнего видимого центра к нижнему видимому центру;
- угол этой оси к вертикали изображения;
- наличие нужной нижней анатомии для укладки.

### Бедро

Размечено:

- верхний край большого вертела;
- боковой край большого вертела;
- верх, кончик и низ малого вертела;
- край седалищной кости.

Метрики:

- ROI-отступ сверху/снизу/сбоку в пикселях и миллиметрах;
- выраженность малого вертела как proxy для ротации;
- наличие обязательных анатомических структур по клиническим критериям.

Текущие выводы по правилам на ручных landmarks:

- `spine_positioning`: правило `L5 + оба гребня подвздошных костей видны` почти закрывает критерий: F1 `0.833`, balanced accuracy `0.911`;
- `hip_positioning_rotation`: выраженность малого вертела работает как полезный proxy: F1 `0.746`, balanced accuracy `0.826`;
- `hip_roi`: composite-порог по верхнему, боковому и нижнему отступу ловит все bad, но даёт лишние FP: recall `1.000`, precision `0.300`;
- `spine_axis`: один угол оси даёт много FP, значит критерий нельзя закрывать только простой геометрией угла.

## Этап 5. Baseline-модели

Статус: начат.

Сделано:

- `scripts/evaluate_laterality_baseline.py`: template-baseline стороны бедра;
- `scripts/evaluate_landmark_baseline.py`: mean-shape baseline landmarks;
- `scripts/predict_landmarks_baseline.py`: единый выход mean-shape landmark-предсказаний для inference skeleton;
- `scripts/evaluate_landmark_knn.py`: KNN/top-k baseline landmarks;
- `scripts/predict_landmarks_knn.py`: KNN landmark-предсказания для inference skeleton;
- `scripts/apply_quality_rules.py`: черновой `quality_class` / `violation_type` из landmark-предсказаний;
- `scripts/train_landmark_heatmap.py`: PyTorch heatmap baseline для landmarks;
- `scripts/predict_landmarks_heatmap.py`: heatmap landmark-предсказания для inference skeleton;
- `scripts/merge_landmark_predictions.py`: гибрид heatmap/KNN landmarks.

Landmark baseline на val:

- mean-shape: mean error около `20.4 мм`, median около `18.7 мм`;
- KNN `k=5`: mean error около `15.7 мм`, median около `12.8 мм`;
- PyTorch heatmap для бедра: mean error `4.36 мм`, median `1.99 мм`, p90 `6.32 мм`;
- PyTorch heatmap для позвоночника: mean error `58.97 мм`, хуже KNN, пока не используем.

Для бедра heatmap уже заметно лучше KNN; geometry loss для малого вертела попробовали, но он ухудшил точность, поэтому финальный вариант сейчас: heatmap без geometry loss + constrained post-processing. Для позвоночника текущий heatmap провалился, поэтому рабочий вариант сейчас гибридный: `hip=PyTorch heatmap`, `spine=KNN`. Есть полный проверяемый поток `DICOM -> inference skeleton -> landmarks -> quality CSV`.

План baseline:

1. Зафиксировать геометрические правила для `spine_positioning`, `hip_positioning_rotation`, `hip_roi`.
2. По `artifacts/rule_error_sheets/` глазами проверить FP/FN и понять, где ошибка правила, а где экспертная метка не совпадает с нашей геометрией.
3. Для `spine_axis` добавить второй подход: small image classifier или embedding-классификатор, потому что угол/отклонение от оси по ручным точкам не объясняют метку достаточно хорошо.
4. Подготовить автоматизацию landmarks: начать с простого keypoint-regression/heatmap baseline или detector-а на canonical images.
5. Собрать inference-пайплайн, который считает landmarks/classifiers/quality для каждого DICOM отдельно; canonical использовать только как debug/train-признак.

Обязательные ограничения:

- split только по `study_folder/study_key`;
- обучать на canonical images;
- на inference считать правила по каждому изображению отдельно; не переносить решение с canonical на crop/duplicate версии;
- отдельно логировать uncertain cases.


## Диагностика проблем после validation quality eval

Статус: исторический диагностический блок после `scripts/evaluate_quality_validation.py`. Часть пунктов уже закрыта ниже отдельными классификаторами и all-DICOM inference.

### 1. Spine positioning / подвздошные кости

Клиническое правило: для укладки позвоночника важно наличие подвздошных костей внизу снимка. Позвонки отдельно не учитывать: они почти всегда есть и не решают критерий укладки.

По ручной landmark-разметке:

- spine canonical: `99`;
- `spine_positioning=1`: `6`;
- оба подвздошных гребня видны: `93`;
- оба/один гребень отсутствуют: `6`;
- правило `bad если нет хотя бы одного подвздошного гребня`: `TP=5`, `FP=1`, `FN=1`, `TN=92`.

Вывод: правило хорошее на ручных точках, но KNN на validation всегда старается поставить подвздошные landmarks даже при отсутствии структуры. Нужен отдельный `iliac_visible` detector/classifier или heatmap-confidence/visibility score. Данных для полноценного CNN-классификатора мало: всего `6` случаев отсутствия подвздошных костей.

### 2. Spine axis

Правило: угол оси позвоночника относительно вертикали изображения.

По всей ручной разметке лучший текущий порог:

```text
spine_axis_bad если angle >= 1.979 deg
```

На ручных landmarks это даёт примерно `recall=0.80`, `precision=0.276`. Угол даёт сигнал, но много FP. Артефакты и искривления не закрывать этим критерием.

### 3. Spine artifact

Ранее не было отдельной модели. Сейчас реализован отдельный CNN-классификатор `spine_artifact`; в ручной разметке `spine_artifact=1`: `17` из `99` spine canonical.

Основной ожидаемый паттерн: косточки бюстгальтера, видимые как дуги/параболы с вершинами вниз; ребра имеют противоположный изгиб. Нужно делать отдельный classifier/detector по spine-изображениям, не смешивать с axis/positioning.

### 4. Hip positioning / required anatomy

Клиническое правило: bad если не виден большой вертел или не видна седалищная кость. Шейку отдельно не искать: при наличии этих структур шейка фактически присутствует.

В текущей ручной landmark-разметке почти все hip-снимки имеют эти точки; отсутствующая структура встречается единично. Поэтому этот критерий лучше считать напрямую по visibility landmarks, а не обучать отдельный классификатор на текущем объеме.

### 5. Hip rotation

Текущий score: нормаль от `tip` малого вертела до основания `upper-lower`, в мм.

По ручной разметке bad rotation двугорбая:

- bad при слишком малом выступании малого вертела;
- bad при слишком большом выступании малого вертела.

Лучшее простое правило на ручных landmarks:

```text
hip_rotation_bad если prominence <= 0.20 мм OR prominence >= 6.346 мм
```

На ручных landmarks: `balanced_accuracy≈0.846`, `F1≈0.761`, `recall≈0.771`, `precision≈0.750`.

Проблема на validation: predicted landmarks часто дают bad-cases prominence около `0.6-1.2 мм`, то есть попадают в нормальную/неуверенную зону и критерий не срабатывает. Значит проблема не только в пороге, а в стабильности предсказания малого вертела и/или в том, что одного prominence-score мало.

Следующие решения:

1. Для spine positioning: сделать `iliac_visible` score/detector, начать с synthetic bottom-crop augmentation нормальных снимков. Полноценный CNN только на реальных `6` missing cases рискован, поэтому synthetic crop используем как bootstrap.
2. Для hip rotation: пока оставить two-sided prominence rule; вернуться к улучшению позже, после обучения на всём наборе.
3. Для spine artifact: собрать отдельный artifact classifier. Positive cases `17`, из них train `11`, val `6`. Для train добавлена left-right mirror augmentation, потому что косточки бюстгальтера сохраняют форму при зеркалировании по вертикальной оси.

Созданы два отдельных augmented dataset, потому что `spine_positioning` и `spine_artifact` - разные задачи и их нельзя смешивать в одном обучающем наборе.

Укладка позвоночника / видимость подвздошных костей:

```bash
uv run python scripts/build_spine_positioning_dataset.py
```

Артефакты:

- `artifacts/spine_positioning_dataset/annotations.csv`;
- `artifacts/spine_positioning_dataset/images/`.

Состав после генерации:

- всего строк: `271`;
- train original spine: `79`, из них positioning bad: `4`;
- val original spine: `20`, из них positioning bad: `2`;
- synthetic train bottom crop positioning bad: `172`;
- crop попадает в набор только если по landmark-точкам обрезка действительно убрала оба подвздошных гребня.

Артефакты позвоночника / косточки бюстгальтера и наложения:

```bash
uv run python scripts/build_spine_artifact_dataset.py
```

Артефакты:

- `artifacts/spine_artifact_dataset/annotations.csv`;
- `artifacts/spine_artifact_dataset/images/`.

Состав после генерации:

- всего строк: `110`;
- train original spine: `79`, из них artifact bad: `11`;
- val original spine: `20`, из них artifact bad: `6`;
- synthetic train artifact horizontal flip: `11`.

Старый смешанный `artifacts/spine_classifier_dataset/` удалён: он объединял две разные задачи и не должен пересоздаваться.

Обучены первые независимые классификаторы:

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

Val sanity-check отдельных классификаторов:

- positioning: `TP=1`, `FP=0`, `FN=1`, `TN=18`, balanced accuracy `0.75`; FN - `img492`, спорная метка, так как оба подвздошных гребня размечены видимыми;
- artifact: `TP=5`, `FP=1`, `FN=1`, `TN=13`, balanced accuracy `0.881`; ошибки: FP `img085`, FN `img257`.

Эти классификаторы встроены в общий quality validation/inference: `spine_positioning` и `spine_artifact` теперь берутся из CNN, `spine_axis` остается по landmark-геометрии. Текущий validation после встраивания: overall quality `TP=6`, `FP=4`, `FN=10`, `TN=30`, balanced accuracy `0.629`; quality_spine balanced accuracy `0.687`.

## Этап 6. Inference и формат ответа

Статус: end-to-end CLI baseline собран.

Сделано:

- чтение входной папки или zip-архива с DICOM;
- строка результата на каждый DICOM;
- группировка по контейнеру/папке исследования, а DICOM `StudyInstanceUID` сохраняется отдельной колонкой;
- первичное определение `spine`, `right_hip`, `left_hip`, `hip_unknown_side`, `unknown`;
- выбор canonical-снимка внутри `study x region`;
- пометка canonical/duplicate как debug-признаков без исключения из quality inference;
- template-baseline для laterality бедра, когда в имени нет `ППОБ/ЛПОБ` или DICOM laterality.

Команда:

```bash
uv run python scripts/infer_pipeline.py --input data/Для\ теста.zip --out-csv artifacts/inference_skeleton.csv
```

Проверка laterality:

```bash
uv run python scripts/evaluate_laterality_baseline.py
```

Результат на canonical train-бёдрах через inference skeleton: `150/152`, ошибки записаны в `artifacts/laterality_inference_errors.csv`.

Нужно доделать:

- заменить KNN landmarks позвоночника на более устойчивую модель поиска точек;
- улучшить качество landmark-модели и правила критериев;
- поддерживать две оценки: стандартную validation на `keypoint_dataset/annotations.csv` и all-DICOM audit на `landmark_all.csv`;
- при необходимости запись XLSX.

Предлагаемые обязательные колонки:

- `path_to_study`;
- `study_uid`;
- `image_uid`;
- `anatomical_region`;
- `quality_class`;
- `violation_type`;
- `processing_status`;
- `time_of_processing`.

Новая договоренность по duplicate/canonical:

- организаторы подтвердили: каждое пришедшее изображение нужно обработать и вывести отдельной строкой, даже если оно похоже на дубль;
- crop/derived-версии могут иметь другое качество, особенно по `hip_roi`;
- поэтому `canonical` больше не используется для копирования качества;
- `predict_landmarks_heatmap.py`, `predict_landmarks_knn.py`, `predict_spine_classifiers.py` теперь обрабатывают все поддержанные DICOM, а не только canonical;
- `apply_quality_rules.py` теперь считает quality построчно по `member`, а не копирует результат с `canonical_member`;
- `is_canonical_for_region`, `is_duplicate_or_derived`, `canonical_member` оставлены как debug/training признаки.

Full inference entrypoint:

- добавлен `scripts/run_full_inference.py`;
- команда запуска всего пайплайна: `uv run python scripts/run_full_inference.py --input <zip-or-folder> --out-csv artifacts/submission.csv`;
- финальный CSV экспортируется в минимальном формате ТЗ: `path_to_study`, `study_uid`, `image_uid`, `anatomical_region`, `quality_class`, `violation_type`, `processing_status`, `time_of_processing`;
- debug/intermediate CSV пишутся в `artifacts/full_inference/`;
- smoke-test на `data/Для теста.zip` прошел: `3` DICOM на входе, `3` строки в `artifacts/submission_test.csv`, debug CSV в `artifacts/full_inference_test/quality_predictions_debug.csv`;
- полный прогон на `data/НД_для_обучения.zip` прошел через тот же entrypoint: `499` DICOM, `499` строк в `artifacts/submission_train.csv`, все `processing_status=Success`, debug CSV в `artifacts/full_inference_train/quality_predictions_debug.csv`;
- `processing_status` в submission приводится к `Success` / `Failure`; подробный внутренний статус остается в debug CSV.

Актуальные файлы с метриками:

- стандартная validation-оценка: `artifacts/quality_validation_report.csv`;
- all-DICOM audit на ручной разметке: `artifacts/quality_train_landmarked_report.csv`;
- ошибки all-DICOM audit: `artifacts/quality_train_landmarked_errors.csv`;
- отдельная проверка ROI по ручным landmarks: `artifacts/hip_roi_all_rule_report.csv`;
- итоговый full-inference train output: `artifacts/submission_train.csv`;
- debug full-inference train output: `artifacts/full_inference_train/quality_predictions_debug.csv`.

All-DICOM inference после отказа от canonical-copy:

- `infer_pipeline.py` больше не помечает non-canonical как `duplicate_or_derived_skipped`; все поддержанные DICOM получают статус `not_evaluated_quality_model_missing` до запуска моделей;
- пересобрана train-цепочка на `data/НД_для_обучения.zip`: `499` строк;
- `predict_landmarks_heatmap.py`: `333` hip DICOM predicted;
- `predict_landmarks_knn.py`: `499` DICOM predicted;
- `merge_landmark_predictions.py`: `333` primary heatmap hip, `166` fallback kNN spine;
- `predict_spine_classifiers.py`: `166` spine DICOM predicted;
- `apply_quality_rules.py`: `499` quality rows, все со статусом `quality_predicted_hybrid`;
- новый audit script: `scripts/evaluate_quality_predictions_against_landmarks.py`;
- audit outputs: `artifacts/quality_train_landmarked_predictions.csv`, `artifacts/quality_train_landmarked_report.csv`, `artifacts/quality_train_landmarked_errors.csv`;
- audit на `248` вручную размеченных изображениях: overall `BA=0.687`, `F1=0.553`;
- all-DICOM audit по отдельным критериям против ручных меток: `spine_positioning BA=0.911`, `spine_axis BA=0.749`, `spine_artifact BA=0.929`, `hip_positioning_rotation BA=0.577`, `hip_roi BA=0.490`;
- стандартная validation-оценка на `50` val из `keypoint_dataset/annotations.csv` осталась: overall `BA=0.629`, `F1=0.462`;
- вывод: отказ от canonical-copy технически сделан, но теперь явно видны слабые места `hip_roi` и `hip_positioning_rotation` на crop/non-canonical случаях.

Отдельная проверка hip ROI:

- добавлен скрипт `scripts/evaluate_hip_roi_all.py`;
- отчеты: `artifacts/hip_roi_all_rule_check.csv`, `artifacts/hip_roi_all_rule_report.csv`;
- по всей ручной hip-разметке есть `149` ROI-размеченных примеров, из них `6` positive;
- все `6` positive попали в train, поэтому в текущем validation split нет ROI-positive;
- официальное правило `30/20/30 мм` по текущим ручным landmarks дает `TP=1`, `FP=3`, `FN=5`, `TN=140`, balanced accuracy `0.573`;
- на текущих predicted landmarks официальное правило дает `TP=0`, `FP=3`, `FN=6`, `TN=140`, balanced accuracy `0.490`;
- вариант `bottom < 37 мм` на predicted landmarks дает `TP=3`, `FP=5`, `FN=3`, `TN=138`, balanced accuracy `0.733`;
- вариант `bottom < 59 мм` на predicted landmarks дает `TP=5`, `FP=11`, `FN=1`, `TN=132`, balanced accuracy `0.878`;
- вывод: ROI нужно тюнить/проверять по всем ROI-positive, а не только по val; часть Excel ROI-positive не совпадает с текущими landmark-margin правилами.

Дополнительные колонки можно добавить для отладки:

- вероятности критериев;
- geometry scores;
- reason/debug message.

## Этап 7. Docker и сдача

Статус: финальный этап.

Нужно:

- CLI entrypoint `scripts/run_full_inference.py` готов;
- Dockerfile;
- README запуска обновлен;
- проверка на `data/Для теста.zip` выполнена;
- smoke-test: выход имеет строку на каждый DICOM.

## Ближайший чеклист

- [x] Сделать автопрефилл `artifacts/manual_image_review.csv`.
- [ ] Открыть `artifacts/contact_sheets/`.
- [ ] Проверить `artifacts/manual_prefill_report.csv` и первые 20 исследований.
- [ ] Отдельно выписать сомнительные случаи.
- [ ] Проверить, хватает ли `region_hint` для автоматического первичного определения области.
- [ ] Выбрать 20-30 позвоночников для pilot landmarks.
- [ ] Выбрать 30-40 бёдер для pilot landmarks.
- [ ] Зафиксировать точные landmark-инструкции.
- [ ] Проверить geometry rules без ML.
- [ ] Принять решение: landmark-модель, embeddings или гибрид.
