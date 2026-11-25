# Web ЛР3: результати перевірок

Дата: 2026-11-26. Це **локальний прогін без Docker Compose**; межі описано в кінці. Контракт і рішення —
[docs/contracts/WEB-LR3.md](../docs/contracts/WEB-LR3.md).

## Середовище

PostgreSQL 16, нова база; міграції `001, 010, 020, 021, 022` застосовано `config/migrate/migrate.sh`. Два процеси
`uvicorn app.main:app` (`app-8001`, `app-8002`), `CLIENT_ORIGIN=http://localhost:8081`, Python 3.13 (образ проєкту
використовує 3.14).

## Результати

| Дослід | Команда | Результат |
|---|---|---|
| О3.1–О3.4 | `python experiments/test_web_lr3.py` | 71 перевірка пройдена: вхід і хибні дані (однакові 401), cookie з потрібними атрибутами, сесія діє на обох екземплярах, вихід її скасовує, прострочена сесія, `X-User-Id` ігнорується, чуже й неіснуюче утримання — однаковий 404, `PATCH` лише для `holder_name`, зайві поля — 422, user → 403 на `close-sales`, staff закриває й відкриває продаж, чужий origin → 403 `csrf-rejected` без ефекту |
| Браузер (Chromium), сторінка зловмисника на `:8082` | сценарій Playwright | `fetch` і HTML-форма з чужого origin заблоковані (403), продаж не закрито; з вимкненим захистом той самий напад закриває продаж |
| Регресія ЛР1 | `python experiments/test_web_lr1.py` | 41 перевірка пройдена |
| Регресія ЛР2 | `python experiments/test_web_lr2.py` | 28 перевірок пройдено |
| Клієнт ЛР2 | `node experiments/test_web_lr2_client.mjs` | 9 перевірок |
| Контракт | `npx @redocly/cli lint --config web/redocly.yaml web/openapi.yaml` | valid |
| Код | `ruff check web/server/app` | чисто |

## Як повторити

```
psql -f experiments/web_lr2_reset.sql
BASES=http://localhost:8001,http://localhost:8002 DATABASE_URL=postgresql://app:app@localhost:5432/app python experiments/test_web_lr3.py
```

Скрипти ЛР1 і ЛР2 тепер входять у систему самі; перед кожним запуском виконуйте `web_lr2_reset.sql`.

## Межі

Прогін у Docker Compose (образ Python 3.14, nginx) і у браузері користувача — окремо; результат дописується нижче.
