# Architecture и ADR

Сначала исследуй существующую систему. Для STANDARD опиши только важные границы текущего MVP и seams расширения. FULL/CRITICAL требуют concept review, legacy 2.1 — ещё process approval. Не делай API-продукт искусственно read-only из-за отсутствия live authority. Сохраняй существующую архитектуру без доказанной причины менять её.

ARCHITECTURE.md должен фиксировать system context, major components и responsibilities, interfaces, data flow, persistence, integrations, security boundaries, deployment, observability, failure handling, constraints и scaling assumptions. Для статических схем используй Mermaid.

Создавай ADR, если потеря решения способна привести к другой реализации. Формат из `assets/templates/ADR.md`; статусы PROPOSED, ACCEPTED, SUPERSEDED, REJECTED. Укажи alternatives, rationale, consequences и связи с requirements/processes/components. Тривиальные решения ADR не требуют.

ARCHITECTURE_REVIEW в FULL/CRITICAL: соответствие требованиям и выбранной карте, альтернативы, tradeoffs. STANDARD включает существенное архитектурное решение в план без отдельного обязательного gate. Рассуждение об архитектуре не заменяет проверку реального сценария.
