# Lifecycle и команды

Project Master хранит машинное состояние в `.project-master/STATE.yaml`. Разрешённый основной путь:

`NEW → DISCOVERY → SPECIFICATION → CONCEPT_REVIEW → PROCESS_MODELING → ARCHITECTURE → ARCHITECTURE_REVIEW → ROADMAP → ROADMAP_REVIEW → EXECUTION ↔ VERIFICATION → COMPLETION_REVIEW → COMPLETE`.

`BLOCKED` и `CHANGE_REVIEW` — контролируемые боковые состояния с `resume_stage`; возвращаться можно только через `state.py resolve`. Нельзя перескакивать gates.

## Bootstrap

1. Определи корень проекта и проверь существующие `.project-master/`, `AGENTS.md`, Git и Spec Kit.
2. Выполни `init_project.py --root ...`. Без `--force` скрипт не перезаписывает память.
3. Проверь `validate_project.py`; INITIAL warnings допустимы, ERROR — нет.
4. Перейди к Discovery. `start <idea>` сохраняет идею в `VISION.md`, но не превращает гипотезы в approved facts.

Если schema/project_master version старая, не мигрируй молча. Выполни `init_project.py --upgrade-plan`, зафиксируй план миграции и запроси approval перед преобразованием состояния.

## Gates

- `CONCEPT_REVIEW`: представить цель, пользователей, сценарии, in/out scope, требования, ограничения, риски и вопросы; затем зафиксировать concept approval.
- Ключевые процессы: REVIEW → APPROVED и `approvals.processes=true`.
- `ARCHITECTURE_REVIEW`: показать компоненты, технологии, ADR, альтернативы, trade-offs и риски.
- `ROADMAP_REVIEW`: показать фазы, компоненты, результаты, critical path, зависимости и риски.
- `COMPLETION_REVIEW`: только после полного аудита; COMPLETE — только после явного completion approval.

Не спрашивай повторно неизменившийся approval. Источник и момент approval сохраняй в `approval_records`.

## Командная семантика

- `status` только читает и кратко сообщает состояние.
- `next` выполняет следующий разрешённый шаг либо называет конкретный gate/blocker.
- `finish` не завершает напрямую; создаёт/обновляет `reviews/final-review.md` и переводит в COMPLETION_REVIEW.
- Любая неизвестная команда трактуется как пользовательское намерение, но не как разрешение обойти lifecycle.
