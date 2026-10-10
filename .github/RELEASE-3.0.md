## Project Master 3.0

От небольшого полезного MVP к полноценному продукту — с памятью цели и личного опыта.

- Goal-first recovery после сжатия контекста.
- BUILD/OPERATE: рабочая версия или измеримый повторяющийся результат.
- STANDARD с первого дня, optional BPMN, короткий цикл MVP → реальный тест → feedback → следующий increment.
- Персональная экспертиза, уроки и результаты остаются у владельца; публикуется только механизм.
- Редактируемые drawio карты взаимодействий skills/компонентов с data handoffs и scoped STOP.
- Разработка возможностей отдельно от разрешения на конкретные внешние действия.
- Compact change control, progress-aware hashes, lock/stale-writer и interrupted-transaction recovery.
- Явная миграция 2.1 → 3.0 с полной резервной копией, сохранением истории и решений.

### Обновление

Обновите общий skill, затем отдельно выполните `upgrade.py plan` и разрешённую миграцию каждого проекта с рассмотренным private mission definition. Обновление общего пакета не запускает рекламу, paid API, импорт личной базы или публикацию сайта. В открытых чатах явно перечитайте новый SKILL.md и выполните recovery.

### Проверка

Release workflow выполняет acceptance/regression tests, Python compilation и strict validation карты до публикации. Structural PASS не подменяет runtime или бизнес-приёмку.

### Лицензия

Бесплатный open-source продукт, MIT. Автор: **Andrey Sovetov / Андрей Советов**. Copyright notice и текст лицензии сохраняются при распространении. Личная память пользователей не входит в публичный пакет.
