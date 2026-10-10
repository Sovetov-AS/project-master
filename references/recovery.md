# Goal-first recovery

При новой сессии, compaction, handoff или drift:

1. Прочитай актуальный установленный SKILL.md. recover.py --root ... возвращает цель/стратегию, increment, метрики, scoped lessons, stage/next_action, integrity errors. Ничего не записывает.
2. Читай только read_next и relevant refs. git status при наличии Git. Старый narrative — в private backup, не каждом новом контексте.
3. Сопоставь миссию, VISION, active contract и реальную систему. Конфликт не решается угадыванием: найди актуальный источник или спроси, если меняются цель/риск.
4. Полный validate_project.py — при upgrade, изменении контрактов, completion, подозрении на drift. Не перечитывай сотни архивных файлов на каждом ходе. Integrity errors требуют диагностики до записи памяти, но не запрещают независимое разрешённое чтение.
5. Восстанови применимые уроки. Экспертиза и feedback владельца важны; гипотеза агента их не отменяет. Старое approval — не новая live/paid authority.

Статус: цель → доказано → делаем → следующий результат → конкретный необходимый выбор. Если выбор не нужен, продолжай без формального вопроса.

CURRENT_STATE 3.0 — derived checkpoint, не журнал. История остаётся в state-events, BUILD_LOG, MISSION histories и backup. Обновляй MISSION по значимым событиям, не каждой команде.

## Прерванная запись

STATE.lock — активный писатель или след сбоя: проверь PID и отсутствие другого процесса, не удаляй автоматически. pending-state.json — checksummed write-ahead journal. После диагностики state.py repair завершает только сохранённую транзакцию и проверяет обе версии STATE/event chain; не принимает произвольную ручную правку. Конфликт/неполная миграция — целостная backup-копия, не reset event log.

MISSION имеет отдельные lock/revision/checksum. Один писатель на проект. Обновление skill на диске не доказывает, что открытый чат его перечитал: явно прочитай новый SKILL и запусти recovery. Skill не перезапускает приложение Codex.
