# Execution loop

Для каждого component соблюдай `RECOVER → LOAD CONTRACT → UNDERSTAND → IMPLEMENT → TEST → VERIFY → REVIEW → PERSIST → ADVANCE`.

Перед production-изменением прочитай STATE, CURRENT_STATE, active phase PLAN/CONTEXT, active component, только referenced requirements/processes/ADRs и `git status` при наличии Git. Не загружай архив без необходимости.

Работай в пределах текущего component contract и делай минимально достаточные изменения. Новую функцию вне scope классифицируй через Change Control; ясное текущее поручение может уже разрешать конкретное расширение без повторного gate. При смене публичного интерфейса/данных обнови затронутые требования и контракты; выбранную карту — только если она есть. Не требуй BPMN или заполнения всех документов для lean MVP.

После реализации запусти релевантные tests/typecheck/lint/build. Сохрани evidence и проверь acceptance criteria, затронутые требования/контракты и выбранную карту, если есть. Только после проверки complete-component; обнови существенные traceability/log/state. CURRENT_STATE обновляется скриптом автоматически, MISSION — при результате/feedback/решении, не для каждой команды.

BUILD_LOG append-only: timestamp, phase, component, значимое action/result, verification, ADR/requirement/process refs и commit hash при наличии. Не логируй каждую команду.

## Three-Strike Protocol

После первой однотипной ошибки диагностируй причину; после второй пересмотри assumptions и approach; после третьей прекрати повтор. Зафиксируй attempted approach, symptoms/evidence, excluded causes, questionable assumptions и alternatives, затем поставь blocker или выбери существенно иной подход.

Git — evidence, не memory. `manual`: не предлагать автоматически; `ask`: после успешного checkpoint предложить commit; `auto`: commit допустим только в согласованных границах. Push никогда не автоматический.
