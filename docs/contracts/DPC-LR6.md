# DPC ЛР6: координатор повернених місць

Web спочатку **резервує повернене конкретне місце поза вільним продажем**, потім надсилає DPC `POST /internal/waitlist/reserves` із окремим `WEB_RESERVE_TOKEN` та `{web_reserve_id,performance_id,seat_id}`. DPC зберігає проєкцію цього резерва, але не продає місце і не випускає квиток. Покупець входить до черги через `POST /v1/waitlist` з `{waitlist_id,performance_id,buyer_id}`. Після призначення Web читає `GET /internal/waitlist/assignments/{web_reserve_id}` тим самим токеном: до призначення 404, після — `assignment_id`, `buyer_id`, `performance_id`, `seat_id`, `generation`. Web має випустити ticket **один раз за assignment_id**. Скасування/повернення reserve, Web endpoint і справжній доказ вилучення місця з продажу ще потребують контракту учасника Web; локальний дослід використовує лише явно створені fixtures.

Два процеси `coordinator-a/b` змагаються за один etcd ключ `/roles/assigner` через compare-and-put `CREATE=0` із lease `LEASE_TTL_S=5` секунд. Лідер renew-ить lease приблизно кожні TTL/3 і звіряє ключ. `generation` — **create_revision ключа etcd**, а не час. Новий лідер реєструє його у PostgreSQL через `POST /internal/coordinator/register` з окремим `COORDINATOR_TOKEN`. API приймає лише покоління більше поточного; повтор тієї самої реєстрації ідемпотентний.

Лідер читає першу пару ready reserve/waiting buyer для тієї самої performance і викликає `POST /internal/coordinator/assign`. У **одній транзакції** API блокує рядок `coordination_state`, перевіряє рівність поточних owner/generation, блокує reserve і waitlist, записує assignment, змінює обидва статуси та додає history. Стара або незареєстрована генерація отримує 409, rejected history записується в тій самій транзакції. `assignment_id=assignment:<web_reserve_id>` є стабільним ключем для майбутнього Web ticket. Повтор того самого assignment повертає `replayed=true` без нового ефекту. `GET /v1/coordinator` показує зареєстрованого owner/generation; `GET /v1/history` — послідовність register/assigned/rejected. Обидва вимагають клієнтський Bearer `API_TOKEN`.

Міграція `012_dpc_waitlist.sql` додає `coordination_state`, `waitlist_entries`, `returned_reserves`, `waitlist_assignments`, `coordination_history`. Вона не змінює Web tables `bookings`/`seats`/`tickets`. `GET /v1/coordinator` показує останнє зареєстроване покоління: у короткому проміжку між expiry старої lease і реєстрацією нового лідера показаний owner може вже не мати активної lease; писати з ним усе одно не можна після реєстрації нового покоління.

## Відтворення

```powershell
docker compose up -d --wait postgres
docker compose run --rm migrate
Get-Content -Raw experiments/dpc_lr1_seed.sql | docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U app -d app
docker compose build api coordinator-a
$env:EXECUTION='local'; docker compose up -d --no-deps --force-recreate api
docker compose --profile coordination up -d --no-deps etcd coordinator-a coordinator-b
python experiments/test_dpc_coordination.py
```

Скрипт створює власні `dpc-test-` покупців і імітує **вже виконані Web резерви** через внутрішній контракт. Він чекає першого призначення, ставить поточного лідера на pause, вимірює час **від завершення `docker compose pause` до першого GET, який бачить новий owner і зареєстроване покоління**, перевіряє друге призначення, stale/unregistered 409, replay, history та повертає paused контейнер до роботи у `finally`. Це тест однієї машини/двох контейнерів; machine-level failover (Д6.4) не заявляється. О6.3 та інші Д6.x не обрані.
