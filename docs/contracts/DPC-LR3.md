# DPC ЛР3: Ray та атомарний ефект входу

Внутрішній `POST /internal/admission` приймає окремий Bearer `RECEIVER_TOKEN`;
клієнтський `API_TOKEN` не дозволяє надсилати перевірений результат квитка.

При `EXECUTION=ray` кожен прийнятий scan з черги ЛР1 стає Ray task. Task перевіряє білет (у production через Web API; для ізольованого досліду через read-only fixture), надсилає результат до захищеного внутрішнього `POST /internal/admission` і повертає рішення. Ray worker **не змінює сектор і не пише ефект**. Приєднання до Ray client `RAY_ADDRESS=ray://ray-head:10001` відбувається під час запуску API; кластер треба запустити раніше. Task має `max_retries=2` після системної аварії worker.

Приємник у PostgreSQL транзакції бере advisory lock за стабільним `ticket_id`, читає `processed_effects(handler='admission',effect_key=ticket_id)`, при новому ефекті блокує рядок `sectors FOR UPDATE`, перевіряє місткість, змінює `inside`, зберігає рішення та фінальний scan. Повтор виклику повертає попереднє рішення й інкрементує тільки діагностичний `scans.receiver_calls` (міграція 011). Новий `scan_id` того самого `ticket_id` також отримує попереднє рішення. `scan_id`, `ticket_id` та `event_id` не змішуються.

Одноразовий файл `/faults/after_effect_before_ack` споживається Ray task **після** HTTP 200 від приємника і до завершення task; процес завершується через `os._exit(1)`. Ray повторює task. Два виклики приємника, один effect key і незмінний `inside` доводять результат. Fault діє тільки при `FAULTS=on`, який задано Ray worker-ам. Shared volume `/faults` призначений лише для локального досліду. `EXECUTION=local` зберігає шлях ЛР1.

Відтворення з кореня, PowerShell:

```powershell
docker compose up -d --wait postgres
docker compose run --rm migrate
Get-Content -Raw experiments/dpc_lr1_seed.sql | docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U app -d app
docker compose build api
$env:TICKET_CHECK_MODE='fixture'; docker compose --profile ray up -d --no-deps ray-head ray-worker
$env:EXECUTION='ray'; docker compose up -d --no-deps --force-recreate api
Get-Content -Raw experiments/dpc_lr1_reset.sql | docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U app -d app
python experiments/test_dpc_ray.py
Get-Content -Raw experiments/dpc_lr1_reset.sql | docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U app -d app
docker compose exec -T api touch /faults/after_effect_before_ack
$env:EXPECT_RETRY='1'; python experiments/test_dpc_ray.py
```

Дочекатися `api.started` перед HTTP тестом. Результати конкретного запуску — `results/dpc-lr3.md`. О3.2 та Д3.x не обрані: `WORKERS` вже обмежує одночасні задачі, але `IN_FLIGHT_LIMIT` окремо ще не реалізовано. У разі аварії самого API in-memory queue ЛР1 не відновлюється, що не є гарантією О3.1.
