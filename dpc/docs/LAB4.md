# DPC ЛР4. Пакетний звіт C01

## О4.1 — Генерація історії Parquet

Для експерименту підготовлено відтворюваний синтетичний набір C01.

- Генератор: `dpc/tools/generator/generate_history.py`
- Специфікація: `dpc/tools/generator/spec.c01.large.json`
- Seed: `7`
- Кількість сканувань: `100000`
- Кількість концертів: `3`
- Задана частка хедлайнера: `60%`
- Фактична частка хедлайнера: `60078 / 100000 = 60.078%`

Розподіл сканувань:

| Концерт | Кількість |
|---|---:|
| screening-c01-headliner | 60078 |
| screening-c01-001 | 20013 |
| screening-c01-002 | 19909 |

Створені Parquet-файли:

- `scans/part-00000.parquet` — 100000 рядків, 901284 байти.
- `performances/performances.parquet` — 3 рядки, 1646 байтів.
- Загальний розмір: 902930 байтів (приблизно 0.86 МіБ).

Кількість рядків підтверджено незалежною перевіркою метаданих Parquet через PyArrow.

Дані зберігаються локально в `data/c01-lab4-large` та не додаються до Git.

## О4.2 — Spark і маршрути звіту

Spark читає `scans` і `performances` з Parquet, залишає рядки з
`accepted=true` та приєднує довідник за `performance_id` (у спільній
схемі це `screenings.id`). Кожна група `(performance_id, gate)` має свій
`pass_count` і `median_event_time_utc`, а також `title`, `venue` і
`headliner`. Порожня історія або історія лише з відмовами дає `rows: []`.
Дублікати ключа довідника й прийняті сканування без відповідного запису
призводять до помилки, щоб кількість проходів не спотворювалася.

Запити використовують наявний заголовок `Authorization: Bearer <API_TOKEN>`.

| Запит | Результат |
|---|---|
| `POST /v1/reports/main/refresh` без тіла | `202`, запускає `report.py` через Spark runner та повертає `state`, `run` і `result: null`. Поки задача працює, повторний запуск повертає `409`. |
| `GET /v1/reports/main` | `state` дорівнює `idle`, `running`, `done` або `failed`. За `done` повертає `result: {"rows": [...]}`. |
| `GET /v1/reports/main/reference` | `{"rows": [...]}` з незалежного розрахунку. Якщо еталон ще не підготовлено, повертає `404`. |

Spark записує результати в окремий каталог для кожного запуску під
`/data/c01-lab4/reports`. API читає їх після успішного завершення задачі.
Стан запусків зберігається в пам’яті наявного runner. Після його перезапуску
новий запит звіту покаже `idle`, а файли попередніх запусків залишаться в томі.

## О4.3 — еталон і медіана

Картка C01 вимагає медіану часу приходу, але не фіксує точку відліку чи
округлення. Для цього звіту обрано **медіану абсолютних UTC-міток
`event_time`**. Набір C01 уже містить ці мітки. Якщо команда надалі обере
час від відкриття входу або початку концерту, знадобиться відповідна
мітка в довіднику та узгоджене оновлення формату звіту.

Для непарної групи Spark бере середню за порядком мітку. Для парної групи
обчислює середину між двома центральними мітками з десятковою арифметикою.
Половину мікросекунди округлює до ранішої мітки. Результат має шість цифр
після крапки й суфікс `Z`, наприклад `2026-10-12T17:30:00.000000Z`.

Еталон читає той самий Parquet через PyArrow в окремому процесі Python.
Він сортує мітки в кожній групі та знаходить середину за допомогою
`datetime`. Автоматична перевірка зіставляє групи за двома ключами й
порівнює кількість проходів, медіану та метадані точно, незалежно від
порядку рядків у відповіді. Для одного порівняння файли під
`/data/c01-lab4/scans` і `/data/c01-lab4/performances` мають залишатися
незмінними. Для іншого набору створіть окремий тестовий Compose-проєкт.

## Результати фактичного локального тестування

