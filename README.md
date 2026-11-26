# C01. Кінотеатри й концерти

Спільний проєкт для курсів «Обмін даними у Web-застосунках» і «Розподілені та паралельні обчислення». DPC ЛР1 реалізована та перевірена на локальних fixtures; інтеграція з майбутнім Web ticket API очікує його реалізації. Інші лабораторні ще не реалізовані.

## Початок роботи

Потрібні Docker із Compose v2.20+ та Python. Команди виконуються з кореня проєкту:

```powershell
git pull
Copy-Item .env.example .env
docker compose config --quiet
docker compose up -d --wait postgres broker
docker compose run --rm migrate
docker compose run --rm broker-init
python experiments/check_foundation.py
```

Запуск оболонок Web і DPC: `docker compose up -d --build`. Web API: http://localhost:8080; DPC API: http://localhost:8000. Це каркаси зі службовими маршрутами. PostgreSQL — `localhost:5432` (локальні база/користувач/пароль: `app`), Kafka — `localhost:9094`, Kafka UI — http://localhost:8085.

Додаткові компоненти запускаються профілями `async`, `ray`, `spark`, `coordination`, `monitoring`, `extras`, наприклад `docker compose --profile spark up -d --build`. Для всіх профілів потрібен значний запас оперативної пам'яті. Зупинка без видалення даних: `docker compose --profile '*' down`.

Клієнти запускаються окремо: `python -m http.server 8081 --bind 127.0.0.1 --directory web/client` і `python -m http.server 8083 --bind 127.0.0.1 --directory dpc/client`.

## Структура

| Шлях | Призначення |
|---|---|
| `docker-compose.yml` | Єдиний запуск, порти, спільні PostgreSQL і Kafka |
| `.env.example`, `config/project.env` | Параметри й спільні константи |
| `migrations/001_shared_foundation.sql`, `010_dpc_scans.sql` | Спільна схема та життєвий цикл DPC scans |
| `web/`, `dpc/` | Компоненти відповідних курсів |
| `experiments/`, `results/` | Сценарії перевірки й майбутні результати |
| `docs/contracts/` | Контракт команди: таблиці, топіки, порти й запуск |
| `docs/knowledge/`, `AGENTS.md` | Збережені вимоги методичок і розподіл роботи |

## Web ЛР1

Каталог і утримання місць: `GET /v1/events` (виконання; `id` = `performance_id`), `GET /v1/events/{id}/categories`, `POST /v1/holds` (201 + Location, одна транзакція, 10 хвилин), `GET /v1/holds` (курсор), `GET /v1/holds/{id}`; для DPC — `GET /v1/tickets/{code}` (код або `ticket_id`) із Bearer `WEB_API_TOKEN`. До ЛР3 користувач задається заголовком `X-User-Id` (`usr-alice`, `usr-bob`, `usr-staff`, міграція `020_web_demo_seed.sql`). Контракт: [web/openapi.yaml](web/openapi.yaml); модель, стани й інваріанти: [docs/contracts/WEB-LR1.md](docs/contracts/WEB-LR1.md); результати й межі перевірки: [results/web-lr1.md](results/web-lr1.md).

```powershell
docker compose up -d --build
Get-Content -Raw experiments/web_lr1_reset.sql | docker compose exec -T postgres psql -X -v ON_ERROR_STOP=1 -U app -d app
python experiments/test_web_lr1.py
Get-Content -Raw experiments/web_dpc_e2e_prepare.sql | docker compose exec -T postgres psql -X -v ON_ERROR_STOP=1 -U app -d app
python experiments/test_web_dpc_e2e.py
npx @redocly/cli lint --config web/redocly.yaml web/openapi.yaml
```

Клієнт: `python -m http.server 8081 --bind 127.0.0.1 --directory web/client`, відкрити http://localhost:8081.

## Web ЛР2

Ідемпотентність і інваріант під конкуренцією: атомарне зменшення залишку, заголовок `Idempotency-Key` для `POST /v1/holds` (повтор повертає збережену відповідь із `Idempotent-Replayed: true`), 409 `request-in-progress`, 503 `overloaded`, точка відмови після commit і клієнтський повтор із тим самим ключем. Міграція `021_web_idempotency.sql`. Контракт і рішення: [docs/contracts/WEB-LR2.md](docs/contracts/WEB-LR2.md); результати: [results/web-lr2.md](results/web-lr2.md).

```powershell
docker compose up -d --build
docker compose restart nginx
Get-Content -Raw experiments/web_lr2_reset.sql | docker compose exec -T postgres psql -X -v ON_ERROR_STOP=1 -U app -d app
python experiments/test_web_lr2.py
node experiments/test_web_lr2_client.mjs
```

## Контракт команди

Деталі: [контракт Дня 1](docs/contracts/README.md) та [інструкція для учасників і агентів](docs/TEAM-WORKFLOW.md). Усі компоненти використовують одну БД та одного брокера. Топіки: `domain-events`, `notifications`, `ticket-telemetry`. Останній є перейменуванням топіка `scans` із методички; зміст подій входу збережено.

`bookings` — утримання Web, `screenings.id` — спільний `performance_id`. Спочатку враховується кількість місць категорії; `seats` підготовлено для конкретних місць у Web ЛР6. DPC перевіряє і погашає `ticket_id` та веде заповненість секторів. Сама схема не реалізує бізнес-операції чи fencing.

Після початку спільної роботи міграцію `001` не змінюємо; нові зміни оформлюємо наступними погодженими міграціями. Команди запуску з README окремих комплектів — довідкові; використовуйте кореневий Compose. Приклади міграцій міської бібліотеки не застосовуються.

Перевірка обмежень схеми та повторної ініціалізації:

```powershell
Get-Content -Raw experiments/foundation_constraints.sql | docker compose exec -T postgres psql -X -v ON_ERROR_STOP=1 -U app -d app
docker compose run --rm migrate
docker compose run --rm broker-init
```

SQL-перевірка відкочує свої тестові дані. Розподіл лабораторних: [TEAM.md](docs/knowledge/TEAM.md); походження каркасів: [UPSTREAM.md](docs/UPSTREAM.md). Вихідні матеріали Andrii Kovtunenko — MIT, оригінальні LICENSE збережено.

## DPC ЛР1

API приймає `POST /v1/scans` із Bearer-токеном, повертає 202 та виконує перевірку білета у пулі `WORKERS`. `GET /v1/scans/{scan_id}` показує `queued`, `processing`, `done`, `rejected` або `failed`; `GET /v1/sector/{sector_id}` показує місткість і кількість усередині. Повна черга повертає 429 з `Retry-After: 1`. Ключ погашення — `ticket_id`, тому інший `scan_id` для вже перевіреного білета повертає збережене рішення.

Типовий `TICKET_CHECK_MODE=web` звертається до `GET /v1/tickets/{code}` Web-сервісу. До появи цього маршруту для локальних тестів можна запустити DPC окремо з `TICKET_CHECK_MODE=fixture`; цей режим читає лише заздалегідь підготовлені білети з БД. Вимоги до відповіді Web та точні команди дослідів: [DPC LR1](docs/contracts/DPC-LR1.md). Режим `RESOURCE_MODE=unprotected` дозволений лише разом із fixture і тільки для `dpc-test-` секторів.
