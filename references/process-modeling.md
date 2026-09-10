# Process modeling и sync

BPMN 2.0 XML — source of truth для flow; sidecar Markdown объясняет смысл. Mermaid допустим для статической архитектуры, но не заменяет BPMN.

## Моделирование

Для существенного процесса выясни trigger, actors/pools/lanes, happy path, decisions, exceptions, external systems, end states, human/system tasks, timers, messages и parallel work. Называй task как «глагол + объект», gateway — вопросом, ветки — ответами. Pools обозначают независимых участников, lanes — роли; sequence flow остаётся внутри pool, message flow связывает pools.

Используй L0/L1/L2 и subprocess, если диаграмма перестаёт читаться на одном экране. Файлы: `processes/{as-is,to-be,system}/PROC-XXX-slug.bpmn` и одноимённый `.md`. Статусы: DRAFT, REVIEW, APPROVED, IMPLEMENTED, DEPRECATED. Ключевые процессы требуют approval.

## Команды

- `process list`: составь список из INDEX и фактических пар BPMN/sidecar, покажи расхождения.
- `process <ID>`: прочитай XML, sidecar и связанные requirements/ADR/components; кратко объясни flow и риски.
- `process review <ID>`: запусти `validate_bpmn.py`, проверь семантику, требования, исключения, границы pools и traceability; не меняй файл.
- `process sync <ID>`: сначала выполни `validate_bpmn.py FILE --check-sync SIDECAR`, чтобы определить ручное изменение без перезаписи. Затем сравни flow и IDs с sidecar/requirements/architecture/roadmap. При непротиворечивом изменении обнови только sidecar (включая новый SHA-256), INDEX и TRACEABILITY. При существенном конфликте создай Change Proposal и перейди в CHANGE_REVIEW.

Никогда не перегенерируй весь XML ради косметики. Сохраняй BPMN DI/layout и существующие element IDs. Если нужно изменить flow, вноси минимальный XML patch и повторно валидируй.

Для Camunda Modeler пользователь открывает `.bpmn` как обычный файл, редактирует визуально, сохраняет и вызывает `$project-master process sync PROC-XXX`.