Перевірки виконала учасниця №4 через PowerShell на Windows 11 із Docker
Desktop, Spark standalone, PostgreSQL і FastAPI. Фінальний сценарій
виконано на синтетичному наборі C01. Результати підтверджують обов’язкове
ядро О4.2 та О4.3 в описаній конфігурації.

### Модульні тести

Пройшли **14 із 14 тестів**. Перевірено незалежний еталон, медіани, UTC,
порожні набори, порівняння результатів і взаємодію API зі Spark runner.

### Spark standalone

- Використано Spark **4.2.0** і один воркер зі статусом `ALIVE`. Через
  обмеження ноутбука з **16 ГБ RAM** запуск через `spark-submit` використовував
  одне ядро виконавця та по `512m` для драйвера й виконавця.
- Набір зі [специфікації C01](../tools/generator/spec.c01.json) скопійовано
  у спільний том під `/data/c01-lab4`. Він містив 120 сканувань для трьох
  концертів, з яких 93 прийняті та 27 відхилені.
- Задача `/jobs/report.py` завершилася успішно. Результат ручного запуску
  записано в `/data/c01-lab4/reports/manual-20261123-011210`.

### Незалежний еталон О4.3

Python-розрахунок створив `/data/c01-lab4/reference.json` із **9 групами та
93 прийнятими проходами**. Для кожного ключа `(performance_id, gate)`
зіставлено всі поля результату Spark і Python-еталона, зокрема кількість
проходів і медіану. Результат перевірки — `Spark and reference: MATCH`.

### Наскрізний HTTP-сценарій

| Запит | Фактичний результат |
|---|---|
| `GET /health` | `status: ok`, `instance: api` |
| `GET /v1/reports/main/reference` | 9 груп і 93 проходи |
| `POST /v1/reports/main/refresh` | `state: running`, ID запуску `20261122-232512-ba372c` |
| `GET /v1/reports/main` | `state: done`, 9 груп і 93 проходи |

Фінальне зіставлення всіх полів звіту з API та незалежного еталона дало
`DPC Lab 4: MATCH (9 groups, 93 accepted scans)`.

## О4.4 — Spark: фізичний план, shuffle та перекіс даних

Експеримент проведено на наборі C01 із 100 000 сканувань.
В обох запусках використано один Spark worker, одне ядро для
застосунку, 512 МБ пам'яті драйвера й виконавця та 8 shuffle-партицій.

| Показник | Базовий | Оптимізований |
|---|---|---|
| AQE | Вимкнено | Увімкнено |
| Broadcast threshold | 0 | 10m |
| Join | SortMergeJoin | BroadcastHashJoin |
| Звичайні Exchange у плані запису | 2 | 1 |
| Shuffle Read, усі стадії | ≈1546,6 КіБ | ≈799,4 КіБ |
| Shuffle Write, усі стадії | ≈1546,5 КіБ | ≈799,4 КіБ |
| Час PowerShell | 41,40 с | 33,55 с |
| Тривалість у Spark History | 22 с | 19 с |

У фінальному оптимізованому плані підтверджено
BroadcastHashJoin, BroadcastExchange та AQEShuffleRead (coalesced).
Зменшення shuffle пов'язане зі зміною способу з'єднання
маленького довідника з історією сканувань.

У базовому запуску Stage 7 мав 8 tasks, із яких лише
3 читали shuffle-дані:
- Task 3: 15 971 запис, 153,4 КіБ.
- Task 6: 48 076 записів, 464 КіБ.
- Task 7: 16 115 записів, 155,5 КіБ.

Найбільша партиція містила приблизно утричі більше записів,
ніж інші непорожні партиції. Це підтверджує data skew.
Водночас найдовша задача не була найбільшою за кількістю
записів, тому вплив перекосу на час не доведений.

Обидва звіти містили 9 груп і точно збіглися з незалежним
Python-еталоном. Час виміряно по одному разу, тому різниця
не є статистично підтвердженим прискоренням. AQE та
broadcast увімкнено разом; їхній окремий внесок не вимірювали.

### Додатковий експеримент О4.4 — Salting для усунення data skew

