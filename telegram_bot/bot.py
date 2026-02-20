import os
import time
import logging
import re
import uuid
import json
import html
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
    from telegram.error import TimedOut, NetworkError
    from telegram.ext import JobQueue
except ImportError:
    raise ImportError("python-telegram-bot не установлен. Установите: pip install python-telegram-bot")

try:
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

try:
    from requests_toolbelt.multipart.encoder import MultipartEncoder
except ImportError:
    MultipartEncoder = None

import requests
import tempfile

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

BOT_TOKEN = "592469309:AAGt48plPSVDfBUcLCKKZjYV3Yjju1tsRrY"
if not BOT_TOKEN or BOT_TOKEN == "ВСТАВЬТЕ_СЮДА_ВАШ_ТОКЕН_ОТ_BOTFATHER" or len(BOT_TOKEN) < 10:
    raise RuntimeError("❌ Вы забыли вставить свой токен! Откройте код и замените строку BOT_TOKEN.")

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
    "draft": "Черновик",
    "published": "Опубликовано",
    "archived": "Архив",
    "deleted": "Удалено",
    "active": "Активно",
    "pending": "На рассмотрении",
    "InDevelopment": "В разработке",
    "Development": "В разработке",
    "Review": "На проверке",
    "Approved": "Утверждено",
    "Rejected": "Отклонено",
    "Completed": "Завершено",
    "processing": "В обработке",
    "ready": "Готово",
    "new": "Новый",
}

TYPE_TRANSLATIONS = {
    "file": "Файл",
    "folder": "Папка",
}

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

def _approval_api_get(token: str, path: str, params: Optional[Dict] = None) -> tuple[int, Optional[object]]:
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

def _get_workspace_scoped_token(token: str, workspace_id: Optional[int]) -> Optional[str]:
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

            # Некоторые реализации могут вернуть 200 без JSON-тела
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

def format_file_info_notification(file_info: Dict, change_type: str, old_state: Optional[Dict] = None, skip_reason: str = "") -> str:
    """Форматирует информацию о файле для уведомления."""
    file_name = file_info.get("originalName") or file_info.get("name") or "Без имени"
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

    author_text = f"👤 Кем создано: {author_name}" if author_name else ""
    time_text = f"🕒 {format_timestamp(current_time)}"

    if file_version:
        version_text = f"🔢 Версия: {file_version}"
    else:
        version_text = ""

    if change_type == "new":
        action_emoji = "🆕"
        action_text = "Новый файл"
    elif change_type == "updated":
        action_emoji = "🔄"
        action_text = "Обновлённый файл"
    elif change_type == "deleted":
        action_emoji = "🗑️"
        action_text = "Удалённый файл"
    else:
        action_emoji = "📄"
        action_text = "Файл"

    path_text = f"📁 {folder_path}" if folder_path else "📁 Корень"
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
        if not self.token:
            return False

        folder_id_str = str(folder_id)
        if not folder_id_str:
            return False

        if not os.path.exists(local_path):
            return False

        url = f"{self.base_url}/api/document/upload/{folder_id_str}"

        for attempt in range(max_retries):
            status = 0
            try:
                try:
                    safe_filename = sanitize_filename(filename)
                except Exception:
                    safe_filename = (filename or "").strip()

                dt = document_type_id
                try:
                    if dt is None:
                        dt = 100
                    dt = int(str(dt).strip())
                except Exception:
                    dt = 100

                meta = [{"filename": safe_filename, "documentTypeId": dt, "documentType": dt}]
                metadata_json = json.dumps(meta, ensure_ascii=False)

                with open(local_path, "rb") as f:
                    if MultipartEncoder is not None:
                        enc = MultipartEncoder(
                            fields={
                                "files": (safe_filename, f, "application/octet-stream"),
                                "documentMetadata": metadata_json,
                            }
                        )
                        headers = {**self._headers(), "Content-Type": enc.content_type}
                        r = requests.post(url, headers=headers, data=enc, timeout=120)
                    else:
                        files = {"files": (safe_filename, f, "application/octet-stream")}
                        data = {"documentMetadata": metadata_json}
                        r = requests.post(url, headers=self._headers(), files=files, data=data, timeout=120)
                    status = int(r.status_code)
                
                if status == 401 and attempt == 0:
                    if self._handle_401():
                        continue
                    else:
                        return False

                try:
                    setattr(self, "_last_upload_status", status)
                    body_trunc = r.text[:2048] if r.text else ""
                    setattr(self, "_last_upload_body", body_trunc)
                    try:
                        response_data = r.json()
                        setattr(self, "_last_upload_response", response_data)
                    except:
                        setattr(self, "_last_upload_response", None)
                except Exception:
                    pass

                ok = (200 <= status <= 201)
                
                if ok:
                    try:
                        for k in list((self.cache or {}).keys()):
                            if isinstance(k, str) and k.startswith("tree:"):
                                try:
                                    self.cache.pop(k, None)
                                except Exception:
                                    pass
                    except Exception:
                        pass
                return ok

            except requests.Timeout:
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                try:
                    setattr(self, "_last_upload_status", 0)
                    setattr(self, "_last_upload_body", "Timeout")
                except Exception:
                    pass
                return False

            except requests.RequestException as e:
                try:
                    setattr(self, "_last_upload_status", status or 0)
                    setattr(self, "_last_upload_body", str(e)[:500])
                except Exception:
                    pass
                return False
            except Exception as e:
                try:
                    setattr(self, "_last_upload_status", status or 0)
                    setattr(self, "_last_upload_body", str(e)[:500])
                except Exception:
                    pass
                return False

        return False

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
            logger.info(f"🔑 Клиентский токен: {client.token[:20]}...{client.token[-20:] if client.token and len(client.token) > 40 else client.token}")
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

