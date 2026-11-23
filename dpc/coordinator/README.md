# Координатор (ЛР6)

Сервіси `coordinator-a` і `coordinator-b` збираються з цього каталогу. `main.py`
захоплює etcd lease, реєструє create_revision у DPC API й призначає тільки
Web-pre-reserved повернені місця покупцям waitlist. `etcd.py` — тонкий клієнт.
Поточний контракт і дослід: [DPC-LR6.md](../../docs/contracts/DPC-LR6.md).

Команди виконуються з кореня проєкту; повний відтворюваний сценарій
`python experiments/test_dpc_coordination.py` сам ставить поточного лідера
на pause, вимірює failover і повертає контейнер до роботи.