**Мета:** перевірити, чи зменшує salting перекіс навантаження під час з'єднання сканувань із довідником концертів, і порівняти продуктивність із базовим Spark-запитом.

Для експерименту створено окремий файл `dpc/spark/jobs/report_salted.py`. Основний `report.py` залишено без змін.

Реалізація використовує 8 значень `_salt`, обчислених за допомогою `pmod(xxhash64(scan_id), 8)`. Записи довідника дублюються для кожного значення salt. З'єднання виконується за двома ключами: `performance_id` та `_salt`.

**Умови контрольного порівняння:**

- Вхідні дані: 100 000 сканувань C01.
- Spark Standalone: 2 workers, по одному ядру для executor.
- Пам'ять драйвера та кожного executor: 512 MiB.
- Shuffle partitions: 8.
- AQE: вимкнено.
- Broadcast Join: вимкнено.
- Для обох варіантів використано однакові дані та конфігурацію.

**Результати вимірювання:**

| Показник | Baseline | Salting |
|---|---:|---:|
| Повний час запуску | 37,25 с | 40,23 с |
| Завершених стадій | 12 | 13 |
| Задач із ненульовим Shuffle Read у фінальній стадії | 3 із 8 | 6 із 8 |
| Максимальний Shuffle Read однієї задачі фінальної стадії | 48 076 записів | 21 532 записи |
| Результат проти незалежного Python-еталона | MATCH | MATCH |

У цьому вимірюванні salted-варіант працював на **2,98 с (приблизно 8%) довше**, ніж baseline.

**Перевірка фізичного плану:**

Spark History Server підтвердив:

- `Project` із `pmod(xxhash64(scan_id), 8)`;
- `Exchange` із `hashpartitioning(performance_id, _salt, 8)`;
- `SortMergeJoin LeftOuter` із двома ключами `performance_id` та `_salt`;
- додатковий `Exchange` за `performance_id` і `gate` перед віконними обчисленнями медіани.

У salted-запуску додаткова стадія мала Shuffle Read приблизно 1049,3 KiB та Shuffle Write приблизно 686,2 KiB.

**Перевірка правильності:** baseline, salted та незалежний Python reference містять по **9 груп і 80 159 прийнятих сканувань**. Повне порівняння всіх рядків, включно з медіанами, дало `ALL THREE MATCH: True`.

**Висновок:** salting було реалізовано й підтверджено фізичним планом. У фінальній стадії спостерігався рівномірніший розподіл прочитаних записів, але це не можна однозначно приписати лише salting, оскільки додатковий `Exchange` також змінив розподіл даних. Точна медіана все одно потребує повторного групування за `performance_id` і `gate`.

Для цього набору та одного контрольного запуску прискорення не отримано. Імовірною причиною є додаткові витрати на shuffle й дублювання малого довідника. Для статистично надійного висновку про продуктивність потрібні повторні вимірювання.

## О4.5 — Відмовостійкість Spark

Для перевірки відмовостійкості запущено Spark Standalone
із двома workers та двома executors (по одному ядру на executor).

Контрольний тест `fault_recovery.py` обробляв 100 000 сканувань
у 12 партиціях. Кожна задача містила затримку 30 секунд,
щоб можна було створити відмову під час обчислення.

Після підтвердження активних задач на обох executors
автоматичний PowerShell-сценарій зупинив `spark-worker-2`.

Результати:
- Spark зафіксував втрату executor та помилки доступу до shuffle.
- Spark History Server показав 4 невдалі спроби задач.
- Stage 2 і Stage 3 завершилися з позначкою `retry 1`.
- Повторно виконана Stage 3 завершила всі 12 задач (12/12).
- Job 2 отримав статус SUCCEEDED, тривалість — 3,3 хв.
- Підсумкова перевірка: 100 000 записів, 12 партицій, PASS.

Висновок: після контрольованої втрати Spark Worker під час
обчислення Spark повторно виконав необхідні стадії та
успішно завершив обробку без втрати записів.

Після експерименту другий worker було відновлено.

## Команди для Windows 11 PowerShell