def get_folder_tree_by_project(project_id, context: ContextTypes.DEFAULT_TYPE, force: bool = False):
    cache = context.user_data.get('tree_cache', {})
    now = time.time()

    if not force and str(project_id) in cache:
        cached_time, tree = cache[str(project_id)]
        if now - cached_time < 600:
            logger.info("🔁 Используем кэш дерева")
            return tree

    client = get_api_client(context)
    if not client:
        return []

    try:
        tree = client.list_folders(project_id, force=force)
        if isinstance(tree, list):
            if 'tree_cache' not in context.user_data:
                context.user_data['tree_cache'] = {}
            context.user_data['tree_cache'][str(project_id)] = (time.time(), tree)
            return tree
        return []
    except Exception as e:
        logger.error(f"Ошибка загрузки дерева: {e}")
        return []

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
        if not fresh_tree:
            logger.error("❌ Не удалось получить свежее дерево")
            return (False, "Не удалось обновить дерево проекта после загрузки.")

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
        logger.info(f"TokenClient создан с токеном: {token[:20]}...{token[-20:] if len(token) > 40 else token}, workspace={workspace_id}")
    
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
        f"💾 Токен сохранен для чата {chat_id}: "
        f"{token[:20]}...{token[-20:] if len(token) > 40 else token}, "
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

