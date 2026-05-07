# Project Architecture Map

## 1. Назначение проекта

**Larix Nexus Desktop** — десктопное приложение (Python/PySide6) для работы с облачной платформой Larix. Основные сценарии:

- Авторизация и управление проектами/воркспейсами через Larix Platform API
- Просмотр дерева папок и файлов проекта (tree + table)
- Загрузка (upload) и скачивание (download) документов
- Двусторонняя синхронизация локальных папок с облаком (compare → plan → execute)
- Сравнение PDF-документов (две версии side-by-side)
- Уведомления о изменениях в папках (JSON storage, legacy SQLite migration)
- Управление публичными ссылками на документы
- Telegram-бот для доступа к платформе из мессенджера

---

## 2. Быстрая навигация

| Задача | Сначала смотреть | Потом смотреть | Комментарий |
|--------|------------------|----------------|-------------|
| Startup / app boot | `main.py` | `larix_nexus/constants.py`, `larix_nexus/ui/__init__.py` | SSL patch → logging → crash diag → Qt app → MainWindow → auto-login |
| Backend / API client | `larix_nexus/api/client.py` | `larix_nexus/api/request_specs.py` | APIClient — все HTTP-операции, auth, cache, retry |
| API contracts / endpoints | `larix_nexus/api/request_specs.py` | `larix_nexus/api/client.py` (`list_documents_in_folder`, `list_files`, upload/download methods) | Пути и payload builders |
| Sync / executor / tool calls | `larix_nexus/sync/engine.py` | `larix_nexus/sync/manager.py`, `larix_nexus/sync/state.py` | compare_and_plan_sync, execute_sync_operations, FolderSyncManager |
| UI / PySide6 | `larix_nexus/ui/__init__.py` | `larix_nexus/ui/main_window.py` | Injection pattern: модули добавляют методы в MainWindow |
| Table / tree / file operations | `larix_nexus/ui/tree_operations.py`, `larix_nexus/ui/table_operations.py` | `larix_nexus/ui/file_ops.py`, `larix_nexus/ui/folder_actions.py` | delegates, context menus, drag-drop |
| Notifications | `larix_nexus/notifications/manager.py` | `larix_nexus/ui/notification_handlers.py` | JSON notifications storage, legacy SQLite migration, subscriptions, pending |
| PDF compare | `larix_nexus/pdf/PDF_Compare.py` | `larix_nexus/widgets/ThemeToggle.py` | PyMuPDF + OpenCV + Pillow, своя тема |
| Telegram bot | `telegram_bot/bot.py` | — | Независимый скрипт, дублирует часть API-логики |
| Tests | Нет автотестов | `main.py --dry-run`, STYLE_REGRESSION_CHECKLIST | Сухой запуск + ручной чеклист стилей |
| Config / env / secrets | `larix_nexus/constants.py`, `larix_nexus/utils/settings.py`, `larix_nexus/utils/keyring.py` | `.gitignore`, `telegram_bot/.env` | ENV: LARIX_BASE_URL, LARIX_DOWNLOAD_DIR, LARIX_ICON_PATH, DEBUG_API |
| Docs / memory | `docs/project-architecture.md` (этот файл) | `larix_nexus/architecture.md` | architecture.md — подробный справочник, этот файл — навигация |
| Build / deploy | `build.bat`, `Larix_Nexus.spec` | `main.py` | PyInstaller, --onefile, --noconsole |

---

## 3. Структура верхнего уровня

