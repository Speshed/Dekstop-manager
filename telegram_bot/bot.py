import os
import sys
import time
import logging
import re
import uuid
import json
import html
import sqlite3
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
    from telegram.error import TimedOut, NetworkError, Conflict
    from telegram.ext import JobQueue
except ImportError:
    raise ImportError("python-telegram-bot не установлен. Установите: pip install python-telegram-bot")

try:
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

import requests
import tempfile

try:
    from requests_toolbelt.multipart.encoder import MultipartEncoder
except ImportError:
    MultipartEncoder = None


def sanitize_upload_filename(filename: str) -> str:
    invalid = '<>:"/\\|?*'
    safe = "".join("_" if ch in invalid else ch for ch in (filename or ""))
    safe = safe.strip().strip(".")
    return safe or "upload.bin"


def upload_document(
    *,
    base_url: str,
    token: str,
    folder_id: int | str,
    local_path: str,
    filename: str,
    document_type_id: int | str | None = None,
    max_retries: int = 3,
    refresh_callback=None,
):
    result = {
        "success": False,
        "status": 0,
        "body": "",
        "response": None,
    }

    folder_id_str = str(folder_id or "").strip()
    if not token or not folder_id_str or not os.path.exists(local_path):
        return result

    safe_filename = sanitize_upload_filename(filename)

    doc_type = document_type_id
    try:
        if doc_type is None:
            doc_type = 100
        doc_type = str(int(str(doc_type).strip()))
    except Exception:
        doc_type = "100"

    metadata_json = json.dumps(
        {"files": [{"fileName": safe_filename, "documentType": doc_type}]},
        ensure_ascii=False,
    )
    url = f"{base_url.rstrip('/')}/api/document/upload/{folder_id_str}"

    for attempt in range(max_retries):
        try:
            headers = {"accept": "*/*", "Authorization": f"Bearer {token}"}
            with open(local_path, "rb") as f:
                if MultipartEncoder is not None:
                    enc = MultipartEncoder(
                        fields={
                            "metadata": metadata_json,
                            "file": (safe_filename, f, "application/octet-stream"),
                        }
                    )
                    req_headers = {**headers, "Content-Type": enc.content_type}
                    response = requests.post(url, headers=req_headers, data=enc, timeout=120)
                else:
                    files = {"file": (safe_filename, f, "application/octet-stream")}
                    data = {"metadata": metadata_json}
                    response = requests.post(url, headers=headers, files=files, data=data, timeout=120)

            result["status"] = int(response.status_code)
            result["body"] = response.text[:2048] if response.text else ""
            try:
                result["response"] = response.json()
            except Exception:
                result["response"] = None

            if result["status"] == 401 and attempt == 0 and refresh_callback and refresh_callback():
                token = refresh_callback.__self__.token if hasattr(refresh_callback, "__self__") else token
                continue

            if 200 <= result["status"] <= 201:
                payload = result["response"]
                if isinstance(payload, list) and payload:
                    result["success"] = bool(payload[0].get("success", True))
                else:
                    result["success"] = True
                return result

            return result
        except requests.Timeout:
            result["status"] = 0
            result["body"] = "Timeout"
            if attempt < max_retries - 1:
                time.sleep(1)
                continue
            return result
        except requests.RequestException as exc:
            result["status"] = result.get("status", 0) or 0
            result["body"] = str(exc)[:2048]
            return result
        except Exception as exc:
            result["status"] = result.get("status", 0) or 0
            result["body"] = str(exc)[:2048]
            return result

    return result

BASE_URL = os.environ.get("LARIX_BASE_URL", "https://platform-api.larix.ru").rstrip("/")
WEB_BASE_URL = os.environ.get("LARIX_WEB_BASE_URL", "https://platform.larix.ru").rstrip("/")
BOT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BOT_DIR, "subscriptions.db")
DOWNLOAD_DIR = os.path.join(BOT_DIR, "Nexus_downloads")
CACHE_TTL_SEC = 600
APPROVALS_POLL_INTERVAL_SEC = max(10, int(os.environ.get("LARIX_APPROVALS_POLL_INTERVAL_SEC", "30")))
APPROVALS_HTTP_TIMEOUT_SEC = max(5, int(os.environ.get("LARIX_APPROVALS_HTTP_TIMEOUT_SEC", "12")))
APPROVALS_HTTP_RETRIES = max(0, int(os.environ.get("LARIX_APPROVALS_HTTP_RETRIES", "2")))

WAITING_FOR_LOGIN = "waiting_for_login"
WAITING_FOR_PASSWORD = "waiting_for_password"
SELECTING_WORKSPACE = "selecting_workspace"
SELECTING_PROJECT = "selecting_project"
IN_EXPLORER = "in_explorer"
AWAITING_UPLOAD = "awaiting_upload"

STATS_PROJECT = "stats_project"
BACK_TO_EXPLORER = "back_to_explorer"
TOGGLE_NOTIFY = "toggle_notify"

BOT_TOKEN = "592469309:AAE7wGnOU7ejSCeUc-beWzHj8Rlss1nbKJg"
if not BOT_TOKEN or len(BOT_TOKEN) < 10:
    raise RuntimeError("❌ Bot token is missing or invalid.")

os.makedirs(BOT_DIR, exist_ok=True)

# Очищаем лог-файл при запуске бота
log_path = os.path.join(BOT_DIR, "bot.log")
if os.path.exists(log_path):
    with open(log_path, 'w', encoding="utf-8") as f:
        pass  # Открытие в режиме 'w' автоматически очищает файл

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_path, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

STATUS_TRANSLATIONS = {
    "ru": {
        "draft": "Черновик",
        "published": "Опубликовано",
        "archived": "Архив",
        "deleted": "Удалено",
        "active": "Активно",
        "pending": "На рассмотрении",
        "InDevelopment": "В разработке",
        "Development": "В разработке",
        "InProgress": "В работе",
        "Review": "На проверке",
        "Approved": "Согласован",
        "Rejected": "Отклонен",
        "Completed": "Завершено",
        "processing": "В обработке",
        "ready": "Готово",
        "new": "Новый",
    },
    "en": {
        "draft": "Draft",
        "published": "Published",
        "archived": "Archive",
        "deleted": "Deleted",
        "active": "Active",
        "pending": "Pending",
        "InDevelopment": "In Development",
        "Development": "In Development",
        "InProgress": "In Progress",
        "Review": "Review",
        "Approved": "Approved",
        "Rejected": "Rejected",
        "Completed": "Completed",
        "processing": "Processing",
        "ready": "Ready",
        "new": "New",
    }
}

TYPE_TRANSLATIONS = {
    "ru": {
        "file": "Файл",
        "folder": "Папка",
    },
    "en": {
        "file": "File",
        "folder": "Folder",
    }
}

def translate_status(status_value, lang: str = "ru") -> str:
    if status_value is None:
        return t(None, "undefined") if lang == "en" else "Не определен"
    raw = str(status_value).strip()
    if not raw:
        return t(None, "undefined") if lang == "en" else "Не определен"
    
    translations = STATUS_TRANSLATIONS.get(lang, STATUS_TRANSLATIONS.get("ru", {}))
    translated = translations.get(raw) or translations.get(raw.lower())
    return translated if translated else raw

def translate_type(type_value, lang: str = "ru") -> str:
    if type_value is None:
        return type_value
    raw = str(type_value).strip()
    if not raw:
        return raw
    
    translations = TYPE_TRANSLATIONS.get(lang, TYPE_TRANSLATIONS.get("ru", {}))
    translated = translations.get(raw) or translations.get(raw.lower())
    return translated if translated else raw

TRANSLATIONS = {
    "ru": {
        "welcome": "🎯 Добро пожаловать!\n\nВведите ваш логин:",
        "login_accepted": "Логин '{username}' принят.\nТеперь введите пароль:",
        "logging_in": "🔐 Выполняю вход...",
        "login_success": "✅ Вход выполнен!",
        "login_success_auto_ws": "✅ Вход выполнен!\nАвтоматически выбрано пространство: {ws_name}\nЗагружаю проекты...",
        "login_success_loading": "✅ Вход выполнен!\nЗагружаю проекты...",
        "login_error": "❌ Ошибка авторизации. Проверьте логин и пароль.\nВведите логин снова:",
        "select_workspace": "Выберите пространство:",
        "select_project": "Выберите проект:",
        "select_new_project": "Выберите новый проект:",
        "projects_load_error": "❌ Не удалось загрузить список проектов.",
        "workspaces_load_error": "❌ Не удалось загрузить список пространств.",
        "workspace_selected": "✅ Выбрано пространство: *{ws_name}*\nЗагружаю проекты...",
        "project_selected": "✅ Выбран проект: *{project_name}*\nЗагружаю структуру...",
        "project_load_error": "❌ Не удалось загрузить структуру проекта.",
        "project_empty": "📂 Проект пуст. В нем нет папок и файлов.",
        "project_not_found": "❌ Проект не найден.",
        "no_project_data": "❌ Нет данных проекта.",
        "back": "🔙 Назад",
        "back_to": "🔙 Назад",
        "statistics": "📊 Статистика",
        "refresh": "🔄 Обновить",
        "change_projects": "🗂️ Сменить проекты",
        "change_workspace": "🏢 Сменить пространство",
        "upload_file": "📤 Загрузить файл",
        "subscribe": "🔔 Подписаться",
        "unsubscribe": "🔕 Отписаться",
        "unsubscribed": "🔕 Вы отписались от уведомлений по папке: *{folder_name}*",
        "subscribed": "🔔 Вы подписались на уведомления по папке: *{folder_name}*",
        "root": "Корень",
        "folder_empty": "📂 Папка пуста",
        "folders_files": "Папок: {folders} | Файлов: {files}",
        "project_stats": "📊 *Статистика проекта*\n\n📁 Проект: *{project_name}*\n📄 Всего документов: *{count}*\n\nНажмите 'Назад', чтобы вернуться.",
        "send_file_to_upload": "📥 Теперь отправьте файл как *документ* (не фото!), чтобы загрузить его в эту папку.",
        "preparing_file": "⏳ Подготавливаю файл '{filename}'...",
        "uploading_to": "📤 Загружаю в папку ID={folder_id}...",
        "upload_success": "✅ {message}",
        "upload_error": "❌ Не удалось загрузить файл: {error}",
        "project_required": "❌ Не удалось определить проект.",
        "logout_success": "✅ Вы вышли из системы.\nВведите логин:",
        "unsubscribed_count": "🔕 Отписано от {count} папок.",
        "select_project_first": "❌ Сначала выберите проект.",
        "language_switched": "✅ Язык изменён на {lang_name}.",
        "language_ru": "🇷🇺 Русский",
        "language_en": "🇬🇧 English",
        "use_start": "Используйте /start для перезапуска.",
        "session_expired": "❌ Сессия истекла. Выполните вход заново.",
        "api_client_unavailable": "❌ API-клиент недоступен.",
        "workspace_switch_error": "❌ Не удалось переключить пространство.",
        "invalid_workspace_id": "❌ Некорректный ID пространства.",
        "invalid_project_id": "❌ Некорректный ID проекта.",
        "error_back": "❌ Ошибка при возврате. Попробуйте снова.",
        "downloading_file": "⏳ Скачиваю файл: {filename}...",
        "file_sent": "✅ Файл отправлен: {filename}",
        "file_too_big": "❌ Файл слишком большой для Telegram ({size:.1f} МБ)\nФайл скачан в: {path}",
        "download_error": "❌ Не удалось скачать файл.",
        "incorrect_params": "❌ Некорректные параметры.",
        "incorrect_ids": "❌ Некорректные ID в параметрах.",
        "approval_files_title": "📎 <b>Файлы согласования</b>\n\n",
        "approval_process": "Согласование: <b>{title}</b>",
        "no_files_found": "Файлы не найдены.",
        "select_file_download": "Выберите файл для скачивания:",
        "new_approval_stage": "🔔 <b>Новый этап согласования</b>\n\nОткройте карточку согласования по ссылке ниже.",
        "kb_restart": "🔄 Перезапуск бота",
        "kb_language": "🌐 RU/EN",
        "no_name": "Без имени",
        "no_title": "Без названия",
        "date_unknown": "Дата неизвестна",
        "undefined": "Не определен",
        "not_specified": "Не указаны",
        "process_id": "Процесс {id}",
        "stage_id": "Этап {id}",
        "click_to_download": "Нажмите, чтобы скачать:",
        "download_btn": "📥 Скачать",
        "version": "Версия",
        "created_by": "Кем создано",
        "modified_by": "Кем изменено",
        "created_at": "Создано",
        "updated_at": "Обновлено",
        "status": "Статус",
        "type": "Тип",
        "folder_not_found": "❌ Папка не найдена.",
        "file_not_found": "❌ Файл не найден.",
        "invalid_folder_id": "❌ Некорректный ID папки.",
        "invalid_file_id": "❌ Некорректный ID файла.",
        "invalid_document_id": "❌ Некорректный ID документа.",
        "error_refresh": "❌ Ошибка при обновлении. Попробуйте снова.",
        "error_open_folder": "❌ Ошибка при открытии папки. Попробуйте снова.",
        "approval_files_list_error": "❌ Не удалось получить список файлов согласования.",
        "approval_params_error": "❌ Некорректные параметры списка файлов.",
        "approval_back_params_error": "❌ Некорректные параметры возврата.",
        "approval_download_params_error": "❌ Некорректные параметры скачивания.",
        "new_file": "Новый файл",
        "updated_file": "Обновлённый файл",
        "deleted_file": "Удалённый файл",
        "file_label": "Файл",
        "folder_notification": "🔔 <b>Уведомление по папке «{path}»</b>",
        "more_changes": "… и ещё {count} изменений.",
        "job_queue_unavailable": "⚠️ Job queue недоступен. Уведомления отключены.",
        "approval_notification": "Согласование: <b>{title}</b>\nЭтап: <b>{step}</b>\nДокументы: <b>{documents}</b>\nСсылка: <a href=\"{link}\">открыть</a>",
        "documents_not_specified": "Не указаны",
        "download_file_btn": "📥 Скачать файл",
    },
    "en": {
        "welcome": "🎯 Welcome!\n\nEnter your login:",
        "login_accepted": "Login '{username}' accepted.\nNow enter your password:",
        "logging_in": "🔐 Logging in...",
        "login_success": "✅ Login successful!",
        "login_success_auto_ws": "✅ Login successful!\nAutomatically selected workspace: {ws_name}\nLoading projects...",
        "login_success_loading": "✅ Login successful!\nLoading projects...",
        "login_error": "❌ Login failed. Check your credentials.\nEnter login again:",
        "select_workspace": "Select workspace:",
        "select_project": "Select project:",
        "select_new_project": "Select new project:",
        "projects_load_error": "❌ Failed to load project list.",
        "workspaces_load_error": "❌ Failed to load workspace list.",
        "workspace_selected": "✅ Selected workspace: *{ws_name}*\nLoading projects...",
        "project_selected": "✅ Selected project: *{project_name}*\nLoading structure...",
        "project_load_error": "❌ Failed to load project structure.",
        "project_empty": "📂 Project is empty. It has no folders or files.",
        "project_not_found": "❌ Project not found.",
        "no_project_data": "❌ No project data.",
        "back": "🔙 Back",
        "back_to": "🔙 Back",
        "statistics": "📊 Statistics",
        "refresh": "🔄 Refresh",
        "change_projects": "🗂️ Change project",
        "change_workspace": "🏢 Change workspace",
        "upload_file": "📤 Upload file",
        "subscribe": "🔔 Subscribe",
        "unsubscribe": "🔕 Unsubscribe",
        "unsubscribed": "🔕 You unsubscribed from folder: *{folder_name}*",
        "subscribed": "🔔 You subscribed to folder: *{folder_name}*",
        "root": "Root",
        "folder_empty": "📂 Folder is empty",
        "folders_files": "Folders: {folders} | Files: {files}",
        "project_stats": "📊 *Project statistics*\n\n📁 Project: *{project_name}*\n📄 Total documents: *{count}*\n\nPress 'Back' to return.",
        "send_file_to_upload": "📥 Now send a file as a *document* (not photo!) to upload it to this folder.",
        "preparing_file": "⏳ Preparing file '{filename}'...",
        "uploading_to": "📤 Uploading to folder ID={folder_id}...",
        "upload_success": "✅ {message}",
        "upload_error": "❌ Failed to upload file: {error}",
        "project_required": "❌ Could not determine project.",
        "logout_success": "✅ You are logged out.\nEnter login:",
        "unsubscribed_count": "🔕 Unsubscribed from {count} folders.",
        "select_project_first": "❌ Select a project first.",
        "language_switched": "✅ Language changed to {lang_name}.",
        "language_ru": "🇷🇺 Русский",
        "language_en": "🇬🇧 English",
        "use_start": "Use /start to restart.",
        "session_expired": "❌ Session expired. Please login again.",
        "api_client_unavailable": "❌ API client unavailable.",
        "workspace_switch_error": "❌ Failed to switch workspace.",
        "invalid_workspace_id": "❌ Invalid workspace ID.",
        "invalid_project_id": "❌ Invalid project ID.",
        "error_back": "❌ Error going back. Please try again.",
        "downloading_file": "⏳ Downloading file: {filename}...",
        "file_sent": "✅ File sent: {filename}",
        "file_too_big": "❌ File too big for Telegram ({size:.1f} MB)\nFile downloaded to: {path}",
        "download_error": "❌ Failed to download file.",
        "incorrect_params": "❌ Incorrect parameters.",
        "incorrect_ids": "❌ Incorrect IDs in parameters.",
        "approval_files_title": "📎 <b>Approval files</b>\n\n",
        "approval_process": "Approval: <b>{title}</b>",
        "no_files_found": "No files found.",
        "select_file_download": "Select file to download:",
        "new_approval_stage": "🔔 <b>New approval stage</b>\n\nOpen the approval card via the link below.",
        "kb_restart": "🔄 Restart bot",
        "kb_language": "🌐 RU/EN",
        "no_name": "No name",
        "no_title": "No title",
        "date_unknown": "Date unknown",
        "undefined": "Undefined",
        "not_specified": "Not specified",
        "process_id": "Process {id}",
        "stage_id": "Stage {id}",
        "click_to_download": "Click to download:",
        "download_btn": "📥 Download",
        "version": "Version",
        "created_by": "Created by",
        "modified_by": "Modified by",
        "created_at": "Created",
        "updated_at": "Updated",
        "status": "Status",
        "type": "Type",
        "folder_not_found": "❌ Folder not found.",
        "file_not_found": "❌ File not found.",
        "invalid_folder_id": "❌ Invalid folder ID.",
        "invalid_file_id": "❌ Invalid file ID.",
        "invalid_document_id": "❌ Invalid document ID.",
        "error_refresh": "❌ Error refreshing. Please try again.",
        "error_open_folder": "❌ Error opening folder. Please try again.",
        "approval_files_list_error": "❌ Failed to get approval files list.",
        "approval_params_error": "❌ Invalid file list parameters.",
        "approval_back_params_error": "❌ Invalid back parameters.",
        "approval_download_params_error": "❌ Invalid download parameters.",
        "new_file": "New file",
        "updated_file": "Updated file",
        "deleted_file": "Deleted file",
        "file_label": "File",
        "folder_notification": "🔔 <b>Notification for folder «{path}»</b>",
        "more_changes": "… and {count} more changes.",
        "job_queue_unavailable": "⚠️ Job queue unavailable. Notifications disabled.",
        "approval_notification": "Approval: <b>{title}</b>\nStage: <b>{step}</b>\nDocuments: <b>{documents}</b>\nLink: <a href=\"{link}\">open</a>",
        "documents_not_specified": "Not specified",
        "download_file_btn": "📥 Download file",
    }
}

def get_main_reply_keyboard(chat_id: int) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(t(chat_id, "kb_restart")), KeyboardButton(t(chat_id, "kb_language"))],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

