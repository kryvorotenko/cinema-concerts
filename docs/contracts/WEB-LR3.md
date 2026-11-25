# Web ЛР3: вхід і доступ

Стан на 2026-11-26. Виконавець — учасник 1. Побудовано на ЛР1 і ЛР2 ([WEB-LR1.md](WEB-LR1.md), [WEB-LR2.md](WEB-LR2.md));
результати запусків — [results/web-lr3.md](../../results/web-lr3.md), маршрути — [web/openapi.yaml](../../web/openapi.yaml).

## Що зроблено (пункти методички)

| Пункт | Реалізація | Перевірка |
|---|---|---|
| О3.1 вхід і сесія | `POST /v1/auth/login`, `POST /v1/auth/logout`, `GET /v1/me`; `web/server/app/auth.py`, `sessions.py`, `passwords.py`; міграція `022_web_sessions.sql` | `experiments/test_web_lr3.py` |
| О3.2 власник лише з сесії | заголовок `X-User-Id` видалено; `user_id` береться з сесії, чуже й неіснуюче утримання дають однаковий 404 | той самий скрипт |
| О3.3 зміна власного об'єкта (обрано) | `PATCH /v1/holds/{id}`: лише `holder_name`, лише власник | той самий скрипт |
| О3.4 дія персоналу (обрано) | `POST /v1/categories/{id}/close-sales` і `open-sales`, роль `staff` | той самий скрипт |

Д-пункти ЛР3 не обрано.

## Вхід і сесія

- Поле `login` — e-mail, регістр не важливий. Пароль зберігається як `scrypt$16384$8$1$<сіль>$<хеш>` (стандартна
  бібліотека). Для невідомого логіну перевіряється фіктивний хеш, тому час і відповідь не відрізняються від хибного
  пароля: завжди 401 `invalid-credentials`.
- Токен сесії — 32 випадкові байти (`secrets.token_urlsafe`), у cookie `session`: `HttpOnly`, `SameSite=Lax`,
  `Path=/`, `Max-Age=3600`, `Secure` вмикається змінною `COOKIE_SECURE=on` (на HTTP-стенді вимкнено).
- У таблиці `sessions` лежить лише SHA-256 токена, тому витік бази не дає чинних сесій. Сесія спільна для `app-a` і
  `app-b`; термін абсолютний (без подовження), прострочені рядки видаляє фонове завдання.
- Вихід видаляє рядок: старий cookie перестає діяти на обох екземплярах.
- Відповіді входу мають `Cache-Control: no-store`.

## Доступ

| Ситуація | Відповідь |
|---|---|
| Немає cookie, токен невідомий або прострочений | 401 `unauthenticated` |
| Чуже або неіснуюче утримання | 404 (однакове тіло, нічого не видно про чужий об'єкт) |
| `close-sales` / `open-sales` від звичайного користувача | 403 `forbidden`, навіть якщо категорії немає |
| `staff` і невідома категорія | 404 |
| `PATCH` із зайвими полями (`user_id`, `status`, `version`) | 422 |
| `PATCH` для утримання у стані expired / cancelled / refunded | 409 `hold-not-editable` |

Закриття продажу не скасовує наявні утримання: нові `POST /v1/holds` у цій категорії отримують 409 `sales-closed`.

## Міжсайтовий запит (CSRF)

Cookie з `SameSite=Lax` не захищає, коли клієнт і зловмисна сторінка відкриті на різних портах `localhost`: це один
«сайт». Тому змінюючі запити (POST, PATCH і інші небезпечні методи) проходять лише якщо виконано одну з умов:

1. `Sec-Fetch-Site: same-origin`;
2. `Origin` дорівнює `CLIENT_ORIGIN` (типово `http://localhost:8081`);
3. немає ні `Origin`, ні `Sec-Fetch-Site` (не браузер, наприклад скрипт перевірок або сервісний виклик).

Інакше — 403 `csrf-rejected` до будь-якої дії. CORS дозволяє лише точний origin клієнта з `credentials`, методи
GET, POST, PATCH, OPTIONS і заголовки `Content-Type`, `Idempotency-Key`, `If-Match`, `X-Request-ID`.

| Варіант захисту | Чому не обрано |
|---|---|
| Лише `SameSite=Strict` | не діє між портами того самого хоста й ламає перехід за посиланням |
| Токен у `localStorage` й заголовок `Authorization` | доступний будь-якому скрипту сторінки (XSS), cookie `HttpOnly` — ні |
| Окремий CSRF-токен | додатковий стан у клієнті й базі; перевірка `Origin`/`Sec-Fetch-Site` дає те саме для сучасних браузерів |

## Зміни для інших учасників

- Учасник 2: у `app/auth.py` є `current_user`; платіж бере `user_id` звідти, клієнт надсилає `credentials: "include"`.
- DPC: `GET /v1/tickets/{code}` як і раніше під сервісним Bearer-токеном, ЛР3 його не змінює.

## Демо-облікові записи

| Логін | Пароль | Роль |
|---|---|---|
| alice@example.invalid | alice-pass | user |
| bob@example.invalid | bob-pass | user |
| staff@example.invalid | staff-pass | staff |