| Путь | Назначение | Когда трогать | Риск |
|------|-----------|---------------|------|
| `main.py` | Точка входа: CLI args, logging, Qt app, auto-login | Запуск/отладка/сухой запуск | Высокий — меняется стартовый флоу |
| `larix_nexus/` | Основной пакет приложения | Всегда | — |
| `larix_nexus/api/` | HTTP-клиент и контракты API | API-задачи, auth, endpoints | Высокий — все обращения к серверу |
| `larix_nexus/ui/` | PySide6 UI: MainWindow + inject-модули | UI-задачи, добавление/изменение экранов | Высокий — монолитный main_window.py (~7000 строк) |
| `larix_nexus/sync/` | Синхронизация: engine + manager + state | Sync-задачи, tombstones, deletion guards | Высокий — бизнес-логика синк-цикла |
| `larix_nexus/models/` | FilesTableModel, TombstoneTableModel, IconProvider | Таблица файлов, иконки | Средний — отображение данных |
| `larix_nexus/notifications/` | JSON-хранилище уведомлений, миграция legacy SQLite/QSettings, подписки, pending | Уведомления о папках | Низкий — изолированный модуль |
| `larix_nexus/pdf/` | PDF_Compare window (PyMuPDF + OpenCV) | Сравнение PDF | Средний — независимое окно |
| `larix_nexus/utils/` | Хелперы: paths, settings, keyring, theme, logging, atomic_json, ssl_patch | Инфраструктура, тема, секреты | Средний — используется повсеместно |
| `larix_nexus/widgets/` | ThemeToggle widget | Тема, UI-виджеты | Низкий |
| `larix_nexus/style_tokens.py` | Общие токены стилей (цвета, радиусы, шрифты) | Темизация | Низкий |
| `larix_nexus/app_style_overrides.py` | Пер-апп переопределения стилей | Тёмная тема main/PDF | Низкий |
| `larix_nexus/constants.py` | Глобальные константы, иконки, QSS | Константы UI, env vars | Средний — завязан на paths.py |
| `larix_nexus/architecture.md` | Подробный справочник архитектуры (исторический) | Справка | Не менять — reference doc |
| `telegram_bot/` | Telegram-бот: авторизация, browse, upload | Бот-задачи | Средний — дублирует часть API |
| `icon/` | Иконки и ресурсы приложения | Добавление иконок | Не трогать без необходимости |
| `docs/` | Навигационная документация (этот файл) | Обновление карты проекта | — |
| `BUGFIX_SERVICE_COMMANDS.md` | Исторический баг-фикс (telegram bot) | Справка | Не менять |
| `RESTART_UX_FIX.md` | Исторический баг-фикс (telegram bot UX) | Справка | Не менять |
| `larix_nexus/STYLE_REGRESSION_CHECKLIST.md` | Чеклист ручного регресса стилей | Проверка UI после стилевых правок | — |
| `larix_nexus/widgets/ThemeToggle_README.md` | Документация ThemeToggle widget | Справка по виджету | — |
| `build.bat` | PyInstaller сборка | Релиз | — |
| `Larix_Nexus.spec` | PyInstaller spec | Релиз | — |
| `.gitignore` | Список игнорируемых файлов | Добавление новых артефактов | — |
| `build/`, `dist/` | Сгенерированные PyInstaller артефакты | Не сканировать | — |
| `__pycache__/`, `*.pyc` | Байт-код Python | Не сканировать | — |
| `*.log`, `*.db`, `*.sqlite` | Runtime-логи и БД | Не сканировать | — |
| `Nexus_downloads/` | Скачанные файлы (runtime) | Не сканировать | — |
| `nul` | Пустой файл (артефакт) | Не сканировать | — |

---

## 4. Backend / API

### Ключевые файлы

- **`larix_nexus/api/client.py`** — `APIClient`, единый HTTP-клиент к Larix Platform API. Содержит auth (login/refresh/logout), CRUD (projects, workspaces, folders, documents), upload/download (streaming + multipart), link management, cache (TTL 600s), 401 retry, SSL patching, sanitize/normalize helpers.
- **`larix_nexus/api/request_specs.py`** — Все API-пути как константы и payload builders. Централизованный источник контрактов.

### Auth

1. `login(username, password, remember_me)` → POST `/api/admin/login` → получает token + refreshToken
2. `_load_auth()` → приоритет: refreshToken → password → accessToken (из keyring)
3. `_refresh_access_token()` → POST `/api/auth/refresh`
4. `_handle_401()` → refresh при 401
5. Токены хранятся в system keyring (`LarixNexus` service), ключи: `{username}:access_token`, `{username}:refresh_token`, `{username}:password`

### API Endpoints (контракты)

