# Lifecycle 3.0

STANDARD / QUICK: `DISCOVERY → SPECIFICATION → ROADMAP → ROADMAP_REVIEW → EXECUTION ↔ VERIFICATION → COMPLETION_REVIEW → COMPLETE`.

Одна рассмотренная цель и план ближайшего инкремента вместо четырёх обязательных reviews. Запрос владельца может быть источником решения: не требуй дополнительную формулу, если границы и проверка ясны. Не отмечай придуманную спецификацию approved. Bootstrap MISSION содержит NEEDS_REVIEW: сначала замени неизвестные реальными данными через mission.py revise, затем утверди roadmap.

FULL / CRITICAL сохраняют concept, архитектурный и roadmap reviews. Между CONCEPT_REVIEW и ARCHITECTURE можно выбрать PROCESS_MODELING, когда бизнес-процесс нужен; BPMN не обязателен. CRITICAL — профиль рискованного пакета, не всех задач проекта навсегда. Legacy 2.1 сохраняет прежние gates до upgrade.

BLOCKED и CHANGE_REVIEW имеют resume_stage. Глобальный BLOCKED — только если остановлен весь текущий путь. Для локального STOP state.py block --scope <action/node> с основанием и resume condition; стадия всего проекта не меняется.

## Запуск

1. Исследуй систему, AGENTS, Git и память; не переписывай готовое решение.
2. init_project.py создаёт 3.0 STANDARD, private MISSION, checkpoint и журнал. Не копирует lifecycle BPMN. Шаблоны архитектуры/требований/рисков — опоры, не обязательная анкета до MVP.
3. recover.py и validate_project.py: структура не заменяет семантику и реальный тест.
4. Короткое Discovery → ближайший полезный результат / критерий / seam → план; один ACTIVE component.

## Завершение и следующий инкремент

finish требует reviews/final-review.md, VERIFIED evidence и реального completion acceptance. COMPLETE не обещает бизнес-успех. Новый increment: COMPLETE → ROADMAP, обновлённая миссия/план по текущему решению, история сохранена, новый контракт утверждён и проверен. OPERATE не завершается из-за одного удачного запуска.

## Upgrade

upgrade.py plan — read-only. apply --mission <private definition> --source <owner instruction> — по поручению. Полная копия памяти и AGENTS остаётся в private/migrations (кроме прежних private backups и locks). Неизвестные STATE поля, active component, approvals и event chain сохранены. Stale approval блокирует upgrade. Старый CURRENT_STATE в backup; новый checkpoint компактен. При прерывании не повторяй вслепую: backup/current STATE, pending-state и MISSION нужно сверить и восстановить согласованно.
