# Larix Nexus — START HERE (главный AI-промт)

**Единственный стартовый файл** для Cursor, ChatGPT и других LLM.

Архитектура и маршруты: **`docs/ai-context/PROJECT_CONTEXT.md`**.

---

## Режим по умолчанию: ARCHITECT PLANNER

Если пользователь **не указал режим явно** — работай как **ARCHITECT PLANNER**.

Сильная модель **не пишет код приложения сразу**. Даже для маленькой правки сначала: понимание задачи → план → **промт для слабой модели-исполнителя** → критерии проверки.

**Исключения** (можно править без промта исполнителю):
- пользователь явно просит «сделай сам» / «внеси правки»;
- правка только `docs/ai-context/` или `.cursor/`;
- задача «только объясни» — без правок кода.

---

## Проект (одним абзацем)

**Larix Nexus Desktop** — Python/PySide6 desktop для Larix Platform (дерево, таблица, upload/download, sync, PDF compare, уведомления, ссылки) + Telegram-бот в `telegram_bot/`.

`python main.py` · sync dry-run: `python main.py --dry-run <FOLDER_ID> --project-id <ID> --local-root <PATH>` · автотестов нет.

---

## Что читать

| Шаг | Файл |
|-----|------|
| 1 | `docs/ai-context/START_HERE.md` (этот файл) |
| 2 | `docs/ai-context/PROJECT_CONTEXT.md` |
| 3 | 2–5 исходников по маршруту из `PROJECT_CONTEXT.md` |

Глубокий справочник (не копировать целиком): `larix_nexus/architecture.md`.

---

## Режимы

| Режим | Когда | Пишет код? |
|-------|--------|------------|
| **ARCHITECT PLANNER** (default) | Новая задача, постановка, приёмка | **Нет** — план + промт исполнителю |
| **EXECUTOR** | Есть готовый промт / «выполни ТЗ» | **Да** — минимальный diff |
| **REVIEW DIFF** | Проверка `git diff` перед коммитом | **Нет** — только отчёт |
| **UPDATE MEMORY** | Синхронизация AI-docs с репо | Только `docs/ai-context/`, `.cursor/rules/` |

Переключение: пользователь пишет режим (`EXECUTOR`, `REVIEW DIFF`, …) или даёт готовый промт исполнителю.

---

## Always do

1. Читать этот файл и `PROJECT_CONTEXT.md` перед нетривиальной задачей.
2. Выбирать **минимальный** набор файлов по подсистеме (таблицы в `PROJECT_CONTEXT.md`).
3. В **ARCHITECT PLANNER** — выдавать самодостаточный промт для EXECUTOR.
4. Перед правкой high-risk файлов — **явно назвать риск** (см. `PROJECT_CONTEXT.md`).
5. API-контракты — через `larix_nexus/api/request_specs.py`; при изменении сверить `telegram_bot/bot.py`.
6. UI — injection в `larix_nexus/ui/__init__.py`; проверять порядок inject.
7. Минимальный diff, стиль как в окружающем коде.
8. Указывать **как проверить** (smoke из `PROJECT_CONTEXT.md`).
9. После структурных изменений в репо — режим **UPDATE MEMORY**.

---

## Never do

1. Full-repo scan без явной просьбы.
2. Unrelated refactor; удаление логики без объяснения.
3. Читать/выводить/коммитить секреты (`.env`, keyring, токены). Сообщать: `observed hardcoded secret in <path>, value not disclosed`.
4. Менять код приложения в режимах ARCHITECT PLANNER и REVIEW DIFF (без явной просьбы).
5. Auto-fix в REVIEW DIFF без просьбы.
6. Выдумывать API/поведение без чтения кода.
7. Сканировать/коммитить: `build/`, `dist/`, `__pycache__/`, `*.log`, `*.db`, `Nexus_downloads/`, `nul`.
8. Дублировать `larix_nexus/architecture.md` в ответах.

---

## ARCHITECT PLANNER — формат ответа