| Endpoint | Method | Описание |
|----------|--------|----------|
| `/api/admin/login` | POST | Авторизация |
| `/api/auth/refresh` | POST | Обновление токена |
| `/api/project/list` | GET | Список проектов |
| `/api/workspace/list` | GET | Список воркспейсов (несколько fallback путей) |
| `/api/admin/workspace/change` | PUT/POST | Переключение воркспейса |
| `/api/folder/list/{project_id}` | GET | Дерево папок проекта |
| `/api/folder/{folder_id}` | GET | Детали папки |
| `/api/folder/add` | POST | Создание папки |
| `/api/folder/update/{folder_id}` | PUT | Переименование/обновление папки |
| `/api/folder/delete/{folder_id}` | DELETE | Удаление папки |
| `/api/folder/{folder_id}/copy` | POST | Копирование папки |
| `/api/document/types` | GET | Типы документов |
| `/api/document/{document_id}` | GET | Детали документа |
| `/api/document/versions/{document_id}` | GET | Версии документа (legacy) |
| `/api/versions/list/{fileId}` | GET | Список версий файла (по fileId) |
| `/api/document/list/{folder_id}` | GET | Список документов в папке |
| `/api/document/download/{document_id}` | GET | Скачивание документа |
| `/api/document/download/{versionId}?isVersion=true` | GET | Скачивание конкретной версии |
| `/api/document/upload/{folder_id}` | POST | Загрузка документа |
| `/api/document/delete/{document_id}` | DELETE | Удаление документа |
| `/api/document/update/{document_id}` | PUT | Переименование/перемещение документа |
| `/api/link/generate` | POST | Генерация публичной ссылки |
| `/api/link/delete` | POST | Удаление публичной ссылки |

### Upload metadata format

```json
{"files": [{"fileName": "<name>", "documentType": "<id_or_100>"}]}
```

Multipart: `file` (binary) + `metadata` (JSON string).

### Version list / version download API

Список версий файла: `GET /api/versions/list/{fileId}` — возвращает `{"success": true, "data": [...]}`.
Каждая версия: `{versionNumber, versionId, fileName, createdBy, createdTs, shared, status}`.

Скачивание версии: `GET /api/document/download/{versionId}?isVersion=true` — binary response.

Важно: `fileId` используется только для `/api/versions/list/{fileId}`, `versionId` — только для скачивания версии. `version_ids` из `folder/list` — только индикатор наличия версий.

`APIClient.list_file_versions(file_id)` — нормализует ответ к snake_case: `{version_id, version_number, file_name, created_by, created_ts, shared, status, _raw}`.

`APIClient.download_document_version(version_id, filename)` — сохраняет в `%TEMP%\larix_nexus_versions\`, возвращает path или `""`.

### API-дублирование

`telegram_bot/bot.py` содержит собственный `upload_document()` и API-вызовы, независимые от `larix_nexus/api/client.py`. При изменении контрактов обновлять оба места.

### Env variables

- `LARIX_BASE_URL` — базовый URL платформы (default: `https://platform-api.larix.ru`)
- `LARIX_DOWNLOAD_DIR` — каталог загрузок (default: `./Nexus_downloads`)
- `LARIX_ICON_PATH` — путь к иконке приложения
- `DEBUG_API` — bool, детальное логирование API
- `LOG_API_RESPONSES` — bool, логирование тел ответов API

---

## 5. Frontend / UI / PySide6

**UI — это PySide6 desktop, не Electron и не web.**

### Ключевые файлы

- **`larix_nexus/ui/main_window.py`** (~7000 строк) — Главное окно. Определяет `MainWindow(QMainWindow)`, создает `APIClient`, дерево, таблицу, toolbar, статус-бар. **Монолит — самая опасная зона редактирования.**
- **`larix_nexus/ui/__init__.py`** —Injection pattern: каждый UI-модуль содержит `inject_*_to_main_window(MainWindow)`, добавляющий методы/сигналы. Порядок injection важен.

### UI inject-модули

