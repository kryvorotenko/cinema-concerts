# DPC ЛР2: інтеграл потоку входу

Модель C01: `λ(t)=A·t·exp(-t/τ)`, `A=120` проходів/хв², `τ=30` хв, `0≤t≤T=90` хв. Інтеграл `a..b` означає очікувану кількість проходів між хвилинами `a` і `b` від відкриття входу. Еталон: `F(t)=-A·τ·(t+τ)·exp(-t/τ)`, `F(b)-F(a)`. Абсолютний допуск експерименту — 0.02 проходу.

`POST /v1/compute` вимагає Bearer `API_TOKEN`. JSON: `{ "a":0, "b":90, "n":5000000, "workers":4, "method":"midpoint", "order":2, "chunks_per_worker":4 }`. `a,b` — скінченні числа з `0≤a<b≤90`; `1≤n≤20000000`; `1≤workers≤4`; `1≤chunks_per_worker≤16`, `n≥workers·chunks_per_worker`. Підтримуються лише `midpoint/order=2` і `simpson/order=4`. Неправильний запит — 400 Problem JSON; без токена — 401. Відповідь: `value`, `reference`, `error=abs(value-reference)`, `time_s`, `workers`, `method`, `order`, `n`, `chunks_per_worker`.

Кожен індекс `i∈[0,n)` означає підінтервал `[a+i·h,a+(i+1)·h]`, `h=(b-a)/n`. Межі частин — `floor(n·j/parts)` і `floor(n·(j+1)/parts)`; суміжні частини без пропусків і перетину. Окремий процес обчислює локальну суму через `math.fsum`; головний процес об'єднує тільки `workers·chunks_per_worker` чисел. Послідовна частина: валідація, створення пулу, передавання малих аргументів/результатів, редукція й закриття пулу. `time_s` вимірює створення пулу, dispatch, роботу, редукцію та shutdown, без HTTP/JSON часу. API виносить блокуючий шлях у thread; CPU цикл виконується процесами.

## Відтворення

```powershell
docker compose build api
python experiments/test_dpc_compute.py
docker compose run --rm --no-deps -v ${PWD}/experiments:/experiments api python /experiments/benchmark_dpc_compute.py 5000000
docker compose up -d --no-deps api
python experiments/test_dpc_compute_api.py
```

Перший скрипт показує незахищену гонку в `multiprocessing.Value` і порівнює її з lock та локальною редукцією на 4 процесах. `Barrier` змушує всі процеси прочитати старе значення до запису, тому lost update відтворюється детерміновано. Benchmark робить три повтори для 1/2/4 процесів за однакових `a,b,n,method,order`, друкує медіану, розкид `max-min`, `Sp=T1/Tp`, `Ep=Sp/p`, профіль одного 4-процесного запуску та повтор без профайлера після зміни **лише** `chunks_per_worker` з 4 на 1. Для ізольованого CPU досліду БД і Kafka не потрібні. Основний API використовує спільний startup, але compute не читає БД.