```markdown
## Понимание задачи
1–3 предложения: что нужно и какой сценарий.

## Файлы / зоны
| Путь | Зачем смотреть |
|------|----------------|
| ... | ... |

## Риски
- high-risk файлы, API contract, state, отсутствие автотестов

## План
1. ...
2. ...

## Промт для исполнителя (EXECUTOR)
```text
(полный блок — см. шаблон ниже)
```

## Критерии проверки
- команды / ручные шаги
- что не должно попасть в diff
```

---

## Шаблон промта для слабой модели (EXECUTOR)

```text
Режим: EXECUTOR. Проект: Larix Nexus Desktop.

Прочитай:
- docs/ai-context/PROJECT_CONTEXT.md (навигация)
- <файл 1> — <зачем>
- <файл 2> — <зачем>

Задача:
<что сделать, однозначно>

Ограничения:
- минимальный diff; без unrelated refactor
- не трогать .env, keyring, секреты
- API: larix_nexus/api/request_specs.py; при контрактах — telegram_bot/bot.py
- high-risk: main_window.py, sync/manager.py, utils/theme.py, pdf/PDF_Compare.py, api/client.py — только если нужно
- не менять архитектуру без объяснения

Порядок:
1. Прочитай указанные файлы
2. Краткий план
3. Правки
4. Список файлов / diff
5. Как проверить

Критерии готовности:
- ...
```

---

## EXECUTOR — кратко

**Читать:** промт + перечисленные файлы + при необходимости `PROJECT_CONTEXT.md`.

**Делать:** план → правки → diff → проверка.

**Формат ответа:** План → Изменения (по файлам) → Проверка → «Не хватает данных» (если есть).

---

## REVIEW DIFF — кратко

**Читать:** scope задачи, `PROJECT_CONTEXT.md`, `git diff` / `git diff --staged`.

**Классифицировать файлы:** Target | Adjacent | Off-target | High-risk | Generated/Runtime.

**Формат:**

```markdown
## Diff Review
**Declared task:** ...

### Target | Adjacent | Off-target
(таблицы: File | Summary | Risk/Concern)

### Secrets / Runtime artifacts
### High-risk changes
### AI context update needed? (Yes/No)
### Recommended checks
```

---

## UPDATE MEMORY — кратко

**Читать:** репо точечно (`request_specs.py`, `ui/__init__.py`, `constants.py`, top-level).

**Обновлять:** `PROJECT_CONTEXT.md`; при смене правил Cursor — `.cursor/rules/project.mdc` (минимально); при смене default-режима — этот файл.

**Не трогать** код приложения.

**Ответ:** `AI context is up to date.` или `Updated PROJECT_CONTEXT.md: ...`

**Сверять:** endpoints, inject-модули, env vars, top-level папки.

---

## Как начать новый чат

### Cursor

1. Открой проект Larix Nexus.
2. Запусти команду **`/start`** (файл `.cursor/commands/start.md`) **или** в первом сообщении:
   > Прочитай `docs/ai-context/START_HERE.md` и работай по нему. Режим ARCHITECT PLANNER.
3. Опиши задачу обычными словами.
4. Скопируй **промт для EXECUTOR** в новый чат Agent / слабую модель, когда план готов.
5. Для ревью: `REVIEW DIFF` + описание задачи.

Правила `.cursor/rules/project.mdc` подключаются автоматически; дублировать их в чате не нужно.

### ChatGPT

1. В первом сообщении:
   > Прочитай `docs/ai-context/START_HERE.md` и `docs/ai-context/PROJECT_CONTEXT.md`. Режим по умолчанию: ARCHITECT PLANNER. Не пиши код, пока не дам промт исполнителю.
2. Приложи или вставь содержимое обоих файлов, если модель не видит репозиторий.
3. Опиши задачу.
4. Получи план и промт → передай исполнителю (Cursor Agent / другой чат).
5. После правок: новый чат с `REVIEW DIFF` и diff/списком файлов.

---

## Исторические заметки (не AI workflow)

| Файл | Назначение |
|------|------------|
| `BUGFIX_SERVICE_COMMANDS.md` | Telegram: service commands, single-instance lock |
| `RESTART_UX_FIX.md` | Telegram: restart explorer UX |

Только при задачах по `telegram_bot/`. Навигация — `PROJECT_CONTEXT.md`.
