# DPC ЛР1: контракт і відтворення

Ця реалізація належить учаснику 3. Міграція `010_dpc_scans.sql` додає історію запитів. Примітив черги — `asyncio.Queue(maxsize=QUEUE_CAPACITY)`; `get()` на порожній черзі призупиняє coroutine без блокування потоку. До запису `queued` місткість резервується синхронно, тому повний буфер відповідає 429 без нового запису. Працюють рівно `WORKERS` worker-coroutines. Після прийняття у працюючому процесі кожен запит переходить до кінцевого стану; crash-durable черга не заявляється.

## API

Усі `/v1` маршрути вимагають `Authorization: Bearer <API_TOKEN>`.

`POST /v1/scans` JSON: `scan_id`, `ticket_id`, `ticket_code`, `gate`, `sector_id` (непорожні рядки), `event_time` (ISO 8601 із timezone). `ticket_code` — код для читання Web; `ticket_id` — стабільний ключ ефекту. Відповідь 202: `{ "scan_id": "...", "state": "queued" }`; фактичний стан може вже змінитись до наступного GET. Повна черга: 429 `application/problem+json`, `Retry-After: 1`. Різний вміст для того самого `scan_id`: 409; одночасна подача однакового ID може вимагати повтору. Неіснуючий сектор: 404. Неправильний payload: 400.

`GET /v1/scans/{id}` повертає запис з `state`, `decision`, `error_code` та UTC часовими полями. `done` означає прохід, `rejected` — предметне рішення (`invalid_ticket`, `wrong_performance`, `sector_full`), `failed` — технічну помилку. `GET /v1/sector/{id}`: `id`, `performance_id`, `capacity`, `inside`. `/health` не чекає БД; `/metrics` містить `queue_length`, `queue_capacity`, `workers_busy`, `scans_refused_total`.

Контракт відповіді Web `GET /v1/tickets/{code}` для сервісного Bearer `WEB_API_TOKEN`: HTTP 200 JSON `{ "ticket_id": "...", "performance_id": "...", "valid": true }`; HTTP 404 для невідомого коду. Інші 4xx/5xx або timeout є технічною помилкою сканування. Web має гарантувати, що `performance_id=screenings.id`, `ticket_id=tickets.id` і `valid` враховує статус ticket/booking. DPC не змінює Web tickets. Поки Web ЛР1 не реалізована, контракт очікує підтвердження учасника 1; fixture не є production fallback.

У захищеному режимі PostgreSQL advisory transaction lock на `ticket_id` серіалізує повтори, `SELECT ... FOR UPDATE` на `sectors` серіалізує різні білети. Перевірка+зміна `inside`, запис `processed_effects` і фінальне рішення scan — одна транзакція. HTTP/Web перевірка (у fixture режимі затримка 100–500 мс) виконується до неї. Навчальний unsafe режим на `dpc-test-` секторах читає `inside` без row lock і робить update за старим значенням, щоб відтворити гонку; на спільних секторах він відхиляється.

## Досліди

Після `docker compose up -d --wait postgres broker` і `docker compose run --rm migrate`:

```powershell
Get-Content -Raw experiments/dpc_lr1_seed.sql | docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U app -d app
docker compose run -d --name dpc-lr1-fixture --service-ports --no-deps -e TICKET_CHECK_MODE=fixture api
$env:EXPECTED_MODE='locked'; python experiments/test_dpc_lr1.py
docker stop dpc-lr1-fixture
Get-Content -Raw experiments/dpc_lr1_reset.sql | docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U app -d app
docker compose run -d --name dpc-lr1-unsafe --service-ports --no-deps -e TICKET_CHECK_MODE=fixture -e RESOURCE_MODE=unprotected api
$env:EXPECTED_MODE='unprotected'; python experiments/test_dpc_lr1.py
docker stop dpc-lr1-unsafe
docker compose run -d --name dpc-lr1-queue --service-ports --no-deps -e TICKET_CHECK_MODE=fixture -e QUEUE_CAPACITY=1 -e WORKERS=1 -e TICKET_CHECK_MIN_MS=500 -e TICKET_CHECK_MAX_MS=500 api
python experiments/test_dpc_queue_full.py
docker stop dpc-lr1-queue
```

Контейнери з цими іменами потрібно видалити (`docker rm ...`) перед повтором. Порт 8000 має бути вільним. Опис результатів — `results/dpc-lr1.md`. Дослід queue: Windows + Docker Desktop, capacity 1, workers 1, 20 одночасних клієнтів, 5 с, fixture ticket check 500 мс. p95 вимірюється окремим клієнтом і охоплює повний HTTP round trip; метрика `/metrics` описує іншу вибірку (останні 2000 запитів усіх маршрутів).
