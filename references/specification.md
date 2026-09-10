# Specification

После Discovery сформируй VISION, CONSTITUTION, REQUIREMENTS, RISKS и OPEN_QUESTIONS из templates. Не дублируй длинные тексты: связывай документы стабильными IDs.

## Требования

Используй префиксы `REQ-F`, `REQ-NF`, `REQ-BR`, `REQ-SEC`, `REQ-INT` и возрастающий трёхзначный номер. ID не переиспользовать после удаления; deprecated requirement оставлять со статусом.

Каждая строка/карточка содержит: ID, Description, Rationale, Source, Priority, Status, Acceptance method, Dependencies, Notes. Требование атомарно и проверяемо насколько разумно. Если прямой тест невозможен, зафиксируй наблюдаемое доказательство или причину ограничения.

Рекомендуемые статусы: `DRAFT`, `REVIEW`, `APPROVED`, `IMPLEMENTED`, `VERIFIED`, `DEPRECATED`. Approval относится к конкретному содержанию; существенное изменение APPROVED requirement запускает Change Control.

## Constitution

Храни только долговечные ограничения, которые нельзя незаметно нарушить: security/privacy, compatibility, data ownership, external permissions, архитектурные запреты и Definition of Done. Не копируй общие правила Codex.

После подготовки переведи в `CONCEPT_REVIEW` через `state.py`, представь компактное резюме и жди явного решения product owner.
