# DPC ЛР6: два координатори, 2026-11-23

Середовище: Windows Docker Desktop, etcd 3.7.2, PostgreSQL 17.11, два окремі coordinator контейнери, `LEASE_TTL_S=5` с, API з `EXECUTION=local`. Схема/команди — `docs/contracts/DPC-LR6.md`. Локальні `dpc-test-` резерви **імітують** Web-pre-reserved returned seats; Web LR6 ще не надав реального підтвердження вилучення місць із продажу.

| Дослід | Старий owner/gen | Новий owner/gen | Failover | Старий gen | Незареєстрований gen | Replay |
|---|---|---|---:|---:|---:|---|
| 1 | coordinator-a / 2 | coordinator-b / 4 | 4.031 с | 409 | не перевірявся | — |
| 2 | coordinator-b / 4 | coordinator-a / 6 | **3.828 с** | **409** | **409** | `replayed=true` |
| 3 | coordinator-a / 6 | coordinator-b / 8 | 5.344 с | 409 | 409 | `replayed=true` |
| 4 | coordinator-b / 12 | coordinator-a / 14 | 4.359 с | 409 | 409 | `replayed=true` |

У кожному досліді перший reserve призначений до паузи старим поколінням, другий — після реєстрації нового. Вимірювання починається після завершення команди pause, завершується першим GET `/v1/coordinator` з новими owner/gen. `coordination_history` мав 10 рядків після другого, 15 після третього та 21 після четвертого досліду; жодного accepted assignment старого покоління після register нового. Paused старий координатор після unpause залогував втрату lease і не зробив нових призначень. Резерв та waitlist мають унікальний assignment, а replay не додає history/ефект повторно. Клієнтський `API_TOKEN` отримав 401 на внутрішніх coordinator і Web-reserve маршрутах. У четвертому досліді Web-token прочитав assignment за `web_reserve_id` із `assignment_id`, який Web має використати для ідемпотентного випуску ticket.

Перевірені пункти ядра: **О6.1, О6.2**. Сквозний Web reserve→assignment→ticket issuance поки залежить від роботи учасника Web; тест не доводить справжнє резервування Web. О6.3/Д6.x не заявляються.