Виконуйте з кореня репозиторію в одній сесії PowerShell. Перший блок запускає
легкі тести та створює окрему копію набору з тієї ж специфікації C01.
Потрібні Python 3.14 або `uv`, а для генерації через `uv` — PyArrow.

```powershell
uv run --no-project --python 3.14 python -B -m unittest experiments.test_dpc_lab4 -v
$tag = [guid]::NewGuid().ToString('N').Substring(0, 12)
$labProject = "cinema-c01-lab4-$tag"
$localData = "./data/c01-lab4-$tag"
uv run --python 3.14 ./dpc/tools/generator/generate_history.py ./dpc/tools/generator/spec.c01.json --out $localData
if ($LASTEXITCODE -ne 0) { throw 'Помилка генерації Parquet' }
```

Коли будете готові до запуску кластера, відкрийте Docker Desktop і перевірте,
що він працює в режимі Linux containers. Блок нижче запускає API, його
залежності PostgreSQL і `migrate`, один Spark worker, master, runner і сервер
історії. Параметри runner обмежують задачу одним ядром і задають по
512 МБ для драйвера та виконавця. Налаштування передається через stdin.

```powershell
docker compose version
docker info --format '{{.OSType}}'
$env:API_PORT = '18000'
$env:POSTGRES_PORT = '15432'
$env:SPARK_MASTER_UI_PORT = '18280'
$env:SPARK_JOB_UI_PORT = '14040'
$env:SPARK_HISTORY_PORT = '28080'
$env:DPC_APP_TAG = "lab4-$tag"
$env:API_TOKEN = 'dev-token'
@'
services:
  spark-runner:
    environment:
      SPARK_SUBMIT_CONF: "spark.ui.port=4040,spark.driver.host=spark-runner,spark.driver.memory=512m,spark.executor.memory=512m,spark.executor.cores=1,spark.cores.max=1"
'@ | docker compose -f docker-compose.yml -f - -p $labProject --profile spark up -d --build api spark-master spark-worker-1 spark-runner spark-history
if ($LASTEXITCODE -ne 0) { throw 'Помилка запуску Compose' }
docker compose -p $labProject --profile spark ps
```

Дочекайтеся статусу **ALIVE** для воркера в [Spark Master UI](http://localhost:18280).
`docker compose cp` створює каталог `/data/c01-lab4` у новому спільному
томі й копіює в нього обидві таблиці. Після копіювання один раз обчисліть
еталон і запустіть наскрізну перевірку.

```powershell
docker compose -p $labProject --profile spark cp $localData spark-runner:/data/c01-lab4
if ($LASTEXITCODE -ne 0) { throw 'Помилка копіювання Parquet' }
docker compose -p $labProject --profile spark exec -T spark-runner python /jobs/report_reference.py /data/c01-lab4 --out /data/c01-lab4/reference.json
if ($LASTEXITCODE -ne 0) { throw 'Помилка розрахунку еталона' }
uv run --no-project --python 3.14 python -B ./experiments/check_dpc_lab4.py --api http://localhost:18000 --expected-total 93 --timeout 300
```

Очікується `DPC Lab 4: OK (9 groups, 93 accepted scans, …)`. Для перегляду
вручну використайте PowerShell:

```powershell
$base = 'http://localhost:18000'
$headers = @{ Authorization = "Bearer $env:API_TOKEN" }
Invoke-RestMethod "$base/health"
Invoke-RestMethod "$base/metrics"
Invoke-RestMethod "$base/metrics/prom"
Invoke-RestMethod "$base/v1/reports/main" -Headers $headers | ConvertTo-Json -Depth 6
Invoke-RestMethod "$base/v1/reports/main/reference" -Headers $headers | ConvertTo-Json -Depth 6
```

У [Spark History Server](http://localhost:28080) знайдіть
`c01-lab4-report`. Щоб зупинити локальні сервіси й зберегти томи, виконайте
`docker compose -p $labProject --profile spark stop api spark-master spark-worker-1 spark-runner spark-history postgres`.
Ім’я проєкту й тег образу окремі. Якщо хтось уже використовує вказані порти
на цьому ноутбуці, оберіть вільні й використайте їх у командах перевірки.