| Модуль | Injection-функция | Ответственность |
|--------|-------------------|----------------|
| `folder_actions.py` | `inject_folder_actions_to_main_window` | Создание, переименование, копирование, удаление папок |
| `sync_handlers.py` | `inject_sync_handlers_to_main_window` | Синхронизация UI: кнопки, прогресс, периодический sync |
| `notification_handlers.py` | `inject_notification_handlers_to_main_window` | Подписки на уведомления, иконки, badges |
| `context_menus.py` | `inject_context_menus_to_main_window` | Контекстные меню дерева и таблицы |
| `table_filters.py` | `inject_table_filters_to_main_window` | Фильтрация и сортировка таблицы |
| `download_operations.py` | `inject_download_operations_to_main_window` | Скачивание файлов |
| `upload_operations.py` | `inject_upload_operations_to_main_window` | Загрузка файлов |
| `theme_operations.py` | `inject_theme_operations_to_main_window` | Переключение темы light/dark |
| `tree_operations.py` | `inject_tree_operations_to_main_window` | Навигация по дереву, раскрытие, refresh |
| `table_operations.py` | `inject_table_operations_to_main_window` | Операции с таблицей: выделение, контекстные действия |
| `ui_helpers.py` | `inject_ui_helpers_to_main_window` | Вспомогательные UI-функции |
| `header_menu.py` | `inject_header_menu_to_main_window` | Меню заголовка таблицы |
| `column_ops.py` | `inject_column_ops_to_main_window` | Управление колонками |
| `file_ops.py` | `inject_file_ops_to_main_window` | Открытие, переименование, свойства файла |
| `tree_search.py` | `inject_tree_search_to_main_window` | Поиск по дереву |

### Дополнительно

- **`larix_nexus/ui/dialogs.py`** — FileDetailsDialog, FolderDetailsDialog, BatchDownloadDialog, SingleDownloadDialog, BatchUploadDialog
- **`larix_nexus/ui/widgets.py`** — ScrollbarProxyStyle, кастомные виджеты
- **`larix_nexus/ui/delegates.py`** — Делегаты для чекбоксов, hover, меню
- **`larix_nexus/ui/drag_drop.py`** — Drag & Drop (между деревом и таблицей)
- **`larix_nexus/ui/dnd_animation.py`** — Анимация DnD
- **`larix_nexus/ui/dnd_validation.py`** — Валидация DnD
- **`larix_nexus/ui/custom_drag_delegate.py`** — Кастомный делегат перетаскивания
- **`larix_nexus/ui/document_type_selection_dialog.py`** — Диалог выбора типа документа

### Модели

- **`larix_nexus/models/files_table.py`** — `FilesTableModel(QAbstractTableModel)`, `IconProvider` — таблица файлов с иконками и чекбоксами
- **`larix_nexus/models/tombstone_table.py`** — `TombstoneTableModel` — таблица удалённых файлов

### Виджеты

- **`larix_nexus/widgets/ThemeToggle.py`** — Анимированный переключатель темы (sun/moon)
- **`larix_nexus/widgets/ThemeToggle_example.py`** — Пример использования ThemeToggle

### Тема/стили

- **`larix_nexus/style_tokens.py`** — Общие токены (цвета, радиусы, шрифты)
- **`larix_nexus/app_style_overrides.py`** — Пер-апп переопределения: main app, PDF compare
- **`larix_nexus/utils/theme.py`** (~3000 строк) — Применение темы, QSS-генерация, патчи QMessageBox/QFileDialog, иконки

### Риски

- `main_window.py` — очень большой монолит (~7000 строк). Изменения каскадно влияют на inject-модули.
- Injection pattern означает, что методы MainWindow не определены в самом классе, а добавляются динамически. IDE не всегда могут их разрешить.

---

## 6. Agent / LLM / RAG / Executor

**Dedicated LLM/RAG subsystem not found.** Синхронизация работает как background executor.

### Sync subsystem

- **`larix_nexus/sync/engine.py`** (~1426 строк) — Ядро синхронизации:
  - `get_local_files(local_root)` — сканирование FS
  - `get_cloud_files(api, project_id, folder_id)` — формирование cloud-списка из API
  - `compare_and_plan_sync(old_state, local, cloud)` — сравнение клиентов, генерация операций (upload/download/delete_local/delete_cloud/skip). Сравнение по `lastModified` с tolerance.
  - `execute_sync_operations(api, project_id, folder_id, local_root, operations, dry_run)` — выполнение операций

