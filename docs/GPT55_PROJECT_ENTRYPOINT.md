# GPT-5.5 Project Entrypoint

## 1. Назначение файла

Этот файл — стартовая инструкция для новых чатов с GPT-5.5 по проекту Larix Nexus. Он даёт короткую рабочую карту проекта, правила поведения старшей модели и формат подготовки задач для более слабой модели-исполнителя.

Подробная навигационная карта уже есть в `docs/project-architecture.md`. Для глубокого разбора модулей используй её и исторический справочник `larix_nexus/architecture.md`; этот файл не должен дублировать их целиком.

## 2. Роль GPT-5.5

GPT-5.5 в этом проекте работает как:

- архитектор: определяет правильную зону проекта, границы изменений и риски;
- ревьюер: проверяет diff, регрессии, off-target изменения, секреты и runtime-артефакты;
- постановщик задач: превращает обычное описание пользователя в точное ТЗ;
- генератор промтов для более слабой модели-исполнителя;
- контролёр качества результата: задаёт критерии проверки и принимает работу после выполнения.

GPT-5.5 не должна сама вносить изменения в код проекта, если пользователь просит разработку. Даже для малых точечных правок сначала нужно подготовить точное ТЗ/промт для модели-исполнителя, указать файлы, ограничения, риски и проверки. Исключение: пользователь явно просит GPT-5.5 изменить документацию/инструкцию или прямо пишет, что GPT-5.5 должна внести правку сама.

## 3. Как пользователь будет работать

1. Пользователь в новом чате пишет: `Посмотри docs/GPT55_PROJECT_ENTRYPOINT.md`.
2. Затем пользователь пишет задачу обычными словами.
3. GPT-5.5 уточняет только критически недостающие данные.
4. GPT-5.5 формирует промт для слабой модели-исполнителя.
5. После выполнения слабой моделью GPT-5.5 проверяет diff, ответ или код по рискам и критериям готовности.

## 4. Краткое описание проекта

Larix Nexus Desktop — Windows-oriented desktop-приложение на Python/PySide6 для работы с облачной платформой Larix. Основные сценарии: авторизация, выбор workspace/project, просмотр дерева папок и таблицы файлов, upload/download документов, публичные ссылки, сравнение PDF-версий, уведомления по папкам и двусторонняя синхронизация локальной папки с облаком.

В проекте также есть отдельный Telegram-бот в `telegram_bot/`, который частично дублирует API-логику desktop-клиента: login, навигация по проектам/папкам, upload/download, подписки и сервисные команды.

Запуск desktop: `python main.py`. Dry-run синхронизации: `python main.py --dry-run <FOLDER_ID> --project-id <ID> --local-root <PATH>`. Сборка EXE: `build.bat` или `Larix_Nexus.spec` через PyInstaller. Автоматических тестов в репозитории не найдено; проверки в основном smoke/manual.

## 5. Карта структуры проекта

