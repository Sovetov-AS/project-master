# Change Control

Новая инструкция пользователя приоритетна, но изменение approved requirements, scope, BPMN, architecture или roadmap сначала проходит Change Control.

1. Классифицируй: `CORRECTION` реализует существующее требование; `SCOPE_CHANGE` меняет утверждённый проект.
2. Выбери profile: correction обычно `QUICK`, локальный scope change — `STANDARD`, новый subsystem — `FULL`, критичный риск — `CRITICAL`. `QUICK`/`STANDARD` разрешены только поверх approved unchanged baseline.
3. Создай package через `scripts/change.py`. Он создаёт `changes/CHG-XXX-slug/` с `PROPOSAL`, requirements/process deltas, impact, plan и verification.
4. Для correction работай внутри существующего scope и сохрани targeted evidence. Если обнаружилось изменение требования, переклассифицируй в `SCOPE_CHANGE`.
5. `SCOPE_CHANGE` переводится в `CHANGE_REVIEW`; до approval не меняй утверждённые sources of truth.
6. После approval атомарно обнови затронутые sources of truth, traceability и roadmap. Повторно утверди только те области, чьи artifact hashes изменились; затем `state.py resolve` в корректную стадию.
7. При отклонении сохрани решение в package и вернись к `resume_stage` без реализации change.

Не исправляй серьёзный drift автоматически и не используй новый request как молчаливое разрешение на архитектурную миграцию.