- **`larix_nexus/sync/manager.py`** (~4771 строк) — `FolderSyncManager(QObject)`:
  - Периодический таймер (`_sync_interval = 300s`)
  - `_InitialSyncWorker(QThread)` / `_ImmediateSyncRunner(QThread)` — фоновые потоки Qt
  - Tombstones: `_register_tombstone()`, `_load_tombstones()`, `_cleanup_expired_tombstones()`
  - Mass-delete protection: `_max_deletion_percent = 0.20`, hysteresis threshold = 2
  - Регистрация маппингов: `register_sync_mapping(project_id, folder_id, local_root)`
  - Сигналы: `refreshRequested`, `autoSyncStarted`, `autoSyncFinished`, `syncItem`

- **`larix_nexus/sync/state.py`** (~245 строк) — JSON-состояние синхронизации:
  - `%APPDATA%\LarixNexus\state\{project_id}-{folder_id}.json` (per-folder)
  - `%APPDATA%\LarixNexus\sync_state.json` (legacy global)
  - `%APPDATA%\LarixNexus\settings\subscriptions.json`

### Sync flow

1. `FolderSyncManager.sync_all()` → для каждого mapping
2. `sync_files_new(api, project_id, folder_id, local_root)` из engine.py
3. `compare_and_plan_sync()` → список операций
4. Проверка mass-delete protection → tombstones при превышении порога
5. `execute_sync_operations()` → upload/download/delete
6. Сохранение нового snapshot в state

---

## 7. Tools / Contracts / External API

### API Request Contracts (`request_specs.py`)

Все пути и payload builders централизованы в `larix_nexus/api/request_specs.py`. Payload-функции возвращают `dict` или JSON-строку (metadata).

### Telegram Bot API

`telegram_bot/bot.py` — самостоятельный бот на `python-telegram-bot`, содержит собственные:
- `upload_document()` — дублирует часть логики `APIClient.upload_file()`
- Авторизация через Larix API
- Навигация по дереву, загрузка файлов, подписки
- Single-instance lock (`bot.lock`)
- Состояния: `WAITING_FOR_LOGIN`, `WAITING_FOR_PASSWORD`, `SELECTING_WORKSPACE`, `SELECTING_PROJECT`, `IN_EXPLORER`, `AWAITING_UPLOAD`, и т.д.

`telegram_bot/.env` — конфигурация бота (token, API URL). **Значения не раскрываются.**

### PDF Compare Tool

`larix_nexus/pdf/PDF_Compare.py` — отдельное окно на PySide6:
- Зависимости: PyMuPDF (`fitz`), OpenCV (`cv2`), Pillow, numpy
- Режимы: Версия 1 / Версия 2 / Сравнение (diff overlay)
- Поддержка тёмной темы через `ThemeTogglePdfStyle`
- Интеграция: `MainWindow.open_pdf_compare_window(pathA, pathB)` — открывает окно сравнения с двумя PDF
- Типовой сценарий сравнения версий: `list_file_versions(file_id)` → выбор двух версий → `download_document_version(version_id)` × 2 → `open_pdf_compare_window(pathA, pathB)`

### External Services / Libraries

| Библиотека | Назначение | Где используется |
|-----------|------------|-----------------|
| PySide6 | UI framework | `larix_nexus/ui/`, `larix_nexus/pdf/`, `main.py` |
| requests | HTTP-клиент | `larix_nexus/api/client.py` |
| requests_toolbelt | MultipartEncoder | `larix_nexus/api/client.py` (optional) |
| keyring | System keyring | `larix_nexus/utils/keyring.py` |
| PyMuPDF (fitz) | PDF рендеринг | `larix_nexus/pdf/PDF_Compare.py` |
| OpenCV (cv2) | Изображения/Diff | `larix_nexus/pdf/PDF_Compare.py` |
| Pillow | Изображения | `larix_nexus/pdf/PDF_Compare.py` |
| numpy | Массивы | `larix_nexus/pdf/PDF_Compare.py` |
| python-telegram-bot | Telegram бот | `telegram_bot/bot.py` |
| PyInstaller | Сборка EXE | `build.bat`, `Larix_Nexus.spec` |
| sqlite3 | Runtime DB в Telegram bot и legacy notification migration | `telegram_bot/bot.py`, `larix_nexus/notifications/manager.py` |
| matplotlib | Charts в боте | `telegram_bot/bot.py` (optional) |

---

## 8. Tests

### Автоматические тесты

