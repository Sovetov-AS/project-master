# Изменения без бюрократии

CORRECTION выполняет принятое требование: малая локальная правка — BUILD_LOG и targeted test, без обязательного CHG. SCOPE_CHANGE меняет цель/контракт: зафиксируй что, зачем, impact, ближайший план, проверку и реальный owner approval.

3.0 QUICK/STANDARD change.py создаёт PROPOSAL + VERIFICATION (FORMAT-3.0); включи scope delta, affected contracts, risk, plan и decision source в proposal. FULL/CRITICAL и legacy 2.1 сохраняют шесть файлов. Старые пакеты не переписываются.

Ясная текущая инструкция может уже разрешать конкретный scope: --authorized-scope --source <точное решение/ссылка> записывает его без повторного CHANGE_REVIEW. Это не разрешает автоматически публиковать, платить, импортировать личные данные или менять продакшен. Если неоднозначность существенно меняет результат — один конкретный вопрос.

Смысловое изменение snapshot требует обновить затронутые approvals с настоящим источником. Обычный progress (Status, completion evidence, checkbox, status cell roadmap) не делает 3.0 plan stale. VISION, REQUIREMENTS и MISSION definition входят в plan; observations/lessons — нет. Произвольный текст не считается автоматически «несмысловым».

Не утверждай всё заново при correction. Не легализуй stale контракт миграцией. Устаревшее project-owned ограничение корректируется явным предметным решением, а не молча общим релизом.
