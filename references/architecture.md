# Architecture и ADR

Начинай только после concept и key-process approvals. Сначала исследуй существующий repository, stack, dependencies, APIs, infrastructure/deployment, data model, security/integration/performance constraints, failure handling и observability. Сохраняй существующую архитектуру без доказанной причины менять её.

ARCHITECTURE.md должен фиксировать system context, major components и responsibilities, interfaces, data flow, persistence, integrations, security boundaries, deployment, observability, failure handling, constraints и scaling assumptions. Для статических схем используй Mermaid.

Создавай ADR, если потеря решения способна привести к другой реализации. Формат из `assets/templates/ADR.md`; статусы PROPOSED, ACCEPTED, SUPERSEDED, REJECTED. Укажи alternatives, rationale, consequences и связи с requirements/processes/components. Тривиальные решения ADR не требуют.

Перед `ARCHITECTURE_REVIEW` проверь соответствие approved requirements и BPMN. На gate покажи архитектуру, технологии, компоненты, ключевые решения, альтернативы, trade-offs и риски. Не переходи к roadmap до architecture approval.
