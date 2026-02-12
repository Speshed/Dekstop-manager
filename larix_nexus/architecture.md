# Larix Nexus Desktop - Архитектура проекта

**Версия:** 1.1.4
**Дата формирования:** 2026-02-04
**Изменения:**
- v1.0.1-1.0.5: Платформо-специфичные исправления для Windows + Python 3.13
- v1.1.0: Стабильная версия с полностью отключёнными QMessageBox диалогами для предотвращения access violation
- v1.1.1: Синхронизация по createTime (newest wins) с сохранением createTime при скачивании через ctypes (Windows)
- v1.1.2: Синхронизация только по lastModified (createTime не используется из-за ненадежности при копировании файлов)
- v1.1.3: Исправлено отсутствие lastModified в cloud_files, что вызывало upload всех локальных файлов в облако
- v1.1.4: Усилен SSL patching для предотвращения access violation при многопоточной синхронизации на Windows + Python 3.13

## Критические исправления для Windows + Python 3.13

### Обзор проблем
1. **Access violation при открытии QFileDialog** - eventFilter пытался применить тёмную тему к QFileDialog
2. **Access violation при SSL handshake** - SSL верификация в многопоточной среде Qt вызывала crash
3. **Access violation при отображении QMessageBox** - прямые вызовы QMessageBox из контекстных меню

### Применённые решения
1. **QFileDialog patch** (theme.py:1922, 3017)
   - Добавлена проверка `not isinstance(obj, QtWidgets.QFileDialog)` в eventFilter

2. **SSL patching** (api/client.py:27-121)
   - Патчинг `requests.Session.get_adapter` для модификации PoolManager
   - Установка `cert_reqs=ssl.CERT_NONE` и `assert_hostname=False` в connection_pool_kw