| Путь | Назначение | Когда смотреть | Риск изменений |
|---|---|---|---|
| `docs/project-architecture.md` | Основная подробная карта проекта и маршруты задач | Перед любой нетривиальной задачей | Низкий, но не превращать в dump дерева |
| `main.py` | Entrypoint desktop: SSL patch, logging, CLI dry-run, Qt app, MainWindow, auto-login | Startup, запуск, dry-run, crash/init issues | Высокий |
| `larix_nexus/api/client.py` | Единый HTTP-клиент Larix Platform API: auth, projects, folders, documents, upload/download, links, cache/retry | Любые API/auth/file operations | Высокий |
| `larix_nexus/api/request_specs.py` | Централизованные API paths и payload builders | Изменения контрактов API | Высокий |
| `larix_nexus/ui/main_window.py` | Главное окно PySide6, большой монолит | UI-задачи, версии/PDF, основные сценарии | Очень высокий |
| `larix_nexus/ui/__init__.py` | Injection pattern: подключает UI-модули к `MainWindow` | Если метод MainWindow не найден или добавляется UI-модуль | Высокий |
| `larix_nexus/ui/` | UI-модули: tree/table/context menus/upload/download/sync/theme | UI и сценарии пользователя | Средний/высокий |
| `larix_nexus/sync/engine.py` | Ядро синхронизации: scan, compare, plan, execute | Sync conflicts, upload/download/delete logic | Высокий |
| `larix_nexus/sync/manager.py` | FolderSyncManager, Qt workers, periodic sync, tombstones, mass-delete protection | Background sync, mappings, retry/deletion guards | Очень высокий |
| `larix_nexus/sync/state.py` | JSON state синхронизации | State paths, migration, snapshots | Средний |
| `larix_nexus/models/` | Qt-модели таблиц файлов и tombstones | Колонки, отображение файлов, иконки | Средний |
| `larix_nexus/notifications/manager.py` | JSON-хранилище уведомлений и legacy SQLite migration | Подписки и badges уведомлений | Средний |
| `larix_nexus/pdf/PDF_Compare.py` | Отдельное окно сравнения PDF через PyMuPDF/OpenCV/Pillow | PDF compare, версии документов | Высокий |
| `larix_nexus/utils/` | Paths, settings, keyring, logging, theme, crash diagnostics, Qt patches | Инфраструктура, секреты, тема, OS/Qt fixes | Средний/высокий |
| `larix_nexus/utils/theme.py` | Большой модуль темизации и QSS/Qt patches | Dark/light theme, style regressions | Очень высокий |
| `larix_nexus/constants.py` | Глобальные константы, env vars, paths, QSS, icon paths | Config, env, UI constants | Средний |
| `larix_nexus/style_tokens.py`, `larix_nexus/app_style_overrides.py` | Токены и overrides стилей | Визуальные правки | Средний |
| `telegram_bot/bot.py` | Основной Telegram-бот, самостоятельный API flow, upload helper, states | Любые задачи по боту | Высокий |
| `telegram_bot/bot_proxy.py` | Вариант бота с proxy-настройками | Proxy-specific bot tasks | Высокий |
| `telegram_bot/.env`, `*.db`, `*.log` | Runtime config/artifacts | Обычно не читать и не выводить | Секреты/артефакты, не трогать |
| `build.bat`, `Larix_Nexus.spec` | PyInstaller build/deploy | Сборка EXE, ресурсы | Средний |
| `.cursor/` | Rules and command memory для Cursor | Правила работы LLM и ревью | Низкий |
| `icon/` | Иконки и ресурсы | Только задачи про ресурсы/сборку | Низкий, бинарники |
| `build/`, `dist/`, `Nexus_downloads/`, `__pycache__/`, `*.log`, `*.db`, `nul` | Generated/runtime/user artifacts | Не сканировать без прямой причины | Не менять/не коммитить |

## 6. Архитектурные зоны

### UI / frontend

Назначение: PySide6 desktop UI, главное окно, дерево папок, таблица файлов, меню, drag-and-drop, upload/download dialogs, тема.

Основные файлы: `larix_nexus/ui/main_window.py`, `larix_nexus/ui/__init__.py`, `tree_operations.py`, `table_operations.py`, `folder_actions.py`, `file_ops.py`, `upload_operations.py`, `download_operations.py`, `context_menus.py`, `dialogs.py`, `delegates.py`, `widgets.py`, `theme_operations.py`.

Можно менять: точечные обработчики в соответствующих inject-модулях, UI-тексты, локальную логику меню/таблицы/дерева.

Менять осторожно: `main_window.py`, порядок injections в `ui/__init__.py`, сигналы/методы, на которые опираются другие UI-модули.

Типичные задачи: добавить пункт меню, исправить отображение таблицы, починить drag/drop, изменить upload/download flow, проверить версии/PDF compare integration.

### Backend / API

Назначение: HTTP-взаимодействие с Larix Platform API, авторизация, refresh token, CRUD папок/документов, upload/download, публичные ссылки.

Основные файлы: `larix_nexus/api/client.py`, `larix_nexus/api/request_specs.py`, `larix_nexus/constants.py`, `larix_nexus/utils/keyring.py`, `larix_nexus/utils/settings.py`.

Можно менять: endpoint constants и payload builders в `request_specs.py`, локальные методы API-клиента под конкретный контракт.

