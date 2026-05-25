# Larix Nexus — Project Context

Устойчивый архитектурный контекст для ИИ. Workflow и режимы — в **`START_HERE.md`**.

Подробный справочник: `larix_nexus/architecture.md`.

## Назначение

Desktop (PySide6) + Telegram-бот: проекты/воркспейсы, дерево и таблица, upload/download, sync local↔cloud, PDF compare, уведомления, публичные ссылки.

## Верхний уровень

| Путь | Назначение | Риск |
|------|------------|------|
| `main.py` | Entrypoint: SSL, logging, Qt, MainWindow | Высокий |
| `larix_nexus/api/` | `client.py` + `request_specs.py` | Высокий |
| `larix_nexus/ui/` | MainWindow + inject-модули | Очень высокий (`main_window.py` ~7000) |
| `larix_nexus/sync/` | engine + manager + state | Очень высокий (`manager.py` ~4770) |
| `larix_nexus/models/` | таблицы файлов, tombstones | Средний |
| `larix_nexus/notifications/` | JSON, legacy migration | Низкий |
| `larix_nexus/pdf/` | PDF_Compare | Высокий (~5120) |
| `larix_nexus/utils/` | paths, settings, keyring, theme | Высокий (`theme.py` ~3175) |
| `telegram_bot/bot.py` | бот, дубли API | Высокий |

## Быстрая навигация

| Задача | Сначала | Потом |
|--------|---------|-------|
| Startup | `main.py` | `constants.py`, `ui/__init__.py` |
| API / auth | `api/client.py` | `request_specs.py`, `utils/keyring.py` |
| UI | `ui/__init__.py` | inject-модуль задачи |
| Sync | `sync/engine.py` | `manager.py`, `state.py`, `ui/sync_handlers.py` |
| Notifications | `notifications/manager.py` | `ui/notification_handlers.py` |
| PDF | `pdf/PDF_Compare.py` | `widgets/ThemeToggle.py` |
| Telegram | `telegram_bot/bot.py` | — |
| Build | `build.bat`, `Larix_Nexus.spec` | `main.py` |
| Config | `constants.py`, `utils/settings.py` | `keyring.py` |

## Типовые маршруты

| Задача | Читать | Менять | Проверка |
|--------|--------|--------|----------|
| Auth | `api/client.py` | client, keyring | `python main.py` |
| Tree / folders | `tree_operations.py`, `request_specs.py` | tree_ops, client | GUI |
| Table | `table_operations.py`, `files_table.py` | table, delegates | GUI |
| Upload / download | upload/download ops | + `api/client.py` | up/down цикл |
| Move API | `request_specs.py`, `client.py` | specs, client | HAR smoke |
| Sync | `engine.py`, `manager.py` | engine/manager/handlers | `--dry-run` |
| Theme | `theme.py`, `style_tokens.py` | theme, tokens | `STYLE_REGRESSION_CHECKLIST.md` |
| PDF | `PDF_Compare.py` | PDF_Compare | обе темы |
| Telegram | `bot.py` | `bot.py` | `python telegram_bot/bot.py` |

## API

- Auth: login → keyring `LarixNexus` (access/refresh/password) → refresh on 401.
- Контракты: **`larix_nexus/api/request_specs.py`** only.
- Upload: multipart `file` + `metadata` `{"files":[{"fileName","documentType"}]}`.
- Move: `PUT /api/document/move` → `[{"documentId","targetFolderId"}]`.
- Версии: `GET /api/versions/list/{fileId}`; download: `?isVersion=true`.
- **`telegram_bot/bot.py`** — дубли upload/API; менять вместе с specs.

## UI

- `main_window.py` — монолит; предпочитать inject-модули.
- `ui/__init__.py` — `inject_*_to_main_window()`; порядок важен.
- Inject: `folder_actions`, `sync_handlers`, `notification_handlers`, `context_menus`, `table_filters`, `download_operations`, `upload_operations`, `theme_operations`, `tree_operations`, `table_operations`, `ui_helpers`, `header_menu`, `column_ops`, `file_ops`, `tree_search`.

## Sync

scan → `compare_and_plan_sync` → mass-delete guard / tombstones → `execute_sync_operations` → `%APPDATA%\LarixNexus\state\*.json`. Failed ops — retry markers; не помечать failed download как synced.

## Env / state

`LARIX_BASE_URL`, `LARIX_DOWNLOAD_DIR`, `DEBUG_API`, `LOG_API_RESPONSES`, `DEBUG_SYNC` — см. `constants.py`.

`%APPDATA%\LarixNexus\` — settings, mappings, sync state, notifications.

## High-risk

| Файл | Почему |
|------|--------|
| `ui/main_window.py` | inject-зависимости |
| `sync/manager.py` | cycle, tombstones, deletion guards |
| `utils/theme.py` | QSS, все темы |
| `pdf/PDF_Compare.py` | отдельное окно |
| `api/client.py` | HTTP, auth, retry |

## Не сканировать

`build/`, `dist/`, `__pycache__/`, `*.log`, `*.db`, `Nexus_downloads/`, `nul`, `icon/` (кроме иконок), локальные PDF/docx, `telegram_bot/*.log`, `*.db`.

## Справочники

| Файл | Когда |
|------|--------|
| `larix_nexus/architecture.md` | глубокий разбор |
| `STYLE_REGRESSION_CHECKLIST.md` | после темы/QSS |
| `BUGFIX_SERVICE_COMMANDS.md` | бот: service commands |
| `RESTART_UX_FIX.md` | бот: restart UX |

## Open questions

Нет формальных `requirements.txt` и автотестов; runtime-артефакты частично в git; SSL/QMessageBox workarounds Win+Py3.13.

**UPDATE MEMORY:** сверять endpoints ↔ `request_specs.py`, inject ↔ `ui/__init__.py`, env ↔ `constants.py`.