def build_approval_notify_markup(workspace_id: int, process_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Скачать файл", callback_data=f"adocs_{workspace_id}_{process_id}")]
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

def _resolve_workspace_name_by_id(token: str, workspace_id: int) -> Optional[str]:
    for endpoint in ("/api/workspace/list", "/api/admin/workspace/list"):
        status_code, payload = _approval_api_get(token, endpoint)
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

def _build_project_name_map(token: str) -> Dict[str, str]:
    status_code, payload = _approval_api_get(token, "/api/project/list")
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

def _translate_status(status_value) -> str:
    if status_value is None:
        return "Не определен"
    raw = str(status_value).strip()
    if not raw:
        return "Не определен"

    translated = STATUS_TRANSLATIONS.get(raw)
    if translated:
        return translated

    translated = STATUS_TRANSLATIONS.get(raw.lower())
    if translated:
        return translated

    return raw

def _list_available_workspaces(token: str) -> List[Dict]:
    result: List[Dict] = []
    seen = set()

    for endpoint in ("/api/workspace/list", "/api/admin/workspace/list"):
        status_code, payload = _approval_api_get(token, endpoint)
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

    status_code, process_payload = _approval_api_get(
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

        step_status_code, steps_payload = _approval_api_get(
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
            prev_users_status_code, prev_users_payload = _approval_api_get(
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

        users_status_code, users_payload = _approval_api_get(
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

            process_info_status_code, process_info_payload = _approval_api_get(
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
                files_text = "Не указаны"

            safe_process_title = html.escape(str(process_title))
            safe_files_text = html.escape(str(files_text))
            created_time_text = format_file_date(created_ts_value) if created_ts_value else "Неизвестно"
            safe_created_time = html.escape(str(created_time_text))
            if prev_step_status in ("Нет предыдущего этапа", "Не определен"):
                prev_step_status_text = prev_step_status
            else:
                prev_step_status_text = _translate_status(prev_step_status)
            safe_prev_step_status = html.escape(str(prev_step_status_text))
            safe_file_statuses = html.escape(str(file_statuses_text))
            project_line = ""
            if project_name:
                safe_project_name = html.escape(str(project_name))
                project_line = f"Проект: <b>{safe_project_name}</b>\n"
            prev_step_comment_line = ""
            if prev_step_comment_text:
                safe_prev_step_comment = html.escape(str(prev_step_comment_text))
                prev_step_comment_line = f"Комментарий к этапу: <b>{safe_prev_step_comment}</b>\n"

            approval_link = f"{WEB_BASE_URL}/approvals/{process_id}"
            approval_link_href = html.escape(approval_link, quote=True)
            reply_markup = build_approval_notify_markup(workspace_id, process_id)

            message = (
                "🔔 <b>Новый этап согласования</b>\n\n"
                f"Согласование: <b>{safe_process_title}</b>\n"
                f"Этап: <b>{safe_step_title}</b>\n"
                f"{project_line}"
                f"Файл(ы): <b>{safe_files_text}</b>\n"
                f"Время создания: <b>{safe_created_time}</b>\n"
                f"Статус предыдущего этапа: <b>{safe_prev_step_status}</b>\n"
                f"{prev_step_comment_line}"
                f"Статусы файлов: <b>{safe_file_statuses}</b>\n"
                f"Рабочее пространство: <b>{safe_workspace_name}</b>\n"
                f'Ссылка на согласование: <a href="{approval_link_href}">открыть</a>\n\n'
                "✅ Нужно согласовать документ на текущем этапе."
            )

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

    project_name_map = _build_project_name_map(api_token)

    workspace_targets = _list_available_workspaces(api_token)

    # Если список пространств не загрузился, пробуем текущий выбранный/из токена как fallback.
    if not workspace_targets:
        fallback_workspace_id = workspace_id
        if fallback_workspace_id is None:
            fallback_workspace_id = _extract_workspace_id_from_token(api_token)
        if fallback_workspace_id is not None and fallback_workspace_id > 0:
            fallback_workspace_name = _resolve_workspace_name_by_id(api_token, fallback_workspace_id) or f"Workspace {fallback_workspace_id}"
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

        scoped_token = _get_workspace_scoped_token(api_token, ws_id)
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

    scoped_token = _get_workspace_scoped_token(api_token, workspace_id)
    if not scoped_token:
        logger.warning(
            f"⚠️ Не удалось переключить контекст workspace для папки {folder_id} (chat={chat_id}, ws={workspace_id})"
        )
        return

    logger.info(f"🔍 Проверка уведомлений для чата {chat_id}, папка {folder_id}, workspace {workspace_id}")
    logger.info(f"🔑 API-токен: {scoped_token[:20]}...{scoped_token[-20:] if len(scoped_token) > 40 else scoped_token}")

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
        for change in changes[:10]:
            change_type = change["type"]
            file_info = change.get("file") or change.get("old_state", {})
            old_state = change.get("old_state")

            # Форматируем информацию о файле с автором и временем
            msg = format_file_info_notification(file_info, change_type, old_state)
            messages.append(msg)

        safe_path_display = path_display.replace("<", "<").replace(">", ">")
        full_message = f"🔔 <b>Уведомление по папке «{safe_path_display}»</b>\n\n" + "\n\n".join(messages)
        if len(changes) > 10:
            full_message += f"\n\n… и ещё {len(changes) - 10} изменений."

        try:
            await safe_send_message(context.bot, chat_id, full_message, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление в чат {chat_id}: {e}")

    # Обновляем сохраненное состояние (для совместимости со старым кодом)
    job_data["saved_state"] = current_files

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not rate_limit(context):
        return

    await update.message.reply_text("🎯 Добро пожаловать!\n\nВведите ваш логин:")
    context.user_data['state'] = WAITING_FOR_LOGIN
    for key in ['username', 'full_tree', 'path', 'file_names', 'project_id', 'projects', 'notify_folder_id', 'api_client']:
        context.user_data.pop(key, None)

async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not rate_limit(context):
        return

    client = get_api_client(context)
    if client:
        client.logout()
    
    chat_id = update.effective_chat.id
    current_larix_user_id = get_chat_user_id(chat_id, context.application)

    if context.application.job_queue:
        approval_job_name = f"approval_notify_{chat_id}"
        for job in context.application.job_queue.get_jobs_by_name(approval_job_name):
            job.schedule_removal()
    remove_chat_token_info(chat_id, context.application)
    clear_chat_approval_download_hints(context.application, chat_id)
    clear_chat_approval_notification_views(context.application, chat_id)
    clear_chat_approval_notifications(chat_id)

    # Удаляем все подписки пользователя и их фоновые задачи (новая база)
    user_subscriptions_new = get_user_subscriptions(chat_id, current_larix_user_id)
    for sub in user_subscriptions_new:
        folder_id = sub['folder_id']
        project_id = sub['project_id']
        ws_id = sub.get('workspace_id')
        sub_user_id = sub.get('larix_user_id')
        remove_notify_jobs(context.application.job_queue, chat_id, project_id, folder_id, ws_id, sub_user_id)
        remove_folder_subscription(chat_id, project_id, folder_id, current_larix_user_id)

    # Для совместимости: чистим старую базу subscriptions.db
    subscriptions_old = load_subscriptions()
    user_subscriptions_old = [s for s in subscriptions_old if s['chat_id'] == chat_id]
    for sub in user_subscriptions_old:
        try:
            remove_subscription(chat_id, sub['folder_id'])
        except Exception:
            pass
    
    for key in ['username', 'projects', 'project_id', 'full_tree', 'path', 'file_names', 'notify_folder_id', 'api_client']:
        context.user_data.pop(key, None)
    context.user_data['state'] = WAITING_FOR_LOGIN
    
    msg = "✅ Вы вышли из системы.\nВведите логин:"
    total_unsub = len(user_subscriptions_new) + len(user_subscriptions_old)
    if total_unsub:
        msg += f"\n\n🔕 Отписано от {total_unsub} папок."
    
    await update.message.reply_text(msg)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not rate_limit(context):
        return

    state = context.user_data.get('state')

    if state == AWAITING_UPLOAD and update.message.document:
        file = update.message.document
        safe_name = sanitize_filename(file.file_name)

        logger.info(f"📥 ПОЛУЧЕН ФАЙЛ ИЗ TELEGRAM:")
        logger.info(f"   Имя файла: {file.file_name}")
        logger.info(f"   Безопасное имя: {safe_name}")
        logger.info(f"   Размер файла: {file.file_size} байт")

        await update.message.reply_text(f"⏳ Подготавливаю файл '{safe_name}'...")

        file_telegram = await file.get_file()
        logger.info(f"   Получен объект File из Telegram: {file_telegram}")

        local_path = os.path.join(DOWNLOAD_DIR, safe_name)
        logger.info(f"   Локальный путь для сохранения: {local_path}")

        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

        await file_telegram.download_to_drive(local_path)
        logger.info(f"   ✅ ФАЙЛ СКАЧАН ИЗ TELEGRAM В: {local_path}")

        path = context.user_data.get('path', [])
        project_id = context.user_data.get('project_id')
        if not project_id:
            await update.message.reply_text("❌ Не удалось определить проект.")
            await show_current_level(update, context)
            return

        if path:
            folder_id = path[-1]["id"]
            folder_name = path[-1].get("name") or path[-1].get("title") or "Подпапка"
            logger.info(f"Загрузка в подпапку: folder_id={folder_id}, name={folder_name}")
        else:
            folder_id = project_id
            logger.info(f"Загрузка в корень проекта: project_id={folder_id}")

        await update.message.reply_text(f"📤 Загружаю в папку ID={folder_id}...")

        success, error_msg = upload_file_to_folder(local_path, folder_id, safe_name, context, update.effective_chat.id)

        logger.info(f"   РЕЗУЛЬТАТ ЗАГРУЗКИ НА СЕРВЕР:")
        logger.info(f"   Success: {success}")
        logger.info(f"   Сообщение: {error_msg}")

        if os.path.exists(local_path):
            logger.info(f"   🗑️ Удаляю локальный файл: {local_path}")
            os.remove(local_path)
            logger.info(f"   ✅ Локальный файл удалён")

        if success:
            await update.message.reply_text(f"✅ {error_msg}")
            
            project_id = context.user_data.get('project_id')
            if project_id:
                logger.info(f"🔄 Обновляю дерево проекта {project_id} после загрузки...")
                full_tree = get_folder_tree_by_project(project_id, context, force=True)
                if full_tree:
                    context.user_data['full_tree'] = full_tree
                    logger.info("✅ Дерево проекта обновлено")
        else:
            await update.message.reply_text(f"❌ Не удалось загрузить файл: {error_msg}")

        context.user_data['state'] = IN_EXPLORER
        await show_current_level(update, context)
        return

    text = update.message.text.strip()

    if state == WAITING_FOR_LOGIN:
        context.user_data['username'] = text
        await update.message.reply_text(f"Логин '{text}' принят.\nТеперь введите пароль:")
        context.user_data['state'] = WAITING_FOR_PASSWORD

    elif state == WAITING_FOR_PASSWORD:
        username = context.user_data['username']
        password = text
        await update.message.reply_text("🔐 Выполняю вход...")

        if login(username, password, context):
            client = get_api_client(context)
            if client and client.token:
                save_chat_token_info(
                    update.effective_chat.id,
                    context.application,
                    client.token,
                    user_id=client.user_id,
                )
                restart_approval_notifications_for_chat(
                    context.application,
                    update.effective_chat.id,
                    workspace_id=None,
                    user_id=client.user_id,
                )

            workspaces = get_workspaces(context)
            if workspaces and len(workspaces) > 1:
                context.user_data['workspaces'] = workspaces
                context.user_data['state'] = SELECTING_WORKSPACE

                keyboard = []
                for ws in workspaces:
                    name = get_workspace_name(ws)
                    ws_id = get_workspace_id(ws)
                    if ws_id:
                        keyboard.append([InlineKeyboardButton(f"🏢 {name}", callback_data=f"workspace_{ws_id}")])

                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text("✅ Вход выполнен!\nВыберите пространство:", reply_markup=reply_markup)
            elif workspaces and len(workspaces) == 1:
                ws = workspaces[0]
                ws_id = get_workspace_id(ws)
                ws_name = get_workspace_name(ws)

                success = client.change_workspace(ws_id)
                context.user_data['workspace_id'] = ws_id
                context.user_data['workspace_name'] = ws_name

                if client and client.token:
                    save_chat_token_info(
                        update.effective_chat.id,
                        context.application,
                        client.token,
                        workspace_id=ws_id,
                        user_id=client.user_id,
                        workspace_name=ws_name,
                    )
                    restart_approval_notifications_for_chat(
                        context.application,
                        update.effective_chat.id,
                        workspace_id=ws_id,
                        user_id=client.user_id,
                    )

                await update.message.reply_text(f"✅ Вход выполнен!\nАвтоматически выбрано пространство: {ws_name}\nЗагружаю проекты...")

                projects = get_project_list(context)
                if not projects:
                    await update.message.reply_text("❌ Не удалось загрузить список проектов.")
                    return

                context.user_data['projects'] = projects
                context.user_data['state'] = SELECTING_PROJECT

                keyboard = []
                for proj in projects:
                    name = get_title(proj)
                    proj_id = proj["id"]
                    keyboard.append([InlineKeyboardButton(f"📦 {name}", callback_data=f"project_{proj_id}")])

                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text("✅ Выберите проект:", reply_markup=reply_markup)
            else:
                await update.message.reply_text("✅ Вход выполнен!\nЗагружаю проекты...")

                projects = get_project_list(context)
                if not projects:
                    await update.message.reply_text("❌ Не удалось загрузить список проектов.")
                    return

                context.user_data['projects'] = projects
                context.user_data['state'] = SELECTING_PROJECT

                if client and client.token:
                    restart_approval_notifications_for_chat(
                        context.application,
                        update.effective_chat.id,
                        workspace_id=context.user_data.get('workspace_id'),
                        user_id=client.user_id,
                    )

                keyboard = []
                for proj in projects:
                    name = get_title(proj)
                    proj_id = proj["id"]
                    keyboard.append([InlineKeyboardButton(f"📦 {name}", callback_data=f"project_{proj_id}")])

                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text("✅ Выберите проект:", reply_markup=reply_markup)
        else:
            await update.message.reply_text("❌ Ошибка авторизации. Проверьте логин и пароль.\nВведите логин снова:")
            context.user_data['state'] = WAITING_FOR_LOGIN

    else:
        await update.message.reply_text("Используйте /start для перезапуска.")

async def show_current_level(update_or_query, context):
    # Определяем, является ли это Update или CallbackQuery
    if hasattr(update_or_query, 'data'):
        # Это CallbackQuery
        query = update_or_query
        message = update_or_query.message
        is_callback = True
    elif hasattr(update_or_query, 'message') and update_or_query.message:
        # Это Update с message
        message = update_or_query.message
        query = None
        is_callback = False
    else:
        # Неизвестный тип
        logger.error(f"show_current_level: неизвестный тип объекта: {type(update_or_query)}")
        return
    
    path = context.user_data.get('path', [])
    full_tree = context.user_data.get('full_tree', [])

    logger.info(f"show_current_level: path={len(path)} уровней, full_tree={len(full_tree)} элементов, is_callback={is_callback}")

    if not full_tree:
        if is_callback:
            try:
                await query.message.edit_text("❌ Нет данных проекта.")
            except (TimedOut, NetworkError):
                await query.message.reply_text("❌ Нет данных проекта.")
        else:
            await message.reply_text("❌ Нет данных проекта.")
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

    chat_id = None
    if is_callback and hasattr(query, 'effective_chat'):
        chat_id = query.effective_chat.id
    elif hasattr(message, 'chat'):
        chat_id = message.chat.id

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
        nav_buttons.append(InlineKeyboardButton("🔙 Назад", callback_data="back"))
    
    # В корне проекта показываем "Сменить проекты" и "Сменить пространство", в подпапках - "Загрузить" и "Подписаться"
    if not path:
        # Корень проекта
        nav_buttons.extend([
            InlineKeyboardButton("📊 Статистика", callback_data=STATS_PROJECT),
            InlineKeyboardButton("🔄 Обновить", callback_data="refresh_folder"),
            InlineKeyboardButton("🗂️ Сменить проекты", callback_data="change_project"),
            InlineKeyboardButton("🏢 Сменить пространство", callback_data="change_workspace"),
        ])
        keyboard.append(nav_buttons)
    else:
        # Подпапка
        nav_buttons.extend([
            InlineKeyboardButton("📊 Статистика", callback_data=STATS_PROJECT),
            InlineKeyboardButton("🔄 Обновить", callback_data="refresh_folder"),
            InlineKeyboardButton("📤 Загрузить файл", callback_data="upload"),
        ])
        keyboard.append(nav_buttons)
        
        # Кнопка подписки
        if chat_id:
            folder_id = path[-1]["id"]
            
            existing = next((s for s in subscriptions if s.get('folder_id') == folder_id and s.get('project_id') == project_id), None)

            notify_text = "🔕 Отписаться" if existing else "🔔 Подписаться"
            keyboard.append([InlineKeyboardButton(notify_text, callback_data=TOGGLE_NOTIFY)])

    reply_markup = InlineKeyboardMarkup(keyboard)
    
    path_str = " → ".join([get_title(p) for p in path]) if path else "Корень"
    
    if not folders and not files:
        text = f"📂 <b>{path_str}</b>\n\n📂 Папка пуста"
    else:
        text = f"📂 <b>{path_str}</b>\n\nПапок: {len(folders)} | Файлов: {len(files)}"
    
    if is_callback:
        try:
            await query.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
        except (TimedOut, NetworkError):
            await query.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
    else:
        await message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not rate_limit(context):
        return

    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("adocs_"):
        parts = data.split("_")
        if len(parts) != 3:
            await query.message.reply_text("❌ Некорректные параметры списка файлов.")
            return

        try:
            workspace_id = int(parts[1])
            process_id = int(parts[2])
        except ValueError:
            await query.message.reply_text("❌ Некорректные ID в параметрах.")
            return

        token = get_api_token_for_chat(update.effective_chat.id, context.application)
        if not token:
            await query.message.reply_text("❌ Сессия истекла. Выполните вход заново.")
            return

        status_code, process_payload = _approval_api_get(
            token,
            f"/api/approvals/process/{process_id}",
            params={"workspaceId": workspace_id},
        )
        if status_code != 200 or not isinstance(process_payload, dict):
            await query.message.reply_text("❌ Не удалось получить список файлов согласования.")
            return

        process_info = process_payload.get("process") if isinstance(process_payload.get("process"), dict) else {}
        process_title = process_info.get("title") or f"Процесс {process_id}"

        documents = _extract_approval_documents(process_payload)
        back_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Назад", callback_data=f"aback_{workspace_id}_{process_id}")]
        ])
        if not documents:
            await query.message.edit_text(
                "📎 <b>Файлы согласования</b>\n\n"
                f"Согласование: <b>{html.escape(str(process_title))}</b>\n"
                "Файлы не найдены.",
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

        buttons.append([InlineKeyboardButton("🔙 Назад", callback_data=f"aback_{workspace_id}_{process_id}")])

        await query.message.edit_text(
            "📎 <b>Файлы согласования</b>\n\n"
            f"Согласование: <b>{html.escape(str(process_title))}</b>\n"
            "Выберите файл для скачивания:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    if data.startswith("aback_"):
        parts = data.split("_")
        if len(parts) != 3:
            await query.message.reply_text("❌ Некорректные параметры возврата.")
            return

        try:
            workspace_id = int(parts[1])
            process_id = int(parts[2])
        except ValueError:
            await query.message.reply_text("❌ Некорректные ID в параметрах.")
            return

        original_text = get_approval_notification_view(
            context.application,
            update.effective_chat.id,
            workspace_id,
            process_id,
        )
        if not original_text:
            original_text = (
                "🔔 <b>Новый этап согласования</b>\n\n"
                "Откройте карточку согласования по ссылке ниже."
            )

        await query.message.edit_text(
            original_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=build_approval_notify_markup(workspace_id, process_id),
        )
        return

    if data.startswith("adocdl_"):
        parts = data.split("_")
        if len(parts) != 4:
            await query.message.reply_text("❌ Некорректные параметры скачивания.")
            return

        try:
            workspace_id = int(parts[1])
            process_id = int(parts[2])
            document_id = int(parts[3])
        except ValueError:
            await query.message.reply_text("❌ Некорректные ID в параметрах.")
            return

        file_name = get_approval_download_hint(context.application, update.effective_chat.id, document_id)
        if not file_name:
            token = get_api_token_for_chat(update.effective_chat.id, context.application)
            if token:
                status_code, process_payload = _approval_api_get(
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

        await query.message.reply_text(f"⏳ Скачиваю файл: {file_name}...")

        filepath = download_file(document_id, file_name, context)
        if filepath and os.path.exists(filepath):
            file_size = os.path.getsize(filepath)
            size_mb = file_size / (1024 * 1024)
            if size_mb < 50:
                with open(filepath, 'rb') as f:
                    await safe_send_document(context.bot, update.effective_chat.id, f, filename=file_name)
                await query.message.reply_text(f"✅ Файл отправлен: {file_name}")
            else:
                await query.message.reply_text(
                    f"❌ Файл слишком большой для Telegram ({size_mb:.1f} МБ)\nФайл скачан в: {filepath}"
                )
        else:
            await query.message.reply_text("❌ Не удалось скачать файл.")
        return

    if data == "change_workspace":
        workspaces = get_workspaces(context)
        if not workspaces:
            await query.message.reply_text("❌ Не удалось загрузить список пространств.")
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
            await query.message.edit_text("🔄 Выберите пространство:", reply_markup=reply_markup)
        except (TimedOut, NetworkError):
            await query.message.reply_text("🔄 Выберите пространство:", reply_markup=reply_markup)
        return

    if data.startswith("workspace_") and context.user_data.get('state') == SELECTING_WORKSPACE:
        try:
            workspace_id = int(data.split("_", 1)[1])
        except (ValueError, IndexError):
            await query.message.reply_text("❌ Некорректный ID пространства.")
            return

        client = get_api_client(context)
        if not client:
            await query.message.reply_text("❌ API-клиент недоступен.")
            return

        success = client.change_workspace(workspace_id)
        if not success:
            await query.message.reply_text("❌ Не удалось переключить пространство.")
            return

        workspaces = context.user_data.get('workspaces', [])
        selected = next((w for w in workspaces if str(get_workspace_id(w)) == str(workspace_id)), None)
        workspace_name = get_workspace_name(selected) if selected else f"Workspace {workspace_id}"
        context.user_data['workspace_id'] = workspace_id
        context.user_data['workspace_name'] = workspace_name
        
        client = get_api_client(context)
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
            await query.message.edit_text(f"✅ Выбрано пространство: *{workspace_name}*\nЗагружаю проекты...", parse_mode='Markdown')
        except (TimedOut, NetworkError):
            await query.message.reply_text(f"✅ Выбрано пространство: *{workspace_name}*\nЗагружаю проекты...", parse_mode='Markdown')

        projects = get_project_list(context)
        if not projects:
            await query.message.reply_text("❌ Не удалось загрузить список проектов.")
            return

        context.user_data['projects'] = projects
        context.user_data['state'] = SELECTING_PROJECT

        keyboard = []
        for proj in projects:
            name = get_title(proj)
            proj_id = proj["id"]
            keyboard.append([InlineKeyboardButton(f"📦 {name}", callback_data=f"project_{proj_id}")])

        keyboard.append([InlineKeyboardButton("🏢 Сменить пространство", callback_data="change_workspace")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await query.message.edit_text("✅ Выберите проект:", reply_markup=reply_markup)
        except (TimedOut, NetworkError):
            await query.message.reply_text("✅ Выберите проект:", reply_markup=reply_markup)
        return

    if data == "change_project":
        projects = get_project_list(context)
        if not projects:
            await query.message.reply_text("❌ Не удалось загрузить список проектов.")
            return

        context.user_data['projects'] = projects
        context.user_data['state'] = SELECTING_PROJECT

        for key in ['full_tree', 'path', 'file_names', 'project_id', 'notify_folder_id']:
            context.user_data.pop(key, None)

        keyboard = []
        for proj in projects:
            name = get_title(proj)
            proj_id = proj["id"]
            keyboard.append([InlineKeyboardButton(f"📦 {name}", callback_data=f"project_{proj_id}")])

        keyboard.append([InlineKeyboardButton("🏢 Сменить пространство", callback_data="change_workspace")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await query.message.edit_text("🔄 Выберите новый проект:", reply_markup=reply_markup)
        except (TimedOut, NetworkError):
            await query.message.reply_text("🔄 Выберите новый проект:", reply_markup=reply_markup)
        return

    if data.startswith("project_") and context.user_data.get('state') == SELECTING_PROJECT:
        try:
            project_id = int(data.split("_", 1)[1])
        except (ValueError, IndexError):
            await query.message.reply_text("❌ Некорректный ID проекта.")
            return

        projects = context.user_data.get('projects', [])
        selected = next((p for p in projects if p["id"] == project_id), None)
        if not selected:
            await query.message.reply_text("❌ Проект не найден.")
            return

        project_name = get_title(selected)
        context.user_data['project_id'] = project_id
        context.user_data['state'] = IN_EXPLORER

        try:
            await query.message.edit_text(f"✅ Выбран проект: *{project_name}*\nЗагружаю структуру...", parse_mode='Markdown')
        except (TimedOut, NetworkError):
            await query.message.reply_text(f"✅ Выбран проект: *{project_name}*\nЗагружаю структуру...", parse_mode='Markdown')

        full_tree = get_folder_tree_by_project(project_id, context)
        if not full_tree:
            await query.message.reply_text("❌ Не удалось загрузить структуру проекта.")
            return

        context.user_data['full_tree'] = full_tree
        context.user_data['path'] = []
        context.user_data['file_names'] = {}

        await show_current_level(query, context)
        return

    if data == "noop":
        await query.answer(text="Папка пуста", show_alert=True)
        return

    if data == "back":
        path = context.user_data['path']
        if path:
            path.pop()
        context.user_data['path'] = path
        try:
            await show_current_level(query, context)
        except Exception as e:
            logger.error(f"❌ Ошибка при возврате: {e}")
            await query.message.reply_text("❌ Ошибка при возврате. Попробуйте снова.")
        return

    if data == STATS_PROJECT:
        full_tree = context.user_data.get('full_tree', [])
        if not full_tree:
            await query.message.reply_text("❌ Не удалось загрузить структуру проекта.")
            return

        file_count = count_files_in_tree(full_tree)
        projects = context.user_data.get('projects', [])
        project_id = context.user_data.get('project_id')
        
        project = next((p for p in projects if p.get('id') == project_id), None)
        project_name = get_title(project) if project else (get_title(projects[0]) if projects else "Проект")

        try:
            await query.message.edit_text(
                f"📊 *Статистика проекта*\n\n"
                f"📁 Проект: *{project_name}*\n"
                f"📄 Всего документов: *{file_count}*\n\n"
                f"Нажмите 'Назад', чтобы вернуться.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=BACK_TO_EXPLORER)]])
            )
        except (TimedOut, NetworkError):
            await query.message.reply_text(
                f"📊 *Статистика проекта*\n\n"
                f"📁 Проект: *{project_name}*\n"
                f"📄 Всего документов: *{file_count}*\n\n"
                f"Нажмите 'Назад', чтобы вернуться.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=BACK_TO_EXPLORER)]])
            )
        return

    if data == BACK_TO_EXPLORER:
        try:
            await show_current_level(query, context)
        except Exception as e:
            logger.error(f"❌ Ошибка при возврате из статистики: {e}")
            await query.message.reply_text("❌ Ошибка при возврате. Попробуйте снова.")
        return

    if data == "upload":
        context.user_data['state'] = AWAITING_UPLOAD
        await query.message.reply_text(
            "📥 Теперь отправьте файл как *документ* (не фото!), чтобы загрузить его в эту папку.",
            parse_mode='Markdown'
        )
        return

    if data == TOGGLE_NOTIFY:
        chat_id = update.effective_chat.id
        project_id = context.user_data.get('project_id')

        if not project_id:
            await query.message.reply_text("❌ Сначала выберите проект.")
            return

        path = context.user_data.get('path', [])

        if not path:
            folder_id = project_id
            folder_name = "Корень проекта"
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

            await query.message.reply_text(f"🔕 Вы отписались от уведомлений по папке: *{folder_name}*", parse_mode='Markdown')
        else:
            # Сначала очищаем старые состояния файлов для этой папки
            conn = sqlite3.connect(BOT_DATA_DB_PATH)
            cursor = conn.cursor()
            cursor.execute(
                'DELETE FROM file_states WHERE chat_id = ? AND project_id = ? AND folder_id = ?',
                (chat_id, project_id, folder_id),
            )
            conn.commit()
            conn.close()
            print(f"[SUBSCRIBE] Очищены старые состояния файлов для folder_id={folder_id}")

            # На подписке обязательно берём свежее дерево, иначе можем сохранить устаревший список файлов
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
                    await query.message.reply_text("❌ Папка не найдена.")
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
                    f"⚠️ Вы подписались на уведомления по папке: *{folder_name}*\n\n"
                    f"ОДНАКО: Функция запланированных задач недоступна. Уведомления не будут приходить автоматически.\n"
                    f"Чтобы включить уведомления, установите: pip install 'python-telegram-bot[job-queue]'",
                    parse_mode='Markdown'
                )
                try:
                    await show_current_level(query, context)
                except Exception as e:
                    logger.error(f"❌ Ошибка при показе после подписки: {e}")
                    await query.message.reply_text("❌ Ошибка. Попробуйте снова.")
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
            
            await query.message.reply_text(f"🔔 Вы подписались на уведомления по папке: *{folder_name}*\n\nУведомления будут приходить каждые 60 секунд.", parse_mode='Markdown')
        
        try:
            await show_current_level(query, context)
        except Exception as e:
            logger.error(f"❌ Ошибка при показе после подписки: {e}")
            await query.message.reply_text("❌ Ошибка. Попробуйте снова.")
        return

    if data == "refresh_folder":
        project_id = context.user_data.get('project_id')
        if not project_id:
            await query.message.reply_text("❌ Проект не выбран.")
            return

        old_path_ids = [p["id"] for p in context.user_data.get('path', [])]

        try:
            await query.message.edit_text("🔄 Обновляю содержимое папки...")
        except (TimedOut, NetworkError):
            await query.message.reply_text("🔄 Обновляю содержимое папки...")
        
        full_tree = get_folder_tree_by_project(project_id, context, force=True)
        if not full_tree:
            await query.message.reply_text("❌ Не удалось обновить структуру.")
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
            await query.message.reply_text("❌ Ошибка при обновлении. Попробуйте снова.")
        return

    if data.startswith("folder_"):
        try:
            folder_id = int(data.split("_", 1)[1])
        except (ValueError, IndexError):
            await query.message.reply_text("❌ Некорректный ID папки.")
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
                await query.edit_message_text(text="❌ Папка не найдена.")
            except (TimedOut, NetworkError):
                await query.message.reply_text("❌ Папка не найдена.")
            return

        path.append(target)
        context.user_data['path'] = path

        try:
            await show_current_level(query, context)
        except Exception as e:
            logger.error(f"❌ Ошибка при показе папки: {e}")
            await query.message.reply_text("❌ Ошибка при открытии папки. Попробуйте снова.")
        return

    if data.startswith("file_"):
        try:
            file_id = int(data.split("_", 1)[1])
        except (ValueError, IndexError):
            await query.message.reply_text("❌ Некорректный ID файла.")
            return

        path = context.user_data.get('path', [])
        current_level = context.user_data['full_tree'] if len(path) == 0 else (path[-1].get("children") or [])
        if not isinstance(current_level, list):
            current_level = []

        file_node = next((item for item in current_level if isinstance(item, dict) and item["id"] == file_id), None)
        if not file_node:
            await query.message.reply_text("❌ Файл не найден.")
            return

        name = file_node.get("originalName") or file_node.get("name") or "Без имени"
        version = file_node.get("version") or file_node.get("version_count") or file_node.get("documentVersion") or file_node.get("docVersion")
        created_by = file_node.get("created_by") or file_node.get("createdBy") or file_node.get("author") or ""
        modified_by = file_node.get("modified_by") or file_node.get("modifiedBy") or ""
        created_at = file_node.get("createdAt") or file_node.get("created_ts") or file_node.get("createTime")
        updated_at = file_node.get("updatedAt") or file_node.get("modified_ts") or file_node.get("modifTime") or file_node.get("modifiedDate")
        status = file_node.get("status") or ""
        file_type = file_node.get("type") or "file"

        parts = [f"📄 <b>{name}</b>"]
        if version:
            parts.append(f"🔢 Версия: {version}")
        if created_by:
            parts.append(f"👤 Кем создано: {created_by}")
        if modified_by:
            parts.append(f"✍️ Кем изменено: {modified_by}")
        if created_at:
            parts.append(f"🗓️ Создано: {format_file_date(created_at)}")
        if updated_at:
            parts.append(f"🕒 Обновлено: {format_file_date(updated_at)}")
        if status:
            parts.append(f"🏷️ Статус: {STATUS_TRANSLATIONS.get(status, status)}")
        if file_type:
            parts.append(f"📁 Тип: {TYPE_TRANSLATIONS.get(file_type, file_type)}")

        parts.append("")
        parts.append("Нажмите, чтобы скачать:")

        await query.message.reply_text("\n".join(parts), parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📥 Скачать", callback_data=f"download_{file_id}")
            ], [
                InlineKeyboardButton("🔙 Назад", callback_data=BACK_TO_EXPLORER)
            ]]))
        return

    if data.startswith("download_"):
        try:
            file_id = int(data.split("_", 1)[1])
        except (ValueError, IndexError):
            await query.message.reply_text("❌ Некорректный ID файла.")
            return

        path = context.user_data.get('path', [])
        current_level = context.user_data['full_tree'] if len(path) == 0 else (path[-1].get("children") or [])
        if not isinstance(current_level, list):
            current_level = []

        file_node = next((item for item in current_level if isinstance(item, dict) and item["id"] == file_id), None)
        if not file_node:
            await query.message.reply_text("❌ Файл не найден.")
            return

        name = file_node.get("originalName") or file_node.get("name") or "Без имени"
        await query.message.reply_text(f"⏳ Скачиваю файл: {name}...")

        filepath = download_file(file_id, name, context)
        if filepath and os.path.exists(filepath):
            file_size = os.path.getsize(filepath)
            size_mb = file_size / (1024 * 1024)
            if size_mb < 50:
                with open(filepath, 'rb') as f:
                    await safe_send_document(context.bot, update.effective_chat.id, f, filename=name)
                await query.message.reply_text(f"✅ Файл отправлен: {name}")
            else:
                await query.message.reply_text(f"❌ Файл слишком большой для Telegram ({size_mb:.1f} МБ)\nФайл скачан в: {filepath}")
        else:
            await query.message.reply_text("❌ Не удалось скачать файл.")

        await show_current_level(query, context)
        return

    if data.startswith("adownload_"):
        try:
            document_id = int(data.split("_", 1)[1])
        except (ValueError, IndexError):
            await query.message.reply_text("❌ Некорректный ID документа.")
            return

        file_name = get_approval_download_hint(context.application, update.effective_chat.id, document_id)
        if not file_name:
            file_name = f"document_{document_id}"

        await query.message.reply_text(f"⏳ Скачиваю файл: {file_name}...")

        filepath = download_file(document_id, file_name, context)
        if filepath and os.path.exists(filepath):
            file_size = os.path.getsize(filepath)
            size_mb = file_size / (1024 * 1024)
            if size_mb < 50:
                with open(filepath, 'rb') as f:
                    await safe_send_document(context.bot, update.effective_chat.id, f, filename=file_name)
                await query.message.reply_text(f"✅ Файл отправлен: {file_name}")
            else:
                await query.message.reply_text(
                    f"❌ Файл слишком большой для Telegram ({size_mb:.1f} МБ)\nФайл скачан в: {filepath}"
                )
        else:
            await query.message.reply_text("❌ Не удалось скачать файл.")

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

def main():
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

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("logout", logout))
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

    logger.info("🚀 Бот запущен!")

    application.run_polling()

if __name__ == "__main__":
    main()