Менять осторожно: auth flow, keyring keys, retries/timeouts, cache invalidation, upload multipart fields. При изменении контрактов проверить `telegram_bot/bot.py`, потому что бот дублирует часть API.

Типичные задачи: новый endpoint, исправить payload, обработать 401/refresh, изменить upload/download/version logic.

### Orchestration / sync executor

Назначение: двусторонняя синхронизация local/cloud, план операций, выполнение upload/download/delete, retry failed operations, tombstones, mass-delete protection.

Основные файлы: `larix_nexus/sync/engine.py`, `larix_nexus/sync/manager.py`, `larix_nexus/sync/state.py`, `larix_nexus/ui/sync_handlers.py`.

Можно менять: локальные правила compare/plan при понятном сценарии, dry-run diagnostics, UI wiring для sync actions.

Менять осторожно: deletion logic, tombstones, mass-delete thresholds, state format, QThread workers, failed-op markers.

Типичные задачи: конфликт синхронизации, файл повторно загружается/удаляется, dry-run показывает неправильный plan, не срабатывает retry.

### RAG / indexing / retrieval

Dedicated LLM/RAG subsystem не найден. Индексация в смысле LLM-поиска отсутствует. Есть только runtime state/cache для API, sync и notifications.

Основные файлы: `larix_nexus/sync/state.py`, `%APPDATA%\LarixNexus\state\*.json`, `%APPDATA%\LarixNexus\settings.json`, `larix_nexus/notifications/manager.py`.

Можно менять: документацию и безопасные state helpers.

Менять осторожно: форматы persisted JSON и migration legacy SQLite.

Типичные задачи: восстановить состояние sync/notifications, описать где хранится память приложения.

### Tools / integrations

Назначение: PDF compare, Telegram bot, OS integration, keyring, PyInstaller resource handling.

Основные файлы: `larix_nexus/pdf/PDF_Compare.py`, `larix_nexus/widgets/ThemeToggle.py`, `telegram_bot/bot.py`, `telegram_bot/bot_proxy.py`, `larix_nexus/utils/paths.py`, `larix_nexus/utils/helpers.py`.

Можно менять: локальные исправления инструмента или интеграции.

Менять осторожно: hardcoded/bot secrets не выводить; proxy/token/env handling не раскрывать; PDF compare большой и независимый.

Типичные задачи: исправить сравнение PDF, upload в Telegram-боте, single-instance lock, proxy bot, open-in-OS.

### Configuration

Назначение: env vars, настройки приложения, keyring, paths, constants, theme keys.

Основные файлы: `larix_nexus/constants.py`, `larix_nexus/utils/settings.py`, `larix_nexus/utils/keyring.py`, `larix_nexus/utils/paths.py`, `.gitignore`, `telegram_bot/.env.example`.

Можно менять: `.env.example`, документацию env vars, безопасные defaults.

Менять осторожно: `.env`, токены, keyring service/keys, `BASE_URL`, `DOWNLOAD_DIR`, persisted settings paths.

Типичные задачи: добавить env var, изменить default path, починить resource path в frozen/dev mode.

### Documentation / memory

Назначение: LLM-навигация, архитектурные заметки, команды Cursor, historical bugfix docs.

Основные файлы: `docs/project-architecture.md`, `docs/GPT55_PROJECT_ENTRYPOINT.md`, `larix_nexus/architecture.md`, `.cursor/rules/project.mdc`, `.cursor/commands/*.md`, `BUGFIX_SERVICE_COMMANDS.md`, `RESTART_UX_FIX.md`.

Можно менять: `docs/GPT55_PROJECT_ENTRYPOINT.md` и точечные обновления `docs/project-architecture.md` после структурных изменений.

Менять осторожно: исторические багфикс-документы и `larix_nexus/architecture.md`; лучше ссылаться, чем переписывать.

Типичные задачи: обновить карту проекта, подготовить prompt для исполнителя, review diff по scope.

### Build / deploy

Назначение: сборка desktop EXE через PyInstaller.

Основные файлы: `build.bat`, `Larix_Nexus.spec`, `main.py`, `icon/`.

Можно менять: add-data, icon/resource paths, PyInstaller options.

Менять осторожно: hardcoded absolute paths в spec, generated `build/` и `dist/` не редактировать вручную.

