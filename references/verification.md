# Verification

Код или документ сами по себе не доказывают выполнение. Component COMPLETE допустим только если выполнены acceptance criteria, tests прошли, evidence сохранено, связанные requirements удовлетворены, BPMN flow не нарушен, документация актуальна и state persisted.

## Evidence

Сохраняй в component `Completion evidence` или отдельном файле `reviews/`: timestamp, проверяемое утверждение, команда/метод, результат, релевантный output или artifact path, environment/limitations. Не сохраняй secrets и избыточные логи.

Результаты: `VERIFIED`, `PARTIALLY VERIFIED`, `NOT VERIFIED`. Если тест не запускался или недоступен, нельзя писать PASS — укажи NOT VERIFIED и причину.

`verify` проверяет active component; при отсутствии active component — текущую phase. Сопоставь evidence с каждым acceptance criterion, requirement и релевантным BPMN path, затем обнови TRACEABILITY и `last_verification` через state.py. Непройденная проверка возвращает component в ACTIVE/BLOCKED, а не маскируется.
