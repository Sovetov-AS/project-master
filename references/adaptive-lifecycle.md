# Adaptive Lifecycle

Выбирай строгость по риску работы, а не по желанию сэкономить шаги.

| Profile | Когда применять | Обязательная защита |
|---|---|---|
| `QUICK` | Локальная correction в существующем компоненте | Approved unchanged concept/architecture/roadmap, change package, targeted tests |
| `STANDARD` | Ограниченное изменение одного процесса или компонента | Approved baseline, impact/delta analysis, затронутые approvals и regression checks |
| `FULL` | Новый проект, новый subsystem, существенный scope change | Полный lifecycle и все human gates |
| `CRITICAL` | Security, деньги, персональные данные, необратимая миграция, production control | `FULL` плюс независимый review, rollback и усиленное evidence |

Новый проект bootstrap-ится только как `FULL` или `CRITICAL`. `QUICK` и `STANDARD` — ускорение change workflow поверх уже утверждённого baseline, а не способ пропустить проектирование нового продукта.

Перед выбором `QUICK` или `STANDARD` проверь hash-bound approvals. Если concept, architecture или roadmap изменились либо их hashes отсутствуют, переключись на `FULL` и восстанови gates.

Повышай профиль при расширении scope, затрагивании нескольких bounded contexts, смене внешнего контракта, миграции данных, новом permission boundary, повторной неудаче verification или конфликте источников истины. Понижай профиль только после сохранённого обоснования в STATE/event log.