3. **QMessageBox disable** (все ui/*.py файлы)
   - Все вызовы QMessageBox заменены на `print(...)` или `self.status.showMessage(...)`
   - Полное отключение диалоговых окон для предотвращения crash

4. **Keyring encoding fix** (utils/keyring.py:84,86)
   - Замена специальных символов ✓ ✗ на [+] [-] для предотвращения encoding errors

---

## Оглавление

1. [Карта проекта](#карта-проекта)
2. [Точки входа](#точки-входа)
3. [API-клиенты и эндпоинты](#api-клиенты-и-эндпоинты)
4. [Конфигурация, константы и секреты](#конфигурация-константы-и-секреты)
5. [Обработка ошибок, логирование, ретраи, таймауты](#обработка-ошибок-логирование-ретраи-таймауты)
6. [Платформо-специфичные исправления](#платформо-специфичные-исправления)
7. [Основные флоу](#основные-флоу)
8. [Модели данных](#модели-данных)
9. [Тесты и запуск](#тесты-и-запуск)
10. [Описание файлов по модулям](#описание-файлов-по-модулям)

---

## Карта проекта

```
larix_nexus/
├── __init__.py                 # Версия приложения
├── constants.py                # Глобальные константы и пути к иконкам
├── api/
│   ├── __init__.py
│   └── client.py              # HTTP клиент для API платформы
├── models/
│   ├── __init__.py
│   ├── files_table.py         # Модель таблицы файлов с иконками
│   └── tombstone_table.py    # Модель таблицы tombstone (удаления)
├── sync/
│   ├── __init__.py
│   ├── engine.py              # Ядро синхронизации (compare + execute)
│   ├── manager.py            # Менеджер FolderSyncManager, воркеры
│   └── state.py              # Хранилище состояний (JSON)
├── ui/
│   ├── __init__.py
│   ├── main_window.py        # Главное окно приложения
│   ├── dialogs.py            # Диалоги (детали, загрузка, загрузка, batch upload)
│   ├── widgets.py            # Кастомные виджеты (Checkbox, Toggle, etc.)
│   ├── delegates.py          # Делегаты для чекбоксов, hover, меню
│   ├── context_menus.py      # Контекстные меню дерева/таблицы
│   ├── table_filters.py      # Фильтрация таблицы
│   ├── table_operations.py    # Операции с таблицей
│   ├── column_ops.py         # Операции с колонками
│   ├── header_menu.py        # Меню заголовка таблицы
│   ├── tree_operations.py    # Операции с деревом
│   ├── tree_search.py        # Поиск по дереву
│   ├── ui_helpers.py         # UI-хелперы (backup)
│   ├── upload_operations.py  # Загрузка файлов в облако
│   ├── download_operations.py # Скачивание из облака
│   ├── file_ops.py          # Операции с файлами
│   ├── folder_actions.py     # Действия над папками
│   ├── sync_handlers.py      # Обработчики синхронизации
│   ├── notification_handlers.py # Обработчики уведомлений
│   ├── theme_operations.py   # Операции тем (светлая/тёмная)
│   └── drag_drop.py         # Drag & Drop (в т.ч. между деревом и таблицей)
├── utils/
│   ├── __init__.py
│   ├── paths.py             # Пути к ресурсам и папкам приложения
│   ├── settings.py          # JSON-настройки (%APPDATA%/LarixNexus/settings.json)
│   ├── atomic_json.py       # Атомарные операции чтения/записи JSON с блокировками
│   ├── keyring.py           # Хранение секретов через keyring
│   ├── logging.py           # Структурированное логирование (sync_log, StructuredFormatter)
│   ├── copy_logger.py       # Логирование копирования (copy_log) [Не подтверждено]
│   ├── app_logging.py       # Инициализация логов, очистка старых (reset_log_files)
│   ├── crash_diagnostics.py # Crash dumps, faulthandler, sys.excepthook
│   ├── helpers.py           # Хелперы: normalize_id, _set_window_theme_dark, compare_file_states
│   ├── theme.py             # Применение светлой/тёмной темы, load_saved_theme
│   ├── safe_dialogs.py     # Безопасные диалоги (в т.ч. для крит. путей) [Не подтверждено]
│   ├── safe_event_filter.py # Фильтр событий (e.g. для безопасных диалогов) [Не подтверждено]
│   ├── messagebox.py        # Патчи QMessageBox (авторазмер) [Не подтверждено]
│   ├── ui_patches.py        # Патчи Qt (QFileDialog, DirPicker, ComboBox) [Не подтверждено]
│   └── ui_trace.py          # Переколлективный трейс UI-действий (trace) [Не подтверждено]
├── notifications/
│   ├── __init__.py
│   └── manager.py           # Управление уведомлениями (SQLite: notifications.db)
└── pdf/
    ├── __init__.py
    └── PDF_Compare.py       # Окно сравнения двух PDF (версии, diff, экспорт)

main.py                      # Точка входа CLI: argparse (--dry-run), создание QApplication, MainWindow
```

---

## Точки входа

### `main.py`

**Назначение:** Точка входа приложения, настройка логирования, инициализация Qt, автологин.

**Ключевые функции/классы:**
- `main()`:
  - `reset_log_files()` → очистка старых логов перед тяжёлыми импортами
  - `start_logging(log_to_file=True, keep_console=False)` → перенаправление всего логирования в файл
  - `install_crash_diagnostics(app=None)` → faulthandler + sys.excepthook + `ui_trace`
  - argparse: `--dry-run FOLDER_ID`, `--project-id`, `--local-root` → для тестов без GUI
  - `QApplication` + `MainWindow` → создание GUI
  - Автологин: `load_settings()`, `api._load_auth()`, `api.list_projects()`
  - При неудаче — `w.open_login_dialog()`

**Входные данные:**
- CLI аргументы: `--dry-run`, `--project-id`, `--local-root`
- Секреты: keyring (access_token, refresh_token, password)
- Настройки: JSON-файл (`%APPDATA%/LarixNexus/settings.json`)

**Выходные данные:**
- Код выхода: `0` (успех), `1` (ошибка)
- В сухом запуске — stdout с результатами dry-run
- В GUI — события Qt

**Зависимости:**
- `larix_nexus.utils.app_logging`
- `larix_nexus.utils.crash_diagnostics`
- `larix_nexus.utils.ui_trace`
- `larix_nexus.ui` → `MainWindow`
- `larix_nexus.notifications.init_notifications_db()`
- `PySide6.QtWidgets.QApplication`, `PySide6.QtGui.QIcon`

**Где используется:**
- Только как скрипт входа (`python main.py` или PyInstaller-EXE).

---

## API-клиенты и эндпоинты

### `api/client.py`

**Назначение:** HTTP-клиент для платформы Larix (BASE_URL), авторизация, CRUD для документов/папок, файловые операции.

**Ключевые классы/функции:**
- `APIClient(base_url: str)`:
  - `self.token`, `self.refresh_token`, `self.current_username`
  - `self.cache: dict` (TTL 600 сек)
- `_save_auth()` → запись в keyring (`access_token`, `refresh_token`, `password`), JSON-настройки (`last_username`, `remember_me`)
- `_load_auth()` → попытка `refresh_token` → `password` → `access_token`
- `_refresh_access_token()` → запрос к `/api/auth/refresh`
- `login(username, password, remember_me)` → POST `/api/admin/login`
- `logout()` → очистка токенов
- `list_projects()` → GET `/api/project/list` (авторетраи 401)
- `list_folders(project_id, force=False)` → GET `/api/folder/list/{project_id}` с кэшем
- `get_folder_details(folder_id, force=False)` → GET `/api/folder/{fid}`
- `list_files(folder_id, project_id=None)` → два метода:
  1. Поиск в дереве проекта через `list_folders()`
  2. Фолбэк `get_folder_details()`
  - Поддержка полей: `children`, `files`, `documents`, `items`, `content`, `folders`
- `get_document_details(document_id)` → GET `/api/document/{doc_id}`
- `get_document_versions(document_id)` → GET `/api/document/versions/{doc_id}`
- `download_file(file_id, filename, progress_cb)` → GET `/api/document/download/{doc_id}` (streaming, сохраняет в DOWNLOAD_DIR)
- `write_file_to(file_id, out_fp, progress_cb, max_retries=3)` → streaming в `out_fp`, ретраи таймаутов
 - `upload_file(folder_id, local_path, filename, max_retries=3)` → POST `/api/document/upload/{folder_id}`, multipart `files` + `documentMetadata` JSON, ретраи таймаутов, инвалидация кэша папки
 - `delete_document(document_id, max_retries=3)` → DELETE `/api/document/delete/{doc_id}` с ретраями (до 3 попыток) для серверных ошибок (500, 502, 503, 504) и timeout (exponential backoff: 1s, 2s, 3s)
 - `delete_folder(folder_id)` → DELETE `/api/folder/delete/{fid}`
- `move_document(document_id, dest_folder_id)` → PUT `/api/document/update/{doc_id}`, использует поля `document_id` и `folder_id` (с логированием через print для отладки)
- `rename_document(document_id, new_name)` → PUT `/api/document/update/{doc_id}`, `payload={"id":..., "originalName":..., "name":...}`
- `create_folder(project_id, parent_id, name)` → POST `/api/folder/add`, возвращает `id`
- `update_folder(folder_id, project_id, name, parent_folder_id)` → PUT `/api/folder/update/{fid}`
- `rename_folder(folder_id, new_name)` → PUT `/api/folder/update/{fid}`, `payload={"id":..., "name":...}`
- `copy_folder(folder_id, dest_folder_id, new_name)` → POST `/api/folder/{src_id}/copy`, возвращает `id`
- `copy_document(document_id, dest_folder_id, new_name)` → download → temp → upload (multipart), возвращает `id`
- `is_available(timeout=6)` → ping к `/api/project/list` (lightweight)

**Вспомогательные функции:**
- `_sanitize_filename(name)` → удаление `<>:"/\\|?*`, обрезка, ограничение длины
- `decide_sync(doc, local_path, user_tz="Europe/Moscow", tol=2.0)` → `"upload"`, `"download"`, `"skip"` по modTime (lastModified) (newest wins)
- `_app_settings()` → `QSettings(SETTINGS_ORG, SETTINGS_APP)` (legacy)
- `decide_sync(doc, local_path, user_tz="Europe/Moscow", tol=2.0)` → `"upload"`, `"download"`, `"skip"` по `modifTime` vs `st_mtime`
- `_cloud_tz_offset_minutes()` → чтение из QSettings (`time/auto`, `time/offset_minutes`)
- `parse_date_like(s, tz_offset_min=None)` → парсинг timestamps (числа, ISO, fallback форматы)
- `_env_bool(name, default=False)` → парсинг env var в bool
- `_api_dbg(msg, *args)` → логирование если `DEBUG_API`

**Константы:**
- `BASE_URL` → из `larix_nexus.constants` (env `LARIX_BASE_URL` или `https://platform-api.larix.ru`)
- `CACHE_TTL_SEC = 600`
- `_API_DEBUG` → env `DEBUG_API`

**Входные данные:**
- HTTP-запросы к платформе
- QSettings/JSON для настроек (time offset)
- keyring для токенов

**Выходные данные:**
- JSON-ответы от API или пустые списки/`None`
- Код выхода: bool (`True`/`False`) для большинства методов

**Зависимости:**
- `requests`
- `PySide6.QtCore.QSettings`, `QSignal`, `QComboBox`
- `requests_toolbelt.multipart.encoder.MultipartEncoder` (опционально)
- `larix_nexus.utils.keyring`
- `larix_nexus.utils.settings`
- `larix_nexus.utils.logging` (`sync_log`, `sync_exc`, `copy_log`)
- `larix_nexus.constants` (`BASE_URL`, `DOWNLOAD_DIR`, `CACHE_TTL_SEC`, `SETTINGS_ORG`, `SETTINGS_APP`)

**Где используется:**
- `main_window.py` → `self.api = APIClient(BASE_URL)`
- `sync/engine.py`, `sync/manager.py` → API-запросы
- `ui/*.py` → операции с файлами/папками

**Обработка ошибок:**
- `401` → попытка `self._handle_401()` → refresh или logout
- Таймауты → ретраи (upload, download, write_file_to)
- Исключения → возвращают `False`, `[]`, `None`, логирование через `sync_exc`

---

## Конфигурация, константы и секреты

### `constants.py`

**Назначение:** Глобальные константы приложения, пути к иконкам, настройки UI.

**Ключевые значения:**
- `BASE_URL = os.environ.get("LARIX_BASE_URL", "https://platform-api.larix.ru").rstrip("/")`
- `DOWNLOAD_DIR = os.environ.get("LARIX_DOWNLOAD_DIR", "./Nexus_downloads")`
- `CACHE_TTL_SEC = 600`
- `APP_TITLE = "Larix Nexus Desktop"`
- `CHECKBOX_COLUMN_WIDTH = 36`
- `NOTIFY_DB_PATH = os.path.join(program_dir(), "notifications.db")`
- `NOTIFY_SETTINGS_GROUP = "notifications/folder_subscriptions"`
- `SETTINGS_ORG = "Larix"`
- `SETTINGS_APP = "NexusDesktop"`
- `SETTINGS_THEME_KEY = "ui/theme"`
- `THEME_LIGHT = "light"`
- `THEME_DARK = "dark"`
- `LIGHT_THEME_QSS = ""`
- `DARK_THEME_QSS = ""` (динамически заполняется из `_COLOR_REPLACEMENTS`)
- `EXTRA_QSS` (дополнительные QSS-правила)
- `SYNC_ROLE = QtCore.Qt.UserRole + 1111`
- `NOTIFY_ROLE = QtCore.Qt.UserRole + 2222`
- Пути к иконкам (LOGIN, ALARM, TOOLBAR, TREE, UI icons)

**Пути к иконкам:**
- `ALARM_ICON_PATH`, `ALARM1_ICON_PATH`
- `LOGIN_ICON_PATH`
- `EYE_OPEN_ICON_PATH`, `EYE_CLOSED_ICON_PATH`
- `TOOLBAR_*_ICON` (REFRESH, UPLOAD, DOWNLOAD, NEW_FOLDER, SETTINGS)
- `FOLDER_ICON_PATH`
- `SORT_ICON_*_PATH`, `ARROW_*_PATH`, `FILTER_ICON_PATH`, `REFRESH_ICON_PATH`, `INSERT_ICON_PATH`, `EDIT_ICON_PATH`, `DELETE_ICON_PATH`, `STRUCTURE_ICON_PATH`, `SYNC_ICON_PATH`, `COMPARISON_ICON_PATH`, `MOVE_FOLDER_ICON_PATH`, `COPY_FOLDER_ICON_PATH`, `BACK_ICON_PATH`, `CUSTOM_FOLDER_ICON_PATH`, `NO_FOLDER_ICON_PATH`, `CUSTOM_SAVE_ICON_PATH`, `CUSTOM_PLUS_ICON_PATH`, `DOWN_ARROW_ICON_PATH`, `FLASH_ICON_PATH`, `LOGIN_ICON_PATH`, `CAD_ICON_PATH`, `GEAR_ICON_NAME`, `CHECK_ICON_*_PATH`
- `RCHECK_ICON_*_PATH` (для PDF compare)
- `WARNING_ICON_PATH`
- `DOWN_ARROW_WHITE_ICON_PATH` (для dark theme в PDF compare)

**_COLOR_REPLACEMENTS:**
- Карта замен цветов для тёмной темы (#FFFFFF→#121212, #F5F5F5→#121212, и т.д.)
- Текстовые цвета (#222→#e0e0e0, #333→#d0d0d0, ...)

**Входные данные:**
- env vars: `LARIX_BASE_URL`, `LARIX_DOWNLOAD_DIR`, `DEBUG_API`
- Функция `program_dir()` из `larix_nexus.utils.paths`

**Выходные данные:**
- Нет (только константы)

**Зависимости:**
- `PySide6.QtCore.Qt`, `QtCore.QSize`
- `larix_nexus.utils.paths.rsrc_path`, `program_dir`

**Где используется:**
- Почти все модули: `api/client.py`, `ui/main_window.py`, `sync/manager.py`, `utils/settings.py`, `ui/dialogs.py`, `pdf/PDF_Compare.py`, и т.д.

---

### `utils/settings.py`

**Назначение:** JSON-хранилище настроек (%APPDATA%\LarixNexus\settings.json).

**Ключевые функции:**
- `_settings_dir()` → `%APPDATA%\LarixNexus`
- `_settings_path()` → `%APPDATA%\LarixNexus\settings.json`
- `load_settings()` → `atomic_read_json(path, default)` → структура по умолчанию
- `save_settings(settings)` → `atomic_write_json(path, settings, ensure_dir=True)`
- `update_settings(updater)` → `atomic_update_json(path, updater, default)`

**Структура default:**
```json
{
  "version": 1,
  "theme": "light",
  "remember_me": false,
  "last_username": "",
  "auto_login": false,
  "ui": {
    "window_geometry": null,
    "splitter_state": null,
    "column_widths": {}
  },
  "sync": {
    "auto_sync_interval": 300,
    "notification_refresh_interval": 300,
    "conflict_resolution": "newer",
    "mass_delete_threshold": 20
  }
}
```

**Входные данные:**
- JSON-файл (если существует)

**Выходные данные:**
- dict с настройками

**Зависимости:**
- `larix_nexus.utils.atomic_json.atomic_read_json`, `atomic_write_json`, `atomic_update_json`

**Где используется:**
- `main.py` → автологин
- `api/client.py` → `last_username`, `remember_me`
- `ui/main_window.py`, `ui/theme_operations.py` → тема, геометрия, splitter
- `sync/manager.py` → интервал синхронизации

---

### `utils/keyring.py`

**Назначение:** Хранение секретов (токены, пароли) через системный keyring.

**Константы:**
- `KEYRING_SERVICE = "LarixNexus"`

**Ключевые функции:**
- `save_credential(username, key, value)` → keyring.set_password
- `get_credential(username, key)` → keyring.get_password
- `delete_credential(username, key)` → keyring.delete_password
- `clear_all_credentials(username)` → удаление всех ключей для юзера
- `debug_credentials_status(username)` → логирование сохранённых значений

**Входные данные:**
- username, key, value

**Выходные данные:**
- `None` при ошибках

**Где используется:**
- `api/client.py` → `_save_auth`, `_load_auth`, `_clear_auth`

---

### `utils/paths.py`

**Назначение:** Пути к ресурсам и директориям приложения.

**Ключевые функции:**
- `program_dir()` → директория запуска (sys.executable или __file__)
- `rsrc_path(*parts)` → путь к ресурсу относительно program_dir

**Константы:**
- `ICON_PATH = rsrc_path("icon", "logo_transparent_multi.ico")` (попытка найти иконку)

**Входные данные:**
- Нет

**Выходные данные:**
- Строки путей

**Где используется:**
- `constants.py` → пути к иконкам
- `main.py` → иконка приложения
- `pdf/PDF_Compare.py` → иконки

---

## Обработка ошибок, логирование, ретраи, таймауты

### `utils/logging.py`

**Назначение:** Структурированное логирование приложения, ротация файлов, маскирование секретов.

**Ключевые функции/классы:**
- `program_dir()` → директория запуска
- `_settings_dir()` → `%APPDATA%\LarixNexus`
- `_main_log_path()` → `%APPDATA%\LarixNexus\larix_nexus.log`
- `_sync_log_path()` → `%APPDATA%\LarixNexus\_sync_debug.log` [Не подтверждено, используется в logging.py, но также в app_logging.py?]
- `_get_env_bool(var_name, default=False)` → парсинг env var в bool
- `_mask_secrets(msg)` → маскирование токенов, паролей, Authorization
- `StructuredFormatter` → форматирует лог в структурированный вид (`ts=... level=... component=... op=... trace_id=... path=... result=... reason=... duration_ms=... extra=... msg=...`)
- `_sync_logger()` → возвращает/создаёт логгер `sync` (с RotatingFileHandler если root не настроен)
- `sync_log(msg, *args, **kwargs)` → логирование с `kwargs` (component, op, trace_id, path, result, reason, duration_ms, extra)
- `sync_exc(msg)` → логирование исключения с traceback

**Константы:**
- `_MAX_LOG_SIZE = 10 * 1024 * 1024`
- `_MAX_LOG_FILES = 10`

**Входные данные:**
- Строки сообщений, аргументы, kwargs для структурированного логирования

**Выходные данные:**
- Запись в файл (`larix_nexus.log`) или stdout

**Где используется:**
- `api/client.py`, `sync/engine.py`, `sync/manager.py`, `utils/atomic_json.py`, `utils/copy_logger.py` (copy_log)

**Маскирование секретов:**
- Bearer tokens: `Bearer [A-Za-z0-9\-._~+/]+=*` → `Bearer ***`
- Long tokens (32+ chars): `\b[A-Za-z0-9]{32,}\b` → `***`
- Authorization: `"Authorization": "..."` → `"Authorization": "***"`
- password: `"password": "..."` → `"password": "***"`
- token: `"token": "..."` → `"token": "***"`

---

### `utils/copy_logger.py`

**Назначение:** Логирование операций копирования [Не подтверждено].

**Ключевые функции:**
- `copy_log(msg, *args, component="API")` → логирование с компонентом

**Входные данные:**
- Сообщения, аргументы

**Выходные данные:**
- Запись в общий лог (через `sync_log`)

**Где используется:**
- `api/client.py.copy_document`

---

### `utils/app_logging.py`

**Назначение:** Инициализация логирования, очистка старых логов, перенаправление stdout/stderr.

**Ключевые функции:**
- `reset_log_files()` → удаление логов размером > 50% от общего места или старее X дней
- `start_logging(log_to_file=True, keep_console=False)` → настройка RotatingFileHandler, перенаправление stdout/stderr
- `stop_logging()` → закрытие логов

**Константы:**
- `_MAX_LOG_SIZE = 10 * 1024 * 1024`
- `_MAX_LOG_FILES = 10`
- `_MAX_TOTAL_LOG_SIZE = 100 * 1024 * 1024`
- `_MAX_LOG_DAYS = 7`

**Входные данные:**
- Нет

**Выходные данные:**
- Булев результат `reset_log_files()`

**Где используется:**
- `main.py` → перед тяжёлыми импортами, при выходе

---

### `utils/crash_diagnostics.py`

**Назначение:** Crash dumps, faulthandler, sys.excepthook [Не подтверждено].

**Ключевые функции:**
- `install_crash_diagnostics(app=None)` → faulthandler.enable, sys.excepthook, traceback

**Входные данные:**
- app (QApplication)

**Выходные данные:**
- Нет

**Где используется:**
- `main.py`

---

### `utils/ui_trace.py`

**Назначение:** Переколлективный трейс UI-действий [Не подтверждено].

**Ключевые функции:**
- `trace(msg)` → запись трейса в файл

**Входные данные:**
- Сообщения

**Выходные данные:**
- Запись в файл

**Где используется:**
- `main.py`, `sync/manager.py`

---

### `api/client.py` — ретраи и таймауты

**Ретраи:**
- `_handle_401()` → refresh token на 401
- `write_file_to(file_id, out_fp, progress_cb, max_retries=3)` → ретраи при таймаутах
- `upload_file(folder_id, local_path, filename, max_retries=3)` → ретраи при таймаутах

**Таймауты:**
- `is_available(timeout=6)` → 6 сек
- `login()` → 12 сек
- `_refresh_access_token()` → 12 сек
- `list_projects()`, `list_folders()`, `get_folder_details()` → 12-20 сек
- `download_file()` → 60 сек (streaming)
- `write_file_to()` → 60 сек (streaming)
- `upload_file()` → 120 сек
- `delete_document()`, `delete_folder()`, `move_document()`, `rename_document()`, `create_folder()`, `update_folder()`, `rename_folder()`, `copy_folder()`, `copy_document()` → 20 сек

---

### `sync/manager.py` — таймауты и ретраи

**Конфигурация:**
- `_sync_interval = 300` сек (по умолчанию 5 минут)
- `_max_retries = 3`
- `_retry_delay_base = 2.0` сек
- `_max_deletion_percent = 0.20`
- `_protection_hysteresis_threshold = 2`
- `_max_ops_per_cycle = 100`

**Ретраи:**
- `_on_periodic_timeout()` → `sync_all()` при каждом таймере
- `_schedule_next_sync()` → расчёт времени до следующей синхронизации (align к минутам если интервал >= 60 сек)

---

## Платформо-специфичные исправления

### `api/client.py` — патчинг requests и SSL для Windows + Python 3.13

**Проблема:** На Windows с Python 3.13 SSL handshake в многопоточной среде (фоновые потоки Qt) может вызывать access violation.

**Решение:** Monkey patch для requests и urllib3:

1. **Патчинг requests функций:**
   - `_safe_get`, `_safe_post`, `_safe_put`, `_safe_delete`, `_safe_patch`, `_safe_request`
   - Автоматически добавляют `verify=False` если не указано
   - Отключают предупреждения urllib3 об небезопасных соединениях

2. **Патчинг requests.Session.get_adapter:**
   - Патчит `requests.Session.get_adapter` для модификации HTTPAdapter
   - Если адаптер имеет `poolmanager`, модифицирует `connection_pool_kw`:
     - Устанавливает `cert_reqs=ssl.CERT_NONE`
     - Устанавливает `assert_hostname=False`
   - Если адаптер имеет `init_poolmanager`, модифицирует `connection_pool_kw`:
     - Устанавливает `cert_reqs=ssl.CERT_NONE`
     - Устанавливает `assert_hostname=False`

3. **Патчинг urllib3.PoolManager:**
   - Переопределяет `PoolManager.__init__` для отключения SSL верификации
   - Добавляет `cert_reqs=ssl.CERT_NONE` и `assert_hostname=False` по умолчанию

4. **Патчинг urllib3.HTTPSConnectionPool:**
   - Переопределяет `HTTPSConnectionPool.__init__` для отключения SSL верификации
   - Устанавливает `cert_reqs=ssl.CERT_NONE` и `assert_hostname=False` по умолчанию

**Где применяется:** При импорте `api/client.py` через `_patch_requests_for_threading()`

**Примечание:** Патчинг происходит на уровне PoolManager/HTTPAdapter, что гарантирует отключение SSL верификации для всех соединений.

---

### `ui/*.py` — патчинг QMessageBox для предотвращения access violation

**Проблема:** На Windows с Python 3.13 вызов `QMessageBox` напрямую из контекстных меню (tree_context_menu, table_context_menu) может вызывать access violation.

**Решение:** Все вызовы `QMessageBox` заменены на `print(...)` или `self.status.showMessage(...)` для вывода сообщений без создания диалоговых окон.

**Где применяется:**
- `ui/tree_operations.py` — синхронизация, уведомления
- `ui/main_window.py` — удаление, версии, навигация, синхронизация
- `ui/download_operations.py` — скачивание файлов
- `ui/file_ops.py` — открытие, переименование, свойства

**Примечание:** Диалоговые окна полностью отключены для предотвращения access violation. Все сообщения выводятся в консоль или в status bar.

---

## Основные флоу

### Автологин

1. `main.py` → `load_settings()` → `last_username`, `remember_me`
2. Если `remember_me`:
   - `w.api._load_auth()`:
     - Пробует `refresh_token` → `api._refresh_access_token()` → `/api/auth/refresh`
     - Если нет → пробует `password` → `api.login()`
     - Если нет → пробует `access_token`
3. Если `_load_auth()` вернул `True`:
   - `api.list_projects()` → проверка валидности токена
   - Если `projects is not None` → автоуспех
4. Иначе → `w.open_login_dialog()`

### Ручной логин

1. `LoginDialog` → ввод username/password, checkbox "Запомнить меня"
2. `_try_login()` → `api.login(username, password, remember_me)`
3. Успех → `_save_auth()`, `save_settings({"last_username":..., "remember_me":...})`
4. Если `remember_me` → keyring save: `password`, `access_token`, `refresh_token`

### Синхронизация папки (FolderSyncManager)

1. `_on_periodic_timeout()` → `sync_all()`
2. Для каждого `folder_id` в `self.map`:
   - Если `_busy_folders` содержит `folder_id` → пропускаем
   - Добавляем в `_busy_folders`
   - Выполняем синхронизацию через `sync_files_new()` или воркер `_InitialSyncWorker`
3. `sync_files_new(api, project_id, folder_id, local_root, dry_run=False)`:
   - `load_state(project_id, folder_id)` → загрузка snapshot
   - `get_local_files(local_root)` → сканирование FS
   - `get_cloud_files(api, project_id, folder_id)` → сканирование облака (два метода)
   - `compare_and_plan_sync(old_state, local_files, cloud_files)` → планирование операций
   - `execute_sync_operations(api, project_id, folder_id, local_root, operations, dry_run)`
   - `save_state(project_id, folder_id, new_state)`
4. Защита от массового удаления:
   - Если `deleted_count / total > _max_deletion_percent`:
     - Включаем protection после 2-х триггеров подряд (hysteresis)
     - Записываем tombstones вместо удаления
   - `execute_queue_under_protection()` → разрешает выполнение pending delete под protection
5. `_self_heal_caches(folder_id)` → очистка last_cloud, last_folders, signatures

### Скачивание файла

1. Пользователь выбирает файл(ы) в таблице
2. `download_operations.py` → `download_selected_files()`
3. Для каждого файла:
   - `api.download_file(file_id, filename, progress_cb)` → streaming
   - Сохранение в `DOWNLOAD_DIR`
4. Конфликты имён → `BatchDownloadDialog` → выбор действия

### Загрузка файла

1. Пользователь перетаскивает файлы в дерево/таблицу или кнопку "Upload"
2. `upload_operations.py` → `upload_files(folder_id, paths)`
3. Для каждого файла:
   - `api.upload_file(folder_id, local_path, filename, max_retries=3)` → multipart
   - Инвалидация кэша папки
   - Обновление UI

### Drag & Drop

1. `drag_drop.py` → DragDropHandler
2. Поддерживается DnD между деревом и таблицей (drag items, drop items)
3. MIME тип: `application/x-larix-nexus-items`
4. Для каждого item: `{id, type, name, folderId, projectId}`
5. При drop:
    - Если drop в дерево → перемещение папки/файла
    - Если drop в таблицу → перемещение в папку (строка с папкой) или текущую папку
6. Подсветка элемента при наведении:
    - `TreeDropFilter` → `_set_hovered_item`, `_clear_hovered_item`
    - `TableDropFilter` → `_set_hovered_row`, `_clear_hovered_row`
    - Обработка событий `DragEnter`, `DragMove`, `DragLeave`
7. Обработка ошибок при перемещении:
    - `move_document` → попытка прямого перемещения (PUT `/api/document/update/{id}`)
    - При ошибке → fallback copy+delete
    - `delete_document` → встроенная логика ретраев (до 3 попыток) для серверных ошибок (500, 502, 503, 504)
    - Если файл скопирован, но не удален → частичный успех с предупреждением в статус-баре

### Сравнение PDF

1. Пользователь выбирает два PDF в таблице
2. `pdf/PDF_Compare.py` → `PDFCompareWindow`
3. Загрузка через PyMuPDF (`fitz`)
4. Режимы: Версия 1 / Версия 2 / Сравнение
5. Масштабирование колесом, поворот, смещение diff (перетаскивание)
6. Навигация по страницам + миниатюры
7. Экспорт текущего изображения в PDF

### Уведомления

1. `notifications/manager.py` → SQLite `notifications.db`
2. `init_notifications_db()` → создание таблиц (folders, notifications, actions_log)
3. `save_folder_notification(folder_id, subscribed)` → подписка/отписка
4. `load_folder_notifications()` → список подписок
5. `save_pending_notifications(notifications)` → сохранение pending
6. `load_pending_notifications()` → загрузка pending
7. `save_user_actions_log(action, file_id, folder_id, timestamp)` → лог действий

---

## Модели данных

### `models/files_table.py`

**Назначение:** Модель таблицы файлов с иконками, поддержкой сортировки и чекбоксов.

**Ключевые классы:**
- `FilesTableModel(QAbstractTableModel)`:
  - `HEADERS = ["", "Название", "Версия", "Тип", "Формат", "Кем создан", "Создано", "Изменено", "Кем изменено"]`
  - `SORT_ROLE = Qt.UserRole + 1`
  - `_data: list` → список items (dict)
  - `_icon_provider: IconProvider` → провайдер иконок
  - `checked: set` → отмеченные элементы
  - `rowCount()`, `columnCount()`, `headerData()`
  - `item_at(row)` → item dict
  - `data(index, role)` → DisplayRole, DecorationRole (иконка), CheckStateRole (чекбокс), UserRole (item), SORT_ROLE
  - `setData(index, value, role)` → CheckStateRole (toggle чекбокса)
  - `flags(index)` → ItemIsEnabled, ItemIsSelectable, ItemIsUserCheckable (col 0), ItemIsDragEnabled
  - `mimeTypes()` → `"application/x-larix-nexus-items"`
  - `supportedDragActions()` → MoveAction, CopyAction
  - `mimeData(indexes)` → JSON payload `{source, items}`
  - `set_items(items)` → обновление модели
- `IconProvider`:
  - `EXT_ICON_MAP` → маппинг расширений файлов к иконкам
  - `FOLDER_ICON_CANDIDATES` → кандидаты иконки папки
  - `get_icon(item)` → иконка для файла/папки
  - `_overlay_badge(base, badge_path)` → добавление badge (sync) к иконке папки

**Вспомогательные функции:**
- `file_ext(name)` → расширение файла
- `parse_date_like(s, tz_offset_min=None)` → парсинг timestamp в epoch seconds
- `_user_display_datetime(ts)` → форматирование timestamp в локальный формат
- `_app_settings()` → QSettings
- `_is_dark_mode()` → проверка тёмной темы
- `_icon_from_pixmap_variants(pm)` → QIcon с multiple pixmap sizes
- `load_white_icon(path)` → загрузка и тинт иконки в белый для тёмной темы
- `_tint_pixmap(pm, color)` → тинт pixmap цветом

**Входные данные:**
- Список items (dict) от API
- Theme (light/dark)

**Выходные данные:**
- Данные для QTableView
- Иконки

**Где используется:**
- `ui/main_window.py` → таблица файлов

---

### `models/tombstone_table.py`

**Назначение:** Модель таблицы tombstone (удаления) для отображения удалённых файлов.

**Ключевые классы:**
- `TombstoneTableModel(QAbstractTableModel)`:
  - `HEADERS = ["Файл", "Сторона", "Дата удаления", "Статус", "Истекает через (дней)"]`
  - `tombstones: list`
  - `set_tombstones(tombstones)` → обновление модели
  - `rowCount()`, `columnCount()`, `headerData()`, `data(index, role)`

**Входные данные:**
- Список tombstones (dict) → `{'relpath', 'side', 'ts', 'pending_op', 'is_dir', 'retained_until'}`

**Выходные данные:**
- Данные для QTableView

**Где используется:**
- [Не подтверждено, возможно в диалоге tombstone]

---

## Тесты и запуск

### Запуск приложения

**CLI:**
```bash
python main.py
```

**PyInstaller EXE:**
```bash
larix_nexus.exe
```

**CLI аргументы:**
- `--dry-run FOLDER_ID` → запуск dry-run синхронизации для указанной папки
- `--project-id INT` → ID проекта (требуется с --dry-run)
- `--local-root PATH` → локальный путь (требуется с --dry-run)

### Тесты

**[Не подтверждено]** - в коде не найдены тестовые файлы (`test_*.py`, `*_test.py`).

---

## Описание файлов по модулям

### `api/`

#### `api/__init__.py`

**Назначение:** Экспорт `APIClient`.

**Ключевые классы/функции:**
- `APIClient`

**Входные данные:**
- Нет

**Выходные данные:**
- Нет

**Зависимости:**
- `.client.APIClient`

**Где используется:**
- `larix_nexus.ui.main_window.py`
- `larix_nexus.sync.engine.py`, `sync/manager.py`

---

#### `api/client.py`

См. раздел [API-клиенты и эндпоинты](#api-клиенты-и-эндпоинты).

---

### `models/`

#### `models/__init__.py`

**Назначение:** Экспорт моделей.

**Ключевые классы/функции:**
- `FilesTableModel`, `TombstoneTableModel`, `IconProvider`, `file_ext`, `parse_date_like`, `_user_display_datetime`

**Входные данные:**
- Нет

**Выходные данные:**
- Нет

**Зависимости:**
- `.files_table`, `.tombstone_table`

**Где используется:**
- `larix_nexus.ui.main_window.py`

---

#### `models/files_table.py`

См. раздел [Модели данных](#модели-данных).

---

#### `models/tombstone_table.py`

См. раздел [Модели данных](#модели-данных).

---

### `sync/`

#### `sync/__init__.py`

**Назначение:** Экспорт функций и классов синхронизации.

**Ключевые классы/функции:**
- `sync_files_new`, `compare_and_plan_sync`, `execute_sync_operations`, `FolderSyncManager`, `_InitialSyncWorker`, `_ImmediateSyncRunner`

**Входные данные:**
- Нет

**Выходные данные:**
- Нет

**Зависимости:**
- `.engine`, `.state`, `.manager`

**Где используется:**
- `larix_nexus.main.py` (dry-run)
- `larix_nexus.ui.main_window.py`
- `larix_nexus.ui.sync_handlers.py`

---

#### `sync/state.py`

**Назначение:** Хранилище состояний синхронизации (JSON).

**Ключевые функции:**
- `load_sync_state(project_id="", folder_id="")` → (files_dict, initial_sync_done)
- `save_sync_state(files_state, project_id="", folder_id="")` → bool
- `clear_sync_state(project_id, folder_id)` → bool
- `load_state(project_id, folder_id)` → dict
- `save_state(project_id, folder_id, state)` → bool
- `update_state(project_id, folder_id, updater)` → bool
- `load_subscriptions()` → dict
- `save_subscriptions(subs)` → bool
- `update_subscription(project_id, folder_id, rel_path, subscribed, last_seen_rev=0)` → bool

**Константы:**
- `SYNC_STATE_FILE = "sync_state.json"`

**Вспомогательные функции:**
- `_sync_state_path()` → `%APPDATA%\LarixNexus/sync_state.json`
- `_state_path(project_id, folder_id)` → `%APPDATA%\LarixNexus/state/{project_id}-{folder_id}.json`
- `_subscriptions_path()` → `%APPDATA%\LarixNexus/settings/subscriptions.json`

**Входные данные:**
- JSON-файлы

**Выходные данные:**
- dict с состоянием

**Зависимости:**
- `larix_nexus.utils.paths.program_dir`
- `larix_nexus.utils.logging.sync_log`, `sync_exc`
- `larix_nexus.utils.helpers.normalize_id`
- `larix_nexus.utils.atomic_json.atomic_read_json`, `atomic_write_json`, `atomic_update_json`

**Где используется:**
- `sync/engine.py`, `sync/manager.py`

---

#### `sync/engine.py`

**Назначение:** Ядро синхронизации (compare + execute).

**Ключевые функции:**
- `get_local_files(local_root, trace_id="")` → `{rel_path: {createTime, lastModified, size, is_folder}}`
- `_parse_timestamp(value, field_name="")` → float epoch seconds
- `get_cloud_files(api, project_id, folder_id, trace_id="")` → `{rel_path: {createTime, lastModified, size, id, createdBy, modifiedBy, version}}`
- `get_cloud_folder_structure(api, project_id, folder_id)` → `{rel_path: folder_id}`
- `compare_and_plan_sync(old_state, local_files, cloud_files, tolerance=2.0, is_initial_sync=False, trace_id="")` → list operations. Сравнение файлов только по lastModified. Если local_mtime > cloud_mtime — upload, иначе — download (с tolerance).
- `execute_sync_operations(api, project_id, folder_id, local_root, operations, dry_run=False, trace_id="")` → {downloaded, uploaded, deleted_local, deleted_cloud, errors}

**Входные данные:**
- api, project_id, folder_id, local_root, old_state

**Выходные данные:**
- operations list, stats dict

**Зависимости:**
- `larix_nexus.utils.paths.program_dir`
- `larix_nexus.utils.logging.sync_log`, `sync_exc`, `new_trace_id`, `is_debug_sync`, `is_dry_run`
- `larix_nexus.utils.helpers.normalize_id`
- `larix_nexus.utils.atomic_json.atomic_read_json`, `atomic_write_json`, `atomic_update_json`
- `larix_nexus.utils.theme._cloud_tz_offset_minutes`

**Где используется:**
- `larix_nexus.sync.manager.py`
- `larix_nexus.main.py` (dry-run)

---

#### `sync/manager.py`

**Назначение:** Менеджер синхронизации папок (FolderSyncManager), воркеры.

**Ключевые классы:**
- `FolderSyncManager(QtCore.QObject)`:
  - `refreshRequested` Signal
  - `autoSyncStarted` Signal
  - `autoSyncFinished` Signal
  - `syncItem(action, rel_path, folder_id)` Signal
  - `__init__(api_client, parent=None)`:
    - `self.api`, `self.settings`, `self.map: dict[str, dict]`
    - `self.timer` → periodic sync
    - `self._busy_folders: set[str]`
    - `self._initial_sync_threads: dict[str, tuple[QThread, QObject]]`
    - `self._first_auto_sync_pending: bool`
    - `self._ensure_cache: dict`
    - `self._retention_days = 30`
    - `self._sync_interval = 300`
    - `self._cleanup_counter = 0`
    - `self._enable_folder_cleanup = True`
    - `self._dry_run_mode = False`
    - `self._max_retries = 3`
    - `self._retry_delay_base = 2.0`
    - `self._max_deletion_percent = 0.20`
    - `self._protection_trigger_count: dict[str, int]`
    - `self._protection_hysteresis_threshold = 2`
    - `self._max_ops_per_cycle = 100`
    - `self._last_valid_snapshot: dict[str, dict]`
  - `start_if_configured()` → запуск таймера если есть маппинги
  - `set_sync_interval(interval_seconds)` → установка интервала
  - `_schedule_next_sync()` → планирование следующей синхронизации
  - `_on_periodic_timeout()` → `sync_all()`
  - `sync_all()` → синхронизация всех папок
  - `_refresh_ui()` → запрос обновления UI
  - `_fid_key(folder_id)` → нормализация folder_id
  - `_fid_group(folder_id)` → QSettings group key
  - `_sig_string_from_cache(sig)` → строка подписи из cache
  - `_defer_folder_deletions()` → bool
  - `_detect_folder_renames_local(...)` → detect local folder renames
  - `_detect_folder_renames_cloud(...)` → detect cloud folder renames
  - `_is_protection_active(folder_id)` → bool
  - `_set_protection_state(folder_id, active, reason="", meta=None)` → установка состояния защиты
  - `_update_mass_delete_protection(folder_id, deleted_count, prev_total, current_total)` → bool
  - `_self_heal_caches(folder_id, reason="")` → очистка кэшей
  - `_cloud_folder_exists_by_path(root_folder_id, rel_path)` → int (1=exists, 0=missing, -1=unknown)
  - `_execute_queue_under_protection()` → bool
  - `_ms_until_next_sync()` → int ms до следующей синхронизации
  - `_collect_cloud_folders(root_folder_node, rel_path="")` → {rel_path: folder_id}
  - `_collect_cloud_dirs(folder_node, rel_path="")` → list[str]
  - `_collect_local_dirs(base)` → list[str]
  - `_sync_directories_first(cloud_root_node, local_root, project_id=0)` → синхронизация папок
  - `_load_last_cloud_set(folder_id)` → set[str]
  - `_load_cloud_snapshot(folder_id)` → dict {files, folders, is_valid}
  - `_save_cloud_snapshot(folder_id, snapshot)` → bool
  - `_load_tombstones(folder_id)` → list[dict]
  - `_save_tombstones(folder_id, tombstones)` → bool
  - `_register_tombstone(folder_id, rel_path, side, is_dir, pending_op="", retained_until=0)` → bool
  - `_cleanup_expired_tombstones(folder_id)` → bool
  - `_execute_pending_deletions(folder_id)` → bool
  - `_sync_folder(folder_id, local_root, project_id)` → bool
  - `register_sync_mapping(project_id, folder_id, local_root)` → bool
  - `unregister_sync_mapping(folder_id)` → bool
  - `get_sync_mappings()` → dict
- `_InitialSyncWorker(QtCore.QThread)` [Не подтверждено]
- `_ImmediateSyncRunner(QtCore.QThread)` [Не подтверждено]

**Вспомогательные функции:**
- `_app_settings()` → QSettings
- `_sync_mappings_path()` → `%APPDATA%\LarixNexus/sync_mappings.json`
- `load_sync_mappings()` → dict
- `save_sync_mappings(mappings)` → bool

**Входные данные:**
- api, project_id, folder_id, local_root

**Выходные данные:**
- Signals (autoSyncStarted, autoSyncFinished, syncItem, refreshRequested)
- bool (успех операции)

**Зависимости:**
- `PySide6.QtCore`, `PySide6.QtGui`, `PySide6.QtWidgets`
- `larix_nexus.api.APIClient`
- `larix_nexus.utils.logging.sync_log`, `sync_exc`
- `larix_nexus.utils.ui_trace.trace`
- `larix_nexus.utils.settings.load_settings`
- `larix_nexus.utils.helpers.normalize_id`, `normalize_project_id`, `enrich_id_types`
- `larix_nexus.sync.engine.sync_files_new`
- `larix_nexus.constants.SETTINGS_ORG`, `SETTINGS_APP`
- `larix_nexus.utils.atomic_json.atomic_read_json`, `atomic_write_json`
- `larix_nexus.sync.state.load_sync_state`, `clear_sync_state`

**Где используется:**
- `larix_nexus.ui.main_window.py` → `self.sync_manager`

---

### `ui/`

#### `ui/__init__.py`

**Назначение:** Экспорт UI-компонентов и инъекция в MainWindow.

**Ключевые классы/функции:**
- `MainWindow`, `ScrollbarProxyStyle`
- `FileDetailsDialog`, `FolderDetailsDialog`, `BatchDownloadDialog`, `SingleDownloadDialog`, `BatchUploadDialog`

**Инъекции:**
- `folder_actions.py` → `inject_folder_actions_to_main_window(MainWindow)`
- `sync_handlers.py` → `inject_sync_handlers_to_main_window(MainWindow)`
- `notification_handlers.py` → `inject_notification_handlers_to_main_window(MainWindow)`
- `context_menus.py` → `inject_context_menus_to_main_window(MainWindow)`
- `table_filters.py` → `inject_table_filters_to_main_window(MainWindow)`
- `download_operations.py` → `inject_download_operations_to_main_window(MainWindow)`
- `upload_operations.py` → `inject_upload_operations_to_main_window(MainWindow)`
- `theme_operations.py` → `inject_theme_operations_to_main_window(MainWindow)`
- `tree_operations.py` → `inject_tree_operations_to_main_window(MainWindow)`
- `table_operations.py` → `inject_table_operations_to_main_window(MainWindow)`
- `ui_helpers.py` → `inject_ui_helpers_to_main_window(MainWindow)`
- `header_menu.py` → `inject_header_menu_to_main_window(MainWindow)`
- `column_ops.py` → `inject_column_ops_to_main_window(MainWindow)`
- `file_ops.py` → `inject_file_ops_to_main_window(MainWindow)`
- `tree_search.py` → `inject_tree_search_to_main_window(MainWindow)`

**Входные данные:**
- Нет

**Выходные данные:**
- Нет

**Зависимости:**
- `.main_window`, `.widgets`, `.dialogs`
- Подмодули `ui/`

**Где используется:**
- `larix_nexus.main.py` → `from larix_nexus.ui import MainWindow, ScrollbarProxyStyle`

---

#### `ui/main_window.py`

**Назначение:** Главное окно приложения.

**Ключевые классы:**
- `LoginDialog(QDialog)`:
  - `__init__(api, parent=None)`:
    - `self.api`, `self.le_username`, `self.le_password`, `self.cb_remember`
  - `_try_login()` → `api.login(username, password, remember_me)`
- `MainWindow(QMainWindow)` [частично прочитано, файл большой]

**Вспомогательные функции:**
- `_sanitize_filename(name)` → re.sub r"[\\/:*?\"<>|]+", "_"
- `normalize_size(item)` → int size из dict
- `open_in_os(path)` → открытие файла/папки в OS
- `_is_file(item)` → bool
- `_is_folder(item)` → bool
- `get_title(node)` → name/title/Без названия
- `cleanup_removed(view)` → удаление устаревших ID из delegate

**Константы:**
- `CUSTOM_ICONS_DIR = rsrc_path("icon")`
- `ARROW_ICON_PATHS = {"left":..., "right":..., "up":..., "down":...}`

**Входные данные:**
- api, settings, ui

**Выходные данные:**
- MainWindow UI

**Зависимости:**
- `PySide6`, `requests`, `zoneinfo`, `ctypes`, `uuid`, `requests_toolbelt.multipart.encoder` (опционально)
- `larix_nexus.api.APIClient`
- `larix_nexus.sync.sync_files_new`
- `larix_nexus.sync.manager.FolderSyncManager`
- `larix_nexus.constants` (все константы)
- `larix_nexus.utils.paths`, `utils.logging`, `utils.copy_logger`, `utils.keyring`, `utils.settings`, `utils.theme`, `utils.helpers`, `utils.atomic_json`
- `larix_nexus.notifications.init_notifications_db`, ...
- `larix_nexus.models.files_table.FilesTableModel`, `IconProvider`, `file_ext`
- `larix_nexus.models.tombstone_table.TombstoneTableModel`
- `.widgets` (NikCheckBoxStyle, ThemeToggle, StickyMenu, HeaderCheckButton, SortHeader, BusyDots, WaitDialog)
- `.delegates` (CheckBoxDelegate, CheckBoxDelegateBg, RowHoverDelegate, MenuLikeTreeDelegate)
- `.dialogs.BatchUploadDialog`, `parse_date_like`, `_user_display_datetime`
- `larix_nexus.utils.theme.white_tinted_icon`, `_app_settings`, `_cloud_tz_offset_minutes`
- `.api.client.PopupComboBox`

**Где используется:**
- `larix_nexus.main.py` → `w = MainWindow()`, `w.show()`

---

#### `ui/dialogs.py`

**Назначение:** Диалоги для просмотра деталей файлов/папок, массового скачивания/загрузки.

**Ключевые классы:**
- `FileDetailsDialog(QDialog)`:
  - `__init__(data, parent=None)` → отображение свойств файла
- `FolderDetailsDialog(QDialog)`:
  - `__init__(data, parent=None)` → отображение свойств папки
- `BatchDownloadDialog(QDialog)`:
  - `__init__(parent, total, icon_provider)` → диалог массового скачивания
  - `STATUS_ICON_FILES = {"ok":..., "process":..., "none":...}`
- `SingleDownloadDialog(QDialog)` [Не подтверждено]
- `BatchUploadDialog(QDialog)` [Не подтверждено]

**Вспомогательные функции:**
- `_app_settings()` → QSettings
- `parse_date_like(s, tz_offset_min=None)` → float epoch seconds
- `_user_display_datetime(ts)` → str formatted
- `_get_white_icon_path_for_dark_theme(path)` → str path

**Константы:**
- `CHECK_ICON_OFF_PATH`, `CHECK_ICON_ON_PATH`, `CHECK_ICON_MID_PATH`

**Входные данные:**
- data (dict), parent, total, icon_provider

**Выходные данные:**
- QDialog UI

**Зависимости:**
- `PySide6.QtCore`, `PySide6.QtGui`, `PySide6.QtWidgets`
- `larix_nexus.utils.theme._get_white_icon_path_for_dark_theme`, `load_white_icon`, `_is_dark_mode`
- `larix_nexus.utils.paths.rsrc_path`, `ICON_PATH`
- `larix_nexus.utils.helpers._set_window_theme_dark`
- `larix_nexus.constants.THEME_LIGHT`, `THEME_DARK`, `SETTINGS_ORG`, `SETTINGS_APP`
- `.widgets.BusyDots`, `NikCheckBoxStyle`, `ConflictListItem`
- `larix_nexus.models.files_table.IconProvider`

**Где используется:**
- `larix_nexus.ui.main_window.py`

---

#### `ui/widgets.py` [Не подтверждено - не прочитан]

**Назначение:** Кастомные виджеты (NikCheckBoxStyle, ThemeToggle, StickyMenu, HeaderCheckButton, SortHeader, BusyDots, WaitDialog, ConflictListItem).

**Ключевые классы:**
- `NikCheckBoxStyle`
- `ThemeToggle`
- `StickyMenu`
- `HeaderCheckButton`
- `SortHeader`
- `BusyDots`
- `WaitDialog`
- `ConflictListItem`

**Где используется:**
- `ui/main_window.py`, `ui/dialogs.py`, `ui/delegates.py`

---

#### `ui/delegates.py` [Не подтверждено - не прочитан]

**Назначение:** Делегаты для чекбоксов, hover-эффектов, меню.

**Ключевые классы:**
- `CheckBoxDelegate`
- `CheckBoxDelegateBg`
- `RowHoverDelegate`
- `MenuLikeTreeDelegate`

**Где используется:**
- `ui/main_window.py`

---

#### `ui/context_menus.py`

**Назначение:** Контекстные меню дерева/таблицы + фильтры в заголовке таблицы (ПКМ по колонке).

**Ключевые функции:**
- `table_context_menu(self, pos)`:
  - контекстное меню по строке таблицы (операции над файлом/папкой, скачать, копировать ссылку, и т.д.)
- `header_context_menu(self, pos)`:
  - контекстное меню по заголовку таблицы (фильтры по колонкам)
  - использует `StickyMenu` (`objectName="nikHeaderMenu"`) + `QWidgetAction` для встраивания виджетов
  - типы фильтров:
    - `Тип` → чекбоксы `Файл/Папка`
    - `Формат` → чекбоксы популярных расширений
    - `Версия / Кем создан / Кем изменено` → текстовый фильтр + кнопка `Варианты` (раскрывает список уникальных значений)
    - `Создано / Изменено` → диапазон дат (два `QCalendarWidget`)
- `inject_context_menus_to_main_window(MainWindow)` → биндинг функций в `MainWindow`.

**Особенности UI:**
- Кнопка `Варианты` в `header_context_menu()` открывает отдельный `StickyMenu` со списком чекбоксов (вместо динамического расширения текущего меню): встраиваемые `QWidgetAction` внутри `QMenu` на Windows нестабильно пересчитывают геометрию и могут визуально «сжиматься».

**Где используется:**
- `ui/__init__.py`

---

#### `ui/table_filters.py` [Не подтверждено - не прочитан]

**Назначение:** Фильтрация таблицы.

**Ключевые функции:**
- `inject_table_filters_to_main_window(MainWindow)`

**Где используется:**
- `ui/__init__.py`

---

#### `ui/table_operations.py` [Не подтверждено - не прочитан]

**Назначение:** Операции с таблицей (сортировка, выбор, etc.).

**Ключевые функции:**
- `inject_table_operations_to_main_window(MainWindow)`

**Где используется:**
- `ui/__init__.py`

---

#### `ui/column_ops.py` [Не подтверждено - не прочитан]

**Назначение:** Операции с колонками (скрытие/показ).

**Ключевые функции:**
- `inject_column_ops_to_main_window(MainWindow)`

**Где используется:**
- `ui/__init__.py`

---

#### `ui/header_menu.py` [Не подтверждено - не прочитан]

**Назначение:** Меню заголовка таблицы.

**Ключевые функции:**
- `inject_header_menu_to_main_window(MainWindow)`

**Где используется:**
- `ui/__init__.py`

---

#### `ui/tree_operations.py` [Не подтверждено - не прочитан]

**Назначение:** Операции с деревом (раскрытие/свертывание, поиск).

**Ключевые функции:**
- `inject_tree_operations_to_main_window(MainWindow)`

**Где используется:**
- `ui/__init__.py`

---

#### `ui/tree_search.py` [Не подтверждено - не прочитан]

**Назначение:** Поиск по дереву.

**Ключевые функции:**
- `inject_tree_search_to_main_window(MainWindow)`

**Где используется:**
- `ui/__init__.py`

---

#### `ui/ui_helpers.py` [Не подтверждено - не прочитан]

**Назначение:** UI-хелперы (backup версии).

**Ключевые функции:**
- `inject_ui_helpers_to_main_window(MainWindow)`

**Где используется:**
- `ui/__init__.py`

---

#### `ui/upload_operations.py`

**Назначение:** Загрузка файлов в облако с поддержкой разрешения конфликтов имен.

**Ключевые функции:**
- `_unique_remote_name(self, taken: set[str], name: str) -> str` → генерация уникального имени файла (file.txt → file_копия.txt, file_копия2.txt) для разрешения конфликтов при загрузке
- `_ensure_subfolder(project_id, parent_id, name)` → создание подпапки с разрешением конфликтов имен
- `_collect_upload_tasks(paths, display_prefix)` → сбор задач загрузки
- `_upload_list_to_folder(target_folder, paths, display_prefix)` → массовая загрузка файлов в папку с диалогом конфликтов
- `upload_files(folder_id, paths)` → загрузка файлов в папку
- `inject_upload_operations_to_main_window(MainWindow)`

**Входные данные:**
- Путь к файлам/папкам для загрузки
- Целевая папка в облаке

**Выходные данные:**
- Загруженные файлы в облако

**Где используется:**
- `ui/__init__.py`
- Drag & Drop операции в tree_operations.py

---

#### `ui/download_operations.py`

**Назначение:** Скачивание файлов из облака с поддержкой разрешения конфликтов имен.

**Ключевые функции:**
- `ensure_downloaded(self, item: dict) -> str` → скачивание файла в локальную папку с разрешением конфликтов имен
- `_copy_file_with_progress(self, src: str, dst: str, on_bytes) -> None` → копирование файла с прогресс-баром
- `_unique_name(self, dest_dir: str, name: str) -> str` → генерация уникального имени файла (file.txt → file_копия.txt, file_копия2.txt) если имя занято
- `_unique_name_for_batch(self, target_dir: str, name: str, used_names: set[str]) -> str` → генерация уникального имени для пакетных операций с учётом уже использованных имён
- `_check_file_conflicts(self, target_folder_id: int | str, filenames: list[str]) -> dict[str, bool]` → проверка конфликтов имен на сервере
- `_prompt_conflict_in_status(self, dest_dir: str, filename: str) -> str` → запрос пользователя как разрешить конфликт
- `download_selected()` → скачивание выбранного файла
- `download_file_plain(node: dict)` → скачивание файла как есть
- `_download_file_plain_fixed(node: dict)` → скачивание файла с исправленным диалогом сохранения
- `download_file_as_zip(node: dict)` → скачивание одного файла как ZIP
- `download_folder_as_zip(node)` → скачивание папки как ZIP
- `download_folder_plain(node)` → скачивание папки как структура каталогов
- `_zip_folder_into(node: dict, zf: zipfile.ZipFile, arc_prefix: str = "")` → рекурсивное добавление содержимого папки в ZIP
- `_copy_folder_into(node: dict, dest_dir: str, into_name: str | None = None)` → рекурсивное копирование содержимого папки в локальный каталог
- `_zip_add_empty_dir(zf: zipfile.ZipFile, arc_dir: str)` → добавление пустой директории в ZIP
- `inject_download_operations_to_main_window(MainWindow)`

**Входные данные:**
- Node/dict с информацией о файле/папке
- Путь назначения для сохранения

**Выходные данные:**
- Скачанные файлы в локальной файловой системе

**Где используется:**
- `ui/__init__.py`
- main_window.py → скачивание файлов и папок

---

#### `ui/file_ops.py` [Не подтверждено - не прочитан]

**Назначение:** Операции с файлами (открытие, переименование, удаление).

**Ключевые функции:**
- `inject_file_ops_to_main_window(MainWindow)`

**Где используется:**
- `ui/__init__.py`

---

#### `ui/folder_actions.py`

**Назначение:** Действия над папками и файлами (создание, переименование, удаление, перемещение, копирование с разрешением конфликтов имен).

**Ключевые функции:**
- `_plural_form(n, forms)` → получение правильной формы множественного числа для русского языка (например, 1 файл, 2 файла, 5 файлов)
- `_generate_unique_name(existing_names: set[str], name: str) -> str` → генерация уникального имени (file.txt → file_копия.txt, file_копия2.txt) для разрешения конфликтов при копировании
- `copy_folder_action(self)` → копирование выбранной папки с добавлением "_копия" к имени
- `copy_selected_action(self)` → копирование выбранных файлов/папок в другую папку с автоматическим разрешением конфликтов имен
- `_do_copy(self, items, result)` → выполнение операции копирования с генерацией уникальных имен для файлов, которые уже существуют в целевой папке
- `_do_copy_folder(self, src_folder_id, dest_folder_id, new_name, dest_path)` → копирование папки
- `move_folder_action(self)` → перемещение выбранной папки
- `move_selected_action(self)` → перемещение выбранных файлов/папок
- `_do_move(self, items, result, project_id)` → выполнение операции перемещения
- `_do_move_folder(self, folder_id, project_id, name, dest_folder_id, dest_path)` → перемещение папки
- `_prompt_folder_select(self, title: str, can_select_current: bool = False) -> dict` → диалог выбора папки назначения
- `_populate_folder_tree_from_nodes(tree, parent_item, nodes, exclude_id=None, can_select_current=False)` → заполнение дерева папок из узлов
- `_populate_folder_tree_from_list(tree, parent_item, nodes, exclude_id=None, can_select_current=False)` → обёртка для заполнения дерева из плоского списка
- `inject_folder_actions_to_main_window(MainWindow)`

**Входные данные:**
- Выбранные файлы/папки
- Целевая папка назначения

**Выходные данные:**
- Скопированные/перемещенные файлы и папки

**Где используется:**
- `ui/__init__.py`
- Контекстные меню дерева и таблицы (context_menus.py, tree_operations.py)

**Особенности:**
- При копировании файлов в ту же папку автоматически добавляется "_копия" к имени
- Если файл "_копия" уже существует → "_копия2", "_копия3" и т.д.
- Файлы не заменяются, а создаются с уникальными именами
- Сообщения в статус-баре используют правильное склонение числительных для русского языка (1 файл, 2 файла, 5 файлов)
- Перемещение файлов:
  - Сначала попытка `move_document` (прямое перемещение через API)
  - При ошибке → fallback copy+delete с множественными попытками
  - copy+delete процесс:
    - `copy_document` → загрузка копии файла в целевую папку
    - 5 попыток удаления с увеличивающимися задержками (2s, 4s, 6s, 8s, 10s)
    - `delete_document` вызывается в цикле до первого успеха или 5 попыток
    - Каждая попытка логируется отдельно
  - Если файл скопирован и удален → успех
  - Если файл скопирован, но не удален после 5 попыток → частичный успех (копия создана, оригинал не удален)
  - Финальное сообщение: "Успешно перемещено: X из Y (возможно, Z файлов не были удалены из исходной папки - ошибки сервера)"

---

#### `ui/sync_handlers.py` [Не подтверждено - не прочитан]

**Назначение:** Обработчики синхронизации (старт, стоп, статус).

**Ключевые функции:**
- `inject_sync_handlers_to_main_window(MainWindow)`

**Где используется:**
- `ui/__init__.py`

---

#### `ui/notification_handlers.py` [Не подтверждено - не прочитан]

**Назначение:** Обработчики уведомлений (показ, подписка/отписка).

**Ключевые функции:**
- `inject_notification_handlers_to_main_window(MainWindow)`

**Где используется:**
- `ui/__init__.py`

---

#### `ui/theme_operations.py` [Не подтверждено - не прочитан]

**Назначение:** Операции тем (переключение светлая/тёмная).

**Ключевые функции:**
- `inject_theme_operations_to_main_window(MainWindow)`

**Где используется:**
- `ui/__init__.py`

---

#### `ui/drag_drop.py`

**Назначение:** Drag & Drop (между деревом и таблицей) с подсветкой элемента при наведении.

**Ключевые классы:**
- `DragEventFilter(QObject)`:
  - `eventFilter(obj, event)` → обработка событий мыши для начала drag из таблицы
  - `_start_drag()` → создание drag операции с preview pixmap
  - `_create_preview(rows)` → создание preview pixmap с иконкой файла и счётчиком (для нескольких файлов)
- `TreeDropFilter(QObject)`:
  - `eventFilter(obj, event)` → обработка DragEnter, DragMove, DragLeave, Drop для дерева папок
  - `_set_hovered_item(item, tree)` → установка подсветки элемента при наведении
  - `_clear_hovered_item(tree)` → очистка подсветки
- `TableDropFilter(QObject)`:
  - `eventFilter(obj, event)` → обработка DragEnter, DragMove, DragLeave, Drop для таблицы файлов
  - `_set_hovered_row(idx, table)` → установка подсветки строки при наведении
  - `_clear_hovered_row(table)` → очистка подсветки

**Константы:**
- `MIME_ITEMS = "application/x-larix-nexus-items"`

**Где используется:**
- `ui/main_window.py` → установка DragEventFilter на viewport таблицы, TreeDropFilter на дерево, TableDropFilter на таблицу

**Особенности:**
- MIME тип: `application/x-larix-nexus-items`
- Payload: `{"source": "table", "items": [{id, type, name, folderId, projectId}]}`
- При drop в дерево → перемещение в выбранную папку
- При drop в таблицу → перемещение в папку (строка с папкой) или текущую папку
- Подсветка элемента при наведении через `setCurrentItem`/`setCurrentIndex`
- При DragLeave → очистка подсветки
- При Drop → очистка подсветки после выполнения операции

---

#### `ui/custom_drag_delegate.py`

**Назначение:** Кастомный делегат drag для улучшенного preview с иконками.

**Ключевые классы:**
- `CustomDragDelegate(QStyledItemDelegate)`:
  - `startDrag(supportedActions, model)` → переопределён для кастомного drag preview
  - `_create_drag_preview(rows, source_model, icon_provider)` → создание preview с иконками (до 5 штук) и счётчиком

**Константы:**
- `ICON_SIZE = 32`
- `ICON_GAP = 8`
- `PAD = 10`
- `MAX_ICONS = 5`

**Где используется:**
- `ui/main_window.py` → установка кастомного делегата для таблицы файлов

---

#### `ui/dnd_animation.py`

**Назначение:** Анимация drop (bounce эффект) для визуального фидбека.

**Ключевые классы:**
- `_AnimatedIconLabel(QLabel)` → лейбл с анимацией
- `DropAnimationOverlay(QWidget)` → оверлей для показа анимации иконок
  - `animate_drop(source_pos, dest_pos, icons)` → запуск анимации bounce
  - `_position_overlay(source_pos, dest_pos)` → позиционирование оверлея
  - `_create_animated_icons(source_pos, dest_pos, icons)` → создание анимированных иконок
  - `_animate_icon(label, source, dest, pixmap)` → анимация bounce
  - `_animate_bounce(label, source, dest)` → вертикальная анимация
  - `_animate_move(label, source, dest)` → горизонтальная анимация
  - `_fade_out_all()` → fade out и cleanup

**Константы:**
- `ANIMATION_DURATION = 600` (ms)
- `STAGGER_DELAY = 40` (ms)
- `BOUNCE_HEIGHT = -30` (pixels)
- `ANIMATION_CURVE = QEasingCurve.OutBack`

**Где используется:**
- Drag & Drop операции в дереве и таблице

---

#### `ui/dnd_validation.py`

**Назначение:** Валидация Drag & Drop операций и утилиты.

**Ключевые классы:**
- `DropOp` → операции (MOVE, COPY, INVALID)
- `DnDColors` → цвета для визуального фидбека (HOVER_VALID, HOVER_INVALID)

**Ключевые функции:**
- `validate_drop_target(dest_folder_id, items, project_id, tree_folder_map)` → валидация drop цели (проверка той же папки, перемещение папки в саму себя или подпапку)
- `get_drop_operation(modifiers, default_op)` → определение операции по модификаторам клавиш (Ctrl=copy, Shift=move)
- `normalize_dnd_items(items)` → нормализация DnD items в стандартный формат
- `parse_mime_data(raw_data)` → парсинг MIME данных из drag операции
- `build_folder_descendants_map(tree_widget)` → построение карты folder_id → descendant folder IDs
- `create_drop_highlight_pixmap(width, height, is_valid)` → создание pixmap для подсветки drop target
- `get_drop_action_label(operation, count)` → человекочитаемая метка для действия

**Константы:**
- `MIME_ITEMS = "application/x-larix-nexus-items"`
- `AUTO_EXPAND_DELAY = 500` (ms)
- `HOVER_DEBOUNCE_DELAY = 100` (ms)

**Где используется:**
- Drag & Drop операции в дереве и таблице

---

#### `ui/document_type_selection_dialog.py`

**Назначение:** Диалог выбора типа документа для batch upload.

**Ключевые классы:**
- `DocumentTypeSelectionDialog(QDialog)`:
  - `get_document_types()` → возвращает dict {task_key: type_id}
  - `_populate_table()` → заполнение таблицы задач
  - `_toggle_all_rows(checked)` → переключение всех чекбоксов
  - `_sync_header_checkbox()` → синхронизация чекбокса в заголовке
  - `_on_combo_changed(row, task)` → обработка изменения типа в combo box

**Ключевые классы:**
- `_SelectAllHeader(QHeaderView)` → кастомный заголовок с чекбоксом "выбрать всё"

**Где используется:**
- Batch upload операций

---

### `utils/`

#### `utils/__init__.py`

**Назначение:** Экспорт utility-функций.

**Ключевые классы/функции:**
- `rsrc_path`, `program_dir`, `ICON_PATH`
- `sync_log`, `sync_exc`, `_cleanup_sync_log_file`, `_sync_log_path`
- `save_credential`, `get_credential`, `delete_credential`, `clear_all_credentials`, `debug_credentials_status`
- `load_settings`, `save_settings`, `update_settings`
- `apply_light_theme`, `apply_dark_theme`, `_is_dark_mode`, `load_saved_theme`, `install_russian_ui`, `install_warning_icon_for_messageboxes`, `enable_msgbox_autosize`, `_patch_messagebox_texts_fixed`, `white_tinted_icon`, `load_white_icon`, `_cloud_tz_offset_minutes`
- `normalize_id`, `normalize_project_id`, `_set_window_theme_dark`, `compare_file_states`
- `atomic_read_json`, `atomic_write_json`, `atomic_update_json`
- `patch_qfiledialog_initial_dir`, `patch_dir_picker_binding`, `patch_combobox_popup_border`
- `patch_messagebox_texts`

**Входные данные:**
- Нет

**Выходные данные:**
- Нет

**Зависимости:**
- `paths`, `logging`, `keyring`, `settings`, `theme`, `helpers`, `atomic_json`, `ui_patches`, `messagebox`

**Где используется:**
- Почти все модули проекта

---

#### `utils/paths.py`

См. раздел [Конфигурация, константы и секреты](#конфигурация-константы-и-секреты).

---

#### `utils/settings.py`

См. раздел [Конфигурация, константы и секреты](#конфигурация-константы-и-секреты).

---

#### `utils/atomic_json.py`

**Назначение:** Атомарные операции чтения/записи JSON с блокировками.

**Ключевые функции:**
- `_get_json_lock(path)` → threading.Lock для файла
- `_acquire_file_lock(lock_path, timeout=15.0)` → bool
- `_release_file_lock(lock_path)` → None
- `atomic_read_json(path, default=None)` → Any
- `atomic_write_json(path, data, ensure_dir=True)` → bool
- `atomic_update_json(path, updater, default=None)` → bool

**Входные данные:**
- path, data, updater, default

**Выходные данные:**
- data, bool

**Зависимости:**
- `os`, `json`, `time`, `threading`
- `larix_nexus.utils.logging.sync_log`, `sync_exc`
- `larix_nexus.utils.paths.program_dir`

**Где используется:**
- `sync/state.py`, `sync/manager.py`, `utils/settings.py`, `api/client.py` (через settings.py)

---

#### `utils/keyring.py`

См. раздел [Конфигурация, константы и секреты](#конфигурация-константы-и-секреты).

---

#### `utils/logging.py`

См. раздел [Обработка ошибок, логирование, ретраи, таймауты](#обработка-ошибок-логирование-ретраи-таймауты).

---

#### `utils/copy_logger.py`

См. раздел [Обработка ошибок, логирование, ретраи, таймауты](#обработка-ошибок-логирование-ретраи-таймауты).

---

#### `utils/app_logging.py`

См. раздел [Обработка ошибок, логирование, ретраи, таймауты](#обработка-ошибок-логирование-ретраи-таймауты).

---

#### `utils/crash_diagnostics.py` [Не подтверждено - не прочитан]

**Назначение:** Crash dumps, faulthandler, sys.excepthook.

**Ключевые функции:**
- `install_crash_diagnostics(app=None)`

**Где используется:**
- `main.py`

---

#### `utils/ui_trace.py`

**Назначение:** Логер UI трейса для диагностики native crashes (access violations).

**Ключевые функции:**
- `trace(msg, *args)` → запись одной строки в `ui_trace.log`
- `log_path()` → путь к лог-файлу (`%APPDATA%/LarixNexus/ui_trace.log`)
- `_ts()` → timestamp в формате `%Y-%m-%d %H:%M:%S.%f`
- `_thread_tag()` → тег потока (tid и name)
- `_qt_thread_tag()` → тег Qt потока (qt_tid)

**Где используется:**
- `main.py`, `sync/manager.py`, `api/client.py`, `utils/safe_dialogs.py`

---

#### `utils/helpers.py`

**Назначение:** Хелперы: normalize_id, _set_window_theme_dark, compare_file_states.

**Ключевые функции:**
- `normalize_id(value)` → str
- `normalize_project_id(value)` → str
- `enrich_id_types(item)` → dict (добавляет _id_str, _id_int)
- `compare_file_states(old_files, new_files, filter_func=None)` → list[dict] {type, file, old_name, version_update}
- `_set_window_theme_dark(window, dark=False)` → None (Windows title bar)

**Входные данные:**
- value, item, old_files, new_files, filter_func, window, dark

**Выходные данные:**
- str, dict, None

**Где используется:**
- `api/client.py`, `sync/manager.py`, `ui/main_window.py`

---

#### `utils/theme.py` [Не подтверждено - не прочитан]

**Назначение:** Применение светлой/тёмной темы, load_saved_theme.

**Ключевые функции:**
- `apply_light_theme(app)`
- `apply_dark_theme(app)`
- `_is_dark_mode()` → bool
- `load_saved_theme()` → str
- `save_theme(theme)` → None
- `install_russian_ui(app)`
- `install_warning_icon_for_messageboxes()`
- `enable_msgbox_autosize(app)`
- `_patch_messagebox_texts_fixed()`
- `white_tinted_icon(path)`
- `load_white_icon(path)`
- `_cloud_tz_offset_minutes()` → int

**Где используется:**
- `main.py`, `ui/main_window.py`, `ui/dialogs.py`, `pdf/PDF_Compare.py`

---

#### `utils/safe_dialogs.py` [Не подтверждено - не прочитан]

**Назначение:** Безопасные диалоги (в т.ч. для крит. путей).

**Где используется:**
- [Не подтверждено]

---

#### `utils/safe_event_filter.py` [Не подтверждено - не прочитан]

**Назначение:** Фильтр событий (e.g. для безопасных диалогов).

**Где используется:**
- [Не подтверждено]

---

#### `utils/messagebox.py` [Не подтверждено - не прочитан]

**Назначение:** Патчи QMessageBox (авторазмер).

**Ключевые функции:**
- `patch_messagebox_texts()`

**Где используется:**
- `main.py`, `utils/__init__.py`

---

#### `utils/ui_patches.py` [Не подтверждено - не прочитан]

**Назначение:** Патчи Qt (QFileDialog, DirPicker, ComboBox).

**Ключевые функции:**
- `patch_qfiledialog_initial_dir()`
- `patch_dir_picker_binding()`
- `patch_combobox_popup_border()`

**Где используется:**
- `main.py`, `utils/__init__.py`

---

### `notifications/`

#### `notifications/__init__.py`

**Назначение:** Экспорт функций управления уведомлениями.

**Ключевые классы/функции:**
- `init_notifications_db`, `save_folder_notification`, `remove_folder_notification`, `load_folder_notifications`, `is_folder_notification_enabled`, `save_pending_notifications`, `load_pending_notifications`, `save_user_actions_log`, `load_user_actions_log`

**Входные данные:**
- Нет

**Выходные данные:**
- Нет

**Зависимости:**
- `.manager`

**Где используется:**
- `larix_nexus.main.py`
- `larix_nexus.ui.main_window.py`
- `larix_nexus.ui.notification_handlers.py`

---

#### `notifications/manager.py` [частично прочитан]

**Назначение:** Управление уведомлениями (SQLite).

**Ключевые функции:**
- `init_notifications_db()` → создание таблиц (folders, notifications, actions_log)
- `save_folder_notification(folder_id, subscribed)` → сохранение подписки
- `remove_folder_notification(folder_id)` → удаление подписки
- `load_folder_notifications()` → список подписок
- `is_folder_notification_enabled(folder_id)` → bool
- `save_pending_notifications(notifications)` → сохранение pending
- `load_pending_notifications()` → загрузка pending
- `save_user_actions_log(action, file_id, folder_id, timestamp)` → лог действий
- `load_user_actions_log()` → лог действий

**Входные данные:**
- folder_id, subscribed, notifications, action, file_id, timestamp

**Выходные данные:**
- dict, list, bool

**Где используется:**
- `larix_nexus.ui.notification_handlers.py`

---

### `pdf/`

#### `pdf/__init__.py` [Не подтверждено - не прочитан]

**Назначение:** Экспорт функций PDF compare.

---

#### `pdf/PDF_Compare.py` [частично прочитан]

**Назначение:** Окно сравнения двух PDF.

**Ключевые классы:**
- `PDFCompareWindow(QMainWindow)` [частично прочитан]

**Вспомогательные функции:**
- `icon_url(path)` → str URL
- `icon_url_encoded(path)` → str URL (encoded)
- `_app_settings()` → QSettings
- `load_saved_theme()` → str
- `save_theme(theme)` → None
- `_set_window_theme(window, dark=False)` → None (Windows title bar)
- `_create_white_arrow_icons()` → создание white versions

**Константы:**
- `SETTINGS_ORG = "Larix"`
- `SETTINGS_APP = "NexusDesktop"`
- `SETTINGS_THEME_KEY = "ui/theme"`
- `THEME_LIGHT = "light"`
- `THEME_DARK = "dark"`
- `ICON_DIR = rsrc_path("icon")`
- `WARNING_ICON_PATH = rsrc_path("icon", "warning.png")`

**_COLOR_REPLACEMENTS:**
- Карта замен цветов для тёмной темы (аналогично `constants.py`)

**Входные данные:**
- path, theme, dark

**Выходные данные:**
- URL, str, None

**Где используется:**
- `larix_nexus.ui.main_window.py`

**Зависимости:**
- `os`, `sys`, `re`, `fitz` (PyMuPDF), `numpy`, `cv2`, `argparse`, `io`, `PIL.Image`, `PIL.ImageOps`
- `PySide6`, `concurrent.futures.ThreadPoolExecutor`, `queue`, `platform`
- `larix_nexus.utils.paths.rsrc_path`, `ICON_PATH`

---

## [Не подтверждено]

- Файлы, помеченные как "[Не подтверждено]" выше, не были полностью прочитаны из-за ограничений на чтение или времени. Их описание основано на частичном чтении, имени файла или инъекциях в `MainWindow`.
- Для подтверждения информации нужно прочитать полный код этих файлов.

---

## Конец документа