def get_user_language(chat_id: int) -> str:
    try:
        conn = sqlite3.connect(BOT_DATA_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT language FROM user_settings WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        conn.close()
        if row and row[0] in ("ru", "en"):
            return row[0]
    except Exception as e:
        logger.error(f"Error getting user language: {e}")
    return "ru"

def set_user_language(chat_id: int, language: str):
    try:
        conn = sqlite3.connect(BOT_DATA_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO user_settings (chat_id, language)
            VALUES (?, ?)
        """, (chat_id, language))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error setting user language: {e}")

def t(chat_id, key: str, **kwargs) -> str:
    if chat_id is None:
        lang = "ru"
    else:
        lang = get_user_language(chat_id)
    translations = TRANSLATIONS.get(lang, TRANSLATIONS.get("ru", {}))
    text = translations.get(key, TRANSLATIONS.get("ru", {}).get(key, key))
    if kwargs:
        try:
            text = text.format(**kwargs)
        except KeyError:
            pass
    return text

import re as _re

SERVICE_COMMAND_PATTERNS = {
    "restart": [
        r"^.*?restart\s*bot",
        r"^.*?перезапуск\s*бота",
        r"^restart\s*bot",
        r"^перезапуск\s*бота",
        r"^.*?перезапускбота",
        r"^перезапускбота",
    ],
    "language": [
        r"^.*?ru\s*/\s*en",
        r"^.*?en\s*/\s*ru",
        r"^ru\s*/\s*en",
        r"^en\s*/\s*ru",
        r"^ruen",
        r"^enru",
        r"^ru\s*en",
        r"^en\s*ru",
    ],
}

def normalize_service_command(text: str) -> tuple[Optional[str], str]:
    """
    Нормализует текст сообщения и проверяет, является ли он служебной командой.
    Возвращает (command_type, normalized_text) или (None, normalized_text).
    """
    if not text:
        return None, ""
    
    original = text
    normalized = text.strip()
    
    # Удаляем variation selectors
    normalized = _re.sub(r"[\ufe00-\ufe0f]", "", normalized)
    
    # Нормализуем пробелы
    normalized = _re.sub(r"\s+", " ", normalized).strip()
    
    # Сохраняем для логирования
    normalized_for_log = normalized
    
    # Приводим к нижнему регистру для паттернов
    normalized_lower = normalized.lower()
    
    # Удаляем лишние символы, но оставляем буквы, цифры, пробелы и разделители
    normalized_lower = _re.sub(r"[^\w\s/а-яё]", "", normalized_lower)
    
    # Проверяем паттерны
    for cmd_type, patterns in SERVICE_COMMAND_PATTERNS.items():
        for pattern in patterns:
            if _re.search(pattern, normalized_lower, _re.IGNORECASE):
                logger.debug(f"🔍 Service command detected: cmd_type={cmd_type}, original='{original}', normalized='{normalized_for_log}', pattern='{pattern}'")
                return cmd_type, normalized
    
    logger.debug(f"🔍 Not a service command: original='{original}', normalized='{normalized_for_log}'")
    return None, normalized

async def safe_send_message(bot, chat_id, text, **kwargs):
    """Безопасная отправка сообщения с повторными попытками при тайм-ауте."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        except TimedOut:
            if attempt < max_retries - 1:
                logger.warning(f"Тайм-аут отправки сообщения, попытка {attempt + 1}/{max_retries}")
                time.sleep(1)
                continue
            else:
                logger.error(f"Не удалось отправить сообщение после {max_retries} попыток")
                raise
        except NetworkError:
            if attempt < max_retries - 1:
                logger.warning(f"Ошибка сети при отправке сообщения, попытка {attempt + 1}/{max_retries}")
                time.sleep(1)
                continue
            else:
                logger.error(f"Не удалось отправить сообщение после {max_retries} попыток")
                raise

async def safe_send_document(bot, chat_id, document, **kwargs):
    """Безопасная отправка документа с повторными попытками при тайм-ауте."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return await bot.send_document(chat_id=chat_id, document=document, **kwargs)
        except TimedOut:
            if attempt < max_retries - 1:
                logger.warning(f"Тайм-аут отправки документа, попытка {attempt + 1}/{max_retries}")
                time.sleep(2)
                continue
            else:
                logger.error(f"Не удалось отправить документ после {max_retries} попыток")
                raise
        except NetworkError:
            if attempt < max_retries - 1:
                logger.warning(f"Ошибка сети при отправке документа, попытка {attempt + 1}/{max_retries}")
                time.sleep(2)
                continue
            else:
                logger.error(f"Не удалось отправить документ после {max_retries} попыток")
                raise

async def safe_edit_message(message, text, **kwargs):
    """Безопасное редактирование сообщения с повторными попытками при тайм-ауте."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return await message.edit_text(text=text, **kwargs)
        except TimedOut:
            if attempt < max_retries - 1:
                logger.warning(f"Тайм-аут редактирования сообщения, попытка {attempt + 1}/{max_retries}")
                time.sleep(1)
                continue
            else:
                logger.error(f"Не удалось отредактировать сообщение после {max_retries} попыток")
                raise
        except NetworkError:
            if attempt < max_retries - 1:
                logger.warning(f"Ошибка сети при редактировании сообщения, попытка {attempt + 1}/{max_retries}")
                time.sleep(1)
                continue
            else:
                logger.error(f"Не удалось отредактировать сообщение после {max_retries} попыток")
                raise

BOT_DATA_DB_PATH = os.path.join(BOT_DIR, "notifications.db")


def _norm_file_id(value) -> str:
    """Normalize file identifiers for DB lookups (SQLite is type-flexible, but our dict keys should be stable)."""
    if value is None:
        return ""
    try:
        s = str(value).strip()
    except Exception:
        s = ""
    return s


def _maybe_int(value) -> Optional[int]:
    try:
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        s = str(value).strip()
        if not s:
            return None
        return int(s)
    except Exception:
        return None

def _decode_jwt_payload(token: str) -> Optional[Dict]:
    try:
        import base64

        if not token or not isinstance(token, str):
            return None
        parts = token.split('.')
        if len(parts) != 3:
            return None
        payload_b64 = parts[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += '=' * padding
        payload_json = base64.urlsafe_b64decode(payload_b64)
        data = json.loads(payload_json)
        return data if isinstance(data, dict) else None
    except Exception:
        return None

def _extract_user_id_from_token(token: str) -> Optional[int]:
    decoded = _decode_jwt_payload(token)
    if not decoded:
        return None

    user_id = (
        decoded.get("user_id")
        or decoded.get("userId")
        or decoded.get("uid")
    )
    if user_id is None:
        for key, value in decoded.items():
            if isinstance(key, str) and key.endswith("/userdata"):
                user_id = value
                break
    return _maybe_int(user_id)

def _extract_workspace_id_from_token(token: str) -> Optional[int]:
    decoded = _decode_jwt_payload(token)
    if not decoded:
        return None
    workspace_id = decoded.get("workspace_id") or decoded.get("workspaceId")
    return _maybe_int(workspace_id)

def _extract_data_list(payload) -> List[Dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return [x for x in payload.get("data", []) if isinstance(x, dict)]
    return []

def _approval_api_get_sync(token: str, path: str, params: Optional[Dict] = None) -> tuple[int, Optional[object]]:
    if not token:
        return (0, None)

    url = f"{BASE_URL}{path}"
    headers = {
        "accept": "*/*",
        "Authorization": f"Bearer {token}",
    }

    last_error = None
    total_attempts = APPROVALS_HTTP_RETRIES + 1
    for attempt in range(total_attempts):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=APPROVALS_HTTP_TIMEOUT_SEC)
            status = int(response.status_code)

            if status == 200:
                try:
                    return (status, response.json())
                except Exception as e:
                    logger.error(f"Ошибка JSON ответа {url}: {e}")
                    return (status, None)

            if status in (429, 500, 502, 503, 504) and attempt < total_attempts - 1:
                time.sleep(1 + attempt)
                continue

            return (status, None)
        except requests.RequestException as e:
            last_error = e
            if attempt < total_attempts - 1:
                time.sleep(1 + attempt)
                continue

    if last_error:
        logger.error(f"Ошибка запроса {url}: {last_error}")
    return (0, None)

async def _approval_api_get(token: str, path: str, params: Optional[Dict] = None) -> tuple[int, Optional[object]]:
    return await asyncio.to_thread(_approval_api_get_sync, token, path, params)

def _get_workspace_scoped_token_sync(token: str, workspace_id: Optional[int]) -> Optional[str]:
    ws_id = _maybe_int(workspace_id)
    if not token:
        return None
    if ws_id is None or ws_id <= 0:
        return token

    headers = {
        "accept": "*/*",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    url_qs = f"{BASE_URL}/api/admin/workspace/change?workspaceId={ws_id}"
    url_body = f"{BASE_URL}/api/admin/workspace/change"
    candidates = [
        ("PUT", url_qs, {"workspaceId": ws_id}),
        ("PUT", url_body, {"workspaceId": ws_id}),
        ("POST", url_qs, {"workspaceId": ws_id}),
        ("POST", url_body, {"workspaceId": ws_id}),
        ("GET", url_qs, None),
    ]

    for method, url, payload in candidates:
        try:
            if method == "PUT":
                resp = requests.put(url, headers=headers, json=payload, timeout=APPROVALS_HTTP_TIMEOUT_SEC)
            elif method == "POST":
                resp = requests.post(url, headers=headers, json=payload, timeout=APPROVALS_HTTP_TIMEOUT_SEC)
            else:
                resp = requests.get(url, headers=headers, timeout=APPROVALS_HTTP_TIMEOUT_SEC)

            if resp.status_code == 405:
                continue
            if resp.status_code == 401:
                return None
            if resp.status_code < 200 or resp.status_code >= 300:
                continue

            try:
                data = resp.json()
            except Exception:
                return token

            token_block = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else data
            if isinstance(token_block, dict):
                access_token = (
                    token_block.get("access")
                    or token_block.get("token")
                    or token_block.get("accessToken")
                    or token_block.get("access_token")
                )
                if isinstance(access_token, str) and access_token:
                    return access_token

            return token
        except requests.RequestException:
            continue

    return None

async def _get_workspace_scoped_token(token: str, workspace_id: Optional[int]) -> Optional[str]:
    return await asyncio.to_thread(_get_workspace_scoped_token_sync, token, workspace_id)

def init_db():
    # Инициализируем старую базу (для совместимости)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subscriptions (
            chat_id INTEGER,
            project_id INTEGER,
            folder_id INTEGER,
            folder_path TEXT,
            file_state TEXT,
            created_at REAL,
            workspace_id INTEGER
        )
    ''')

    cursor.execute("PRAGMA table_info(subscriptions)")
    columns = [col[1] for col in cursor.fetchall()]

    if 'workspace_id' not in columns:
        cursor.execute("ALTER TABLE subscriptions ADD COLUMN workspace_id INTEGER")
        conn.commit()
        logger.info("Миграция: добавлена колонка workspace_id в таблицу subscriptions")

    conn.close()

    # Инициализируем базу уведомлений
    conn = sqlite3.connect(BOT_DATA_DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS folder_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            larix_user_id INTEGER NOT NULL DEFAULT 0,
            project_id INTEGER NOT NULL,
            folder_id INTEGER NOT NULL,
            folder_path TEXT NOT NULL,
            workspace_id INTEGER,
            created_at REAL NOT NULL,
            UNIQUE(chat_id, larix_user_id, project_id, folder_id)
        )
    ''')

    # Миграция folder_subscriptions -> user-scoped subscriptions
    try:
        cursor.execute("PRAGMA table_info(folder_subscriptions)")
        fs_cols = cursor.fetchall() or []
        fs_col_names = [c[1] for c in fs_cols]

        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='folder_subscriptions'")
        row = cursor.fetchone()
        fs_table_sql = row[0] if row and row[0] else ""
        fs_table_sql_norm = re.sub(r"\s+", "", fs_table_sql).lower()

        desired_unique = "unique(chat_id,larix_user_id,project_id,folder_id)"
        needs_fs_migration = (
            "larix_user_id" not in fs_col_names
            or desired_unique not in fs_table_sql_norm
        )

        if needs_fs_migration:
            logger.info("📦 Миграция: обновляю схему folder_subscriptions (user-scoped)")
            cursor.execute("DROP TABLE IF EXISTS folder_subscriptions_old")
            cursor.execute("ALTER TABLE folder_subscriptions RENAME TO folder_subscriptions_old")
            cursor.execute('''
                CREATE TABLE folder_subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    larix_user_id INTEGER NOT NULL DEFAULT 0,
                    project_id INTEGER NOT NULL,
                    folder_id INTEGER NOT NULL,
                    folder_path TEXT NOT NULL,
                    workspace_id INTEGER,
                    created_at REAL NOT NULL,
                    UNIQUE(chat_id, larix_user_id, project_id, folder_id)
                )
            ''')

            if "larix_user_id" in fs_col_names:
                cursor.execute('''
                    INSERT OR REPLACE INTO folder_subscriptions
                    (chat_id, larix_user_id, project_id, folder_id, folder_path, workspace_id, created_at)
                    SELECT
                        COALESCE(chat_id, 0) AS chat_id,
                        COALESCE(larix_user_id, 0) AS larix_user_id,
                        COALESCE(project_id, 0) AS project_id,
                        COALESCE(folder_id, 0) AS folder_id,
                        COALESCE(folder_path, '') AS folder_path,
                        workspace_id,
                        COALESCE(created_at, 0) AS created_at
                    FROM folder_subscriptions_old
                ''')
            else:
                cursor.execute('''
                    INSERT OR REPLACE INTO folder_subscriptions
                    (chat_id, larix_user_id, project_id, folder_id, folder_path, workspace_id, created_at)
                    SELECT
                        COALESCE(chat_id, 0) AS chat_id,
                        0 AS larix_user_id,
                        COALESCE(project_id, 0) AS project_id,
                        COALESCE(folder_id, 0) AS folder_id,
                        COALESCE(folder_path, '') AS folder_path,
                        workspace_id,
                        COALESCE(created_at, 0) AS created_at
                    FROM folder_subscriptions_old
                ''')

            cursor.execute("DROP TABLE IF EXISTS folder_subscriptions_old")
    except Exception as e:
        logger.error(f"❌ Ошибка миграции folder_subscriptions: {e}")

    # file_states schema v2:
    # - file_id stored as TEXT (API ids may be strings)
    # - PRIMARY KEY includes chat+project+folder to avoid cross-chat collisions
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS file_states (
            chat_id INTEGER NOT NULL,
            project_id INTEGER NOT NULL,
            folder_id INTEGER NOT NULL,
            file_id TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_version TEXT,
            file_updated_at REAL,
            file_created_at REAL,
            file_author TEXT,
            file_created_by TEXT,
            file_modified_by TEXT,
            file_status TEXT,
            folder_path TEXT,
            last_checked_at REAL NOT NULL,
            PRIMARY KEY (chat_id, project_id, folder_id, file_id)
        )
    ''')

    # Migrate legacy file_states schema if needed
    try:
        cursor.execute("PRAGMA table_info(file_states)")
        cols = cursor.fetchall() or []
        col_names = [c[1] for c in cols]
        pk_cols = [c[1] for c in cols if int(c[5] or 0) > 0]
        file_id_type = ""
        try:
            file_id_type = next((c[2] for c in cols if c[1] == "file_id"), "")
        except Exception:
            file_id_type = ""

        desired_pk = ["chat_id", "project_id", "folder_id", "file_id"]
        needs_migration = False
        if any(x not in col_names for x in desired_pk):
            needs_migration = True
        if pk_cols != desired_pk:
            needs_migration = True
        if (file_id_type or "").strip().upper() != "TEXT":
            needs_migration = True

        if needs_migration:
            logger.info("📦 Миграция: обновляю схему file_states (v2)")
            # Best-effort: keep existing data.
            cursor.execute("DROP TABLE IF EXISTS file_states_old")
            cursor.execute("ALTER TABLE file_states RENAME TO file_states_old")
            cursor.execute('''
                CREATE TABLE file_states (
                    chat_id INTEGER NOT NULL,
                    project_id INTEGER NOT NULL,
                    folder_id INTEGER NOT NULL,
                    file_id TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    file_version TEXT,
                    file_updated_at REAL,
                    file_created_at REAL,
                    file_author TEXT,
                    file_created_by TEXT,
                    file_modified_by TEXT,
                    file_status TEXT,
                    folder_path TEXT,
                    last_checked_at REAL NOT NULL,
                    PRIMARY KEY (chat_id, project_id, folder_id, file_id)
                )
            ''')

            # Some very old schemas had (file_id, folder_id) PK and chat_id/project_id columns.
            # Copy what we can and cast file_id to TEXT.
            cursor.execute('''
                INSERT OR REPLACE INTO file_states
                (chat_id, project_id, folder_id, file_id, file_name, file_version,
                 file_updated_at, file_created_at, file_author, file_created_by,
                 file_modified_by, file_status, folder_path, last_checked_at)
                SELECT
                    COALESCE(chat_id, 0) AS chat_id,
                    COALESCE(project_id, 0) AS project_id,
                    COALESCE(folder_id, 0) AS folder_id,
                    CAST(file_id AS TEXT) AS file_id,
                    COALESCE(file_name, '') AS file_name,
                    file_version,
                    file_updated_at,
                    file_created_at,
                    file_author,
                    file_created_by,
                    file_modified_by,
                    file_status,
                    folder_path,
                    COALESCE(last_checked_at, 0) AS last_checked_at
                FROM file_states_old
            ''')
            cursor.execute("DROP TABLE IF EXISTS file_states_old")
    except Exception as e:
        logger.error(f"❌ Ошибка миграции file_states: {e}")

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bot_uploads (
            file_id TEXT NOT NULL,
            chat_id INTEGER NOT NULL,
            folder_id INTEGER NOT NULL,
            file_name TEXT NOT NULL,
            uploaded_at REAL NOT NULL,
            PRIMARY KEY (file_id, chat_id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS approval_notifications (
            chat_id INTEGER NOT NULL,
            process_id INTEGER NOT NULL,
            step_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            workspace_id INTEGER,
            notified_at REAL NOT NULL,
            PRIMARY KEY (chat_id, process_id, step_id, user_id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_settings (
            chat_id INTEGER PRIMARY KEY,
            language TEXT NOT NULL DEFAULT 'ru'
        )
    ''')

    # Индексы
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_folder_subscriptions_chat ON folder_subscriptions(chat_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_folder_subscriptions_chat_user ON folder_subscriptions(chat_id, larix_user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_states_folder ON file_states(chat_id, project_id, folder_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_states_project ON file_states(chat_id, project_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_states_chat ON file_states(chat_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_bot_uploads_chat ON bot_uploads(chat_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_approval_notifications_chat ON approval_notifications(chat_id)')

    conn.commit()
    conn.close()

# ==================== ФУНКЦИИ БАЗЫ ДАННЫХ БОТА ====================

def add_folder_subscription(
    chat_id: int,
    project_id: int,
    folder_id: int,
    folder_path: str,
    workspace_id: Optional[int] = None,
    larix_user_id: Optional[int] = None,
) -> bool:
    """Добавляет подписку на папку."""
    conn = sqlite3.connect(BOT_DATA_DB_PATH)
    cursor = conn.cursor()
    user_id = _maybe_int(larix_user_id) or 0

    try:
        cursor.execute('''
            INSERT OR REPLACE INTO folder_subscriptions
            (chat_id, larix_user_id, project_id, folder_id, folder_path, workspace_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (chat_id, user_id, project_id, folder_id, folder_path, workspace_id, time.time()))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error adding folder subscription: {e}")
        return False
    finally:
        conn.close()

def remove_folder_subscription(
    chat_id: int,
    project_id: int,
    folder_id: int,
    larix_user_id: Optional[int] = None,
) -> bool:
    """Удаляет подписку на папку."""
    conn = sqlite3.connect(BOT_DATA_DB_PATH)
    cursor = conn.cursor()
    user_id = _maybe_int(larix_user_id)

    try:
        if user_id is None:
            cursor.execute(
                'DELETE FROM folder_subscriptions WHERE chat_id = ? AND project_id = ? AND folder_id = ?',
                (chat_id, project_id, folder_id),
            )
        else:
            cursor.execute(
                'DELETE FROM folder_subscriptions WHERE chat_id = ? AND larix_user_id = ? AND project_id = ? AND folder_id = ?',
                (chat_id, user_id, project_id, folder_id),
            )

        cursor.execute(
            'SELECT COUNT(*) FROM folder_subscriptions WHERE chat_id = ? AND project_id = ? AND folder_id = ?',
            (chat_id, project_id, folder_id),
        )
        remaining = int((cursor.fetchone() or [0])[0])
        if remaining == 0:
            cursor.execute(
                'DELETE FROM file_states WHERE chat_id = ? AND project_id = ? AND folder_id = ?',
                (chat_id, project_id, folder_id),
            )
            cursor.execute(
                'DELETE FROM bot_uploads WHERE chat_id = ? AND folder_id = ?',
                (chat_id, folder_id),
            )

        conn.commit()
        return True
    except Exception as e:
        print(f"Error removing folder subscription: {e}")
        return False
    finally:
        conn.close()

def remove_file_state(chat_id: int, file_id, folder_id: int, project_id: Optional[int] = None) -> bool:
    """Удаляет состояние файла из базы (при удалении файла)."""
    conn = sqlite3.connect(BOT_DATA_DB_PATH)
    cursor = conn.cursor()

    try:
        fid = _norm_file_id(file_id)
        if project_id is None:
            cursor.execute('DELETE FROM file_states WHERE file_id = ? AND folder_id = ? AND chat_id = ?', (fid, folder_id, chat_id))
        else:
            cursor.execute(
                'DELETE FROM file_states WHERE file_id = ? AND folder_id = ? AND chat_id = ? AND project_id = ?',
                (fid, folder_id, chat_id, project_id),
            )
        conn.commit()
        print(f"[REMOVE_STATE] Удалено состояние файла: file_id={fid}, folder_id={folder_id}")
        return True
    except Exception as e:
        print(f"Error removing file state: {e}")
        return False
    finally:
        conn.close()

def reset_folder_file_states(chat_id: int, folder_id: int, project_id: Optional[int] = None) -> bool:
    """Очищает состояния файлов для папки, чтобы пересоздать актуальный слепок."""
    conn = sqlite3.connect(BOT_DATA_DB_PATH)
    cursor = conn.cursor()
    try:
        if project_id is None:
            cursor.execute(
                'DELETE FROM file_states WHERE chat_id = ? AND folder_id = ?',
                (chat_id, folder_id),
            )
        else:
            cursor.execute(
                'DELETE FROM file_states WHERE chat_id = ? AND folder_id = ? AND project_id = ?',
                (chat_id, folder_id, project_id),
            )
        conn.commit()
        return True
    except Exception as e:
        print(f"Error resetting folder file states: {e}")
        return False
    finally:
        conn.close()

def get_user_subscriptions(chat_id: int, larix_user_id: Optional[int] = None) -> List[Dict]:
    """Возвращает все подписки пользователя."""
    conn = sqlite3.connect(BOT_DATA_DB_PATH)
    cursor = conn.cursor()
    user_id = _maybe_int(larix_user_id)

    if user_id is None:
        cursor.execute('''
            SELECT chat_id, larix_user_id, project_id, folder_id, folder_path, workspace_id, created_at
            FROM folder_subscriptions
            WHERE chat_id = ?
        ''', (chat_id,))
    else:
        cursor.execute('''
            SELECT chat_id, larix_user_id, project_id, folder_id, folder_path, workspace_id, created_at
            FROM folder_subscriptions
            WHERE chat_id = ? AND larix_user_id = ?
        ''', (chat_id, user_id))

    rows = cursor.fetchall()
    conn.close()

    return [
        {
            "chat_id": row[0],
            "larix_user_id": row[1],
            "project_id": row[2],
            "folder_id": row[3],
            "folder_path": row[4],
            "workspace_id": row[5],
            "created_at": row[6]
        }
        for row in rows
    ]

def get_all_folder_subscriptions() -> List[Dict]:
    """Возвращает все подписки из новой базы уведомлений."""
    conn = sqlite3.connect(BOT_DATA_DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT chat_id, larix_user_id, project_id, folder_id, folder_path, workspace_id, created_at
        FROM folder_subscriptions
    ''')

    rows = cursor.fetchall()
    conn.close()

    return [
        {
            "chat_id": row[0],
            "larix_user_id": row[1],
            "project_id": row[2],
            "folder_id": row[3],
            "folder_path": row[4],
            "workspace_id": row[5],
            "created_at": row[6]
        }
        for row in rows
    ]

def update_subscriptions_workspace(chat_id: int, workspace_id: int | str | None, larix_user_id: Optional[int] = None) -> bool:
    """Обновляет workspace_id для подписок пользователя."""
    conn = sqlite3.connect(BOT_DATA_DB_PATH)
    cursor = conn.cursor()
    try:
        user_id = _maybe_int(larix_user_id)
        if user_id is None:
            cursor.execute(
                'UPDATE folder_subscriptions SET workspace_id = ? WHERE chat_id = ?',
                (workspace_id, chat_id),
            )
        else:
            cursor.execute(
                'UPDATE folder_subscriptions SET workspace_id = ? WHERE chat_id = ? AND larix_user_id = ?',
                (workspace_id, chat_id, user_id),
            )
        conn.commit()
        return True
    except Exception as e:
        print(f"Error updating subscriptions workspace: {e}")
        return False
    finally:
        conn.close()

def record_bot_upload(chat_id: int, file_id: int, folder_id: int, file_name: str) -> bool:
    """Записывает файл как загруженный через бота."""
    conn = sqlite3.connect(BOT_DATA_DB_PATH)
    cursor = conn.cursor()

    try:
        fid = _norm_file_id(file_id)
        cursor.execute('''
            INSERT OR REPLACE INTO bot_uploads (file_id, chat_id, folder_id, file_name, uploaded_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (fid, chat_id, folder_id, file_name, time.time()))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error recording bot upload: {e}")
        return False
    finally:
        conn.close()

def is_recent_bot_upload(chat_id: int, file_id, minutes: int = 5) -> bool:
    """Проверяет, был ли файл загружен через бота в последние N минут."""
    if not os.path.exists(BOT_DATA_DB_PATH):
        return False

    conn = sqlite3.connect(BOT_DATA_DB_PATH)
    cursor = conn.cursor()

    try:
        threshold = time.time() - (minutes * 60)
        fid = _norm_file_id(file_id)
        cursor.execute('''
            SELECT COUNT(*) FROM bot_uploads
            WHERE file_id = ? AND chat_id = ? AND uploaded_at > ?
        ''', (fid, chat_id, threshold))

        count = cursor.fetchone()[0]
        return count > 0
    except Exception as e:
        print(f"Error checking bot upload: {e}")
        return False
    finally:
        conn.close()

def is_approval_notification_sent(chat_id: int, process_id: int, step_id: int, user_id: int) -> bool:
    """Проверяет, отправлялось ли уже уведомление по этапу согласования."""
    conn = sqlite3.connect(BOT_DATA_DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute(
            '''
            SELECT 1
            FROM approval_notifications
            WHERE chat_id = ? AND process_id = ? AND step_id = ? AND user_id = ?
            LIMIT 1
            ''',
            (chat_id, process_id, step_id, user_id),
        )
        return cursor.fetchone() is not None
    except Exception as e:
        logger.error(f"Ошибка проверки дедупликации согласований: {e}")
        return False
    finally:
        conn.close()

def mark_approval_notification_sent(
    chat_id: int,
    process_id: int,
    step_id: int,
    user_id: int,
    workspace_id: Optional[int] = None,
) -> bool:
    """Фиксирует факт отправки уведомления по этапу согласования."""
    conn = sqlite3.connect(BOT_DATA_DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute(
            '''
            INSERT OR REPLACE INTO approval_notifications
            (chat_id, process_id, step_id, user_id, workspace_id, notified_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (chat_id, process_id, step_id, user_id, workspace_id, time.time()),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Ошибка записи дедупликации согласований: {e}")
        return False
    finally:
        conn.close()

def clear_chat_approval_notifications(chat_id: int) -> bool:
    """Очищает сохраненные уведомления согласований для чата."""
    conn = sqlite3.connect(BOT_DATA_DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute('DELETE FROM approval_notifications WHERE chat_id = ?', (chat_id,))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Ошибка очистки дедупликации согласований: {e}")
        return False
    finally:
        conn.close()

def update_file_state(chat_id: int, file_info: Dict, folder_id: int, project_id: int, folder_path: str = "") -> bool:
    """Обновляет или создает состояние файла в базе."""
    conn = sqlite3.connect(BOT_DATA_DB_PATH)
    cursor = conn.cursor()

    try:
        file_id = _norm_file_id(file_info.get("id"))
        if not file_id:
            return False
        file_name = file_info.get("originalName") or file_info.get("name") or "Без имени"
        file_version = file_info.get("version") or file_info.get("version_count") or file_info.get("documentVersion")

        updated_at = file_info.get("updatedAt") or file_info.get("modified_ts") or file_info.get("modifTime") or file_info.get("modifiedDate")
        created_at = file_info.get("createdAt") or file_info.get("created_ts") or file_info.get("createTime")

        updated_ts = parse_iso_datetime(updated_at) if updated_at else 0
        created_ts = parse_iso_datetime(created_at) if created_at else 0

        if updated_ts == 0 and created_ts > 0:
            updated_ts = created_ts

        author = file_info.get("author")
        created_by = file_info.get("created_by") or file_info.get("createdBy")
        modified_by = file_info.get("modified_by") or file_info.get("modifiedBy")
        status = file_info.get("status")

        print(f"[UPDATE_STATE] file_id={file_id}, name={file_name}, version={file_version}")

        cursor.execute('''
            INSERT OR REPLACE INTO file_states
            (chat_id, project_id, folder_id, file_id, file_name, file_version,
             file_updated_at, file_created_at, file_author,
             file_created_by, file_modified_by, file_status,
             folder_path, last_checked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            chat_id, project_id, folder_id, file_id,
            file_name, str(file_version) if file_version else None,
            updated_ts, created_ts, author,
            created_by, modified_by, status,
            folder_path, time.time(),
        ))

        conn.commit()
        return True
    except Exception as e:
        print(f"Error updating file state: {e}")
        return False
    finally:
        conn.close()

def get_file_state(chat_id: int, file_id, folder_id: int, project_id: Optional[int] = None) -> Optional[Dict]:
    """Получает сохраненное состояние файла из базы."""
    conn = sqlite3.connect(BOT_DATA_DB_PATH)
    cursor = conn.cursor()

    fid = _norm_file_id(file_id)
    if project_id is None:
        cursor.execute('''
            SELECT file_id, folder_id, project_id, file_name, file_version,
                   file_updated_at, file_created_at, file_author,
                   file_created_by, file_modified_by, file_status, folder_path
            FROM file_states
            WHERE file_id = ? AND folder_id = ? AND chat_id = ?
        ''', (fid, folder_id, chat_id))
    else:
        cursor.execute('''
            SELECT file_id, folder_id, project_id, file_name, file_version,
                   file_updated_at, file_created_at, file_author,
                   file_created_by, file_modified_by, file_status, folder_path
            FROM file_states
            WHERE file_id = ? AND folder_id = ? AND chat_id = ? AND project_id = ?
        ''', (fid, folder_id, chat_id, project_id))

    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return {
        "file_id": row[0],
        "folder_id": row[1],
        "project_id": row[2],
        "file_name": row[3],
        "file_version": row[4],
        "file_updated_at": row[5],
        "file_created_at": row[6],
        "file_author": row[7],
        "file_created_by": row[8],
        "file_modified_by": row[9],
        "file_status": row[10],
        "folder_path": row[11]
    }

def get_folder_file_states(chat_id: int, folder_id: int, project_id: Optional[int] = None) -> List[Dict]:
    """Получает состояния всех файлов в папке."""
    conn = sqlite3.connect(BOT_DATA_DB_PATH)
    cursor = conn.cursor()

    if project_id is None:
        cursor.execute('''
            SELECT file_id, folder_id, project_id, file_name, file_version,
                   file_updated_at, file_created_at, file_author,
                   file_created_by, file_modified_by, file_status, folder_path
            FROM file_states
            WHERE folder_id = ? AND chat_id = ?
        ''', (folder_id, chat_id))
    else:
        cursor.execute('''
            SELECT file_id, folder_id, project_id, file_name, file_version,
                   file_updated_at, file_created_at, file_author,
                   file_created_by, file_modified_by, file_status, folder_path
            FROM file_states
            WHERE folder_id = ? AND chat_id = ? AND project_id = ?
        ''', (folder_id, chat_id, project_id))

    rows = cursor.fetchall()
    conn.close()

    result = [
        {
            "file_id": row[0],
            "folder_id": row[1],
            "project_id": row[2],
            "file_name": row[3],
            "file_version": row[4],
            "file_updated_at": row[5],
            "file_created_at": row[6],
            "file_author": row[7],
            "file_created_by": row[8],
            "file_modified_by": row[9],
            "file_status": row[10],
            "folder_path": row[11]
        }
        for row in rows
    ]

    print(f"[GET_STATES] Получено {len(result)} сохраненных состояний для folder_id={folder_id}")
    for s in result[:3]:
        print(f"   file_id={s['file_id']}, file_name={s['file_name']}, file_version={s['file_version']}")
    if len(result) > 3:
        print(f"   ... и ещё {len(result) - 3} файлов")

    return result

def compare_file_states(old_state: Optional[Dict], new_state: Optional[Dict]) -> Optional[str]:
    """Сравнивает старое и новое состояние файла."""
    if not old_state:
        print(f"[COMPARE] Файл НОВЫЙ (нет old_state): file_id={new_state.get('id')}, name={new_state.get('name')}")
        return "new"

    if not new_state:
        print(f"[COMPARE] Файл УДАЛЁН (нет new_state): file_id={old_state.get('file_id')}, name={old_state.get('file_name')}")
        return "deleted"

    old_version = old_state.get("file_version") or "0"
    new_version = new_state.get("version") or "0"

    print(f"[COMPARE] file_id={new_state.get('id')}, file_name={new_state.get('name')}")
    print(f"[COMPARE]   old_version={old_version}, new_version={new_version}")

    try:
        old_num = int(old_version)
        new_num = int(new_version)
        if new_num > old_num:
            print(f"[COMPARE]   -> ОБНОВЛЁН (версия изменилась: {old_num} -> {new_num})")
            return "updated"
    except (ValueError, TypeError) as e:
        print(f"[COMPARE]   Ошибка преобразования версии: {e}")
        if new_version != old_version:
            print(f"[COMPARE]   -> ОБНОВЛЁН (строки версий разные: '{old_version}' != '{new_version}')")
            return "updated"

    old_updated = old_state.get("file_updated_at", 0)
    new_updated = new_state.get("file_updated_at", 0)
    if not new_updated:
        try:
            raw = new_state.get("updatedAt")
            new_updated = parse_iso_datetime(raw) if raw else 0
        except Exception:
            new_updated = 0
    print(f"[COMPARE]   old_updated={old_updated}, new_updated={new_updated}")
    if new_updated > 0 and old_updated > 0 and new_updated > old_updated:
        print(f"[COMPARE]   -> ОБНОВЛЁН (по времени: {old_updated} -> {new_updated})")
        return "updated"

    print(f"[COMPARE]   -> БЕЗ ИЗМЕНЕНИЙ")
    return None

def check_folder_changes(chat_id: int, folder_id: int, project_id: int, current_files: List[Dict], skip_recent_uploads: bool = True) -> List[Dict]:
    """Проверяет изменения в папке по сравнению с сохраненными состояниями."""
    print(f"[CHECK] chat_id={chat_id}, folder_id={folder_id}, project_id={project_id}")
    print(f"[CHECK] Файлов в текущем списке: {len(current_files)}")

    old_states = get_folder_file_states(chat_id, folder_id, project_id)
    old_states_dict = {str(s.get("file_id")): s for s in old_states if _norm_file_id(s.get("file_id"))}
    print(f"[CHECK] Сохраненных состояний файлов: {len(old_states)}")

    changes = []
    current_files_dict: Dict[str, Dict] = {}
    for f in (current_files or []):
        fid = _norm_file_id((f or {}).get("id"))
        if not fid:
            continue
        current_files_dict[fid] = f

    for fid, file_info in current_files_dict.items():
        old_state = old_states_dict.get(fid)

        if skip_recent_uploads and is_recent_bot_upload(chat_id, fid, minutes=5):
            print(f"[CHECK] Пропускаем файл загруженный ботом: file_id={fid}")
            continue

        change_type = compare_file_states(old_state, file_info)

        if change_type:
            print(f"[CHECK] Обнаружено изменение: type={change_type}, file_id={fid}")
            changes.append({
                "type": change_type,
                "file": file_info,
                "old_state": old_state
            })

    for fid, old_state in list(old_states_dict.items()):
        if skip_recent_uploads and is_recent_bot_upload(chat_id, fid, minutes=5):
            remove_file_state(chat_id, fid, folder_id, project_id)
            continue

        if fid not in current_files_dict:
            print(f"[CHECK] Обнаружено удаление: file_id={fid}")
            changes.append({
                "type": "deleted",
                "file": None,
                "old_state": old_state
            })
            remove_file_state(chat_id, fid, folder_id, project_id)

    for file_info in current_files:
        update_file_state(chat_id, file_info, folder_id, project_id, file_info.get("path", ""))

    print(f"[CHECK] Итого изменений: {len(changes)}")
    return changes

def format_file_info_notification(file_info: Dict, change_type: str, old_state: Optional[Dict] = None, skip_reason: str = "", lang: str = "ru") -> str:
    ru = lang == "ru"
    no_name = "Без имени" if ru else "No name"
    root_text = "Корень" if ru else "Root"
    
    file_name = file_info.get("originalName") or file_info.get("name") or no_name
    file_version = file_info.get("version") or file_info.get("version_count") or file_info.get("documentVersion")
    folder_path = file_info.get("path", "")

    author_name = None
    if change_type in ("new", "updated"):
        author_name = file_info.get("created_by") or file_info.get("createdBy") or file_info.get("author")
        if not author_name and old_state:
            author_name = old_state.get("file_created_by") or old_state.get("file_author")
    elif change_type == "deleted" and old_state:
        author_name = old_state.get("file_created_by") or old_state.get("file_author")
        file_name = old_state.get("file_name", file_name)
        file_version = old_state.get("file_version", file_version)
        folder_path = old_state.get("folder_path", folder_path)

    current_time = time.time()

    created_by_label = "Кем создано" if ru else "Created by"
    author_text = f"👤 {created_by_label}: {author_name}" if author_name else ""
    time_text = f"🕒 {format_timestamp(current_time)}"

    if file_version:
        version_label = "Версия" if ru else "Version"
        version_text = f"🔢 {version_label}: {file_version}"
    else:
        version_text = ""

    if change_type == "new":
        action_emoji = "🆕"
        action_text = "Новый файл" if ru else "New file"
    elif change_type == "updated":
        action_emoji = "🔄"
        action_text = "Обновлённый файл" if ru else "Updated file"
    elif change_type == "deleted":
        action_emoji = "🗑️"
        action_text = "Удалённый файл" if ru else "Deleted file"
    else:
        action_emoji = "📄"
        action_text = "Файл" if ru else "File"

    path_text = f"📁 {folder_path}" if folder_path else f"📁 {root_text}"
    skip_reason_text = f"\n⏭️ {skip_reason}" if skip_reason else ""

    parts = []
    parts.append(f"{action_emoji} {action_text}:")
    parts.append(f"📄 {file_name}")
    if version_text:
        parts.append(version_text)
    if author_text:
        parts.append(author_text)
    if time_text:
        parts.append(time_text)
    if path_text:
        parts.append(path_text)
    if skip_reason_text:
        parts.append(skip_reason)

    return "\n".join(parts)

def format_timestamp(timestamp: float) -> str:
    """Форматирует timestamp в читаемый формат."""
    if not timestamp or timestamp <= 0:
        return ""

    try:
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime("%d.%m.%Y %H:%M")
    except:
        return str(timestamp)

def parse_iso_datetime(dt_str: str) -> float:
    """Парсит ISO datetime строку в Unix timestamp."""
    if not dt_str:
        return 0

    dt_str = dt_str.strip()

    formats = [
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(dt_str, fmt)
            return dt.timestamp()
        except ValueError:
            continue

    return 0

def delete_user_db(chat_id: int) -> bool:
    """Удаляет данные пользователя (при logout)."""
    conn = sqlite3.connect(BOT_DATA_DB_PATH)
    cursor = conn.cursor()

    try:
        cursor.execute('DELETE FROM folder_subscriptions WHERE chat_id = ?', (chat_id,))
        cursor.execute('DELETE FROM file_states WHERE chat_id = ?', (chat_id,))
        cursor.execute('DELETE FROM bot_uploads WHERE chat_id = ?', (chat_id,))
        cursor.execute('DELETE FROM approval_notifications WHERE chat_id = ?', (chat_id,))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error deleting user data: {e}")
        return False
    finally:
        conn.close()

def has_bot_data_db() -> bool:
    """Проверяет, существует ли база bot_data.db."""
    return os.path.exists(BOT_DATA_DB_PATH)

def migrate_subscriptions_from_old_db() -> int:
    """Мигрирует подписки из старой базы bot_data.db (старый subscriptions.db) в notifications.db."""
    old_db_path = os.path.join(BOT_DIR, "subscriptions.db")

    if not os.path.exists(old_db_path):
        return 0

    # Проверяем, есть ли данные в новой базе
    if has_bot_data_db():
        conn = sqlite3.connect(BOT_DATA_DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM folder_subscriptions')
        count = cursor.fetchone()[0]
        conn.close()
        if count > 0:
            logger.info("📦 Пропускаем миграцию (уже есть данные в notifications.db)")
            return 0

    try:
        old_conn = sqlite3.connect(old_db_path)
        old_cursor = old_conn.cursor()

        old_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='subscriptions'")
        if not old_cursor.fetchone():
            old_conn.close()
            return 0

        old_cursor.execute("SELECT chat_id, project_id, folder_id, folder_path, file_state, workspace_id FROM subscriptions")
        rows = old_cursor.fetchall()
        old_conn.close()

        new_conn = sqlite3.connect(BOT_DATA_DB_PATH)
        new_cursor = new_conn.cursor()

        migrated_count = 0
        for row in rows:
            chat_id, project_id, folder_id, folder_path, file_state_json, workspace_id = row

            print(f"[MIGRATION] Миграция: chat_id={chat_id}, folder_id={folder_id}")

            try:
                new_cursor.execute('''
                    INSERT OR REPLACE INTO folder_subscriptions
                    (chat_id, larix_user_id, project_id, folder_id, folder_path, workspace_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (chat_id, 0, project_id, folder_id, folder_path, workspace_id, time.time()))

                if file_state_json:
                    file_states = json.loads(file_state_json)
                    if isinstance(file_states, list):
                        print(f"[MIGRATION] Файлов для миграции: {len(file_states)}")
                        for file_info in file_states:
                            file_id = file_info.get("id")
                            file_name = file_info.get("name")
                            file_version = file_info.get("version")
                            print(f"[MIGRATION]   Мигрирую: id={file_id}, name={file_name}, version={file_version}")

                            updated_at = file_info.get("updatedAt") or file_info.get("modified_ts")
                            created_at = file_info.get("createdAt") or file_info.get("created_ts")

                            updated_ts = parse_iso_datetime(updated_at) if updated_at else 0
                            created_ts = parse_iso_datetime(created_at) if created_at else 0
                            if updated_ts == 0 and created_ts > 0:
                                updated_ts = created_ts

                            file_version_str = str(file_info.get("version")) if file_info.get("version") else None

                            new_cursor.execute('''
                                INSERT OR REPLACE INTO file_states
                                (chat_id, project_id, folder_id, file_id, file_name, file_version,
                                 file_updated_at, file_created_at, file_author,
                                 file_created_by, file_modified_by, file_status,
                                 folder_path, last_checked_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ''', (
                                chat_id, project_id, folder_id, _norm_file_id(file_id),
                                file_info.get("name") or "Без имени", file_version_str,
                                updated_ts, created_ts, file_info.get("author"),
                                file_info.get("created_by"), file_info.get("modified_by"),
                                file_info.get("status"), file_info.get("path", ""),
                                time.time(),
                            ))

                new_conn.commit()
                migrated_count += 1
            except Exception as e:
                print(f"Error migrating subscription: {e}")
                import traceback
                print(traceback.format_exc())

        new_conn.close()

        # Создаем резервную копию старой базы
        backup_path = old_db_path + ".backup"
        try:
            import shutil
            shutil.copy2(old_db_path, backup_path)
            print(f"Created backup of old DB: {backup_path}")
        except Exception as e:
            print(f"Error creating backup: {e}")

        return migrated_count
    except Exception as e:
        print(f"Error during migration: {e}")
        import traceback
        print(traceback.format_exc())
        return 0

# ==================== КОНЕЦ ФУНКЦИЙ БАЗЫ ДАННЫХ ПОЛЬЗОВАТЕЛЯ ====================

def save_subscription(chat_id, project_id, folder_id, folder_path, file_state, workspace_id=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM subscriptions WHERE chat_id = ? AND folder_id = ?",
        (chat_id, folder_id)
    )
    cursor.execute('''
        INSERT INTO subscriptions (chat_id, project_id, folder_id, folder_path, file_state, created_at, workspace_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (chat_id, project_id, folder_id, folder_path, json.dumps(file_state), time.time(), workspace_id))
    conn.commit()
    conn.close()

def remove_subscription(chat_id, folder_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM subscriptions WHERE chat_id = ? AND folder_id = ?", (chat_id, folder_id))
    conn.commit()
    conn.close()

def load_subscriptions():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id, project_id, folder_id, folder_path, file_state, workspace_id FROM subscriptions")
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "chat_id": row[0],
            "project_id": row[1],
            "folder_id": row[2],
            "folder_path": row[3],
            "file_state": json.loads(row[4]),
            "workspace_id": row[5]
        }
        for row in rows
    ]

def sanitize_filename(name: str) -> str:
    if not name or not isinstance(name, str):
        return f"file_{uuid.uuid4().hex[:8]}"
    clean = re.sub(r'[^\w\-.]', '_', name)
    clean = clean.strip('._')
    return clean[:100] or f"file_{uuid.uuid4().hex[:8]}"

def cleanup_old_files(directory=None, max_age_seconds=3600):
    if directory is None:
        directory = DOWNLOAD_DIR
    
    now = time.time()
    try:
        if not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
            return
        for filename in os.listdir(directory):
            filepath = os.path.join(directory, filename)
            if os.path.isfile(filepath):
                file_age = now - os.path.getctime(filepath)
                if file_age > max_age_seconds:
                    os.remove(filepath)
                    logger.info(f"🧹 Удалён старый файл: {filename}")
    except Exception as e:
        logger.error(f"❌ Ошибка при очистке: {e}")

def rate_limit(context: ContextTypes.DEFAULT_TYPE, seconds=1):
    now = datetime.now()
    last_request = context.user_data.get('last_request_time')
    if last_request and (now - last_request) < timedelta(seconds=seconds):
        return False
    context.user_data['last_request_time'] = now
    return True

def get_title(node):
    return node.get("name") or node.get("title") or "Без названия"

def count_files_in_tree(tree):
    count = 0
    for item in tree:
        if isinstance(item, dict):
            if item.get("type") == "file":
                count += 1
            elif item.get("type") == "folder":
                children = item.get("children", [])
                if isinstance(children, list):
                    count += count_files_in_tree(children)
    return count

def get_files_flat(tree, parent_path=""):
    if not isinstance(tree, list):
        return []
    files = []
    for item in tree:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "file":
            name = item.get("originalName") or item.get("name") or "Без имени"
            updated_at_raw = item.get("updatedAt") or item.get("modified_ts") or item.get("modifTime") or item.get("modifiedDate")
            created_at_raw = item.get("createdAt") or item.get("created_ts") or item.get("createTime")
            try:
                updated_ts = parse_iso_datetime(updated_at_raw) if updated_at_raw else 0
            except Exception:
                updated_ts = 0
            try:
                created_ts = parse_iso_datetime(created_at_raw) if created_at_raw else 0
            except Exception:
                created_ts = 0
            if updated_ts == 0 and created_ts > 0:
                updated_ts = created_ts
            file_data = {
                "id": item["id"],
                "name": name,
                "updatedAt": updated_at_raw,
                "version": item.get("version") or item.get("version_count") or item.get("documentVersion") or item.get("docVersion"),
                "path": parent_path,
                "file_updated_at": updated_ts,
                "file_created_at": created_ts,
                "createdBy": item.get("createdBy"),
                "created_by": item.get("created_by"),
                "author": item.get("author"),
            }
            print(f"[GET_FILES_FLAT] === ФАЙЛ ИЗ API ===")
            print(f"[GET_FILES_FLAT] id={item.get('id')}")
            print(f"[GET_FILES_FLAT] name={name}")
            print(f"[GET_FILES_FLAT] version={file_data['version']}")
            print(f"[GET_FILES_FLAT] updatedAt={file_data['updatedAt']}")
            print(f"[GET_FILES_FLAT] Все поля файла: {list(item.keys())}")
            print(f"[GET_FILES_FLAT] ====================")
            files.append(file_data)
        elif item.get("type") == "folder":
            folder_name = get_title(item)
            new_path = f"{parent_path}/{folder_name}" if parent_path else folder_name
            children = item.get("children")
            if children is None:
                children = []
            if isinstance(children, list):
                files.extend(get_files_flat(children, new_path))
    return files
 
def format_file_date(updated_at):
    """Форматирует дату обновления файла."""
    if not updated_at:
        return "Дата неизвестна"
    
    # Если это строка ISO формат
    if isinstance(updated_at, str):
        try:
            # Пробуем разные форматы
            for fmt in ["%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S"]:
                try:
                    dt = datetime.strptime(updated_at, fmt)
                    return dt.strftime("%d.%m.%Y %H:%M")
                except ValueError:
                    continue
        except Exception:
            pass
        
        # Если не получилось распарсить, возвращаем как есть
        return updated_at
    
    # Если это число (Unix timestamp)
    elif isinstance(updated_at, (int, float)):
        try:
            dt = datetime.fromtimestamp(updated_at)
            return dt.strftime("%d.%m.%Y %H:%M")
        except Exception:
            return str(updated_at)
    
    # Иначе возвращаем как есть
    return str(updated_at)

def get_workspace_id(workspace: dict) -> int | str | None:
    return workspace.get("id") or workspace.get("workspace_id") or workspace.get("workspaceId")

def get_workspace_name(workspace: dict) -> str:
    return workspace.get("name") or workspace.get("title") or "Без названия"

class APIClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.token = None
        self.refresh_token = None
        self.current_username = None
        self.cache = {}
        self.user_id = None
        self.workspace_id = None
        self.selected_workspace_id = None

    def _headers(self):
        h = {"accept": "*/*"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _cached_get(self, key: str):
        it = self.cache.get(key)
        if not it: return None
        ts, data = it
        if (time.time() - ts) < CACHE_TTL_SEC: return data
        return None

    def _handle_401(self) -> bool:
        if self.refresh_token:
            if self._refresh_access_token():
                return True
        self.logout()
        return False

    def _decode_jwt(self, token: str) -> dict | None:
        import base64
        try:
            if not token or not isinstance(token, str):
                return None
            parts = token.split('.')
            if len(parts) != 3:
                return None
            payload_b64 = parts[1]
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += '=' * padding
            payload_json = base64.urlsafe_b64decode(payload_b64)
            import json
            return json.loads(payload_json)
        except Exception:
            return None

    def _sync_identity_from_token(self) -> None:
        if not self.token:
            return
        decoded = self._decode_jwt(self.token)
        if not decoded or not isinstance(decoded, dict):
            return

        ws = decoded.get("workspace_id") or decoded.get("workspaceId")
        if ws is not None:
            self.workspace_id = ws
            if self.selected_workspace_id is None:
                self.selected_workspace_id = ws

        uid = (
            decoded.get("user_id")
            or decoded.get("userId")
            or decoded.get("uid")
        )
        if uid is None:
            for k, v in decoded.items():
                if isinstance(k, str) and k.endswith("/userdata"):
                    uid = v
                    break
        if uid is not None:
            self.user_id = uid

    def _refresh_access_token(self) -> bool:
        if not self.refresh_token:
            return False

        url = f"{self.base_url}/api/auth/refresh"
        try:
            r = requests.post(
                url,
                json={"refresh_token": self.refresh_token},
                headers={"accept": "*/*", "Content-Type": "application/json"},
                timeout=12
            )
            
            if r.status_code != 200:
                return False
            
            data = r.json()
            
            access_token = data.get("token") or data.get("accessToken") or data.get("access_token")
            refresh_token = data.get("refreshToken") or data.get("refresh_token")
            
            if access_token:
                self.token = access_token
                
                if refresh_token:
                    self.refresh_token = refresh_token

                try:
                    self._sync_identity_from_token()
                except Exception:
                    pass
                
                return True
            
            return False
        except requests.RequestException:
            return False

    def login(self, username: str, password: str, remember_me: bool = True) -> bool:
        url = f"{self.base_url}/api/admin/login"
        payload = {"username": username, "password": password, "app_code": ""}
        try:
            r = requests.post(url, json=payload, headers={"accept": "*/*","Content-Type":"application/json"}, timeout=12)
            if r.status_code == 401:
                return False
            r.raise_for_status()
            data = r.json()

            token = data.get("token") or data.get("accessToken") or data.get("access_token")
            refresh_token = data.get("refreshToken") or data.get("refresh_token")

            if not token:
                return False

            self.token = token
            self.refresh_token = refresh_token
            self.current_username = username

            try:
                self._sync_identity_from_token()
            except Exception:
                pass

            return True
        except requests.RequestException:
            return False

    def logout(self):
        self.token = None
        self.refresh_token = None
        self.current_username = None
        self.cache.clear()

    def list_projects(self):
        if not self.token: 
            return []
        
        url = f"{self.base_url}/api/project/list"
        
        for attempt in range(2):
            try:
                r = requests.get(url, headers=self._headers(), timeout=12)
                
                if r.status_code == 401:
                    if attempt == 0 and self._handle_401():
                        continue
                    return []
                
                r.raise_for_status()
                data = r.json()
                
                projects = []
                
                if isinstance(data, list):
                    projects = data
                elif isinstance(data, dict) and "data" in data and isinstance(data.get("data"), list):
                    projects = data.get("data", [])
                
                if self.selected_workspace_id:
                    ws_id = str(self.selected_workspace_id)
                    
                    filtered = [p for p in projects if str(p.get("workspaceId")) == ws_id or str(p.get("workspace_id")) == ws_id]
                    
                    if not filtered:
                        pass
                    else:
                        projects = filtered
                
                return projects
            except requests.RequestException:
                return []
        return []

    def list_workspaces(self):
        if not self.token:
            return []
        
        endpoints = [
            f"{self.base_url}/api/workspace/list",
            f"{self.base_url}/api/admin/workspace/list",
            f"{self.base_url}/api/workspaces",
            f"{self.base_url}/api/user/workspaces",
        ]
        
        for url in endpoints:
            for attempt in range(2):
                try:
                    r = requests.get(url, headers=self._headers(), timeout=12)
                    
                    if r.status_code == 401:
                        if attempt == 0 and self._handle_401():
                            continue
                        break
                    
                    if r.status_code == 200:
                        data = r.json()
                        
                        workspaces = []
                        
                        if isinstance(data, list):
                            workspaces = data
                        elif isinstance(data, dict) and "data" in data and isinstance(data.get("data"), list):
                            workspaces = data.get("data", [])
                        
                        if workspaces:
                            return workspaces
                except requests.RequestException:
                    break
        
        decoded = self._decode_jwt(self.token)
        if decoded and isinstance(decoded, dict):
            workspace_id = decoded.get("workspace_id") or decoded.get("workspaceId")
            if workspace_id:
                workspaces = [{"id": workspace_id, "name": f"Workspace {workspace_id}"}]
                return workspaces
        
        return []

    def change_workspace(self, workspace_id):
        if not self.token:
            return False

        try:
            self._sync_identity_from_token()
        except Exception:
            pass

        if str(self.workspace_id) == str(workspace_id) and str(self.selected_workspace_id) == str(workspace_id):
            return True

        url_qs = f"{self.base_url}/api/admin/workspace/change?workspaceId={workspace_id}"
        url_body = f"{self.base_url}/api/admin/workspace/change"
        for attempt in range(2):
            try:
                headers = dict(self._headers() or {})
                headers.setdefault("Content-Type", "application/json")

                candidates = [
                    ("PUT", url_qs, {"workspaceId": workspace_id}),
                    ("PUT", url_body, {"workspaceId": workspace_id}),
                    ("POST", url_qs, {"workspaceId": workspace_id}),
                    ("POST", url_body, {"workspaceId": workspace_id}),
                    ("GET", url_qs, None),
                ]

                r = None
                for method, url, payload in candidates:
                    if method == "PUT":
                        r = requests.put(url, headers=headers, json=payload, timeout=12)
                    elif method == "POST":
                        r = requests.post(url, headers=headers, json=payload, timeout=12)
                    else:
                        r = requests.get(url, headers=self._headers(), timeout=12)

                    if r.status_code == 405:
                        continue
                    break

                if r is None:
                    return False

                if r.status_code == 401:
                    if attempt == 0 and self._handle_401():
                        continue
                    return False

                r.raise_for_status()
                data = r.json()

                token_block = None
                if isinstance(data, dict):
                    token_block = data.get("data") if isinstance(data.get("data"), dict) else data

                access_token = None
                refresh_token = None
                if isinstance(token_block, dict):
                    access_token = (
                        token_block.get("access")
                        or token_block.get("token")
                        or token_block.get("accessToken")
                        or token_block.get("access_token")
                    )
                    refresh_token = (
                        token_block.get("refresh")
                        or token_block.get("refreshToken")
                        or token_block.get("refresh_token")
                    )

                if not access_token:
                    return False

                self.token = access_token
                if refresh_token:
                    self.refresh_token = refresh_token

                self.selected_workspace_id = workspace_id
                self.workspace_id = workspace_id

                try:
                    self.cache.clear()
                except Exception:
                    pass

                try:
                    self._sync_identity_from_token()
                except Exception:
                    pass

                return True
            except requests.RequestException:
                return False

        return False

    def list_folders(self, project_id: int | str, force: bool = False):
        key = f"tree:{project_id}"
        
        if force:
            self.cache.pop(key, None)
        
        if not force:
            cached = self._cached_get(key)
            if cached is not None: 
                return cached
        
        if not self.token: 
            return []
        
        url = f"{self.base_url}/api/folder/list/{project_id}"
        for attempt in range(2):
            try:
                r = requests.get(url, headers=self._headers(), timeout=20)
                if r.status_code == 401:
                    if attempt == 0 and self._handle_401():
                        continue
                        return []
                r.raise_for_status()
                data = r.json()
                if isinstance(data, list):
                    self.cache[key] = (time.time(), data)
                    return data
                return []
            except requests.RequestException:
                return []
        return []

    def get_document_types(self) -> dict:
        if not self.token:
            return {}

        url = f"{self.base_url}/api/document/types"
        for attempt in range(2):
            try:
                r = requests.get(url, headers=self._headers(), timeout=12)
                if r.status_code == 401:
                    if attempt == 0 and self._handle_401():
                        continue
                    return {}
                r.raise_for_status()
                data = r.json()

                if isinstance(data, dict) and isinstance(data.get("data"), dict):
                    return data.get("data") or {}

                if isinstance(data, dict) and data and all(isinstance(v, str) for v in data.values()):
                    return data

                return {}
            except requests.RequestException:
                return {}
            except Exception:
                return {}
        return {}

    def get_folder_details(self, folder_id: int | str, force: bool = False) -> dict | None:
        if not self.token:
            return None
        fid = str(folder_id)
        if not fid:
            return None

        if force:
            self.cache.pop(f"folder:{fid}", None)

        url = f"{self.base_url}/api/folder/{fid}"
        try:
            r = requests.get(url, headers=self._headers(), timeout=20)
            if r.status_code == 401:
                if self._handle_401():
                    r = requests.get(url, headers=self._headers(), timeout=20)
                else:
                    return None
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, dict) else None
        except requests.RequestException:
            return None

    def list_files(self, folder_id: int | str, project_id: int | str | None = None) -> list:
        folder_id_str = str(folder_id)
        if not folder_id_str:
            return []

        if project_id:
            try:
                folders_tree = self.list_folders(project_id, force=True)
                if folders_tree:
                    def find_folder_in_tree(tree, target_id):
                        if not isinstance(tree, list):
                            return None
                        for item in tree:
                            if str(item.get("id")) == target_id:
                                return item
                            children = item.get("children") or item.get("folders") or []
                            result = find_folder_in_tree(children, target_id)
                            if result:
                                return result
                        return None

                    folder_node = find_folder_in_tree(folders_tree, folder_id_str)
                    if folder_node:
                        children = folder_node.get("children") or folder_node.get("files") or []
                        if isinstance(children, list):
                            return children
            except Exception as e:
                pass

        folder_data = self.get_folder_details(folder_id_str)

        if not isinstance(folder_data, dict):
            return []

        children = (folder_data.get("children") or
                   folder_data.get("files") or
                   folder_data.get("documents") or
                   folder_data.get("items") or
                   folder_data.get("content") or
                   folder_data.get("folders") or [])

        if isinstance(children, list):
            return children

        if isinstance(folder_data, dict) and any(k.isdigit() for k in folder_data.keys()):
            result = list(folder_data.values())
            return result

        return []

    def download_file(self, file_id: int | str, filename: str) -> str:
        if not self.token:
            return ""

        doc_id = str(file_id)
        if not doc_id:
            return ""

        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        safe = sanitize_filename(filename or f"file_{doc_id}.bin")
        filepath = os.path.join(DOWNLOAD_DIR, safe)
        url = f"{self.base_url}/api/document/download/{doc_id}"

        try:
            with requests.get(url, headers=self._headers(), stream=True, timeout=60) as r:
                r.raise_for_status()
                chunk = 256 * 1024
                with open(filepath, "wb") as f:
                    for part in r.iter_content(chunk_size=chunk):
                        if not part:
                            continue
                        f.write(part)

            return filepath
        except requests.RequestException:
            return ""
        except Exception:
            return ""

    def upload_file(self, folder_id: int | str, local_path: str, filename: str, document_type_id: int | str | None = None, max_retries: int = 3) -> bool:
        result = upload_document(
            base_url=self.base_url,
            token=self.token or "",
            folder_id=folder_id,
            local_path=local_path,
            filename=filename,
            document_type_id=document_type_id,
            max_retries=max_retries,
            refresh_callback=self._handle_401,
        )

        self._last_upload_status = result.get("status", 0)
        self._last_upload_body = result.get("body", "")
        self._last_upload_response = result.get("response")

        if result.get("success"):
            try:
                for key in list((self.cache or {}).keys()):
                    if isinstance(key, str) and key.startswith("tree:"):
                        self.cache.pop(key, None)
            except Exception:
                pass

        return bool(result.get("success"))

def get_api_client(context: ContextTypes.DEFAULT_TYPE) -> Optional[APIClient]:
    if 'api_client' not in context.user_data:
        context.user_data['api_client'] = APIClient(BASE_URL)
    client = context.user_data['api_client']
    
    workspace_id = context.user_data.get('workspace_id')
    if workspace_id:
        client.selected_workspace_id = workspace_id
    
    if not client.token:
        return None
    
    return client

def login(username: str, password: str, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        client = APIClient(BASE_URL)
        success = client.login(username, password, remember_me=False)

        if success:
            context.user_data['api_client'] = client
            logger.info("✅ Успешный вход")
            logger.info("Access token obtained successfully")
            return True
        else:
            logger.warning("Неверный логин или пароль")
            return False
    except Exception as e:
        logger.error(f"Ошибка входа: {e}")
        return False

def get_workspaces(context: ContextTypes.DEFAULT_TYPE):
    client = get_api_client(context)
    if not client:
        return []

    try:
        workspaces = client.list_workspaces()
        return workspaces if isinstance(workspaces, list) else []
    except Exception as e:
        logger.error(f"Ошибка загрузки списка workspace: {e}")
        return []

def get_project_list(context: ContextTypes.DEFAULT_TYPE):
    client = get_api_client(context)
    if not client:
        return []
    
    try:
        projects = client.list_projects()
        return projects if isinstance(projects, list) else []
    except Exception as e:
        logger.error(f"Ошибка загрузки списка проектов: {e}")
        return []

def _clear_explorer_state(context: ContextTypes.DEFAULT_TYPE, reason: str = ""):
    """
    Clears all explorer-related state data.

    Args:
        context: Telegram context
        reason: Reason for clearing (for logging)
    """
    keys_to_remove = [
        'tree_cache',
        'full_tree',
        'path',
        'file_names',
        'project_id',
        'notify_folder_id',
        'explorer_message_id',
        'explorer_chat_id',
    ]
    
    cleared = []
    for key in keys_to_remove:
        if key in context.user_data:
            context.user_data.pop(key)
            cleared.append(key)
    
    if cleared:
        logger.info(f"🧹 Cleared explorer state ({reason}): {', '.join(cleared)}")

def get_folder_tree_by_project(project_id, context: ContextTypes.DEFAULT_TYPE, force: bool = False):
    """
    Returns:
        list: Tree structure (may be empty [])
        None: Error occurred (API client unavailable or request failed)
    """
    cache = context.user_data.get('tree_cache', {})
    now = time.time()

    if not force and str(project_id) in cache:
        cached_time, tree = cache[str(project_id)]
        if now - cached_time < 600:
            logger.info("🔁 Используем кэш дерева")
            return tree

    client = get_api_client(context)
    if not client:
        logger.error("❌ API клиент недоступен для загрузки дерева проекта")
        return None

    try:
        tree = client.list_folders(project_id, force=force)
        if isinstance(tree, list):
            if 'tree_cache' not in context.user_data:
                context.user_data['tree_cache'] = {}
            context.user_data['tree_cache'][str(project_id)] = (time.time(), tree)
            return tree
        logger.error(f"❌ API вернул не список: {type(tree)}")
        return None
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки дерева: {e}")
        return None

def download_file(file_id, file_name, context: ContextTypes.DEFAULT_TYPE):
    client = get_api_client(context)
    if not client:
        return None

    try:
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        safe_name = sanitize_filename(file_name)
        filepath = client.download_file(file_id, safe_name)
        
        if filepath:
            cleanup_old_files(DOWNLOAD_DIR, max_age_seconds=3600)
            return filepath
        else:
            logger.error(f"Ошибка при скачивании файла {file_id}")
            return None
    except Exception as e:
        logger.error(f"Ошибка сети при скачивании: {e}")
        return None

def upload_file_to_folder(file_path, folder_id, filename, context: ContextTypes.DEFAULT_TYPE, chat_id: int = None):
    client = get_api_client(context)
    if not client:
        return (False, "API клиент недоступен. Авторизуйтесь заново (/logout, затем /start).")

    try:
        safe_name = sanitize_filename(filename)
        
        logger.info(f"📤 ЗАПРОС НА ЗАГРУЗКУ ФАЙЛА:")
        logger.info(f"   folder_id: {folder_id}")
        logger.info(f"   Имя: {safe_name}")
        
        if not os.path.exists(file_path):
            return (False, f"Файл не найден: {file_path}")
        
        project_id = context.user_data.get('project_id')
        logger.info(f"   Проверяю существование папки {folder_id} (project_id={project_id})...")
        
        folder_exists = False
        is_root_folder = (str(folder_id) == str(project_id))
        
        if is_root_folder:
            folder_exists = True
        else:
            folder_details = client.get_folder_details(folder_id, force=True)
            if folder_details is None:
                return (False, f"❌ Папка была удалена или перемещена. Обновите структуру папок (кнопка '🔄 Обновить'). folder_id={folder_id}")
            else:
                folder_exists = True
        
        logger.info(f"   Получаю список типов документов...")
        doc_types = client.get_document_types()
        doc_type_id = 100
        
        if doc_types and isinstance(doc_types, dict):
            doc_type_ids = []
            for key, value in doc_types.items():
                try:
                    doc_type_ids.append(int(key))
                except:
                    pass
            doc_type_ids = sorted(doc_type_ids)
            if doc_type_ids:
                doc_type_id = doc_type_ids[0]
                first_type = doc_types.get(str(doc_type_id), {})
                if isinstance(first_type, dict):
                    type_name = first_type.get("name", "Unknown")
                else:
                    type_name = str(first_type) if first_type else "Unknown"
                logger.info(f"   Доступно типов документов: {len(doc_type_ids)}")
                logger.info(f"   Использую первый тип: id={doc_type_id}, name={type_name}")
        
        logger.info(f"   Проверяю файлы в папке {folder_id}...")
        cache_key = f"tree:{project_id}"
        if hasattr(client, 'cache') and cache_key in client.cache:
            del client.cache[cache_key]
        folder_docs = client.list_files(folder_id, project_id=project_id)
        file_count_before = sum(1 for item in folder_docs if item.get("type") != "folder") if folder_docs else 0
        logger.info(f"   Файлов в папке ДО загрузки: {file_count_before}")
        
        logger.info(f"   Используем client.upload_file() (document_type_id={doc_type_id})")
        
        success = client.upload_file(folder_id, file_path, safe_name, document_type_id=doc_type_id)
        
        logger.info(f"   client.upload_file() вернул: {success}")
        
        if not success:
            status = getattr(client, "_last_upload_status", None)
            body = getattr(client, "_last_upload_body", "")
            response = getattr(client, "_last_upload_response", None)
            
            error_msg = "Не удалось загрузить файл"
            if status is not None:
                error_msg = f"HTTP {status}"
            if body:
                body_trunc = str(body)[:500]
                error_msg += f": {body_trunc}"
            
            if status == 401:
                error_msg = "Ошибка авторизации (401). Сессия истекла. Выполните /logout и /start."
            elif status == 403:
                error_msg = "Нет прав на загрузку в эту папку (403)."
            elif status == 404:
                error_msg = "Папка не найдена (404). folder_id=" + str(folder_id)
            elif status == 413:
                error_msg = "Файл слишком большой (413)."
            elif status == 0:
                error_msg = f"Таймаут или ошибка соединения: {body}"
            
            return (False, error_msg)
        
        logger.info("✅ Загрузка успешна")
        
        logger.info(f"   Проверяю файлы в папке ПОСЛЕ загрузки...")
        import time as time_module
        time_module.sleep(0.5)

        cache_key = f"tree:{project_id}"
        if hasattr(client, 'cache') and cache_key in client.cache:
            del client.cache[cache_key]
        folder_docs_after = client.list_files(folder_id, project_id=project_id)
        file_count_after = sum(1 for item in folder_docs_after if item.get("type") != "folder") if folder_docs_after else 0
        logger.info(f"   Файлов в папке ПОСЛЕ загрузки: {file_count_after}")

        file_found = False
        file_id = None
        if folder_docs_after:
            for doc in folder_docs_after:
                doc_type = doc.get("type") or ""
                if doc_type == "folder":
                    continue

                doc_name = doc.get("originalName") or doc.get("name") or ""
                if doc_name == safe_name:
                    file_found = True
                    file_id = doc.get("id")
                    logger.info(f"   ✅ Файл найден в папке по API! file_id={file_id}")
                    break

        if not file_found:
            logger.error(f"❌ Файл '{safe_name}' НЕ найден в папке {folder_id} после загрузки!")
            return (False, "Сервер не создал файл (HTTP 200, но файл не появился). Проверьте права доступа и папку.")

        if hasattr(client, 'cache') and client.cache:
            for k in list(client.cache.keys()):
                if isinstance(k, str) and k.startswith("tree:"):
                    try:
                        del client.cache[k]
                    except:
                        pass

        project_id = context.user_data.get('project_id')
        if not project_id:
            logger.error("❌ Не определен project_id")
            return (False, "Не определен ID проекта.")

        if context.user_data.get('tree_cache'):
            cache_key = str(project_id)
            if cache_key in context.user_data['tree_cache']:
                logger.info("🔄 Инвалидирую кэш дерева проекта")
                del context.user_data['tree_cache'][cache_key]

        fresh_tree = get_folder_tree_by_project(project_id, context, force=True)
        if fresh_tree is None:
            logger.error("❌ Не удалось получить свежее дерево (ошибка API)")
            return (False, "Не удалось обновить дерево проекта после загрузки (ошибка API).")

        context.user_data['full_tree'] = fresh_tree

        logger.info(f"✅ Файл '{safe_name}' загружен успешно")

        # Записываем файл как загруженный через бота
        if file_id:
            record_bot_upload(chat_id, file_id, folder_id, safe_name)
        
        cleanup_old_files(DOWNLOAD_DIR, max_age_seconds=3600)
        return (True, "Файл успешно загружен")
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки файла: {e}")
        import traceback
        logger.error(f"   Traceback: {traceback.format_exc()}")
        return (False, f"Ошибка: {str(e)}")

class TokenClient:
    def __init__(self, base_url: str, token: str, workspace_id: int | str | None = None):
        self.client = APIClient(base_url)
        self.client.token = token
        self.client.workspace_id = workspace_id
        self.client.selected_workspace_id = workspace_id
        logger.info(f"TokenClient created: access token present, workspace={workspace_id}")
    
    def list_folders(self, project_id: int | str, force: bool = False) -> list:
        logger.info(f"TokenClient.list_folders вызван для project_id={project_id}, force={force}")
        result = self.client.list_folders(project_id, force=force)
        logger.info(f"TokenClient.list_folders вернул {len(result)} элементов")
        return result

def get_folder_tree_by_project_for_job(project_id, api_token, workspace_id=None):
    try:
        client = TokenClient(BASE_URL, api_token, workspace_id)
        tree = client.list_folders(project_id, force=True)
        if tree is None:
            return []
        return tree if isinstance(tree, list) else []
    except Exception as e:
        logger.error(f"Ошибка загрузки дерева в фоне: {e}")
        return []

def find_folder_by_id(tree, target_id):
    if not isinstance(tree, list):
        return None
    target_norm = str(target_id)
    for item in tree:
        if not isinstance(item, dict):
            continue
        try:
            item_id_norm = str(item.get("id"))
        except Exception:
            item_id_norm = ""
        if item_id_norm == target_norm and item.get("type") == "folder":
            return item
        if item.get("type") == "folder":
            children = item.get("children")
            if children is None:
                children = []
            if isinstance(children, list):
                result = find_folder_by_id(children, target_id)
                if result:
                    return result
    return None

def get_chat_token_info(chat_id, application) -> Dict:
    tokens = application.bot_data.get('chat_tokens', {})
    token_info = tokens.get(chat_id)
    return token_info if isinstance(token_info, dict) else {}

def get_api_token_for_chat(chat_id, application):
    token_info = get_chat_token_info(chat_id, application)
    token = token_info.get("token")
    return token if isinstance(token, str) and token else None

def get_chat_workspace_id(chat_id, application):
    token_info = get_chat_token_info(chat_id, application)
    workspace_id = _maybe_int(token_info.get("workspace_id"))
    if workspace_id is not None:
        return workspace_id

    token = token_info.get("token")
    if isinstance(token, str) and token:
        return _extract_workspace_id_from_token(token)
    return None

def get_chat_workspace_name(chat_id, application) -> Optional[str]:
    token_info = get_chat_token_info(chat_id, application)
    workspace_name = token_info.get("workspace_name")
    if isinstance(workspace_name, str) and workspace_name.strip():
        return workspace_name.strip()
    return None

def get_chat_user_id(chat_id, application):
    token_info = get_chat_token_info(chat_id, application)
    user_id = _maybe_int(token_info.get("user_id"))
    if user_id is not None:
        return user_id

    token = token_info.get("token")
    if isinstance(token, str) and token:
        return _extract_user_id_from_token(token)
    return None

def save_chat_token_info(chat_id, application, token, workspace_id=None, user_id=None, workspace_name=None):
    if 'chat_tokens' not in application.bot_data:
        application.bot_data['chat_tokens'] = {}

    existing = application.bot_data['chat_tokens'].get(chat_id, {})
    if not isinstance(existing, dict):
        existing = {}

    resolved_workspace_id = _maybe_int(workspace_id)
    if resolved_workspace_id is None:
        resolved_workspace_id = _maybe_int(existing.get("workspace_id"))
    if resolved_workspace_id is None and isinstance(token, str) and token:
        resolved_workspace_id = _extract_workspace_id_from_token(token)

    resolved_user_id = _maybe_int(user_id)
    if resolved_user_id is None:
        resolved_user_id = _maybe_int(existing.get("user_id"))
    if resolved_user_id is None and isinstance(token, str) and token:
        resolved_user_id = _extract_user_id_from_token(token)

    resolved_workspace_name = workspace_name
    if not (isinstance(resolved_workspace_name, str) and resolved_workspace_name.strip()):
        prev_name = existing.get("workspace_name")
        resolved_workspace_name = prev_name if isinstance(prev_name, str) else None
    if isinstance(resolved_workspace_name, str):
        resolved_workspace_name = resolved_workspace_name.strip()
    if not resolved_workspace_name:
        resolved_workspace_name = None

    application.bot_data['chat_tokens'][chat_id] = {
        "token": token,
        "workspace_id": resolved_workspace_id,
        "user_id": resolved_user_id,
        "workspace_name": resolved_workspace_name,
    }
    logger.info(
        f"Token saved for chat {chat_id}: "
        f"workspace={resolved_workspace_id} ({resolved_workspace_name}), user_id={resolved_user_id}"
    )

def remove_chat_token_info(chat_id, application):
    tokens = application.bot_data.get('chat_tokens', {})
    if isinstance(tokens, dict):
        tokens.pop(chat_id, None)

def save_approval_download_hint(application, chat_id: int, document_id: int, file_name: str):
    cache = application.bot_data.get("approval_download_hints")
    if not isinstance(cache, dict):
        cache = {}
        application.bot_data["approval_download_hints"] = cache

    key = f"{chat_id}:{document_id}"
    cache[key] = file_name

def get_approval_download_hint(application, chat_id: int, document_id: int) -> Optional[str]:
    cache = application.bot_data.get("approval_download_hints")
    if not isinstance(cache, dict):
        return None

    value = cache.get(f"{chat_id}:{document_id}")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None

def clear_chat_approval_download_hints(application, chat_id: int):
    cache = application.bot_data.get("approval_download_hints")
    if not isinstance(cache, dict):
        return

    prefix = f"{chat_id}:"
    for key in list(cache.keys()):
        if isinstance(key, str) and key.startswith(prefix):
            cache.pop(key, None)

def save_approval_notification_view(application, chat_id: int, workspace_id: int, process_id: int, text: str):
    cache = application.bot_data.get("approval_notification_views")
    if not isinstance(cache, dict):
        cache = {}
        application.bot_data["approval_notification_views"] = cache

    cache[f"{chat_id}:{workspace_id}:{process_id}"] = text

def get_approval_notification_view(application, chat_id: int, workspace_id: int, process_id: int) -> Optional[str]:
    cache = application.bot_data.get("approval_notification_views")
    if not isinstance(cache, dict):
        return None

    value = cache.get(f"{chat_id}:{workspace_id}:{process_id}")
    if isinstance(value, str) and value.strip():
        return value
    return None

def clear_chat_approval_notification_views(application, chat_id: int):
    cache = application.bot_data.get("approval_notification_views")
    if not isinstance(cache, dict):
        return

    prefix = f"{chat_id}:"
    for key in list(cache.keys()):
        if isinstance(key, str) and key.startswith(prefix):
            cache.pop(key, None)

def build_approval_notify_markup(workspace_id: int, process_id: int, lang: str = "ru") -> InlineKeyboardMarkup:
    download_text = TRANSLATIONS.get(lang, {}).get("download_file_btn", "📥 Скачать файл")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(download_text, callback_data=f"adocs_{workspace_id}_{process_id}")]
    ])

def _get_current_pending_step(steps: List[Dict]) -> Optional[Dict]:
    for item in steps:
        if not isinstance(item, dict):
            continue

        is_current = bool(item.get("isCurrent"))
        status = str(item.get("status") or "").strip().lower()
        if not is_current or status != "pending":
            continue

        step_info = item.get("step")
        if not isinstance(step_info, dict):
            continue

        step_id = _maybe_int(step_info.get("id"))
        if step_id is None:
            continue

        return {
            "id": step_id,
            "title": step_info.get("title") or f"Этап {step_info.get('stepNo', '?')}",
            "step_no": step_info.get("stepNo"),
        }
    return None

async def _resolve_workspace_name_by_id(token: str, workspace_id: int) -> Optional[str]:
    for endpoint in ("/api/workspace/list", "/api/admin/workspace/list"):
        status_code, payload = await _approval_api_get(token, endpoint)
        if status_code != 200:
            continue

        workspaces = _extract_data_list(payload)
        for ws in workspaces:
            ws_id = get_workspace_id(ws)
            if ws_id is not None and str(ws_id) == str(workspace_id):
                ws_name = get_workspace_name(ws)
                if isinstance(ws_name, str) and ws_name.strip():
                    return ws_name.strip()
    return None

async def _build_project_name_map(token: str) -> Dict[str, str]:
    status_code, payload = await _approval_api_get(token, "/api/project/list")
    if status_code != 200:
        return {}

    projects = _extract_data_list(payload)
    project_map: Dict[str, str] = {}
    for project in projects:
        project_id = _maybe_int(project.get("id") or project.get("projectId") or project.get("project_id"))
        if project_id is None:
            continue

        title = get_title(project)
        if isinstance(title, str) and title.strip():
            project_map[str(project_id)] = title.strip()
    return project_map

def _extract_approval_file_names(process: Dict) -> List[str]:
    documents = _extract_approval_documents(process)
    names = [doc.get("name") for doc in documents if isinstance(doc.get("name"), str) and doc.get("name").strip()]
    if names:
        return names

    result: List[str] = []
    seen = set()

    def push_name(value):
        if not isinstance(value, str):
            return
        name = value.strip()
        if not name:
            return
        key = name.lower()
        if key in seen:
            return
        seen.add(key)
        result.append(name)

    candidate_list_keys = (
        "files",
        "documents",
        "docs",
        "attachments",
        "approvalDocuments",
        "documentList",
        "processFiles",
    )
    candidate_name_keys = (
        "name",
        "title",
        "originalName",
        "fileName",
        "filename",
        "documentName",
        "docName",
    )

    for key in candidate_list_keys:
        items = process.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, str):
                push_name(item)
                continue
            if not isinstance(item, dict):
                continue
            for name_key in candidate_name_keys:
                push_name(item.get(name_key))

            nested_doc = item.get("document")
            if isinstance(nested_doc, dict):
                for name_key in candidate_name_keys:
                    push_name(nested_doc.get(name_key))

    for direct_key in ("fileName", "filename", "documentName", "docName"):
        push_name(process.get(direct_key))

    return result

def _extract_approval_documents(payload: Dict) -> List[Dict]:
    result: List[Dict] = []
    seen = set()

    def push_document(doc_id, name):
        doc_id_int = _maybe_int(doc_id)
        if doc_id_int is None:
            return

        name_str = str(name).strip() if isinstance(name, str) else ""
        if not name_str:
            name_str = f"document_{doc_id_int}"

        key = str(doc_id_int)
        if key in seen:
            return
        seen.add(key)
        result.append({"id": doc_id_int, "name": name_str})

    if not isinstance(payload, dict):
        return result

    documents = payload.get("documents")
    if isinstance(documents, list):
        for item in documents:
            if not isinstance(item, dict):
                continue
            doc = item.get("document") if isinstance(item.get("document"), dict) else item
            if not isinstance(doc, dict):
                continue

            push_document(
                doc.get("id") or doc.get("documentId") or doc.get("doc_id"),
                doc.get("fileName")
                or doc.get("originalName")
                or doc.get("name")
                or doc.get("title")
                or doc.get("documentName"),
            )

    files = payload.get("files")
    if isinstance(files, list):
        for item in files:
            if not isinstance(item, dict):
                continue
            push_document(
                item.get("id") or item.get("documentId") or item.get("doc_id"),
                item.get("fileName")
                or item.get("originalName")
                or item.get("name")
                or item.get("title")
                or item.get("documentName"),
            )

    return result

def _translate_status(status_value, lang: str = "ru") -> str:
    if status_value is None:
        return "Undefined" if lang == "en" else "Не определен"
    raw = str(status_value).strip()
    if not raw:
        return "Undefined" if lang == "en" else "Не определен"

    translations = STATUS_TRANSLATIONS.get(lang, STATUS_TRANSLATIONS.get("ru", {}))
    translated = translations.get(raw)
    if translated:
        return translated

    translated = translations.get(raw.lower())
    if translated:
        return translated

    return raw

async def _list_available_workspaces(token: str) -> List[Dict]:
    result: List[Dict] = []
    seen = set()

    for endpoint in ("/api/workspace/list", "/api/admin/workspace/list"):
        status_code, payload = await _approval_api_get(token, endpoint)
        if status_code != 200:
            continue

        for ws in _extract_data_list(payload):
            ws_id = _maybe_int(get_workspace_id(ws))
            if ws_id is None or ws_id <= 0:
                continue
            if ws_id in seen:
                continue

            seen.add(ws_id)
            ws_name = get_workspace_name(ws)
            if not isinstance(ws_name, str) or not ws_name.strip():
                ws_name = f"Workspace {ws_id}"

            result.append({"id": ws_id, "name": ws_name.strip()})

    return result

async def _check_approval_notifications_in_workspace(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    api_token: str,
    my_user_id: int,
    workspace_id: int,
    workspace_name: str,
    project_name_map: Dict[str, str],
) -> int:
    logger.info(
        f"🔍 Проверка согласований: chat={chat_id}, workspace={workspace_id} ({workspace_name}), user_id={my_user_id}"
    )

    status_code, process_payload = await _approval_api_get(
        api_token,
        "/api/approvals/process/list",
        params={"workspaceId": workspace_id},
    )
    if status_code != 200:
        logger.warning(
            f"⚠️ Не удалось загрузить процессы согласования для workspace={workspace_id}: HTTP {status_code}"
        )
        return 0

    processes = _extract_data_list(process_payload)
    if not processes:
        return 0

    notifications_sent = 0
    for process in processes:
        process_id = _maybe_int(process.get("id") or process.get("processId") or process.get("approvalProcessId"))
        if process_id is None:
            continue

        step_status_code, steps_payload = await _approval_api_get(
            api_token,
            f"/api/approvals/process/{process_id}/steps",
            params={"workspaceId": workspace_id},
        )
        if step_status_code != 200:
            logger.warning(
                f"⚠️ Не удалось загрузить шаги процесса {process_id} (workspace={workspace_id}): HTTP {step_status_code}"
            )
            continue

        steps = _extract_data_list(steps_payload)
        current_step = _get_current_pending_step(steps)
        if not current_step:
            continue

        step_id = _maybe_int(current_step.get("id"))
        if step_id is None:
            continue

        current_step_no = _maybe_int(current_step.get("step_no"))
        prev_step_status = None
        prev_step_id = None
        if current_step_no is not None and current_step_no > 0:
            target_prev_step_no = current_step_no - 1
            for step_item in steps:
                if not isinstance(step_item, dict):
                    continue
                step_meta = step_item.get("step")
                if not isinstance(step_meta, dict):
                    continue
                step_no = _maybe_int(step_meta.get("stepNo"))
                if step_no != target_prev_step_no:
                    continue

                prev_step_id = _maybe_int(step_meta.get("id"))

                status_value = step_item.get("status")
                if isinstance(status_value, str) and status_value.strip():
                    prev_step_status = status_value.strip()
                break

        if not prev_step_status:
            prev_step_status = "Нет предыдущего этапа" if current_step_no == 0 else "Не определен"

        prev_step_comment_text = ""
        if prev_step_id is not None:
            prev_users_status_code, prev_users_payload = await _approval_api_get(
                api_token,
                f"/api/approvals/process/step/{prev_step_id}/users",
                params={"workspaceId": workspace_id},
            )
            if prev_users_status_code == 200:
                prev_step_comments: List[str] = []
                for prev_item in _extract_data_list(prev_users_payload):
                    step_user_data = prev_item.get("stepUser") if isinstance(prev_item.get("stepUser"), dict) else {}
                    cmt = step_user_data.get("cmt")
                    if not isinstance(cmt, str) or not cmt.strip():
                        continue

                    full_name = prev_item.get("userFullName")
                    if isinstance(full_name, str) and full_name.strip():
                        prev_step_comments.append(f"{full_name.strip()}: {cmt.strip()}")
                    else:
                        prev_step_comments.append(cmt.strip())

                if prev_step_comments:
                    unique_prev_comments = list(dict.fromkeys(prev_step_comments))
                    prev_step_comment_text = "; ".join(unique_prev_comments[:2])
                    if len(unique_prev_comments) > 2:
                        prev_step_comment_text += f" (+{len(unique_prev_comments) - 2})"

        users_status_code, users_payload = await _approval_api_get(
            api_token,
            f"/api/approvals/process/step/{step_id}/users",
            params={"workspaceId": workspace_id},
        )
        if users_status_code != 200:
            logger.warning(
                f"⚠️ Не удалось загрузить пользователей шага {step_id} (process={process_id}): HTTP {users_status_code}"
            )
            continue

        step_users = _extract_data_list(users_payload)
        if not step_users:
            continue

        for item in step_users:
            step_user = item.get("stepUser") if isinstance(item.get("stepUser"), dict) else {}
            user_id = _maybe_int(step_user.get("userId") or step_user.get("user_id"))
            if user_id is None or user_id != my_user_id:
                continue

            user_step_status = _maybe_int(step_user.get("status"))
            if user_step_status != 0:
                continue

            if is_approval_notification_sent(chat_id, process_id, step_id, user_id):
                continue

            process_title = process.get("title") or process.get("name") or f"Процесс {process_id}"
            step_title = current_step.get("title") or f"Этап {step_id}"
            process_status = process.get("status")
            process_project_id = _maybe_int(
                process.get("projectId") or process.get("project_id") or process.get("workspaceProjectId")
            )
            created_ts_value = (
                process.get("createdTs")
                or process.get("createTime")
                or process.get("createdAt")
                or process.get("created_at")
            )
            safe_step_title = html.escape(str(step_title))
            safe_workspace_name = html.escape(str(workspace_name))

            process_info_status_code, process_info_payload = await _approval_api_get(
                api_token,
                f"/api/approvals/process/{process_id}",
                params={"workspaceId": workspace_id},
            )
            file_status_entries: List[str] = []

            if process_info_status_code == 200 and isinstance(process_info_payload, dict):
                process_info = process_info_payload.get("process")
                if isinstance(process_info, dict):
                    process_title = process_info.get("title") or process_title
                    process_status = process_info.get("status") or process_status
                    process_project_id = _maybe_int(
                        process_info.get("projectId")
                        or process_info.get("project_id")
                        or process_info.get("workspaceProjectId")
                    ) or process_project_id
                    created_ts_value = (
                        process_info.get("createdTs")
                        or process_info.get("createTime")
                        or process_info.get("createdAt")
                        or process_info.get("created_at")
                        or created_ts_value
                    )

                raw_docs = process_info_payload.get("documents")
                if isinstance(raw_docs, list):
                    for raw_doc in raw_docs:
                        if not isinstance(raw_doc, dict):
                            continue

                        doc_meta = raw_doc.get("document") if isinstance(raw_doc.get("document"), dict) else {}
                        doc_name = (
                            doc_meta.get("fileName")
                            or doc_meta.get("originalName")
                            or doc_meta.get("name")
                            or doc_meta.get("title")
                            or doc_meta.get("documentName")
                        )
                        if not isinstance(doc_name, str) or not doc_name.strip():
                            doc_id = _maybe_int(doc_meta.get("id") or raw_doc.get("docVerId"))
                            doc_name = f"Документ {doc_id}" if doc_id is not None else "Документ"

                        doc_status_raw = raw_doc.get("status")
                        doc_status_text = _translate_status(doc_status_raw)
                        entry = f"{doc_name.strip()} — {doc_status_text}"

                        doc_comment = raw_doc.get("comment")
                        if isinstance(doc_comment, str) and doc_comment.strip():
                            entry += f" ({doc_comment.strip()})"

                        file_status_entries.append(entry)

                documents_for_download = _extract_approval_documents(process_info_payload)
                file_names = _extract_approval_file_names(process_info_payload)
            else:
                documents_for_download = _extract_approval_documents(process)
                file_names = _extract_approval_file_names(process)

            if not file_status_entries and file_names:
                for fname in file_names[:5]:
                    if isinstance(fname, str) and fname.strip():
                        file_status_entries.append(f"{fname.strip()} — Не определен")

            if file_status_entries:
                visible_statuses = file_status_entries[:4]
                file_statuses_text = "; ".join(visible_statuses)
                if len(file_status_entries) > 4:
                    file_statuses_text += f" (+{len(file_status_entries) - 4})"
            else:
                file_statuses_text = "Не определены"

            project_name = project_name_map.get(str(process_project_id)) if process_project_id is not None else None
            if isinstance(project_name, str):
                project_name = project_name.strip()
            if not project_name:
                project_name = None

            if file_names:
                visible_file_names = file_names[:5]
                files_text = ", ".join(visible_file_names)
                if len(file_names) > 5:
                    files_text += f" (+{len(file_names) - 5})"
            else:
                files_text = t(chat_id, "documents_not_specified")

            safe_process_title = html.escape(str(process_title))
            safe_step_title = html.escape(str(step_title))
            safe_files_text = html.escape(str(files_text))

            approval_link = f"{WEB_BASE_URL}/approvals/{process_id}"
            approval_link_href = html.escape(approval_link, quote=True)
            lang = get_user_language(chat_id)
            reply_markup = build_approval_notify_markup(workspace_id, process_id, lang=lang)

            message = t(chat_id, "approval_notification", 
                title=safe_process_title, 
                step=safe_step_title, 
                documents=safe_files_text, 
                link=approval_link_href)

            try:
                save_approval_notification_view(context.application, chat_id, workspace_id, process_id, message)
                await safe_send_message(
                    context.bot,
                    chat_id,
                    message,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=reply_markup,
                )
                mark_approval_notification_sent(chat_id, process_id, step_id, user_id, workspace_id)
                notifications_sent += 1
            except Exception as e:
                logger.error(
                    f"Не удалось отправить уведомление по согласованию в чат {chat_id} "
                    f"(process={process_id}, step={step_id}): {e}"
                )

    return notifications_sent

async def check_approval_notifications_job(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data or {}
    chat_id = job_data.get("chat_id")
    if chat_id is None:
        return

    workspace_id = _maybe_int(job_data.get("workspace_id"))
    if workspace_id in (None, 0):
        workspace_id = get_chat_workspace_id(chat_id, context.application)
    if workspace_id is not None and workspace_id <= 0:
        workspace_id = None

    api_token = get_api_token_for_chat(chat_id, context.application)
    if not api_token:
        logger.warning(f"❌ Нет API-токена для чата {chat_id}. Проверка согласований пропущена.")
        return

    my_user_id = _maybe_int(job_data.get("user_id"))
    if my_user_id is None:
        my_user_id = get_chat_user_id(chat_id, context.application)
    if my_user_id is None:
        my_user_id = _extract_user_id_from_token(api_token)

    if my_user_id is None:
        logger.warning(f"❌ Нет user_id Larix для чата {chat_id}. Проверка согласований пропущена.")
        return

    project_name_map = await _build_project_name_map(api_token)

    workspace_targets = await _list_available_workspaces(api_token)

    # Если список пространств не загрузился, пробуем текущий выбранный/из токена как fallback.
    if not workspace_targets:
        fallback_workspace_id = workspace_id
        if fallback_workspace_id is None:
            fallback_workspace_id = _extract_workspace_id_from_token(api_token)
        if fallback_workspace_id is not None and fallback_workspace_id > 0:
            fallback_workspace_name = await _resolve_workspace_name_by_id(api_token, fallback_workspace_id) or f"Workspace {fallback_workspace_id}"
            workspace_targets.append({"id": fallback_workspace_id, "name": fallback_workspace_name})

    if not workspace_targets:
        logger.warning(
            f"⚠️ Не удалось определить рабочие пространства для проверки согласований (chat={chat_id}, user_id={my_user_id})"
        )
        return

    total_sent = 0
    for target in workspace_targets:
        ws_id = _maybe_int(target.get("id"))
        if ws_id is None or ws_id <= 0:
            continue
        ws_name = target.get("name") if isinstance(target.get("name"), str) else f"Workspace {ws_id}"

        scoped_token = await _get_workspace_scoped_token(api_token, ws_id)
        if not scoped_token:
            logger.warning(
                f"⚠️ Не удалось переключить контекст workspace для согласований: ws={ws_id}, chat={chat_id}"
            )
            continue

        total_sent += await _check_approval_notifications_in_workspace(
            context,
            chat_id,
            scoped_token,
            my_user_id,
            ws_id,
            ws_name,
            project_name_map,
        )

    if total_sent:
        logger.info(f"📢 Отправлено уведомлений по согласованиям: {total_sent}")

def restart_approval_notifications_for_chat(application, chat_id: int, workspace_id=None, user_id=None):
    if not application.job_queue:
        logger.warning("⚠️ JobQueue недоступен. Уведомления по согласованиям не запущены.")
        return

    job_name = f"approval_notify_{chat_id}"
    for job in application.job_queue.get_jobs_by_name(job_name):
        job.schedule_removal()

    token = get_api_token_for_chat(chat_id, application)
    if not token:
        logger.info(f"ℹ️ Нет токена для чата {chat_id}. Задача согласований не создана.")
        return

    resolved_workspace = _maybe_int(workspace_id)
    if resolved_workspace in (None, 0):
        resolved_workspace = get_chat_workspace_id(chat_id, application)
    if resolved_workspace in (None, 0):
        resolved_workspace = _extract_workspace_id_from_token(token)
    if resolved_workspace is not None and resolved_workspace <= 0:
        resolved_workspace = None

    resolved_user = _maybe_int(user_id)
    if resolved_user is None:
        resolved_user = get_chat_user_id(chat_id, application)
    if resolved_user is None:
        resolved_user = _extract_user_id_from_token(token)

    if resolved_user is None:
        logger.info(
            f"ℹ️ Недостаточно данных для запуска проверки согласований chat={chat_id}: "
            f"workspace={resolved_workspace}, user_id={resolved_user}"
        )
        return

    application.job_queue.run_repeating(
        check_approval_notifications_job,
        interval=APPROVALS_POLL_INTERVAL_SEC,
        first=10,
        name=job_name,
        data={
            "chat_id": chat_id,
            "workspace_id": resolved_workspace,
            "user_id": resolved_user,
        },
    )
    ws_log = resolved_workspace if resolved_workspace is not None else "ALL"
    logger.info(
        f"✅ Запущена задача согласований для чата {chat_id} "
        f"(workspace={ws_log}, user_id={resolved_user}, interval={APPROVALS_POLL_INTERVAL_SEC}s)"
    )

def build_notify_job_name(chat_id: int, project_id: int, folder_id: int, workspace_id=None, larix_user_id=None) -> str:
    user = _maybe_int(larix_user_id)
    user_part = user if user is not None else "na"
    ws = _maybe_int(workspace_id)
    ws_part = ws if ws is not None else "na"
    return f"notify_{chat_id}_{user_part}_{ws_part}_{project_id}_{folder_id}"

def remove_notify_jobs(job_queue, chat_id: int, project_id: int, folder_id: int, workspace_id=None, larix_user_id=None):
    if not job_queue:
        return

    ws = _maybe_int(workspace_id)
    ws_part = ws if ws is not None else "na"
    names = {
        build_notify_job_name(chat_id, project_id, folder_id, workspace_id, larix_user_id),
        f"notify_{chat_id}_{ws_part}_{project_id}_{folder_id}",
        f"notify_{chat_id}_{folder_id}",  # legacy name
    }
    for name in names:
        for job in job_queue.get_jobs_by_name(name):
            job.schedule_removal()

async def check_notifications_job(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    chat_id = job_data["chat_id"]
    folder_id = job_data["folder_id"]
    project_id = job_data["project_id"]
    saved_state = job_data.get("saved_state")
    path_display = job_data.get("path_display", "Папка")
    workspace_id = job_data.get("workspace_id")
    if workspace_id is None:
        workspace_id = get_chat_workspace_id(chat_id, context.application)

    subscription_user_id = _maybe_int(job_data.get("larix_user_id"))
    if subscription_user_id in (None, 0):
        logger.info(
            f"ℹ️ Пропуск legacy-подписки chat={chat_id}, folder={folder_id}: "
            "нет привязки к user_id Larix"
        )
        return

    current_chat_user_id = get_chat_user_id(chat_id, context.application)
    if current_chat_user_id is None or subscription_user_id != current_chat_user_id:
        logger.info(
            f"ℹ️ Пропуск проверки подписки chat={chat_id}, folder={folder_id}: "
            f"подписка user_id={subscription_user_id}, текущий user_id={current_chat_user_id}"
        )
        return

    api_token = get_api_token_for_chat(chat_id, context.application)
    if not api_token:
        logger.warning(f"❌ Нет API-токена для чата {chat_id}. Пропускаем проверку, подписка сохранена.")
        return

    scoped_token = await _get_workspace_scoped_token(api_token, workspace_id)
    if not scoped_token:
        logger.warning(
            f"⚠️ Не удалось переключить контекст workspace для папки {folder_id} (chat={chat_id}, ws={workspace_id})"
        )
        return

    logger.info(f"🔍 Проверка уведомлений для чата {chat_id}, папка {folder_id}, workspace {workspace_id}")
    logger.info(f"API token present for chat {chat_id}, workspace {workspace_id}")

    full_tree = get_folder_tree_by_project_for_job(project_id, scoped_token, workspace_id)
    if not full_tree:
        logger.warning(f"⚠️ Не удалось обновить дерево для проекта {project_id}")
        return

    if folder_id == project_id:
        current_files = get_files_flat(full_tree)
    else:
        folder_obj = find_folder_by_id(full_tree, folder_id)
        if not folder_obj:
            logger.warning(f"Папка {folder_id} не найдена в проекте {project_id}")
            return
        current_files = get_files_flat(folder_obj.get("children", []), path_display)

    logger.info(f"📂 Получено {len(current_files)} файлов из API")
    for f in current_files[:3]:
        logger.info(f"   Файл: id={f.get('id')}, name={f.get('name')}, version={f.get('version')}")
    if len(current_files) > 3:
        logger.info(f"   ... и ещё {len(current_files) - 3} файлов")

    # Если это первый запуск после рестарта, сбрасываем слепок без уведомлений
    if job_data.get("skip_first_notification"):
        reset_folder_file_states(chat_id, folder_id, project_id)
        for file_info in current_files:
            update_file_state(chat_id, file_info, folder_id, project_id, file_info.get("path", ""))
        job_data["saved_state"] = current_files
        job_data["skip_first_notification"] = False
        logger.info("✅ Первичный слепок обновлён, уведомления пропущены")
        return

    # Используем новую функцию для проверки изменений
    changes = check_folder_changes(chat_id, folder_id, project_id, current_files, skip_recent_uploads=True)

    if changes:
        logger.info(f"📢 Обнаружено {len(changes)} изменений")
    else:
        logger.info(f"✅ Изменений нет")

    if changes:
        messages = []
        lang = get_user_language(chat_id)
        for change in changes[:10]:
            change_type = change["type"]
            file_info = change.get("file") or change.get("old_state", {})
            old_state = change.get("old_state")

            msg = format_file_info_notification(file_info, change_type, old_state, lang=lang)
            messages.append(msg)

        safe_path_display = html.escape(str(path_display))
        notification_header = t(chat_id, "folder_notification", path=safe_path_display)
        full_message = f"{notification_header}\n\n" + "\n\n".join(messages)
        if len(changes) > 10:
            full_message += f"\n\n{t(chat_id, 'more_changes', count=len(changes) - 10)}"

        try:
            await safe_send_message(context.bot, chat_id, full_message, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление в чат {chat_id}: {e}")

    # Обновляем сохраненное состояние (для совместимости со старым кодом)
    job_data["saved_state"] = current_files

async def refresh_current_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = context.user_data.get('state')
    
    if state == WAITING_FOR_LOGIN:
        await update.message.reply_text(t(chat_id, "welcome"), reply_markup=get_main_reply_keyboard(chat_id))
    elif state == WAITING_FOR_PASSWORD:
        username = context.user_data.get('username', '')
        await update.message.reply_text(t(chat_id, "login_accepted", username=username), reply_markup=get_main_reply_keyboard(chat_id))
    elif state == SELECTING_WORKSPACE:
        workspaces = get_workspaces(context)
        if workspaces:
            keyboard = []
            lang = get_user_language(chat_id)
            for ws in workspaces:
                name = get_workspace_name(ws)
                ws_id = get_workspace_id(ws)
                if ws_id:
                    keyboard.append([InlineKeyboardButton(f"🏢 {name}", callback_data=f"workspace_{ws_id}")])
            await update.message.reply_text(t(chat_id, "select_workspace"), reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text(t(chat_id, "workspaces_load_error"))
    elif state == SELECTING_PROJECT:
        projects = context.user_data.get('projects', [])
        if projects:
            keyboard = []
            for proj in projects:
                name = get_title(proj)
                proj_id = proj["id"]
                keyboard.append([InlineKeyboardButton(f"📦 {name}", callback_data=f"project_{proj_id}")])

            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(t(chat_id, "select_project"), reply_markup=reply_markup)
        else:
            await update.message.reply_text(t(chat_id, "login_error"))
            context.user_data['state'] = WAITING_FOR_LOGIN

    else:
        await update.message.reply_text(t(chat_id, "use_start"))

async def show_project_selection_screen(chat_id: int, context, bot, previous_message=None):
    """
    Shows project selection screen. Used for recovery after errors.
    If previous_message is provided, tries to edit it; otherwise sends new message.
    """
    projects = context.user_data.get('projects', [])
    if not projects:
        projects = get_project_list(context)
        if projects:
            context.user_data['projects'] = projects
    
    if not projects:
        if previous_message:
            try:
                await previous_message.reply_text(t(chat_id, "projects_load_error"))
            except:
                await bot.send_message(chat_id, t(chat_id, "projects_load_error"))
        else:
            await bot.send_message(chat_id, t(chat_id, "projects_load_error"))
        return
    
    context.user_data['state'] = SELECTING_PROJECT
    
    keyboard = []
    for proj in projects:
        name = get_title(proj)
        proj_id = proj["id"]
        keyboard.append([InlineKeyboardButton(f"📦 {name}", callback_data=f"project_{proj_id}")])
    keyboard.append([InlineKeyboardButton(t(chat_id, "change_workspace"), callback_data="change_workspace")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if previous_message:
        try:
            await previous_message.reply_text(t(chat_id, "select_project"), reply_markup=reply_markup)
            return
        except Exception as e:
            logger.warning(f"Could not reply to previous message: {e}")
    
    await bot.send_message(chat_id, t(chat_id, "select_project"), reply_markup=reply_markup)

async def show_empty_project_explorer(chat_id: int, context, bot, project_name: str, project_id: int):
    """
    Shows explorer for an empty project.
    """
    context.user_data['project_id'] = project_id
    context.user_data['full_tree'] = []
    context.user_data['path'] = []
    context.user_data['file_names'] = {}
    context.user_data['state'] = IN_EXPLORER
    
    keyboard = [
        [InlineKeyboardButton(t(chat_id, "statistics"), callback_data=STATS_PROJECT)],
        [InlineKeyboardButton(t(chat_id, "refresh"), callback_data="refresh_folder")],
        [InlineKeyboardButton(t(chat_id, "change_projects"), callback_data="change_project")],
        [InlineKeyboardButton(t(chat_id, "change_workspace"), callback_data="change_workspace")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"📂 <b>{html.escape(project_name)}</b>\n\n{t(chat_id, 'project_empty')}"
    
    await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode="HTML")

async def show_current_level(update_or_query, context):
    query = None
    message = None
    chat_id = None
    
    if hasattr(update_or_query, 'data'):
        query = update_or_query
        message = update_or_query.message
        is_callback = True
        if message and hasattr(message, 'chat'):
            chat_id = message.chat.id
        elif hasattr(query, 'effective_chat') and query.effective_chat:
            chat_id = query.effective_chat.id
    elif hasattr(update_or_query, 'message') and update_or_query.message:
        message = update_or_query.message
        is_callback = False
        if hasattr(message, 'chat'):
            chat_id = message.chat.id
    else:
        logger.error(f"show_current_level: неизвестный тип объекта: {type(update_or_query)}")
        return
    
    path = context.user_data.get('path', [])
    full_tree = context.user_data.get('full_tree', [])

    logger.info(f"show_current_level: path={len(path)} уровней, full_tree={len(full_tree)} элементов, is_callback={is_callback}")

    if not full_tree:
        if is_callback:
            try:
                await query.message.edit_text(t(chat_id, "no_project_data"))
            except (TimedOut, NetworkError):
                await query.message.reply_text(t(chat_id, "no_project_data"))
        else:
            await message.reply_text(t(chat_id, "no_project_data"))
        return

    current_level = full_tree if len(path) == 0 else (path[-1].get("children") or [])

    if not isinstance(current_level, list):
        current_level = []

    folders = []
    files = []

    for item in current_level:
        if isinstance(item, dict):
            if item.get("type") == "folder":
                folders.append(item)
            elif item.get("type") == "file":
                files.append(item)

    keyboard = []

    project_id = context.user_data.get('project_id')
    subscribed_folder_ids = set()
    subscriptions = []
    if chat_id and project_id:
        current_larix_user_id = get_chat_user_id(chat_id, context.application)
        subscriptions = get_user_subscriptions(chat_id, current_larix_user_id)
        subscribed_folder_ids = {
            s.get('folder_id') for s in subscriptions if s.get('project_id') == project_id
        }

    for folder in folders:
        name = get_title(folder)
        fid = folder["id"]
        bell = " 🔔" if fid in subscribed_folder_ids else ""
        keyboard.append([InlineKeyboardButton(f"📁 {name}{bell}", callback_data=f"folder_{fid}")])

    for file in files:
        name = file.get("originalName") or file.get("name") or t(chat_id, "no_name")
        fid = file["id"]
        keyboard.append([InlineKeyboardButton(f"📄 {name}", callback_data=f"file_{fid}")])

    nav_buttons = []
    if path:
        nav_buttons.append(InlineKeyboardButton(t(chat_id, "back"), callback_data="back"))
    
    lang = get_user_language(chat_id) if chat_id else "ru"
    
    if not path:
        nav_buttons.extend([
            InlineKeyboardButton(t(chat_id, "statistics"), callback_data=STATS_PROJECT),
            InlineKeyboardButton(t(chat_id, "refresh"), callback_data="refresh_folder"),
            InlineKeyboardButton(t(chat_id, "change_projects"), callback_data="change_project"),
            InlineKeyboardButton(t(chat_id, "change_workspace"), callback_data="change_workspace"),
        ])
        keyboard.append(nav_buttons)
    else:
        nav_buttons.extend([
            InlineKeyboardButton(t(chat_id, "statistics"), callback_data=STATS_PROJECT),
            InlineKeyboardButton(t(chat_id, "refresh"), callback_data="refresh_folder"),
            InlineKeyboardButton(t(chat_id, "upload_file"), callback_data="upload"),
        ])
        keyboard.append(nav_buttons)
        
        if chat_id:
            folder_id = path[-1]["id"]
            
            existing = next((s for s in subscriptions if s.get('folder_id') == folder_id and s.get('project_id') == project_id), None)

            notify_text = t(chat_id, "unsubscribe") if existing else t(chat_id, "subscribe")
            keyboard.append([InlineKeyboardButton(notify_text, callback_data=TOGGLE_NOTIFY)])

    reply_markup = InlineKeyboardMarkup(keyboard)
    
    path_str = " → ".join([get_title(p) for p in path]) if path else t(chat_id, "root")
    
    if not folders and not files:
        text = f"📂 <b>{path_str}</b>\n\n{t(chat_id, 'folder_empty')}"
    else:
        text = f"📂 <b>{path_str}</b>\n\n{t(chat_id, 'folders_files', folders=len(folders), files=len(files))}"
    
    if is_callback:
        try:
            await query.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
            context.user_data['explorer_message_id'] = query.message.message_id
            context.user_data['explorer_chat_id'] = query.message.chat.id
            logger.info(f"💾 Explorer message updated via callback: message_id={query.message.message_id}, chat_id={query.message.chat.id}")
        except (TimedOut, NetworkError):
            await query.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
    else:
        sent_message = await message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
        context.user_data['explorer_message_id'] = sent_message.message_id
        context.user_data['explorer_chat_id'] = sent_message.chat.id
        logger.info(f"💾 New explorer message sent: message_id={sent_message.message_id}, chat_id={sent_message.chat.id}")

async def refresh_explorer_after_language_change(context, chat_id: int):
    """
    Пересоздаёт explorer-сообщение после смены языка.
    Всегда отправляет НОВОЕ сообщение на новом языке, а не редактирует старое.
    """
    logger.info(f"🔄 refresh_explorer_after_language_change: пересоздание explorer для chat_id={chat_id}")
    
    path = context.user_data.get('path', [])
    full_tree = context.user_data.get('full_tree', [])
    
    logger.info(f"   path={len(path)} уровней, full_tree={len(full_tree) if full_tree else 0} элементов")
    
    if not full_tree:
        logger.warning(f"   ⚠️ full_tree пустой, невозможно пересоздать explorer")
        return
    
    current_level = full_tree if len(path) == 0 else (path[-1].get("children") or [])
    if not isinstance(current_level, list):
        current_level = []
    
    folders = []
    files = []
    for item in current_level:
        if isinstance(item, dict):
            if item.get("type") == "folder":
                folders.append(item)
            elif item.get("type") == "file":
                files.append(item)
    
    logger.info(f"   📁 {len(folders)} папок, 📄 {len(files)} файлов")
    
    keyboard = []
    project_id = context.user_data.get('project_id')
    subscribed_folder_ids = set()
    subscriptions = []
    if chat_id and project_id:
        current_larix_user_id = get_chat_user_id(chat_id, context.application)
        subscriptions = get_user_subscriptions(chat_id, current_larix_user_id)
        subscribed_folder_ids = {
            s.get('folder_id') for s in subscriptions if s.get('project_id') == project_id
        }
    
    for folder in folders:
        name = get_title(folder)
        fid = folder["id"]
        bell = " 🔔" if fid in subscribed_folder_ids else ""
        keyboard.append([InlineKeyboardButton(f"📁 {name}{bell}", callback_data=f"folder_{fid}")])
    
    for file in files:
        name = file.get("originalName") or file.get("name") or "Без имени"
        fid = file["id"]
        keyboard.append([InlineKeyboardButton(f"📄 {name}", callback_data=f"file_{fid}")])
    
    nav_buttons = []
    if path:
        nav_buttons.append(InlineKeyboardButton(t(chat_id, "back"), callback_data="back"))
    
    if not path:
        nav_buttons.extend([
            InlineKeyboardButton(t(chat_id, "statistics"), callback_data=STATS_PROJECT),
            InlineKeyboardButton(t(chat_id, "refresh"), callback_data="refresh_folder"),
            InlineKeyboardButton(t(chat_id, "change_projects"), callback_data="change_project"),
            InlineKeyboardButton(t(chat_id, "change_workspace"), callback_data="change_workspace"),
        ])
        keyboard.append(nav_buttons)
    else:
        nav_buttons.extend([
            InlineKeyboardButton(t(chat_id, "statistics"), callback_data=STATS_PROJECT),
            InlineKeyboardButton(t(chat_id, "refresh"), callback_data="refresh_folder"),
            InlineKeyboardButton(t(chat_id, "upload_file"), callback_data="upload"),
        ])
        keyboard.append(nav_buttons)
        
        if chat_id:
            folder_id = path[-1]["id"]
            existing = next((s for s in subscriptions if s.get('folder_id') == folder_id and s.get('project_id') == project_id), None)
            notify_text = t(chat_id, "unsubscribe") if existing else t(chat_id, "subscribe")
            keyboard.append([InlineKeyboardButton(notify_text, callback_data=TOGGLE_NOTIFY)])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    path_str = " → ".join([get_title(p) for p in path]) if path else t(chat_id, "root")
    
    if not folders and not files:
        text = f"📂 <b>{path_str}</b>\n\n{t(chat_id, 'folder_empty')}"
    else:
        text = f"📂 <b>{path_str}</b>\n\n{t(chat_id, 'folders_files', folders=len(folders), files=len(files))}"
    
    logger.info(f"   📤 Отправка нового explorer-сообщения на новом языке...")
    
    try:
        new_message = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        context.user_data['explorer_message_id'] = new_message.message_id
        context.user_data['explorer_chat_id'] = new_message.chat.id
        logger.info(f"   ✅ Новое explorer-сообщение отправлено: message_id={new_message.message_id}, chat_id={new_message.chat.id}")
        logger.info(f"   💾 Обновлены explorer_message_id и explorer_chat_id в user_data")
    except Exception as e:
        logger.error(f"   ❌ Не удалось отправить новое explorer-сообщение: {e}")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает команду /start и Restart bot."""
    chat_id = update.effective_chat.id
    
    logger.info(f"🔄 start_command вызвана для chat_id={chat_id}")
    
    # Сохраняем ID старого explorer-сообщения до очистки
    old_explorer_message_id = context.user_data.get('explorer_message_id')
    old_explorer_chat_id = context.user_data.get('explorer_chat_id')
    
    logger.info(f"   old_explorer_message_id={old_explorer_message_id}, old_explorer_chat_id={old_explorer_chat_id}")
    
    # Удаляем или деактивируем старое explorer-сообщение
    if old_explorer_message_id and old_explorer_chat_id:
        try:
            logger.info(f"   🗑️ Попытка удаления старого explorer-сообщения {old_explorer_message_id}")
            await context.bot.delete_message(
                chat_id=old_explorer_chat_id,
                message_id=old_explorer_message_id
            )
            logger.info(f"   ✅ Старое explorer-сообщение удалено")
        except Exception as e:
            logger.warning(f"   ⚠️ Не удалось удалить старое explorer-сообщение: {e}")
            # Пробуем убрать inline keyboard как fallback
            try:
                logger.info(f"   🔧 Попытка убрать inline keyboard...")
                await context.bot.edit_message_reply_markup(
                    chat_id=old_explorer_chat_id,
                    message_id=old_explorer_message_id,
                    reply_markup=None
                )
                logger.info(f"   ✅ Inline keyboard удалена")
            except Exception as e2:
                logger.warning(f"   ⚠️ Не удалось убрать inline keyboard: {e2}")
    
    # Очищаем все данные пользователя (включая explorer-related)
    context.user_data.clear()
    context.user_data['state'] = WAITING_FOR_LOGIN
    
    logger.info(f"   ✅ user_data очищена (path, full_tree, file_names, explorer_message_id, etc.), state установлен в WAITING_FOR_LOGIN")
    
    # Показываем приветственное сообщение
    await update.message.reply_text(t(chat_id, "welcome"), reply_markup=get_main_reply_keyboard(chat_id))
    
    logger.info(f"   ✅ Welcome-сообщение отправлено")

async def logout_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает команду /logout."""
    chat_id = update.effective_chat.id
    
    logger.info(f"🚪 logout_command вызвана для chat_id={chat_id}")
    
    # Сохраняем ID старого explorer-сообщения до очистки
    old_explorer_message_id = context.user_data.get('explorer_message_id')
    old_explorer_chat_id = context.user_data.get('explorer_chat_id')
    
    logger.info(f"   old_explorer_message_id={old_explorer_message_id}, old_explorer_chat_id={old_explorer_chat_id}")
    
    client = get_api_client(context)
    if client:
        client.logout()
    
    clear_chat_token_info(context.application, chat_id)
    clear_chat_approval_notification_views(context.application, chat_id)
    
    # Удаляем или деактивируем старое explorer-сообщение
    if old_explorer_message_id and old_explorer_chat_id:
        try:
            logger.info(f"   🗑️ Попытка удаления старого explorer-сообщения {old_explorer_message_id}")
            await context.bot.delete_message(
                chat_id=old_explorer_chat_id,
                message_id=old_explorer_message_id
            )
            logger.info(f"   ✅ Старое explorer-сообщение удалено")
        except Exception as e:
            logger.warning(f"   ⚠️ Не удалось удалить старое explorer-сообщение: {e}")
            # Пробуем убрать inline keyboard как fallback
            try:
                logger.info(f"   🔧 Попытка убрать inline keyboard...")
                await context.bot.edit_message_reply_markup(
                    chat_id=old_explorer_chat_id,
                    message_id=old_explorer_message_id,
                    reply_markup=None
                )
                logger.info(f"   ✅ Inline keyboard удалена")
            except Exception as e2:
                logger.warning(f"   ⚠️ Не удалось убрать inline keyboard: {e2}")
    
    # Очищаем все данные пользователя (включая explorer-related)
    context.user_data.clear()
    context.user_data['state'] = WAITING_FOR_LOGIN
    
    logger.info(f"   ✅ user_data очищена, state установлен в WAITING_FOR_LOGIN")
    
    await update.message.reply_text(t(chat_id, "logout_success"), reply_markup=get_main_reply_keyboard(chat_id))
    
    logger.info(f"   ✅ Logout-сообщение отправлено")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = context.user_data.get('state')
    
    update_id = update.update_id
    last_update_id = context.user_data.get('last_update_id')
    if last_update_id is not None and update_id <= last_update_id:
        logger.warning(f"⚠️ Дублирующий update_id={update_id} (last={last_update_id}), пропускаем")
        return
    context.user_data['last_update_id'] = update_id
    
    # Обработка текстовых сообщений
    if update.message.text:
        text = update.message.text
        text_stripped = text.strip()
        
        # Логируем входящее сообщение
        logger.info(f"📩 Текстовое сообщение от chat_id={chat_id}, state={state}: '{text}'")
        
        # Проверка на служебные команды (ДО любых проверок логина/пароля!)
        cmd_type, normalized = normalize_service_command(text_stripped)
        
        # Блокируем служебные команды от записи в username/password
        if cmd_type is not None:
            logger.warning(f"🚫 Блокируем служебную команду cmd_type={cmd_type}: текст '{text}' не будет записан как логин/пароль")
            
            if cmd_type == "restart":
                logger.info(f"🔄 Служебная команда restart от chat_id={chat_id}")
                await start_command(update, context)
                return
            
            if cmd_type == "language":
                logger.info(f"🌐 Служебная команда language от chat_id={chat_id}")
                current_lang = get_user_language(chat_id)
                new_lang = "en" if current_lang == "ru" else "ru"
                set_user_language(chat_id, new_lang)
                lang_name = TRANSLATIONS["en"]["language_en"] if new_lang == "en" else TRANSLATIONS["ru"]["language_ru"]
                await update.message.reply_text(t(chat_id, "language_switched", lang_name=lang_name), reply_markup=get_main_reply_keyboard(chat_id))
                
                if state == IN_EXPLORER:
                    await refresh_explorer_after_language_change(context, chat_id)
                elif state == WAITING_FOR_LOGIN:
                    logger.info(f"📝 Обновление экрана для состояния WAITING_FOR_LOGIN")
                    await update.message.reply_text(t(chat_id, "welcome"), reply_markup=get_main_reply_keyboard(chat_id))
                elif state == WAITING_FOR_PASSWORD:
                    logger.info(f"📝 Обновление экрана для состояния WAITING_FOR_PASSWORD")
                    username = context.user_data.get('username', '')
                    await update.message.reply_text(t(chat_id, "login_accepted", username=username), reply_markup=get_main_reply_keyboard(chat_id))
                elif state == SELECTING_WORKSPACE:
                    workspaces = get_workspaces(context)
                    if workspaces:
                        keyboard = []
                        for ws in workspaces:
                            name = get_workspace_name(ws)
                            ws_id = get_workspace_id(ws)
                            if ws_id:
                                keyboard.append([InlineKeyboardButton(f"🏢 {name}", callback_data=f"workspace_{ws_id}")])
                        await update.message.reply_text(t(chat_id, "select_workspace"), reply_markup=InlineKeyboardMarkup(keyboard))
                elif state == SELECTING_PROJECT:
                    projects = context.user_data.get('projects', [])
                    if projects:
                        keyboard = []
                        for proj in projects:
                            name = get_title(proj)
                            proj_id = proj["id"]
                            keyboard.append([InlineKeyboardButton(f"📦 {name}", callback_data=f"project_{proj_id}")])
                        keyboard.append([InlineKeyboardButton(t(chat_id, "change_workspace"), callback_data="change_workspace")])
                        await update.message.reply_text(t(chat_id, "select_project"), reply_markup=InlineKeyboardMarkup(keyboard))
                else:
                    logger.warning(f"⚠️ Неизвестное состояние при смене языка: {state}")
                return
        else:
            logger.debug(f"✓ Сообщение не является служебной командой: '{text}'")
    
    if state == WAITING_FOR_LOGIN:
        username = update.message.text.strip() if update.message.text else ""
        if not username:
            await update.message.reply_text(t(chat_id, "welcome"))
            return
        context.user_data['username'] = username
        context.user_data['state'] = WAITING_FOR_PASSWORD
        await update.message.reply_text(t(chat_id, "login_accepted", username=username), reply_markup=get_main_reply_keyboard(chat_id))
        return
    
    if state == WAITING_FOR_PASSWORD:
        password = update.message.text if update.message.text else ""
        username = context.user_data.get('username', '')
        
        logger.info(f"🔐 Обработка пароля для chat_id={chat_id}, username={username}, update_id={update_id}")
        
        await update.message.reply_text(t(chat_id, "logging_in"))
        
        success = login(username, password, context)
        logger.info(f"🔐 Результат login() для chat_id={chat_id}: success={success}")
        
        if success:
            client = get_api_client(context)
            if client:
                save_chat_token_info(chat_id, context.application, client.token, user_id=client.user_id)
            
            workspaces = get_workspaces(context)
            if len(workspaces) == 1:
                ws = workspaces[0]
                ws_id = get_workspace_id(ws)
                ws_name = get_workspace_name(ws)
                
                # ВАЖНО: Сначала вызываем client.change_workspace(ws_id), а потом загружаем проекты
                if client:
                    logger.info(f"🏢 Single workspace detected: {ws_name} (id={ws_id})")
                    
                    success = client.change_workspace(ws_id)
                    if success:
                        logger.info(f"✅ Workspace changed successfully via API")
                        context.user_data['workspace_id'] = ws_id
                        context.user_data['workspace_name'] = ws_name
                        save_chat_token_info(chat_id, context.application, client.token, workspace_id=ws_id, user_id=client.user_id, workspace_name=ws_name)
                        
                        restart_approval_notifications_for_chat(
                            context.application,
                            update.effective_chat.id,
                            workspace_id=ws_id,
                            user_id=client.user_id,
                        )
                        
                        await update.message.reply_text(t(chat_id, "login_success_auto_ws", ws_name=ws_name), parse_mode='Markdown', reply_markup=get_main_reply_keyboard(chat_id))
                        
                        projects = get_project_list(context)
                        if not projects:
                            await update.message.reply_text(t(chat_id, "projects_load_error"))
                            return
                        
                        context.user_data['projects'] = projects
                        context.user_data['state'] = SELECTING_PROJECT
                        
                        keyboard = []
                        for proj in projects:
                            name = get_title(proj)
                            proj_id = proj["id"]
                            keyboard.append([InlineKeyboardButton(f"📦 {name}", callback_data=f"project_{proj_id}")])
                        keyboard.append([InlineKeyboardButton(t(chat_id, "change_workspace"), callback_data="change_workspace")])
                        
                        await update.message.reply_text(t(chat_id, "select_project"), reply_markup=InlineKeyboardMarkup(keyboard))
                    else:
                        logger.warning(f"⚠️ change_workspace() failed for workspace {ws_name}")
                        await update.message.reply_text(t(chat_id, "workspace_switch_error"))
                        return
                else:
                    logger.warning(f"⚠️ API client not available after login")
                    await update.message.reply_text(t(chat_id, "projects_load_error"))
                    return
            else:
                context.user_data['workspaces'] = workspaces
                context.user_data['state'] = SELECTING_WORKSPACE
                
                await update.message.reply_text(t(chat_id, "login_success_loading"), reply_markup=get_main_reply_keyboard(chat_id))
                
                keyboard = []
                for ws in workspaces:
                    name = get_workspace_name(ws)
                    ws_id = get_workspace_id(ws)
                    if ws_id:
                        keyboard.append([InlineKeyboardButton(f"🏢 {name}", callback_data=f"workspace_{ws_id}")])
                
                await update.message.reply_text(t(chat_id, "select_workspace"), reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            context.user_data['state'] = WAITING_FOR_LOGIN
            await update.message.reply_text(t(chat_id, "login_error"), reply_markup=get_main_reply_keyboard(chat_id))
        return
    
    if state == AWAITING_UPLOAD:
        if update.message.document:
            document = update.message.document
            file_name = document.file_name or f"file_{document.file_id}"
            
            await update.message.reply_text(t(chat_id, "preparing_file", filename=file_name))
            
            try:
                new_file = await document.get_file()
                temp_path = os.path.join(DOWNLOAD_DIR, sanitize_filename(file_name))
                os.makedirs(DOWNLOAD_DIR, exist_ok=True)
                await new_file.download_to_drive(temp_path)
                
                client = get_api_client(context)
                if not client:
                    await update.message.reply_text(t(chat_id, "session_expired"))
                    return
                
                path = context.user_data.get('path', [])
                project_id = context.user_data.get('project_id')
                
                if path:
                    folder_id = path[-1]["id"]
                else:
                    folder_id = project_id
                
                await update.message.reply_text(t(chat_id, "uploading_to", folder_id=folder_id))
                
                logger.info(f"📤 Upload request: folder_id={folder_id}, temp_path={temp_path}, file_name={file_name}")

                success, upload_error = upload_file_to_folder(temp_path, folder_id, file_name, context, chat_id=chat_id)

                upload_status = getattr(client, "_last_upload_status", None)
                upload_body = getattr(client, "_last_upload_body", "")
                upload_response = getattr(client, "_last_upload_response", None)
                
                logger.info(f"📤 Upload result: success={success}, status={upload_status}")
                if upload_body:
                    logger.info(f"📤 Upload response body: {upload_body[:500]}")
                if upload_response:
                    logger.info(f"📤 Upload response json: {str(upload_response)[:500]}")
                
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
                
                if success:
                    await update.message.reply_text(t(chat_id, "upload_success", message=file_name))
                    full_tree = get_folder_tree_by_project(project_id, context, force=True)
                    if full_tree:
                        context.user_data['full_tree'] = full_tree
                else:
                    error_msg = upload_error or "Upload failed"
                    if not upload_error and upload_status:
                        error_msg = f"HTTP {upload_status}"
                    if upload_body:
                        error_msg += f": {upload_body[:200]}"
                    logger.error(f"❌ Upload failed: folder_id={folder_id}, file={file_name}, status={upload_status}, body={upload_body[:500] if upload_body else 'N/A'}")
                    await update.message.reply_text(t(chat_id, "upload_error", error=error_msg))
                
                context.user_data['state'] = IN_EXPLORER
                await show_current_level(update, context)
            except Exception as e:
                logger.error(f"Ошибка загрузки файла: {e}")
                await update.message.reply_text(t(chat_id, "upload_error", error=str(e)))
                context.user_data['state'] = IN_EXPLORER
        else:
            await update.message.reply_text(t(chat_id, "send_file_to_upload"), parse_mode='Markdown')
        return
    
    await update.message.reply_text(t(chat_id, "use_start"), reply_markup=get_main_reply_keyboard(chat_id))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not rate_limit(context):
        return

    query = update.callback_query
    try:
        await query.answer()
    except Exception as e:
        err_str = str(e).lower()
        if "too old" in err_str or "timeout" in err_str or "invalid" in err_str:
            logger.warning(f"⚠️ query.answer() failed (callback expired): {e}")
        else:
            logger.error(f"❌ query.answer() error: {e}")
    data = query.data
    chat_id = update.effective_chat.id

    if data == "toggle_language":
        current_lang = get_user_language(chat_id)
        new_lang = "en" if current_lang == "ru" else "ru"
        set_user_language(chat_id, new_lang)
        lang_name = TRANSLATIONS["en"]["language_en"] if new_lang == "en" else TRANSLATIONS["ru"]["language_ru"]
        await query.answer(text=t(chat_id, "language_switched", lang_name=lang_name), show_alert=False)
        
        state = context.user_data.get('state')
        if state == SELECTING_WORKSPACE:
            workspaces = get_workspaces(context)
            if workspaces:
                keyboard = []
                for ws in workspaces:
                    name = get_workspace_name(ws)
                    ws_id = get_workspace_id(ws)
                    if ws_id:
                        keyboard.append([InlineKeyboardButton(f"🏢 {name}", callback_data=f"workspace_{ws_id}")])
                try:
                    await query.message.edit_text(t(chat_id, "select_workspace"), reply_markup=InlineKeyboardMarkup(keyboard))
                except (TimedOut, NetworkError):
                    await query.message.reply_text(t(chat_id, "select_workspace"), reply_markup=InlineKeyboardMarkup(keyboard))
            return
        elif state == SELECTING_PROJECT:
            projects = context.user_data.get('projects', [])
            if projects:
                keyboard = []
                for proj in projects:
                    name = get_title(proj)
                    proj_id = proj["id"]
                    keyboard.append([InlineKeyboardButton(f"📦 {name}", callback_data=f"project_{proj_id}")])
                keyboard.append([InlineKeyboardButton(t(chat_id, "change_workspace"), callback_data="change_workspace")])
                try:
                    await query.message.edit_text(t(chat_id, "select_project"), reply_markup=InlineKeyboardMarkup(keyboard))
                except (TimedOut, NetworkError):
                    await query.message.reply_text(t(chat_id, "select_project"), reply_markup=InlineKeyboardMarkup(keyboard))
            return
        elif state == IN_EXPLORER:
            full_tree = context.user_data.get('full_tree', [])
            if full_tree is None or len(full_tree) == 0:
                project_id = context.user_data.get('project_id')
                projects = context.user_data.get('projects', [])
                selected = next((p for p in projects if p["id"] == project_id), None) if project_id else None
                project_name = get_title(selected) if selected else t(chat_id, "root")
                await show_empty_project_explorer(chat_id, context, context.bot, project_name, project_id or 0)
            else:
                await refresh_explorer_after_language_change(context, chat_id)
            return
        else:
            logger.info(f"🌐 toggle_language: state={state}, no specific refresh needed")
            return

    if data.startswith("adocs_"):
        parts = data.split("_")
        if len(parts) != 3:
            await query.message.reply_text(t(chat_id, "approval_params_error"))
            return

        try:
            workspace_id = int(parts[1])
            process_id = int(parts[2])
        except ValueError:
            await query.message.reply_text(t(chat_id, "incorrect_ids"))
            return

        token = get_api_token_for_chat(update.effective_chat.id, context.application)
        if not token:
            await query.message.reply_text(t(chat_id, "session_expired"))
            return

        status_code, process_payload = await _approval_api_get(
            token,
            f"/api/approvals/process/{process_id}",
            params={"workspaceId": workspace_id},
        )
        if status_code != 200 or not isinstance(process_payload, dict):
            await query.message.reply_text(t(chat_id, "approval_files_list_error"))
            return

        process_info = process_payload.get("process") if isinstance(process_payload.get("process"), dict) else {}
        process_title = process_info.get("title") or t(chat_id, "process_id", id=process_id)

        documents = _extract_approval_documents(process_payload)
        back_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(t(chat_id, "back"), callback_data=f"aback_{workspace_id}_{process_id}")]
        ])
        if not documents:
            await query.message.edit_text(
                t(chat_id, "approval_files_title") +
                f"{t(chat_id, 'approval_process', title=html.escape(str(process_title)))}\n"
                f"{t(chat_id, 'no_files_found')}",
                parse_mode="HTML",
                reply_markup=back_markup,
            )
            return

        buttons = []
        for doc in documents[:15]:
            doc_id = _maybe_int(doc.get("id"))
            if doc_id is None:
                continue

            file_name = doc.get("name") if isinstance(doc.get("name"), str) else f"document_{doc_id}"
            save_approval_download_hint(context.application, update.effective_chat.id, doc_id, file_name)

            short_name = file_name.strip()
            if len(short_name) > 35:
                short_name = short_name[:32] + "..."

            buttons.append([
                InlineKeyboardButton(short_name, callback_data=f"adocdl_{workspace_id}_{process_id}_{doc_id}")
            ])

        buttons.append([InlineKeyboardButton(t(chat_id, "back"), callback_data=f"aback_{workspace_id}_{process_id}")])

        await query.message.edit_text(
            t(chat_id, "approval_files_title") +
            f"{t(chat_id, 'approval_process', title=html.escape(str(process_title)))}\n"
            f"{t(chat_id, 'select_file_download')}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    if data.startswith("aback_"):
        parts = data.split("_")
        if len(parts) != 3:
            await query.message.reply_text(t(chat_id, "approval_back_params_error"))
            return

        try:
            workspace_id = int(parts[1])
            process_id = int(parts[2])
        except ValueError:
            await query.message.reply_text(t(chat_id, "incorrect_ids"))
            return

        original_text = get_approval_notification_view(
            context.application,
            update.effective_chat.id,
            workspace_id,
            process_id,
        )
        if not original_text:
            original_text = t(chat_id, "new_approval_stage")

        await query.message.edit_text(
            original_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=build_approval_notify_markup(workspace_id, process_id, lang=get_user_language(chat_id)),
        )
        return

    if data.startswith("adocdl_"):
        parts = data.split("_")
        if len(parts) != 4:
            await query.message.reply_text(t(chat_id, "approval_download_params_error"))
            return

        try:
            workspace_id = int(parts[1])
            process_id = int(parts[2])
            document_id = int(parts[3])
        except ValueError:
            await query.message.reply_text(t(chat_id, "incorrect_ids"))
            return

        file_name = get_approval_download_hint(context.application, update.effective_chat.id, document_id)
        if not file_name:
            token = get_api_token_for_chat(update.effective_chat.id, context.application)
            if token:
                status_code, process_payload = await _approval_api_get(
                    token,
                    f"/api/approvals/process/{process_id}",
                    params={"workspaceId": workspace_id},
                )
                if status_code == 200 and isinstance(process_payload, dict):
                    for doc in _extract_approval_documents(process_payload):
                        doc_id = _maybe_int(doc.get("id"))
                        if doc_id == document_id:
                            file_name = doc.get("name") if isinstance(doc.get("name"), str) else None
                            break

        if not file_name:
            file_name = f"document_{document_id}"

        await query.message.reply_text(t(chat_id, "downloading_file", filename=file_name))

        filepath = download_file(document_id, file_name, context)
        if filepath and os.path.exists(filepath):
            file_size = os.path.getsize(filepath)
            size_mb = file_size / (1024 * 1024)
            if size_mb < 50:
                with open(filepath, 'rb') as f:
                    await safe_send_document(context.bot, update.effective_chat.id, f, filename=file_name)
                await query.message.reply_text(t(chat_id, "file_sent", filename=file_name))
            else:
                await query.message.reply_text(
                    t(chat_id, "file_too_big", size=size_mb, path=filepath)
                )
        else:
            await query.message.reply_text(t(chat_id, "download_error"))
        return

    if data == "change_workspace":
        workspaces = get_workspaces(context)
        if not workspaces:
            await query.message.reply_text(t(chat_id, "workspaces_load_error"))
            return
        
        if len(workspaces) == 1:
            ws = workspaces[0]
            ws_id = get_workspace_id(ws)
            ws_name = get_workspace_name(ws)
            
            logger.info(f"🏢 Single workspace detected: {ws_name}")
            
            client = get_api_client(context)
            if not client:
                await query.message.reply_text(t(chat_id, "api_client_unavailable"))
                return
            
            success = client.change_workspace(ws_id)
            if not success:
                logger.warning(f"⚠️ change_workspace() failed for workspace {ws_name}")
                await query.message.reply_text(t(chat_id, "workspace_switch_error"))
                return
            
            _clear_explorer_state(context, reason="workspace_switch")
            
            context.user_data['workspace_id'] = ws_id
            context.user_data['workspace_name'] = ws_name
            
            save_chat_token_info(chat_id, context.application, client.token, workspace_id=ws_id, user_id=client.user_id, workspace_name=ws_name)
            restart_approval_notifications_for_chat(
                context.application,
                update.effective_chat.id,
                workspace_id=ws_id,
                user_id=client.user_id,
            )
            
            try:
                await query.message.edit_text(t(chat_id, "workspace_selected", ws_name=ws_name), parse_mode='Markdown')
            except (TimedOut, NetworkError):
                await query.message.reply_text(t(chat_id, "workspace_selected", ws_name=ws_name), parse_mode='Markdown')
            
            projects = get_project_list(context)
            if not projects:
                await query.message.reply_text(t(chat_id, "projects_load_error"))
                return
            
            context.user_data['projects'] = projects
            context.user_data['state'] = SELECTING_PROJECT
            
            keyboard = []
            for proj in projects:
                name = get_title(proj)
                proj_id = proj["id"]
                keyboard.append([InlineKeyboardButton(f"📦 {name}", callback_data=f"project_{proj_id}")])
            keyboard.append([InlineKeyboardButton(t(chat_id, "change_workspace"), callback_data="change_workspace")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            try:
                await query.message.edit_text(t(chat_id, "select_project"), reply_markup=reply_markup)
            except (TimedOut, NetworkError):
                await query.message.reply_text(t(chat_id, "select_project"), reply_markup=reply_markup)
            return
        
        context.user_data['workspaces'] = workspaces
        context.user_data['state'] = SELECTING_WORKSPACE

        keyboard = []
        for ws in workspaces:
            name = get_workspace_name(ws)
            ws_id = get_workspace_id(ws)
            if ws_id:
                keyboard.append([InlineKeyboardButton(f"🏢 {name}", callback_data=f"workspace_{ws_id}")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await query.message.edit_text(t(chat_id, "select_workspace"), reply_markup=reply_markup)
        except (TimedOut, NetworkError):
            await query.message.reply_text(t(chat_id, "select_workspace"), reply_markup=reply_markup)
        return

    if data.startswith("workspace_") and context.user_data.get('state') == SELECTING_WORKSPACE:
        try:
            workspace_id = int(data.split("_", 1)[1])
        except (ValueError, IndexError):
            await query.message.reply_text(t(chat_id, "invalid_workspace_id"))
            return

        client = get_api_client(context)
        if not client:
            await query.message.reply_text(t(chat_id, "api_client_unavailable"))
            return

        # Clear old explorer state before switching
        _clear_explorer_state(context, reason="workspace_switch")
        
        success = client.change_workspace(workspace_id)
        if not success:
            logger.warning(f"⚠️ change_workspace() failed for workspace {workspace_id}")
            await query.message.reply_text(t(chat_id, "workspace_switch_error"))
            return
        
        workspaces = context.user_data.get('workspaces', [])
        selected = next((w for w in workspaces if str(get_workspace_id(w)) == str(workspace_id)), None)
        workspace_name = get_workspace_name(selected) if selected else f"Workspace {workspace_id}"
        
        context.user_data['workspace_id'] = workspace_id
        context.user_data['workspace_name'] = workspace_name
        context.user_data['state'] = SELECTING_PROJECT
        if client and client.token:
            save_chat_token_info(
                update.effective_chat.id,
                context.application,
                client.token,
                workspace_id=workspace_id,
                user_id=client.user_id,
                workspace_name=workspace_name,
            )
            restart_approval_notifications_for_chat(
                context.application,
                update.effective_chat.id,
                workspace_id=workspace_id,
                user_id=client.user_id,
            )
        
        try:
            await query.message.edit_text(t(chat_id, "workspace_selected", ws_name=workspace_name), parse_mode='Markdown')
        except (TimedOut, NetworkError):
            await query.message.reply_text(t(chat_id, "workspace_selected", ws_name=workspace_name), parse_mode='Markdown')

        projects = get_project_list(context)
        if not projects:
            await query.message.reply_text(t(chat_id, "projects_load_error"))
            return
        
        context.user_data['projects'] = projects
        context.user_data['state'] = SELECTING_PROJECT
        
        keyboard = []
        for proj in projects:
            name = get_title(proj)
            proj_id = proj["id"]
            keyboard.append([InlineKeyboardButton(f"📦 {name}", callback_data=f"project_{proj_id}")])
        keyboard.append([InlineKeyboardButton(t(chat_id, "change_workspace"), callback_data="change_workspace")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await query.message.edit_text(t(chat_id, "select_project"), reply_markup=reply_markup)
        except (TimedOut, NetworkError):
            await query.message.reply_text(t(chat_id, "select_project"), reply_markup=reply_markup)
        return

    if data == "change_project":
        # Clear old explorer state before loading new project list
        _clear_explorer_state(context, reason="project_change")
        
        projects = get_project_list(context)
        if not projects:
            await query.message.reply_text(t(chat_id, "projects_load_error"))
            return

        context.user_data['projects'] = projects
        context.user_data['state'] = SELECTING_PROJECT

        keyboard = []
        for proj in projects:
            name = get_title(proj)
            proj_id = proj["id"]
            keyboard.append([InlineKeyboardButton(f"📦 {name}", callback_data=f"project_{proj_id}")])

        keyboard.append([InlineKeyboardButton(t(chat_id, "change_workspace"), callback_data="change_workspace")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await query.message.edit_text(t(chat_id, "select_new_project"), reply_markup=reply_markup)
        except (TimedOut, NetworkError):
            await query.message.reply_text(t(chat_id, "select_new_project"), reply_markup=reply_markup)
        return

    if data.startswith("project_") and context.user_data.get('state') == SELECTING_PROJECT:
        try:
            project_id = int(data.split("_", 1)[1])
        except (ValueError, IndexError):
            await query.message.reply_text(t(chat_id, "invalid_project_id"))
            await show_project_selection_screen(chat_id, context, context.bot, query.message)
            return

        projects = context.user_data.get('projects', [])
        selected = next((p for p in projects if p["id"] == project_id), None)
        if not selected:
            await query.message.reply_text(t(chat_id, "project_not_found"))
            await show_project_selection_screen(chat_id, context, context.bot, query.message)
            return

        project_name = get_title(selected)
        context.user_data['project_id'] = project_id
        context.user_data['state'] = IN_EXPLORER

        try:
            await query.message.edit_text(t(chat_id, "project_selected", project_name=project_name), parse_mode='Markdown')
        except (TimedOut, NetworkError):
            await query.message.reply_text(t(chat_id, "project_selected", project_name=project_name), parse_mode='Markdown')

        full_tree = get_folder_tree_by_project(project_id, context)
        
        if full_tree is None:
            await query.message.reply_text(t(chat_id, "project_load_error"))
            await show_project_selection_screen(chat_id, context, context.bot, query.message)
            return
        
        if len(full_tree) == 0:
            await show_empty_project_explorer(chat_id, context, context.bot, project_name, project_id)
            return

        context.user_data['full_tree'] = full_tree
        context.user_data['path'] = []
        context.user_data['file_names'] = {}

        await show_current_level(query, context)
        return

    if data == "noop":
        await query.answer(text=t(chat_id, "folder_empty"), show_alert=True)
        return

    if data == "back":
        path = context.user_data.get('path', [])
        if path:
            path.pop()
        context.user_data['path'] = path
        try:
            await show_current_level(query, context)
        except Exception as e:
            logger.error(f"❌ Ошибка при возврате: {e}")
            await query.message.reply_text(t(chat_id, "error_back"))
            try:
                await show_current_level(query, context)
            except Exception as e2:
                logger.error(f"❌ Повторная ошибка при возврате: {e2}")
                await show_project_selection_screen(chat_id, context, context.bot, query.message)
        return

    if data == STATS_PROJECT:
        full_tree = context.user_data.get('full_tree', [])
        if not full_tree:
            await query.message.reply_text(t(chat_id, "project_load_error"))
            return

        file_count = count_files_in_tree(full_tree)
        projects = context.user_data.get('projects', [])
        project_id = context.user_data.get('project_id')
        
        project = next((p for p in projects if p.get('id') == project_id), None)
        project_name = get_title(project) if project else (get_title(projects[0]) if projects else t(chat_id, "root"))

        try:
            await query.message.edit_text(
                t(chat_id, "project_stats", project_name=project_name, count=file_count),
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(chat_id, "back"), callback_data=BACK_TO_EXPLORER)]])
            )
        except (TimedOut, NetworkError):
            await query.message.reply_text(
                t(chat_id, "project_stats", project_name=project_name, count=file_count),
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(chat_id, "back"), callback_data=BACK_TO_EXPLORER)]])
            )
        return

    if data == BACK_TO_EXPLORER:
        try:
            await show_current_level(query, context)
        except Exception as e:
            logger.error(f"❌ Ошибка при возврате из статистики: {e}")
            await query.message.reply_text(t(chat_id, "error_back"))
        return

    if data == "upload":
        context.user_data['state'] = AWAITING_UPLOAD
        await query.message.reply_text(
            t(chat_id, "send_file_to_upload"),
            parse_mode='Markdown'
        )
        return

    if data == TOGGLE_NOTIFY:
        chat_id = update.effective_chat.id
        project_id = context.user_data.get('project_id')

        if not project_id:
            await query.message.reply_text(t(chat_id, "select_project_first"))
            return

        path = context.user_data.get('path', [])

        if not path:
            folder_id = project_id
            folder_name = t(chat_id, "root")
        else:
            folder_id = path[-1]["id"]
            folder_name = get_title(path[-1])

        workspace_id = context.user_data.get('workspace_id')
        current_larix_user_id = get_chat_user_id(chat_id, context.application)
        if current_larix_user_id is None:
            current_larix_user_id = 0

        subscriptions = get_user_subscriptions(chat_id, current_larix_user_id)
        existing = next((s for s in subscriptions if s.get('folder_id') == folder_id and s.get('project_id') == project_id), None)

        if existing:
            remove_folder_subscription(chat_id, project_id, folder_id, current_larix_user_id)

            existing_ws = existing.get('workspace_id')
            existing_user = existing.get('larix_user_id', current_larix_user_id)
            remove_notify_jobs(
                context.application.job_queue,
                chat_id,
                project_id,
                folder_id,
                existing_ws,
                existing_user,
            )

            await query.message.reply_text(t(chat_id, "unsubscribed", folder_name=folder_name), parse_mode='Markdown')
        else:
            conn = sqlite3.connect(BOT_DATA_DB_PATH)
            cursor = conn.cursor()
            cursor.execute(
                'DELETE FROM file_states WHERE chat_id = ? AND project_id = ? AND folder_id = ?',
                (chat_id, project_id, folder_id),
            )
            conn.commit()
            conn.close()
            print(f"[SUBSCRIBE] Очищены старые состояния файлов для folder_id={folder_id}")

            full_tree = get_folder_tree_by_project(project_id, context, force=True)
            if full_tree:
                context.user_data['full_tree'] = full_tree
            else:
                full_tree = context.user_data.get('full_tree', [])

            if folder_id == project_id:
                current_files = get_files_flat(full_tree)
            else:
                folder_obj = find_folder_by_id(full_tree, folder_id)
                if not folder_obj:
                    await query.message.reply_text(t(chat_id, "folder_empty"))
                    return
                current_files = get_files_flat(folder_obj.get("children", []), folder_name)

            # Добавляем подписку в новую базу
            add_folder_subscription(
                chat_id,
                project_id,
                folder_id,
                folder_name,
                workspace_id,
                current_larix_user_id,
            )

            # Сохраняем начальные состояния файлов
            for file_info in current_files:
                update_file_state(chat_id, file_info, folder_id, project_id, file_info.get("path", ""))
            
            # Проверяем, доступен ли job_queue
            if not context.application.job_queue:
                await query.message.reply_text(
                    t(chat_id, "subscribed", folder_name=folder_name) + "\n\n" + t(chat_id, "job_queue_unavailable"),
                    parse_mode='Markdown'
                )
                try:
                    await show_current_level(query, context)
                except Exception as e:
                    logger.error(f"❌ Ошибка при показе после подписки: {e}")
                    await query.message.reply_text(t(chat_id, "error_back"))
                return
            
            job_name = build_notify_job_name(
                chat_id,
                project_id,
                folder_id,
                workspace_id,
                current_larix_user_id,
            )
            remove_notify_jobs(
                context.application.job_queue,
                chat_id,
                project_id,
                folder_id,
                workspace_id,
                current_larix_user_id,
            )
            
            context.application.job_queue.run_repeating(
                check_notifications_job,
                interval=60,
                first=10,
                name=job_name,
                data={
                    "chat_id": chat_id,
                    "folder_id": folder_id,
                    "project_id": project_id,
                    "saved_state": current_files,
                    "path_display": folder_name,
                    "workspace_id": workspace_id,
                    "larix_user_id": current_larix_user_id,
                }
            )
            
            await query.message.reply_text(t(chat_id, "subscribed", folder_name=folder_name), parse_mode='Markdown')
        
        try:
            await show_current_level(query, context)
        except Exception as e:
            logger.error(f"❌ Ошибка при показе после подписки: {e}")
            await query.message.reply_text(t(chat_id, "error_back"))
        return

    if data == "refresh_folder":
        project_id = context.user_data.get('project_id')
        if not project_id:
            await query.message.reply_text(t(chat_id, "select_project_first"))
            await show_project_selection_screen(chat_id, context, context.bot, query.message)
            return

        old_path_ids = [p["id"] for p in context.user_data.get('path', [])]

        try:
            await query.message.edit_text(t(chat_id, "refresh") + "...")
        except (TimedOut, NetworkError):
            await query.message.reply_text(t(chat_id, "refresh") + "...")
        
        full_tree = get_folder_tree_by_project(project_id, context, force=True)
        
        if full_tree is None:
            await query.message.reply_text(t(chat_id, "project_load_error"))
            await show_project_selection_screen(chat_id, context, context.bot, query.message)
            return
        
        if len(full_tree) == 0:
            projects = context.user_data.get('projects', [])
            selected = next((p for p in projects if p["id"] == project_id), None)
            project_name = get_title(selected) if selected else t(chat_id, "root")
            await show_empty_project_explorer(chat_id, context, context.bot, project_name, project_id)
            return

        context.user_data['full_tree'] = full_tree

        new_path = []
        current_level = full_tree
        for folder_id in old_path_ids:
            if not isinstance(current_level, list):
                current_level = []
            target = next((item for item in current_level if isinstance(item, dict) and item.get("id") == folder_id and item.get("type") == "folder"), None)
            if not target:
                break
            new_path.append(target)
            current_level = target.get("children", [])

        context.user_data['path'] = new_path
        try:
            await show_current_level(query, context)
        except Exception as e:
            logger.error(f"❌ Ошибка при обновлении папки: {e}")
            await query.message.reply_text(t(chat_id, "error_refresh"))
            context.user_data['full_tree'] = full_tree
            context.user_data['path'] = new_path
            await show_current_level(query, context)
        return

    if data.startswith("folder_"):
        try:
            folder_id = int(data.split("_", 1)[1])
        except (ValueError, IndexError):
            await query.message.reply_text(t(chat_id, "invalid_folder_id"))
            return

        full_tree = context.user_data['full_tree']
        path = context.user_data['path']
        current_level = full_tree if len(path) == 0 else (path[-1].get("children") or [])
        if not isinstance(current_level, list):
            current_level = []

        target = next((item for item in current_level if isinstance(item, dict) and item["id"] == folder_id), None)
        if not target or target.get("type") != "folder":
            logger.error(f"❌ Папка не найдена: folder_id={folder_id}, current_level_ids={[item.get('id') for item in current_level if isinstance(item, dict)]}")
            try:
                await query.edit_message_text(text=t(chat_id, "folder_not_found"))
            except (TimedOut, NetworkError):
                await query.message.reply_text(t(chat_id, "folder_not_found"))
            return

        path.append(target)
        context.user_data['path'] = path

        try:
            await show_current_level(query, context)
        except Exception as e:
            logger.error(f"❌ Ошибка при показе папки: {e}")
            await query.message.reply_text(t(chat_id, "error_open_folder"))
        return

    if data.startswith("file_"):
        try:
            file_id = int(data.split("_", 1)[1])
        except (ValueError, IndexError):
            await query.message.reply_text(t(chat_id, "invalid_file_id"))
            return

        path = context.user_data.get('path', [])
        current_level = context.user_data['full_tree'] if len(path) == 0 else (path[-1].get("children") or [])
        if not isinstance(current_level, list):
            current_level = []

        file_node = next((item for item in current_level if isinstance(item, dict) and item["id"] == file_id), None)
        if not file_node:
            await query.message.reply_text(t(chat_id, "file_not_found"))
            return

        lang = get_user_language(chat_id)
        name = file_node.get("originalName") or file_node.get("name") or t(chat_id, "no_name")
        version = file_node.get("version") or file_node.get("version_count") or file_node.get("documentVersion") or file_node.get("docVersion")
        created_by = file_node.get("created_by") or file_node.get("createdBy") or file_node.get("author") or ""
        modified_by = file_node.get("modified_by") or file_node.get("modifiedBy") or ""
        created_at = file_node.get("createdAt") or file_node.get("created_ts") or file_node.get("createTime")
        updated_at = file_node.get("updatedAt") or file_node.get("modified_ts") or file_node.get("modifTime") or file_node.get("modifiedDate")
        status = file_node.get("status") or ""
        file_type = file_node.get("type") or "file"

        parts = [f"📄 <b>{html.escape(name)}</b>"]
        if version:
            parts.append(f"🔢 {t(chat_id, 'version')}: {version}")
        if created_by:
            parts.append(f"👤 {t(chat_id, 'created_by')}: {html.escape(created_by)}")
        if modified_by:
            parts.append(f"✍️ {t(chat_id, 'modified_by')}: {html.escape(modified_by)}")
        if created_at:
            parts.append(f"🗓️ {t(chat_id, 'created_at')}: {format_file_date(created_at)}")
        if updated_at:
            parts.append(f"🕒 {t(chat_id, 'updated_at')}: {format_file_date(updated_at)}")
        if status:
            parts.append(f"🏷️ {t(chat_id, 'status')}: {translate_status(status, lang)}")
        if file_type:
            parts.append(f"📁 {t(chat_id, 'type')}: {translate_type(file_type, lang)}")

        parts.append("")
        parts.append(t(chat_id, "click_to_download"))

        await query.message.reply_text("\n".join(parts), parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(t(chat_id, "download_btn"), callback_data=f"download_{file_id}")
            ], [
                InlineKeyboardButton(t(chat_id, "back"), callback_data=BACK_TO_EXPLORER)
            ]]))
        return

    if data.startswith("download_"):
        try:
            file_id = int(data.split("_", 1)[1])
        except (ValueError, IndexError):
            await query.message.reply_text(t(chat_id, "invalid_file_id"))
            return

        path = context.user_data.get('path', [])
        current_level = context.user_data['full_tree'] if len(path) == 0 else (path[-1].get("children") or [])
        if not isinstance(current_level, list):
            current_level = []

        file_node = next((item for item in current_level if isinstance(item, dict) and item["id"] == file_id), None)
        if not file_node:
            await query.message.reply_text(t(chat_id, "file_not_found"))
            return

        name = file_node.get("originalName") or file_node.get("name") or t(chat_id, "no_name")
        await query.message.reply_text(t(chat_id, "downloading_file", filename=name))

        filepath = download_file(file_id, name, context)
        if filepath and os.path.exists(filepath):
            file_size = os.path.getsize(filepath)
            size_mb = file_size / (1024 * 1024)
            if size_mb < 50:
                with open(filepath, 'rb') as f:
                    await safe_send_document(context.bot, update.effective_chat.id, f, filename=name)
                await query.message.reply_text(t(chat_id, "file_sent", filename=name))
            else:
                await query.message.reply_text(
                    t(chat_id, "file_too_big", size=size_mb, path=filepath)
                )
        else:
            await query.message.reply_text(t(chat_id, "download_error"))

        await show_current_level(query, context)
        return

def restore_subscriptions(application):
    subscriptions = get_all_folder_subscriptions()

    if not application.job_queue:
        logger.warning("⚠️ JobQueue недоступен. Подписки восстановлены, но уведомления работать не будут.")
        return
    
    restored_count = 0
    skipped_legacy = 0

    for sub in subscriptions:
        chat_id = sub['chat_id']
        larix_user_id = sub.get('larix_user_id')
        if _maybe_int(larix_user_id) in (None, 0):
            skipped_legacy += 1
            continue

        folder_id = sub['folder_id']
        project_id = sub['project_id']
        path_display = sub['folder_path']
        workspace_id = sub['workspace_id']
        
        # Сбрасываем слепок файлов для пересоздания актуального состояния
        reset_folder_file_states(chat_id, folder_id, project_id)

        job_name = build_notify_job_name(chat_id, project_id, folder_id, workspace_id, larix_user_id)
        remove_notify_jobs(application.job_queue, chat_id, project_id, folder_id, workspace_id, larix_user_id)
        
        application.job_queue.run_repeating(
            check_notifications_job,
            interval=60,
            first=10,
            name=job_name,
            data={
                "chat_id": chat_id,
                "folder_id": folder_id,
                "project_id": project_id,
                "saved_state": None,
                "path_display": path_display,
                "workspace_id": workspace_id,
                "larix_user_id": larix_user_id,
                "skip_first_notification": True
            }
        )
        restored_count += 1
    
    logger.info(
        f"📋 Восстановлено {restored_count} user-scoped подписок"
        + (f" (legacy пропущено: {skipped_legacy})" if skipped_legacy else "")
    )

def restore_user_subscriptions(context, chat_id):
    # Сначала проверяем и мигрируем старые подписки если они есть
    subscriptions = load_subscriptions()
    user_subscriptions = [s for s in subscriptions if s['chat_id'] == chat_id]

    if user_subscriptions:
        logger.info(f"🔄 Обнаружены старые подписки для пользователя {chat_id}, запускаем миграцию...")
        # Загружаем из новой базы
        current_larix_user_id = get_chat_user_id(chat_id, context.application)
        user_subscriptions = get_user_subscriptions(chat_id, current_larix_user_id)

    if not context.application.job_queue:
        logger.warning(f"⚠️ JobQueue недоступен. Подписки пользователя {chat_id} не будут восстановлены с автоматическими уведомлениями.")
        return

    for sub in user_subscriptions:
        folder_id = sub['folder_id']
        project_id = sub['project_id']
        path_display = sub['folder_path']
        workspace_id = sub['workspace_id']
        larix_user_id = sub.get('larix_user_id')
        if _maybe_int(larix_user_id) in (None, 0):
            continue

        job_name = build_notify_job_name(chat_id, project_id, folder_id, workspace_id, larix_user_id)
        remove_notify_jobs(context.application.job_queue, chat_id, project_id, folder_id, workspace_id, larix_user_id)

        context.application.job_queue.run_repeating(
            check_notifications_job,
            interval=60,
            first=10,
            name=job_name,
            data={
                "chat_id": chat_id,
                "folder_id": folder_id,
                "project_id": project_id,
                "saved_state": None,
                "path_display": path_display,
                "workspace_id": workspace_id,
                "larix_user_id": larix_user_id,
                "skip_first_notification": True
            }
        )

    logger.info(f"📋 Восстановлено {len(user_subscriptions)} подписок для пользователя {chat_id}")

def refresh_user_subscriptions_after_workspace(context, chat_id: int, workspace_id: int | str | None):
    """Совместимость: смена workspace не пересоздает слепок и не перезапускает подписки."""
    logger.info(
        f"ℹ️ refresh_user_subscriptions_after_workspace пропущен для chat={chat_id}, "
        f"workspace={workspace_id}; слепок не пересобирается"
    )

def acquire_instance_lock() -> bool:
    """
    Проверяет и создает файл блокировки, чтобы не допустить запуск нескольких экземпляров.
    Возвращает True если блокировка получена, False если уже запущен другой экземпляр.
    """
    lock_file = os.path.join(BOT_DIR, "bot.lock")
    instance_id = str(uuid.uuid4())[:8]
    
    logger.info(f"🔒 Проверка блокировки экземпляра...")
    logger.info(f"   Instance ID: {instance_id}")
    logger.info(f"   Lock file: {lock_file}")
    logger.info(f"   PID: {os.getpid()}")
    logger.info(f"   Script: {__file__}")
    
    # Проверяем, существует ли lock-файл
    if os.path.exists(lock_file):
        try:
            with open(lock_file, 'r', encoding='utf-8') as f:
                lock_content = f.read().strip()
            
            # Парсим содержимое lock-файла
            lock_data = {}
            for line in lock_content.split('\n'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    lock_data[key.strip()] = value.strip()
            
            locked_pid = lock_data.get('pid', 'unknown')
            locked_time = lock_data.get('time', 'unknown')
            locked_instance = lock_data.get('instance_id', 'unknown')
            locked_script = lock_data.get('script', 'unknown')
            
            # Проверяем, жив ли процесс
            is_process_alive = False
            try:
                if locked_pid != 'unknown' and sys.platform != 'win32':
                    # Unix: проверка через kill с сигналом 0
                    os.kill(int(locked_pid), 0)
                    is_process_alive = True
                elif locked_pid != 'unknown' and sys.platform == 'win32':
                    # Windows: нет простой проверки, считаем что процесс жив если файл свежий
                    if locked_time != 'unknown':
                        try:
                            locked_timestamp = float(locked_time)
                            if time.time() - locked_timestamp < 30:  # файл создан меньше 30 сек назад
                                is_process_alive = True
                        except ValueError:
                            pass
            except (ProcessLookupError, ValueError, OSError):
                is_process_alive = False
            
            if is_process_alive:
                logger.error("=" * 70)
                logger.error("❌ ОШИБКА: Бот уже запущен!")
                logger.error("=" * 70)
                logger.error(f"   Instance ID текущего: {instance_id}")
                logger.error(f"   Instance ID запущенного: {locked_instance}")
                logger.error(f"   PID текущего процесса: {os.getpid()}")
                logger.error(f"   PID запущенного процесса: {locked_pid}")
                logger.error(f"   Текущий скрипт: {__file__}")
                logger.error(f"   Запущенный скрипт: {locked_script}")
                logger.error(f"   Время запуска: {locked_time}")
                logger.error("=" * 70)
                logger.error("   ВОЗМОЖНЫЕ ПРИЧИНЫ:")
                logger.error("   1. Вы запустили бота несколько раз")
                logger.error("   2. Предыдущий запуск завершился с ошибкой без удаления lock-файла")
                logger.error("   3. Вы используете разные скрипты с одним токеном")
                logger.error("")
                logger.error("   РЕШЕНИЕ:")
                logger.error(f"   Остановите процесс с PID {locked_pid}")
                logger.error(f"   Или удалите lock-файл: {lock_file}")
                logger.error("   (Если уверены, что старый процесс не работает)")
                logger.error("=" * 70)
                return False
            else:
                logger.warning(f"⚠️ Lock-файл найден, но процесс PID={locked_pid} не активен")
                logger.warning(f"   Удаляем устаревший lock-файл...")
                try:
                    os.remove(lock_file)
                except OSError as e:
                    logger.error(f"   ❌ Не удалось удалить lock-файл: {e}")
                    return False
        except Exception as e:
            logger.error(f"   ❌ Ошибка чтения lock-файла: {e}")
            return False
    
    # Создаем новый lock-файл
    try:
        with open(lock_file, 'w', encoding='utf-8') as f:
            f.write(f"pid={os.getpid()}\n")
            f.write(f"time={time.time()}\n")
            f.write(f"instance_id={instance_id}\n")
            f.write(f"script={__file__}\n")
        logger.info(f"✅ Lock-файл создан: {lock_file}")
        return True
    except OSError as e:
        logger.error(f"   ❌ Не удалось создать lock-файл: {e}")
        return False

def release_instance_lock():
    """Удаляет lock-файл при нормальном завершении работы."""
    lock_file = os.path.join(BOT_DIR, "bot.lock")
    try:
        if os.path.exists(lock_file):
            os.remove(lock_file)
            logger.info(f"🔓 Lock-файл удален: {lock_file}")
    except OSError as e:
        logger.warning(f"⚠️ Не удалось удалить lock-файл: {e}")

def main():
    logger.info(f"🚀 Запуск Telegram-бота (PID={os.getpid()})")
    logger.info(f"📍 Рабочая директория: {os.getcwd()}")
    logger.info(f"🐍 Python: {sys.version}")
    
    # Проверка single-instance lock
    if not acquire_instance_lock():
        logger.error("❌ Не удалось получить блокировку экземпляра. Выход.")
        sys.exit(1)
    
    try:
        init_db()
    
        # Миграция подписок из старой базы (только если нужно)
        if not has_bot_data_db():
            logger.info("📦 Запускаем миграцию подписок...")
            migrated = migrate_subscriptions_from_old_db()
            if migrated > 0:
                logger.info(f"📦 Мигрировано {migrated} подписок в notifications.db")
        else:
            logger.info("📦 Пропускаем миграцию (уже есть данные в notifications.db)")
        
        application = Application.builder().token(BOT_TOKEN).build()
    
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("logout", logout_command))
        application.add_handler(CallbackQueryHandler(button_handler))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(MessageHandler(filters.Document.ALL, handle_message))
    
        logger.info(f"🔍 JobQueue доступен: {application.job_queue is not None}")
        if not application.job_queue:
            logger.warning("⚠️ JobQueue не инициализирован! Уведомления работать не будут.")
            logger.warning("⚠️ Для исправления установите: pip install 'python-telegram-bot[job-queue]'")
        else:
            # Восстанавливаем подписки только при старте сервера
            restore_subscriptions(application)
    
        logger.info("🚀 Бот запущен и начинает polling...")
    
        try:
            application.run_polling()
        except Conflict as e:
            logger.error("=" * 60)
            logger.error("❌ CONFLICT ERROR: Обнаружен другой запущенный экземпляр бота!")
            logger.error(f"   PID этого процесса: {os.getpid()}")
            logger.error("   Bot token present (value hidden)")
            logger.error("   Возможные причины:")
            logger.error("   1. Другой процесс бота уже запущен с тем же токеном")
            logger.error("   2. Webhook установлен для этого бота (удалите через BotFather)")
            logger.error("   Решение: остановите другой процесс или удалите webhook")
            logger.error("=" * 60)
            sys.exit(1)
        except KeyboardInterrupt:
            logger.info("⏹️ Бот остановлен пользователем (Ctrl+C)")
        except Exception as e:
            logger.error(f"❌ Критическая ошибка: {e}")
            raise
    finally:
        # Освобождаем lock-файл при любом завершении
        release_instance_lock()


if __name__ == "__main__":
    main()