Типичные задачи: не попали иконки в EXE, сломалась frozen-сборка, изменить название/иконку приложения.

### Tests / verification

Назначение: автоматических тестов не найдено; используются smoke/manual checks.

Основные проверки: `python main.py`, `python main.py --dry-run <FOLDER_ID> --project-id <ID> --local-root <PATH>`, `python -B -m py_compile <changed_files>`, `python telegram_bot/bot.py`, `build.bat`, `larix_nexus/STYLE_REGRESSION_CHECKLIST.md`.

Можно менять: добавить тесты или requirements только отдельной задачей.

Менять осторожно: не считать отсутствие автотестов успешной проверкой; для UI/API/sync нужны ручные критерии.

Типичные задачи: составить smoke-plan, проверить syntax, проверить GUI сценарий.

## 7. Правила для GPT-5.5

- Сначала читать этот файл, затем при необходимости `docs/project-architecture.md`.
- Не сканировать весь проект без необходимости.
- Для задачи выбирать минимальный набор файлов по зоне и маршрутам из `docs/project-architecture.md`.
- Не делать unrelated refactor.
- Не менять архитектуру без явного запроса.
- Не удалять существующую логику без объяснения.
- Не трогать секреты, `.env`, keyring, токены, пароли и приватные данные.
- Не выводить значения секретов; если найден секрет, писать только: `observed hardcoded secret in <path>, value not disclosed`.
- Не менять формат публичных API без предупреждения и проверки `telegram_bot/bot.py`.
- Для рискованных изменений сначала давать план.
- Если задача связана с изменением кода проекта — выдавать промт для модели-исполнителя, а не реализацию, даже если изменение маленькое.
- Самостоятельно редактировать файлы только при явной просьбе пользователя или при правке документации/инструкций вроде этого файла.
- Учитывать high-risk файлы: `larix_nexus/ui/main_window.py`, `larix_nexus/sync/manager.py`, `larix_nexus/utils/theme.py`, `larix_nexus/pdf/PDF_Compare.py`, `larix_nexus/api/client.py`.
- Не сканировать и не коммитить runtime/generated зоны: `.git/`, `build/`, `dist/`, `__pycache__/`, `*.pyc`, `*.log`, `*.db`, `Nexus_downloads/`, local PDFs/DOCX/XLSX, `nul`.

## 8. Формат ответа GPT-5.5 на обычную задачу пользователя

### Краткое понимание задачи

1-3 предложения: что пользователь хочет изменить/проверить и какой сценарий затронут.

### Какие файлы/зоны нужно смотреть

Список конкретных путей. Начинать с 2-5 файлов, не с полного проекта.

### Риски

Кратко указать high-risk файлы, API-contract risk, persisted state risk, secrets/runtime artifacts risk или отсутствие автотестов.

### Промт для слабой модели

Готовый промт в отдельном code block. Он должен быть самодостаточным: контекст, файлы, задача, ограничения, порядок работы, проверки.

### Критерии проверки

Список признаков корректного результата: syntax/smoke commands, ручной UI/API сценарий, отсутствие unrelated diff, отсутствие секретов и runtime artifacts.

## 9. Шаблон промта для слабой модели

```text
Ты модель-исполнитель. Работай строго по задаче ниже.

Контекст проекта:
[краткое описание проекта]

Нужно изменить:
[конкретные файлы/зоны]

Задача:
[что сделать]

Ограничения:
- не делать unrelated refactor;
- не менять публичные интерфейсы без необходимости;
- не удалять существующую логику;
- не трогать секреты и env-файлы;
- сохранять текущий стиль проекта;
- если нужно изменить архитектуру — сначала явно объяснить почему.

Порядок работы:
1. Прочитай указанные файлы.
2. Найди минимальное место изменения.
3. Предложи план.
4. Внеси изменения.
5. Покажи diff или список изменённых файлов.
6. Укажи, как проверить результат.

Критерии готовности:
- [критерий 1]
- [критерий 2]
- [критерий 3]

Если данных не хватает:
- не выдумывай;
- явно напиши, чего не хватает;
- предложи минимальный безопасный вариант.
```
