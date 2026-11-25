# Web ЛР2: результати перевірок

Дата: 2026-11-25. Це **локальний прогін без Docker Compose**; межі описано в кінці. Контракт і рішення —
[docs/contracts/WEB-LR2.md](../docs/contracts/WEB-LR2.md).

## Середовище

PostgreSQL 16 (пакет Ubuntu), нова база; міграції `001, 010, 020, 021` застосовано штатним
`config/migrate/migrate.sh`. Два процеси `uvicorn app.main:app` із `web/server` (`app-8001`, `app-8002`),
`POOL_SIZE=10`, `FAULTS=on`, Python 3.13 (образ проєкту використовує 3.14). Запити йдуть напряму на обидва екземпляри,
не через nginx.

## Результати

| Дослід | Команда | Результат |
|---|---|---|
| О2.2 функціональні перевірки | `python experiments/test_web_lr2.py functional` (із `DATABASE_URL`) | 25 перевірок пройдено (26 з `CHECK_PURGE=1`): немає ключа, порожній, задовгий, із пропуском — 400; повтор — та сама відповідь, `Idempotent-Replayed`, один ефект; інший порядок полів і пробіли — той самий відбиток; інше тіло — 422; ключ іншого користувача незалежний; повтор через другий екземпляр — збережена відповідь; 409 не зберігається |
| О2.2 20 паралельних запитів з одним ключем | той самий скрипт | рівно одне утримання (один `id`), решта — повтор 201 або 409 `request-in-progress` із `Retry-After`; зайнято одне місце |
| О2.2 термін ключа | той самий скрипт (`DATABASE_URL`) | прострочений ключ не повторюється, запит виконується як новий |
| О2.2 очищення | `CHECK_PURGE=1 python experiments/test_web_lr2.py functional` | 1200 прострочених ключів видалено фоновим завданням порціями по 500 протягом 60 с (типовий період завдання) |
| О2.1 300 покупців / 50 місць, два екземпляри | `python experiments/test_web_lr2.py race` | 50×201, 250×409, жодної іншої відповіді, `available = 0`, сума місць створених утримань 50 з 50; близько 5,5 с, повторів немає (також з `POOL_SIZE=3`) |
| О2.1 для порівняння: `INVARIANT_MODE=unprotected` | те саме | 300×201: **продано 300 місць на 50**, у базі 300 утримань, `available = 31` (залишок розійшовся з утриманнями) |
| О2.3 відмова після commit | `touch /faults/after_commit_before_response`, потім `python experiments/test_web_lr2.py fault` | перший запит залишився без відповіді (`RemoteProtocolError`, процес завершився після commit); повтор із тим самим ключем на другому екземплярі — 201 із `Idempotent-Replayed: true`, зайнято одне місце; після перезапуску першого екземпляра повтор дає ту саму відповідь, місце все одно одне |
| О2.4 клієнт | `node experiments/test_web_lr2_client.mjs` | 9 перевірок: той самий ключ і тіло в усіх спробах, не раніше `Retry-After`, 409 `request-in-progress` повторюється, 422 і 409 `not-enough-seats` — ні, межі спроб і часу, результат «невідомий» з ключем, джитер у межах `100·2^(n-1)` |
| Регресія ЛР1 | `python experiments/test_web_lr1.py` (тепер із ключами) | 41 перевірка пройдена |
| Контракт | `npx @redocly/cli lint --config web/redocly.yaml web/openapi.yaml` | valid, без попереджень |
| Код | `ruff check` і `ruff format --check` на модулях Web | чисто |

## Як повторити

Перед кожним повтором `experiments/web_lr2_reset.sql` повертає демоданні до початкового стану й очищає ключі.

```
psql -f experiments/web_lr2_reset.sql
BASES=http://localhost:8001,http://localhost:8002 DATABASE_URL=postgresql://app:app@localhost:5432/app python experiments/test_web_lr2.py
```

Для режиму `fault` спершу створіть файл відмови в спільному каталозі (`docker compose exec app-a touch
/faults/after_commit_before_response`), а перший запит скрипт надішле на `BASES[0]`; Docker піднімає процес знову
(`restart: unless-stopped`), скрипт чекає до 60 с.

## Що не перевірено

- Запуск у Docker Compose (образ `project-web`, nginx, `restart: unless-stopped`) для ЛР2 ще не виконано;
  після отримання результатів тут слід додати окремий розділ.
- Перезапуск процесу після відмови локально зроблено вручну, а не політикою Docker.
- Браузерний клієнт з повтором (`index.html`) у браузері не відкривався: логіку `callIdempotent` перевірено лише
  Node-тестом із підміною `fetch`.
- Python 3.14 (образ проєкту) не перевірявся.
