# Roadmap

После architecture approval декомпозируй `PROJECT → PHASE → COMPONENT`.

Phase имеет самостоятельную цель и проверяемый результат. Component — минимальная разумная единица, которую можно понять, реализовать, протестировать и принять. IDs: `P01`, `P01-C01`. Для каждой фазы создай `phases/PXX-slug/PLAN.md`, `CONTEXT.md` и `components/CXX-slug.md` из templates.

Component contract содержит ID, Name, Status, Purpose, Requirements, Processes, Dependencies, Non-goals, Implementation approach, Expected files, Acceptance criteria, Verification, Risks, Completion evidence и Notes. Статусы: PLANNED, READY, ACTIVE, BLOCKED, VERIFYING, COMPLETE, SUPERSEDED.

Проверь, что каждое requirement покрыто компонентом или явно отнесено out of scope/deferred, зависимости ацикличны либо осознанно разрешены, а acceptance criteria наблюдаемы. Одновременно ACTIVE может быть только один component.

На `ROADMAP_REVIEW` покажи цель/components/result каждой фазы, critical path, dependencies и risks. После approval выбери первый READY component, сделай его единственным ACTIVE через `state.py set-active` и только затем переходи к EXECUTION.
