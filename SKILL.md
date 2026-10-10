---
name: project-master
description: >-
  Сопровождает проекты, которые ведутся через Project Master: восстанавливает цель и локальную память, планирует проверяемые MVP-инкременты, развивает приложения и агентов от простого к сложному, хранит персональные уроки и измеримые результаты, проверяет взаимодействие компонентов и управляет точечными остановками. Использовать для запуска, продолжения, планирования, реализации, восстановления или аудита такого проекта; не навязывать lifecycle разовой задаче.
metadata:
  version: "3.0"
  short-description: Цель, память и развитие проекта от MVP к продукту
---

# Project Master 3.0

Общий skill — механизм; `<PROJECT_ROOT>/.project-master/` — память проекта. Данные, опыт и профессиональные знания владельца не добавляются в установленный skill или публичный пакет. История чата не заменяет память на диске.

## Вход и восстановление

1. Найди реальный корень: ближайший родитель с .project-master, иначе Git root, иначе cwd. Не создавай вторую память в deployment-проекте, если у него уже есть связь с исходным проектом.
2. status/аудит — чтение, без инициализации или upgrade. start без памяти — bootstrap по [lifecycle.md](references/lifecycle.md). Не навязывай Project Master маленькой разовой задаче.
3. При resume/compaction/handoff прочитай актуальный SKILL.md заново и выполни `python3 <SKILL_ROOT>/scripts/recover.py --root <PROJECT_ROOT>` по [recovery.md](references/recovery.md). Восстанови цель, текущий increment, стратегию, результаты и применимые уроки ДО выбора следующей задачи. Затем только active contract и relevant refs, не весь архив.
4. Память 2.1 поддерживается без молчаливой миграции. Upgrade требует поручения, upgrade.py plan, backup и рассмотренное private mission definition. Для 2.0 сначала migrate.py (→2.1), затем upgrade.py (→3.0).
5. В 3.0 новый проект по умолчанию STANDARD. Правила v3 имеют приоритет над legacy full-lifecycle инструкциями; project-owned ограничения не отменяются автоматически.

## Рабочий принцип

Конечная цель → ближайший полный полезный MVP → реальный тест → feedback → следующий increment. Сохраняй минимальный seam расширения, не строй будущий SaaS заранее. «Для себя → другим пользователям → отдельное приложение» — стратегия, не объём первого дня.

BUILD — рабочая версия продукта. OPERATE — повторяющаяся работа с измеримым результатом, периодом, источником, target и лимитами. Количество задач не бизнес-успех. Нет данных — UNKNOWN, не ноль. Смена цели/режима сохраняет историю и требует решения владельца. Никаких фоновых расписаний без поручения.

Ясное текущее поручение может быть источником approval: запиши источник и действуй в его границах, не проси повторить специальную формулу. Собственная догадка не approval; историческое approval не новая live-write authority.

## Читать только нужный маршрут

| Намерение | Reference |
|---|---|
| запуск / стадии | [lifecycle.md](references/lifecycle.md) |
| resume / status / next | [recovery.md](references/recovery.md) |
| цель / стратегия / метрики / знания / feedback | [goal-memory.md](references/goal-memory.md) |
| профиль | [adaptive-lifecycle.md](references/adaptive-lifecycle.md) |
| handoffs / skills / stops продукта | [interaction-map.md](references/interaction-map.md) |
| бизнес-процесс BPMN, когда нужен | [process-modeling.md](references/process-modeling.md) |
| Discovery / specification | [discovery.md](references/discovery.md), [specification.md](references/specification.md) |
| архитектура / roadmap | [architecture.md](references/architecture.md), [roadmap.md](references/roadmap.md) |
| исполнение / проверка | [execution.md](references/execution.md), [verification.md](references/verification.md) |
| scope change | [change-control.md](references/change-control.md) |
| audit / finish | [completion-audit.md](references/completion-audit.md) |
| экономия / capability | [model-routing.md](references/model-routing.md) |

## Границы по действию, не урезание продукта

- Разделяй возможность продукта, реализацию/локальные тесты и разрешение на живое действие. Нет Ads.write authority — не запрет разрабатывать Ads.write.
- STOP: причина, происхождение OWNER/PROVIDER/TOOL_POLICY/PROJECT_DECISION/HYPOTHESIS, проверяемое основание, конкретная область, владелец решения, условие продолжения. Запрет провайдера требует актуального официального источника/evidence; гипотеза не запрет API. Останови затронутую ветку, продолжай независимую разрешённую работу.
- Действующее ограниченное разрешение не требует повторного подтверждения каждого обычного действия. Новая операция/объект/бюджет/срок/необратимость вне него — отдельное решение. Публикация кода, подключение, импорт базы, платный запрос, запуск продукта — разные действия.
- Один писатель памяти и один ACTIVE component. Параллельные чтения допустимы; делегирование только когда разрешено пользователем/средой. Не запускай несколько чатов-писателей одного корня.
- STATE через state.py, MISSION через mission.py. Не обходи hash/lock/pending transaction ручной правкой. Approval связан с контрактом, не обычным прогрессом или layout диаграммы. Уже stale approval не легализуется upgrade.
- COMPLETE только с evidence, review и реальным owner acceptance. Тесты, runtime acceptance и бизнес-результат — разные уровни.
- Commit/push только в пределах поручения. Личную память не публиковать даже при выпуске общего skill.

## Инструменты

Из каталога установленного skill, с явным --root; перед новой мутацией читай --help.

```bash
python3 scripts/init_project.py --root <PROJECT_ROOT> --idea <IDEA> --profile STANDARD
python3 scripts/recover.py --root <PROJECT_ROOT>
python3 scripts/upgrade.py --root <PROJECT_ROOT> plan
python3 scripts/upgrade.py --root <PROJECT_ROOT> apply --mission <PRIVATE_DEFINITION.json> --source <OWNER_DECISION>
python3 scripts/state.py --root <PROJECT_ROOT> validate
python3 scripts/mission.py --root <PROJECT_ROOT> show
python3 scripts/validate_project.py --root <PROJECT_ROOT>
python3 scripts/workflow.py validate <FILE.drawio> --root <PROJECT_ROOT>
python3 scripts/workflow.py compare <FILE.drawio> --baseline <PREVIOUS.drawio>
```

Русский по умолчанию. Статус: цель, доказанный результат, текущая работа, следующий шаг и конкретный выбор. Вопрос только когда ответ существенно меняет результат, архитектуру, стоимость или риск.