**Автоматические тесты (test_*.py, *_test.py, pytest, unittest) не найдены в репозитории.**

### Smoke / manual checks

| Проверка | Команда |
|----------|---------|
| Запуск приложения | `python main.py` |
| Dry-run sync | `python main.py --dry-run <FOLDER_ID> --project-id <ID> --local-root <PATH>` |
| Telegram bot | `python telegram_bot/bot.py` |
| PDF compare (standalone) | `python -m larix_nexus.pdf.PDF_Compare` (если поддерживает `__main__`) |
| Style regression | Следовать `larix_nexus/STYLE_REGRESSION_CHECKLIST.md` |
| API debug | Установить `DEBUG_API=1` env var |

---

## 9. Config / Environment / Startup

### Entrypoint

- `main.py` → `main()` → SSL patch, logging, crash diagnostics, QApplication, MainWindow, auto-login

### CLI arguments

```
python main.py [--dry-run FOLDER_ID --project-id INT --local-root PATH]
```

### Build

- `build.bat` — PyInstaller: `py -m PyInstaller main.py --onefile --name Larix_Nexus --noconsole --icon icon\logo_transparent_multi.ico --add-data icon;icon`
- `Larix_Nexus.spec` — PyInstaller spec file (hardcoded path to icon)

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LARIX_BASE_URL` | `https://platform-api.larix.ru` | API base URL |
| `LARIX_DOWNLOAD_DIR` | `./Nexus_downloads` | Directory for downloads |
| `LARIX_ICON_PATH` | `rsrc_path("icon", "logo_transparent_multi.ico")` | Application icon |
| `DEBUG_API` | `False` | Detailed API logging |
| `LOG_API_RESPONSES` | `False` | Log API response bodies |
| `LARIX_SAFE_MESSAGEBOX` | `True` on Windows | Use safe messagebox replacement |
| `DEBUG_SYNC` | `False` | Detailed sync logging |

### Settings & state paths

| Path | Purpose |
|------|---------|
| `%APPDATA%\LarixNexus\settings.json` | JSON settings (theme, remember_me, etc.) |
| `%APPDATA%\LarixNexus\sync_mappings.json` | Folder sync mappings |
| `%APPDATA%\LarixNexus\sync_state.json` | Legacy global sync state |
| `%APPDATA%\LarixNexus\state\{pid}-{fid}.json` | Per-folder sync state |
| `%APPDATA%\LarixNexus\settings\subscriptions.json` | Notification subscriptions |
| `%APPDATA%\LarixNexus\larix_nexus.log` | Main log file |
| `%APPDATA%\LarixNexus\_sync_debug.log` | Sync debug log |
| `%APPDATA%\LarixNexus\notifications.json` | Active notifications JSON storage |
| `%APPDATA%\LarixNexus\notifications.db` | Legacy notifications SQLite file, removed/migrated by `notifications/manager.py` |
| System keyring (`LarixNexus` service) | Auth tokens & passwords |

### Keyring

- Service: `LarixNexus`
- Keys: `{username}:access_token`, `{username}:refresh_token`, `{username}:password`

### Telegram bot config

- `telegram_bot/.env` — Bot token and API URL (tracked, **значения не раскрываются**)

### PyInstaller resource handling

- `sys._MEIPASS` for bundled resources
- `larix_nexus/utils/paths.py: rsrc_path()` resolves icon/resource paths correctly in both dev and frozen mode

---

## 10. Cursor / LLM Memory

### Primary navigation file

**`docs/project-architecture.md`** (этот файл) — первая точка входа для LLM. Читать перед любой нетривиальной задачей.

### Existing documentation

| Файл | Назначение | Когда использовать |
|------|-----------|-------------------|
| `docs/project-architecture.md` | Навигационная карта проекта (этот файл) | Перед началом любой задачи |
| `larix_nexus/architecture.md` | Подробный исторический справочник архитектуры | Для глубокого понимания модулей, флоу, контрактов; проверять актуальность по коду |
| `BUGFIX_SERVICE_COMMANDS.md` | Баг-фикс: single-instance lock + service commands в боте | Только при работе с telegram_bot |
| `RESTART_UX_FIX.md` | Баг-фикс: UX перезапуска бота | Только при работе с telegram_bot |
| `larix_nexus/STYLE_REGRESSION_CHECKLIST.md` | Чеклист ручного регресса стилей | После изменений в theme/style_tokens/QSS |
| `larix_nexus/widgets/ThemeToggle_README.md` | Документация ThemeToggle widget | При работе с виджетом темы |

