# Execution loop

Для каждого component соблюдай `RECOVER → LOAD CONTRACT → UNDERSTAND → IMPLEMENT → TEST → VERIFY → REVIEW → PERSIST → ADVANCE`.

Перед production-изменением прочитай STATE, CURRENT_STATE, active phase PLAN/CONTEXT, active component, только referenced requirements/processes/ADRs и `git status` при наличии Git. Не загружай архив без необходимости.

Работай только в пределах component contract и делай минимально достаточные изменения. Новая полезная функция вне approved scope — не бонус: классифицируй её через Change Control. Не меняй публичные интерфейсы, данные или процессы без отражения в requirements/BPMN/architecture.

После реализации запусти релевантные tests/typecheck/lint/build. Переведи component в VERIFYING, сохрани evidence, проведи review против acceptance criteria, requirements и BPMN. Только после этого сделай COMPLETE, обнови TRACEABILITY, BUILD_LOG, CURRENT_STATE и STATE.

BUILD_LOG append-only: timestamp, phase, component, значимое action/result, verification, ADR/requirement/process refs и commit hash при наличии. Не логируй каждую команду.

## Three-Strike Protocol

После первой однотипной ошибки диагностируй причину; после второй пересмотри assumptions и approach; после третьей прекрати повтор. Зафиксируй attempted approach, symptoms/evidence, excluded causes, questionable assumptions и alternatives, затем поставь blocker или выбери существенно иной подход.

Git — evidence, не memory. `manual`: не предлагать автоматически; `ask`: после успешного checkpoint предложить commit; `auto`: commit допустим только в согласованных границах. Push никогда не автоматический.
