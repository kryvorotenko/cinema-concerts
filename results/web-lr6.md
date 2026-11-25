# Web ЛР6: результати перевірок

Дата: 2026-11-26. Це **локальний прогін без Docker Compose**; межі описано в кінці. Контракт і рішення —
[docs/contracts/WEB-LR6.md](../docs/contracts/WEB-LR6.md).

## Середовище

PostgreSQL 16, нова база; міграції `001, 010, 020, 021, 022, 023` застосовано `config/migrate/migrate.sh`, потім
`python -m app.seats_admin backfill`. Два процеси `uvicorn app.main:app` (`app-8001`, `app-8002`), Python 3.13
(образ проєкту використовує 3.14). Запити йдуть напряму на обидва екземпляри.

## Результати

| Дослід | Команда | Результат |
|---|---|---|
| Заповнення й перевірка | `python -m app.seats_admin backfill`, потім `check` | створено 385 місць для 6 категорій, двом наявним утриманням призначено місця; усі 5 перевірок `ok` |
| О6.1 місця, прапорець, конкуренція | `python experiments/test_web_lr6.py` | 39 перевірок пройдено: прапорець off — старий запит працює, відповідь без нових полів, сервер призначає сусідні місця одного ряду, повтор із тим самим ключем дає збережену відповідь, вибір місць 422; прапорець on — схема місць, `places` у відповідях, вибір місць, `seat-taken` без жодних змін, 422 для повторюваних, невідомих, чужої категорії та неправильної форми тіла; 30 паралельних запитів на одне місце через два екземпляри — один 201 і 29 `seat-taken`; 40 паралельних запитів по 2 місця в категорії з 5 місць — 2 успішні; прострочене утримання й скасування звільняють місця (сканер і тригер); повернення прапорця в off |
| О6.3 коректне завершення | `python experiments/test_web_lr6_shutdown.py` | 15 перевірок пройдено: після SIGTERM `/ready` — 503 `draining` із `Retry-After`, `/health` — 200, новий `POST` і `GET` — 503 `shutting-down` (`Connection: close`), процес ще живий; запит, розпочатий до сигналу (пауза 4 с), закінчився 201 і його утримання є в базі; процес зупинився через 3,3 с після сигналу, у журналі `shutdown.draining` і `shutdown.stopping` (`inflight=0`, `timed_out=false`), порт закрито |
| Повернення: код ЛР3 на схемі ЛР6 | сервер із коду ЛР3 (порт 8003) на тій самій базі, прапорець on | старий код створив утримання без місць (`booking_seats` порожня для нього) і сам перевів його в `expired`; тригер звільнив місця, `available` повернувся до 50; `seats_admin check` після цього — усі перевірки `ok` |
| Регресія ЛР1 | `python experiments/test_web_lr1.py` | 41 перевірка пройдена |
| Регресія ЛР2 | `python experiments/test_web_lr2.py` | 28 перевірок пройдено (гонка 300/50 з призначенням місць теж без помилок) |
| Регресія ЛР3 | `python experiments/test_web_lr3.py` | 71 перевірка пройдена |
| Клієнт ЛР2 | `node experiments/test_web_lr2_client.mjs` | 9 перевірок |
| Браузер (Chromium) | сценарій Playwright | вхід, «Обрати місця», вибір двох місць, «Утримати вибрані місця» — 201, місця на схемі стали зайнятими, у таблиці утримань видно «Місця» |
| Контракт | `npx @redocly/cli lint --config web/redocly.yaml web/openapi.yaml` | valid |
| Код | `ruff check web/server/app` | чисто |

## Як повторити

```
docker compose exec app-a python -m app.seats_admin backfill
docker compose exec app-a python -m app.seats_admin check
BASES=http://localhost:8001,http://localhost:8002 DATABASE_URL=postgresql://app:app@localhost:5432/app python experiments/test_web_lr6.py
docker compose run --rm --no-deps -v "${PWD}/experiments:/srv/experiments" app-a python /srv/experiments/test_web_lr6_shutdown.py
```

Тест місць сам скидає демоданні (`web_lr2_reset.sql`) на початку й наприкінці та вмикає й вимикає прапорець
`explicit-seats`; тест завершення піднімає власний процес uvicorn на порту 18010 всередині контейнера.

## Межі

Прогін у Docker Compose (образ Python 3.14, nginx) і у браузері користувача — окремо; результат дописується нижче.
Повернення перевірено локально на коді ЛР3 без Docker; поступове оновлення під навантаженням (О6.4) не виконувалось.