### Cursor integration

Файлы Cursor memory/config:

| Файл | Назначение |
|------|-----------|
| `.cursor/rules/project.mdc` | Общие правила проекта и навигация (alwaysApply) |
| `.cursor/commands/start-task.md` | Команда `/start-task` — старт задачи с навигацией |
| `.cursor/commands/start_task.md` | Алиас `/start_task` — то же содержание |
| `.cursor/commands/update-memory.md` | Команда `/update-memory` — обновление архитектурной карты |
| `.cursor/commands/update_memory.md` | Алиас `/update_memory` — то же содержание |
| `.cursor/commands/review-diff.md` | Команда `/review-diff` — ревью изменений |
| `.cursor/commands/review_diff.md` | Алиас `/review_diff` — то же содержание |

Доступны оба варианта имён: `/start-task` и `/start_task`, `/update-memory` и `/update_memory`, `/review-diff` и `/review_diff`.

---

## 11. Типовые маршруты работы

| Если задача про... | Читать сначала | Обычно менять | Проверять тестами |
|--------------------|----------------|--------------|-------------------|
| Login / auth / API tokens | `larix_nexus/api/client.py` (_save_auth, _load_auth, login) | `api/client.py`, `utils/keyring.py`, `utils/settings.py` | `python main.py`, verify auto-login |
| Project / folder tree | `ui/tree_operations.py`, `api/request_specs.py` (FOLDER_*) | `ui/tree_operations.py`, `api/client.py` (list_folders, list_documents) | GUI: expand tree, check loading |
| File table | `ui/table_operations.py`, `models/files_table.py` | `ui/table_operations.py`, `models/files_table.py`, `ui/delegates.py` | GUI: load folder, check columns/sort |
| Upload / download | `ui/upload_operations.py`, `ui/download_operations.py` | `ui/upload_operations.py`, `ui/download_operations.py`, `api/client.py` (upload_file, download_file, download_document_version) | Upload/download cycle |
| Version list / compare PDF | `ui/main_window.py` (_show_versions_for_node, _show_compare_versions_for_node), `api/client.py` (list_file_versions, download_document_version) | `api/request_specs.py` (VERSIONS_LIST_PATH), `pdf/PDF_Compare.py` | View versions, download version, compare 2 PDF versions |
| Sync conflicts / deletions | `sync/engine.py`, `sync/manager.py`, `sync/state.py` | `sync/engine.py`, `sync/manager.py` | `--dry-run`, check tombstones, mass-delete protection |
| Notifications | `notifications/manager.py`, `ui/notification_handlers.py` | `notifications/manager.py`, `ui/notification_handlers.py` | GUI: subscribe, check badge |
| Theme / style | `utils/theme.py`, `style_tokens.py`, `app_style_overrides.py` | `utils/theme.py`, `style_tokens.py`, constants.py QSS | STYLE_REGRESSION_CHECKLIST |
| PDF compare | `pdf/PDF_Compare.py`, `widgets/ThemeToggle.py` | `pdf/PDF_Compare.py` | Open PDF compare in both themes |
| Telegram bot | `telegram_bot/bot.py` | `telegram_bot/bot.py` | `python telegram_bot/bot.py`, test login + browse |
| Build / package | `build.bat`, `Larix_Nexus.spec` | `build.bat`, `Larix_Nexus.spec` | `build.bat`, check `dist/Larix_Nexus.exe` |
| Docs / memory update | `docs/project-architecture.md` | This file | Re-read this file |

---

## 12. Что не надо сканировать без необходимости

