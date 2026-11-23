# Контракт команди: День 1

Зафіксовано 2026-11-19 за прямим запитом користувача. Це основа для паралельної
розробки; DPC ЛР1/2 додані окремо. Спільний запуск — тільки кореневий
`docker-compose.yml`; одна PostgreSQL, один Kafka KRaft, один `migrate`.
Константи для всіх процесів: [`config/project.env`](../../config/project.env).

## Словник БД

| Назва проєкту | Значення / власник |
|---|---|
| users | Користувачі user/staff, password_hash; Web |
| venues | Майданчик, місто, назва часової зони; Web |
| events | Програма: фільм або концерт, може мати кілька виконань; Web |
| screenings | Конкретний сеанс/концерт у часі й на майданчику; **screenings.id = performance_id** |
| seat_categories | Місткість/залишок/ціна категорії конкретного screening; Web |
| seats | Заготовка конкретних місць (ряд/номер); поки порожня, призначення додається у Web ЛР6 |
| bookings | Утримання з картки (`hold`); user/screening/category/кількість, status, hold_expires_at, version, fencing_token; Web |
| tickets | Один ticket на booking, ticket.id — спільний ticket_id, code — код перевірки Web |
| sectors | Місткість і inside фан-зони конкретного screening; DPC |
| outbox | Стабільні id/type/aggregate/version/payload/time/topic, published_at; Web/DPC записують власні події у транзакції ефекту |
| processed_effects | `(handler,effect_key)` PRIMARY KEY, event_id, збережене decision; DPC admission використовує **ticket_id** як effect_key |

Усі ID — непорожні за контрактом застосунків рядки. БД використовує text;
формат генерації UUID/інших ID узгоджується в API, розширення PostgreSQL не потрібні.
Моменти — timestamptz, гроші — bigint копійки + ISO-код валюти. Дані початково порожні.
booking: held→confirmed/expired/cancelled; confirmed→refunded. HOLD_MINUTES=10.
Додаткові таблиці operations/auth/notifications/scans/assignments/history
додаються новими міграціями власниками відповідних лабораторних.

Початковий SQL захищає типи, зв'язки, залишок 0..capacity, один ticket на booking,
унікальний effect key. **Він не виконує продажі чи погашення**: перевірка + зміна
available/inside + effect/booking мають бути атомарними у майбутньому коді.
Верхня межа sectors.inside контролюється DPC транзакцією; відсутність upper CHECK
дозволяє окремий навчальний unsafe-дослід. Небезпечний режим не для спільних даних.
fencing_token в bookings зарезервовано за запитом команди; справжній fencing
ЛР6 потребує registered generations та історії **ресурсу призначень DPC**.

## DPC чисельний розрахунок

У гілці DPC ЛР2 додано незалежний від БД `POST /v1/compute` для інтеграла
потоку входу C01. Контракт параметрів, A/τ/T, послідовної частини та дослідів:
[DPC-LR2.md](DPC-LR2.md). Він не змінює схему БД чи Kafka.

## Kafka

DPC ЛР1 додала `migrations/002_dpc_scans.sql`, HTTP API та окремий контракт
[DPC-LR1.md](DPC-LR1.md). Web ticket API іще очікує реалізацію учасника 1;
саме він підтвердить формат сервісної відповіді.

| Топік | Константа | Ключ повідомлення | Призначення |
|---|---|---|---|
| domain-events | TOPIC_DOMAIN_EVENTS | aggregate_id | Web ЛР4: hold.created/payment.requested/payment.succeeded/payment.failed/event.rescheduled |
| notifications | TOPIC_NOTIFICATIONS | user_id | Web ЛР5, окрема consumer group кожного gateway |
| ticket-telemetry | TOPIC_TICKET_TELEMETRY, EVENTS_TOPIC | gate | DPC ЛР5: події входу за [JSON Schema](ticket-telemetry.schema.json) |

`ticket-telemetry` — **узгоджене користувачем перейменування топіка `scans`**
з методички. Зміст не змінюється: accepted=true, fixed window 1 minute, key gate.
Не створюємо паралельний топік scans і не публікуємо одну подію в обидва.
Назва топіка не означає перенесення продажів Web до DPC.
Точний envelope domain-events/notifications буде додано при Web ЛР4/5;
для нього вже зафіксовані стабільний id, тип, aggregate/version/time, ключі вище.

Telemetry: event_id/performance_id/ticket_id/gate/sector_id/accepted/event_time;
час UTC `YYYY-MM-DDTHH:mm:ss.sssZ`. Retry зберігає event_id і тіло.
Інша справжня подія — новий event_id. Погашення дедуплікується за ticket_id,
stream delivery — за event_id, це різні ключі й гарантії.

Внутрішній bootstrap **broker:9092**, alias **kafka:9092** веде до того самого брокера.
З хоста **localhost:9094**. Топіки створює broker-init; типово по 3 партиції,
replication factor 1. Для керованого досліду О5.3 до першої ініціалізації
задайте TELEMETRY_PARTITIONS=1 або використайте окремий тестовий топік.
Повтор broker-init безпечний, але **не змінює** partitions існуючого топіка.

## Порти й спільні конфіги

Повний виконуваний список — `docker-compose.yml`; всі його змінні — `.env.example`.

| Сервіс | Хост → контейнер |
|---|---|
| nginx / Web API | 8080 → 80 |
| app-a / app-b | 8001 / 8002 → 8000 |
| gateway-a / gateway-b | 8091 / 8092 → 8000 |
| api / DPC | 8000 → 8000 |
| postgres | 5432 → 5432 |
| broker / Kafka UI | 9094 → 9094 / 8085 → 8080 |
| external-sim | 8090 → 8000 |
| Ray dashboard | 8265 → 8265 |
| Spark master / job / stream / history | 8280 → 8080 / 4040 → 4040 / 4041 → 4041 / 18080 → 18080 |
| etcd | 2379 → 2379 |
| Prometheus Web / DPC | 9090 / 9091 → 9090 |
| Grafana Web / DPC | 3000 / 3001 → 3000 |
| Redis / Keycloak / flags / Jaeger | 6379 / 8180 / 8099 / 16686 → 6379 / 8180 / 8016 / 16686 |
| Клієнти поза Compose | Web 8081, DPC 8083 |

Default-стек: PostgreSQL, migrate, Kafka, broker-init, Kafka UI,
app-a/app-b/app-canary, nginx, gateway-a/b, api. Heavy-профілі:
`async`, `ray`, `spark`, `coordination`, `monitoring`, `extras`.
Каркаси gateway/canary потрібні початковій конфігурації upstream nginx;
це не означає, що Web ЛР5/6 вже виконано.

## Початок роботи учасника

```sh
git pull
cp .env.example .env
docker compose up -d --wait postgres broker
docker compose run --rm migrate
docker compose run --rm broker-init
python experiments/check_foundation.py
```

PowerShell: `Copy-Item .env.example .env`. Загальний запуск оболонок API:
`docker compose up -d --build`. Spark: `docker compose --profile spark up -d --build`;
Ray/координатори/async аналогічно з їхніми профілями. Усі компоненти:
`docker compose --profile '*' up -d --build` (потребує значно більше RAM).
Предметні API DPC ЛР1/2 описані в окремих контрактах; інші API ще TODO.

Правило міграцій: 001 після спільного старту не редагувати, нові номери узгоджувати.
Не запускати окремо колишні web/dpc Compose поверх спільної БД.
Томи старого каркаса автоматично не видаляються й не об'єднуються; для нової
основи використовуються pgdata/kafkadata. Не виконуйте down -v без наміру стерти дані.
