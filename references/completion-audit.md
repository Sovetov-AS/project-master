# Audit и completion

`audit` — read-only по умолчанию. Ищи:

- REQUIREMENT DRIFT: implementation/roadmap расходятся с REQUIREMENTS.
- PROCESS DRIFT: код, sidecar или архитектура расходятся с `.bpmn`.
- ARCHITECTURE DRIFT: фактические boundaries/interfaces расходятся с ARCHITECTURE/ADR.
- IMPLEMENTATION DRIFT: component contract/evidence расходятся с кодом.
- STATE DRIFT: STATE/CURRENT_STATE/roadmap/component statuses расходятся.

Каждый finding содержит Severity, Evidence, Expected, Actual, Impact, Recommendation. Серьёзные findings не исправлять автоматически.

`finish` разрешён, когда components завершены или явно superseded. Перейди в VERIFICATION, запусти project/BPMN/traceability validators, проверь VISION, REQUIREMENTS, BPMN, ARCHITECTURE, ROADMAP, TRACEABILITY, tests, risks, open questions, docs и deployment readiness. Создай `reviews/final-review.md` с разделами VERIFIED, PARTIALLY VERIFIED, NOT VERIFIED, OUT OF SCOPE.

Представь: что задумано, построено и доказано; остаток, ограничения и technical debt. Затем перейди в COMPLETION_REVIEW. Только явный completion approval и отсутствие blocking ERROR позволяют `state.py transition COMPLETE`.
