# Change Control

Новая инструкция пользователя приоритетна, но изменение approved requirements, scope, BPMN, architecture или roadmap сначала проходит Change Control.

1. Классифицируй: `CORRECTION` реализует существующее требование; `SCOPE CHANGE` изменяет сам проект.
2. Для correction обнови component/defect evidence без расширения scope.
3. Для существенного scope change создай `changes/CHG-XXX-slug.md` из template-полей: Problem, Proposed change, Reason, affected requirements/processes/architecture/components, Roadmap impact, Risks, Alternatives, Recommendation.
4. Переведи через `state.py transition CHANGE_REVIEW`, сохрани `resume_stage` и запроси approval product owner.
5. После approval атомарно обнови затронутые sources of truth, approvals для изменившихся артефактов, traceability и roadmap; затем `state.py resolve` в корректную стадию.
6. При отклонении сохрани решение и вернись к `resume_stage` без реализации change.

Не исправляй серьёзный drift автоматически и не используй новый request как молчаливое разрешение на архитектурную миграцию.
