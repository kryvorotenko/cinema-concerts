# C01. Кінотеатри й концерти

Спільний каркас для курсів «Обмін даними у Web-застосунках» і «Розподілені та паралельні обчислення». Лабораторні роботи ще не реалізовані.

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
| `migrations/001_shared_foundation.sql` | Початкова схема для обох курсів |
| `web/`, `dpc/` | Компоненти відповідних курсів |
| `experiments/`, `results/` | Сценарії перевірки й майбутні результати |
| `docs/contracts/` | Контракт команди: таблиці, топіки, порти й запуск |
| `docs/knowledge/`, `AGENTS.md` | Збережені вимоги методичок і розподіл роботи |

## Контракт команди

Деталі: [контракт Дня 1](docs/contracts/README.md). Усі компоненти використовують одну БД та одного брокера. Топіки: `domain-events`, `notifications`, `ticket-telemetry`. Останній є перейменуванням топіка `scans` із методички; зміст подій входу збережено.

`bookings` — утримання Web, `screenings.id` — спільний `performance_id`. Спочатку враховується кількість місць категорії; `seats` підготовлено для конкретних місць у Web ЛР6. DPC перевіряє і погашає `ticket_id` та веде заповненість секторів. Сама схема не реалізує бізнес-операції чи fencing.

Після початку спільної роботи міграцію `001` не змінюємо; нові зміни оформлюємо наступними погодженими міграціями. Команди запуску з README окремих комплектів — довідкові; використовуйте кореневий Compose. Приклади міграцій міської бібліотеки не застосовуються.

Перевірка обмежень схеми та повторної ініціалізації:

```powershell
Get-Content -Raw experiments/foundation_constraints.sql | docker compose exec -T postgres psql -X -v ON_ERROR_STOP=1 -U app -d app
docker compose run --rm migrate
docker compose run --rm broker-init
```

SQL-перевірка відкочує свої тестові дані. Розподіл лабораторних: [TEAM.md](docs/knowledge/TEAM.md); походження каркасів: [UPSTREAM.md](docs/UPSTREAM.md). Вихідні матеріали Andrii Kovtunenko — MIT, оригінальні LICENSE збережено.