| Путь | Причина |
|------|---------|
| `.git/` | VCS internals |
| `build/`, `dist/` | PyInstaller output |
| `__pycache__/`, `*.pyc`, `*.pyo` | Python bytecode |
| `*.log`, `*.db`, `*.sqlite`, `*.sqlite3` | Runtime logs/databases |
| `Nexus_downloads/` | Downloaded user files |
| `nul`, `*.nul` | Empty artifacts |
| `icon/` | Binary images (only scan if adding icons) |
| Local PDFs, docx, xlsx | User test files |
| `telegram_bot/bot.log` | Bot runtime log |
| `telegram_bot/subscriptions.db` | Bot runtime DB |
| `telegram_bot/notifications.db` | Bot runtime DB |
| `telegram_bot/__pycache__/` | Bytecode |
| `larix_nexus/utils/_sync_debug.log` | Debug log outside AppData (tracked, probably should be gitignored) |

---

## 13. Правила обновления этого файла

1. **Добавление/удаление top-level папок** — обновить раздел 3
2. **Перемещение entrypoints** (например, новый `main.py` или точка входа) — обновить разделы 2, 3, 9
3. **Изменение API контрактов** (endpoints, payloads) — обновить разделы 4, 7
4. **Изменение sync архитектуры** (state file paths, engine logic, manager signals) — обновить разделы 6, 7
5. **Добавление тестов** — обновить раздел 8
6. **Добавление/удаление Cursor memory-файлов** — обновить раздел 10
7. **Формат**: навигационный, concise, не exhaustive tree
8. **Неопределённости** — помечать в разделе 14 как Open questions, не угадывать
9. **Не копировать** большие участки из `larix_nexus/architecture.md` — ссылаться на него

---

## 14. Open questions / unclear areas

1. **requirements.txt / pyproject.toml не найдены.** Зависимости не зафиксированы формально. Нужно создать `requirements.txt` или `pyproject.toml`.
2. **Автоматические тесты отсутствуют.** Нет `tests/` директории, `test_*.py` или `*_test.py` файлов.
3. **Runtime-артефакты в git:** `__pycache__/`, `*.pyc`, `*.log`, `*.db`, `nul`, `larix_nexus/utils/sync/_sync_debug.log` — отслеживаются git. `.gitignore` частично покрывает, но не полностью.
4. **`telegram_bot/.env` отслеживается git.** Файл может содержать секреты. Рекомендация: добавить `.env` в `.gitignore` и использовать `.env.example` с placeholder-ами.
5. **Hardcoded secret обнаружен в Telegram bot source.** Значение не раскрывается. Нужно вынести секрет в env/keyring/secret manager и удалить из истории git при отдельной security-задаче.
6. **`larix_nexus/utils/ui_helpers_backup.py`** — backup-модуль, назначение неясно. Возможно, устаревшая копия `ui_helpers.py`.
7. **Монолитный `main_window.py`** (~6969 строк) — поддерживаемость снижена. Рассмотреть рефакторинг при масштабных UI-изменениях.
8. **Монолитный `sync/manager.py`** (~4771 строк) — аналогично.
9. **Монолитный `utils/theme.py`** (~3175 строк) — аналогично.
10. **Монолитный `pdf/PDF_Compare.py`** (~5122 строк) — аналогично.
11. **Телеграм-бот дублирует API-логику** (`upload_document` и др.) — при изменении контрактов нужно обновлять оба места.
12. **SSL verification глобально отключена** (`ssl.CERT_NONE`, `urllib3` patching) — это workaround для Windows + Python 3.13 crash. В продакшене нужно вернуть верификацию после исправления корневой проблемы.
13. **QMessageBox отключены** — все вызовы заменены на `print()` / `status.showMessage()` как workaround для access violation на Windows + Python 3.13. Нужен план восстановления диалогов.
14. **Telegram bot tracked runtime artifacts** (`bot.log`, `subscriptions.db`, `notifications.db`) лучше добавить в `.gitignore`.

---

## 15. Последние архитектурные изменения

- Добавлен `VERSIONS_LIST_PATH = "/api/versions/list/{file_id}"` в `request_specs.py` и `list_file_versions()` / `download_document_version()` в `APIClient` для работы с версиями файлов по новому API.
- UI: `_show_versions_for_node` и `_show_compare_versions_for_node` переведены на `list_file_versions` + `download_document_version` вместо `get_document_versions` + `download_file`.
- Скачанные версии сохраняются в `%TEMP%\larix_nexus_versions\` (не в git-tracked `Nexus_downloads/`).
- PDF compare cleanup теперь учитывает как `DOWNLOAD_DIR`, так и versions temp dir.
