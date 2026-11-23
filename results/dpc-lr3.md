# DPC ЛР3: локальний Ray дослід, 2026-11-23

Середовище: Windows Docker Desktop, один Ray head і два Ray worker контейнери, образ Python 3.14/Ray 2.59.0, PostgreSQL 17.11, API з `EXECUTION=ray`, `TICKET_CHECK_MODE=fixture`. Сектор `dpc-test-sector` capacity 2, перед кожним дослідом `inside=0`, fixture ticket 1 valid. Запуск: `docs/contracts/DPC-LR3.md`.

| Дослід | Стан scan | Виклики приємника | Записи ефекту `ticket_id` | `inside` |
|---|---|---:|---:|---:|
| Без fault | done | 1 | 1 | 1 |
| `after_effect_before_ack` | done | **2** | **1** | **1** |
| Новий scan_id того самого ticket_id після звичайного запуску | done, те саме decision | 1 для нового scan | 1 загалом | 1 |

При fault у логах API є `fault.hit` від `(scan_task pid=774)` о 18:27:10 UTC; приємник відповів двічі о 18:27:10 і 18:27:11. SQL контроль для scan fault дав `receiver_calls=2`, один рядок `processed_effects` з `event_id` першого scan. Отже, Ray повторив task після аварії worker, а предметний ефект не подвоївся. Ресурс змінював лише API приємник. Окремий скрипт після reset підтвердив новий `scan_id` з тим самим квитком без нового проходу.

Обмеження: Web ticket endpoint ще не готовий, тому перевірка квитка була read-only fixture; production шлях викликає Web API. Це дослід retry Ray worker, не crash recovery самого API. О3.2/Д3.x не заявляються.

Після відокремлення `RECEIVER_TOKEN` повторено fault-дослід на фінальному коді:
scan `dpc-ray-4f93315e-f49e-48e2-80a9-0a347db7bf08` завершився `done`,
`receiver_calls=2`, `inside=1`; новий scan того самого ticket теж `done` без
зростання `inside`. Спроба виклику `/internal/admission` з клієнтським
`API_TOKEN` отримала 401.
