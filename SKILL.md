---
name: project-master
description: Управляет полным жизненным циклом сложного проекта с репозиторной памятью, human gates, BPMN, roadmap, поэтапной реализацией, recovery, проверкой и change control. Использовать для запуска, продолжения, планирования, реализации или аудита проекта, который ведётся через Project Master.
metadata:
  version: "2.1"
  short-description: Управление сложным проектом от идеи до приёмки
---

# Project Master 2.1

Управляй проектом через `<PROJECT_ROOT>/.project-master/`. История разговора не является памятью. Глобальный skill — движок; никогда не сохраняй в нём состояние конкретного проекта.

## Маршрутизация

1. Найди корень текущего проекта: ближайший родитель с `.project-master/`, иначе ближайший Git root, иначе текущий каталог.
2. Без команды: если `.project-master/STATE.yaml` отсутствует — действуй как `start`; иначе как `resume`.
3. Перед существенной работой запусти recovery по [recovery.md](references/recovery.md). Для новой идеи используй [discovery.md](references/discovery.md), затем [specification.md](references/specification.md).
4. Выбери минимально достаточный lifecycle profile по [adaptive-lifecycle.md](references/adaptive-lifecycle.md). Новый проект начинает с `FULL` или `CRITICAL`; `QUICK` и `STANDARD` допустимы только для изменений поверх неизменившегося approved baseline.
5. Для нетривиальной работы запиши требуемую capability и effort по [model-routing.md](references/model-routing.md). Не закрепляй этапы за конкретными именами моделей.
6. Загружай только reference текущего режима:

| Команда | Действие | Reference |
|---|---|---|
| `init`, `start [idea]` | Безопасный bootstrap, затем Discovery | [lifecycle.md](references/lifecycle.md) |
| `resume`, `status`, `next` | Восстановить контекст и продолжить разрешённое действие | [recovery.md](references/recovery.md) |
| `process ...` | Моделировать, читать, синхронизировать или ревьюить BPMN | [process-modeling.md](references/process-modeling.md) |
| архитектура | Проектировать после concept/process approvals | [architecture.md](references/architecture.md) |
| roadmap | Декомпозировать после architecture approval | [roadmap.md](references/roadmap.md) |
| выполнение | Работать только над одним ACTIVE component | [execution.md](references/execution.md) |
| `change <description>` | Создать change package и классифицировать correction/scope change | [change-control.md](references/change-control.md) |
| `verify` | Проверить component/phase и сохранить evidence | [verification.md](references/verification.md) |
| `audit`, `finish` | Найти drift или провести completion review | [completion-audit.md](references/completion-audit.md) |

## Непереходимые границы

- Не писать production code до approvals concept, ключевых processes, architecture и roadmap.
- Не менять approved scope, requirements, BPMN, architecture или roadmap без Change Control.
- Не иметь более одного ACTIVE component.
- Не объявлять PASS/COMPLETE без сохранённого verification evidence.
- Не считать approval действительным, если hash утверждённых артефактов изменился.
- Не перезаписывать существующий `AGENTS.md`, `.project-master/` или ручные BPMN-изменения.
- Не commit/push автоматически: `git_checkpoint_mode` по умолчанию `ask`; push всегда требует отдельного разрешения.
- Все переходы состояния выполнять через `scripts/state.py`.

## Детерминированные операции

Запускай скрипты из каталога этого skill, передавая явный `--root`:

```bash
python3 scripts/init_project.py --root <PROJECT_ROOT> [--name NAME] [--idea TEXT]
python3 scripts/migrate.py --root <PROJECT_ROOT> plan|apply
python3 scripts/state.py --root <PROJECT_ROOT> show|validate|summary
python3 scripts/change.py --root <PROJECT_ROOT> --title TITLE --description TEXT --kind CORRECTION|SCOPE_CHANGE
python3 scripts/validate_project.py --root <PROJECT_ROOT>
python3 scripts/validate_bpmn.py <FILE.bpmn>
python3 scripts/traceability.py --root <PROJECT_ROOT> validate
```

Для мутаций сначала прочитай help конкретного скрипта. При ошибке validator не обходи gate вручную: устрани несогласованность или зафиксируй change/blocker.

## Общение

Основной язык — русский; filenames и IDs — английские; BPMN labels — русские. Пользователь — product owner. Задавай только вопросы, способные изменить продукт, scope, процесс, риск или критерий готовности. При resume показывай короткий статус в формате из [recovery.md](references/recovery.md); если решение не требуется, продолжай approved component.
