# -*- coding: utf-8 -*-

import os
import json
import mimetypes
import sys
import time
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, Callable, TYPE_CHECKING
if TYPE_CHECKING:
    from typing import Tuple
import subprocess

from PySide6.QtCore import QSettings, Signal
from PySide6.QtWidgets import QComboBox

import requests
import tempfile
from zoneinfo import ZoneInfo, available_timezones

try:
    from requests_toolbelt.multipart.encoder import (  # type: ignore
        MultipartEncoder,
        MultipartEncoderMonitor,
    )
except Exception:
    MultipartEncoder = None  # type: ignore
    MultipartEncoderMonitor = None  # type: ignore

# ============================================================================
# SSL Patching for Windows + Python 3.13 to prevent access violation
# ============================================================================
import ssl
import urllib3
import urllib3.util.ssl_
from requests.adapters import HTTPAdapter
from .request_specs import (
    AUTH_LOGIN_PATH,
    AUTH_REFRESH_PATH,
    DOCUMENT_DELETE_PATH,
    DOCUMENT_DETAILS_PATH,
    DOCUMENT_DOWNLOAD_PATH,
    DOCUMENT_LIST_PATH,
    DOCUMENT_TYPES_PATH,
    DOCUMENT_UPDATE_PATH,
    DOCUMENT_MOVE_PATH,
    DOCUMENT_UPLOAD_CONTENT_TYPE,
    DOCUMENT_UPLOAD_FILE_FIELD,
    DOCUMENT_UPLOAD_METADATA_FIELD,
    DOCUMENT_UPLOAD_PATH,
    DOCUMENT_VERSIONS_PATH,
    VERSIONS_LIST_PATH,
    FOLDER_ADD_PATH,
    FOLDER_COPY_PATH,
    FOLDER_CHECK_RIGHTS_PATH,
    FOLDER_DELETE_PATH,
    FOLDER_DETAILS_PATH,
    FOLDER_LIST_PATH,
    FOLDER_UPDATE_PATH,
    PROJECT_LIST_PATH,
    WORKSPACE_CHANGE_PATH,
    WORKSPACE_LIST_PATHS,
    build_auth_refresh_payload,
    build_document_move_payload,
    build_documents_move_payload,
    build_document_rename_payload,
    build_document_upload_metadata,
    build_folder_copy_payload,
    build_folder_create_payload,
    build_folder_rename_payload,
    build_folder_update_payload,
    build_login_payload,
    build_url,
    build_workspace_change_payload,
    build_workspace_change_query_url,
)

# Import and apply SSL patching from centralized module
from larix_nexus.utils.ssl_patch import *  # noqa: F401,F403

# Additional patching for urllib3 utilities
try:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

def _patch_urllib3_classes():
    """Patch urllib3 PoolManager and HTTPSConnectionPool."""
    try:
        original_poolmanager_init = urllib3.PoolManager.__init__
        def patched_poolmanager_init(self, *args, **kwargs):
            result = original_poolmanager_init(self, *args, **kwargs)
            self.connection_pool_kw.setdefault('cert_reqs', ssl.CERT_NONE)
            self.connection_pool_kw.setdefault('assert_hostname', False)
            return result
        urllib3.PoolManager.__init__ = patched_poolmanager_init
    except Exception:
        pass
    
    try:
        original_https_init = urllib3.HTTPSConnectionPool.__init__
        def patched_https_init(self, *args, **kwargs):
            result = original_https_init(self, *args, **kwargs)
            self.cert_reqs = ssl.CERT_NONE
            return result
        urllib3.HTTPSConnectionPool.__init__ = patched_https_init
    except Exception:
        pass

_patch_urllib3_classes()

# ============================================================================

from larix_nexus.constants import (
    BASE_URL,
    DOWNLOAD_DIR,
    CACHE_TTL_SEC,
    SETTINGS_ORG,
    SETTINGS_APP,
)
from larix_nexus.utils.keyring import (
    KEYRING_SERVICE,
    save_credential,
    get_credential,
    delete_credential,
    clear_all_credentials,
    debug_credentials_status,
)
from larix_nexus.utils.settings import load_settings, save_settings
from larix_nexus.utils.logging import sync_log, sync_exc
from larix_nexus.utils.copy_logger import copy_log


def _env_bool(name: str, default: bool = False) -> bool:
    try:
        v = (os.getenv(name) or "").strip().lower()
        if v in ("1", "true", "yes", "y", "on"):
            return True
        if v in ("0", "false", "no", "n", "off"):
            return False
    except Exception:
        pass
    return default


_API_DEBUG = _env_bool("DEBUG_API", False)
_LOG_API_RESPONSES = _env_bool("LOG_API_RESPONSES", False)
_API_LOG = logging.getLogger("api")

# Large upload: sync_log multipart diagnostics + PreparedRequest send (browser-like CL)
_LARGE_STREAMING_UPLOAD_LOG_BYTES = 5 * 1024 * 1024
_LARGE_STREAMING_UPLOAD_SESSION_BYTES = 10 * 1024 * 1024


def _api_dbg(msg: str, *args) -> None:
    if not _API_DEBUG:
        return
    try:
        _API_LOG.debug(msg, *args)
    except Exception:
        pass


def _safe_url_for_api_log(url: str) -> str:
    """Strip query string (may contain sensitive params); never log tokens from headers here."""
    try:
        return url.split("?", 1)[0]
    except Exception:
        return url


def _log_api_response(url: str, method: str, status_code: int, response_data: Any, error: str = "") -> None:
    """Log API response details if LOG_API_RESPONSES is enabled."""
    if not _LOG_API_RESPONSES:
        return
    try:
        sync_log("API Response: {} {} status={}", method, url, status_code, component="API", op="response", result=str(status_code))
        
        if status_code >= 400:
            sync_log("API Error Response: {}", str(response_data)[:1000], component="API", op="error", reason=error)
        else:
            sync_log("API Response Body: {}", str(response_data)[:2000], component="API", op="success")
    except Exception:
        pass

# --- Lazy popup combobox to trigger loading on open ---
class PopupComboBox(QComboBox):
    aboutToPopup = Signal()
    def showPopup(self):
        try:
            self.aboutToPopup.emit()
        except Exception:
            pass
        super().showPopup()

# ============================================================================

def _sanitize_filename(name: str) -> str:
    """Return filename safe for Windows/macOS/Linux (no path separators, no reserved chars)."""
    if not isinstance(name, str):
        name = str(name or "")
    # Strip directories
    name = name.replace("\\", "/").split("/")[-1]
    # Remove reserved characters on Windows
    forbidden = set('<>:"/\\|?*')
    cleaned = ''.join('_' if ch in forbidden or ord(ch) < 32 else ch for ch in name)
    cleaned = cleaned.strip().rstrip('. ')
    if not cleaned:
        cleaned = "file"
    # Limit very long names
    if len(cleaned) > 240:
        base, ext = os.path.splitext(cleaned)
        cleaned = (base[:230] + ext) if len(ext) < 10 else cleaned[:240]
    return cleaned


def _app_settings() -> QSettings:
    """Legacy QSettings accessor.

    Note: The modern settings storage is JSON via larix_nexus.utils.settings.
    """
    return QSettings(SETTINGS_ORG, SETTINGS_APP)

# ============================================================================

def decide_sync(doc, local_path, user_tz: str = "Europe/Moscow", tol: float = 2.0):
    """Decide sync direction based on cloud vs local times.

    Rules:
    - Cloud time = doc["modifTime"] or doc["createTime"]. If missing -> "skip".
    - Parse ISO strings; if no timezone offset in the string, treat as UTC.
    - Convert to ZoneInfo(user_tz) and compare epoch seconds.
    - Local time = Path(local_path).stat().st_mtime (seconds).
    - Compare with tolerance (seconds):
        local > cloud + tol   -> "upload"
        cloud > local + tol   -> "download"
        otherwise             -> "skip"

    Always prints the chosen action and returns it. Safe on empty/missing fields.
    """
    from datetime import datetime, timezone
    from pathlib import Path
    try:
        from zoneinfo import ZoneInfo  # Python 3.9+
    except Exception:
        ZoneInfo = None  # type: ignore

    try:
        if not isinstance(doc, dict):
            print("decide_sync: skip (doc is not dict)")
            return "skip"
        raw = doc.get("modifTime") or doc.get("createTime")
        if not raw:
            print("decide_sync: skip (no cloud time)")
            return "skip"

        cloud_dt = None
        if isinstance(raw, (int, float)):
            try:
                ts = float(raw)
                if ts > 1e12:
                    ts = ts / 1000.0
                cloud_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            except Exception:
                cloud_dt = None
        if cloud_dt is None:
            s = str(raw).strip()
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            try:
                dt = datetime.fromisoformat(s)
            except Exception:
                print("decide_sync: skip (unparseable cloud time)")
                return "skip"
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            cloud_dt = dt

        try:
            if ZoneInfo is not None:
                tz = ZoneInfo(user_tz)
                cloud_ts = cloud_dt.astimezone(tz).timestamp()
            else:
                cloud_ts = cloud_dt.timestamp()
        except Exception:
            cloud_ts = cloud_dt.timestamp()

        try:
            lp = Path(local_path)
            local_ts = float(lp.stat().st_mtime)
        except Exception:
            local_ts = 0.0

        t = float(tol)
        if local_ts > cloud_ts + t:
            action = "upload"
        elif cloud_ts > local_ts + t:
            action = "download"
        else:
            action = "skip"

        print(f"decide_sync: {action} (local={local_ts:.3f}, cloud={cloud_ts:.3f}, tol={t}, tz='{user_tz}')")
        return action
    except Exception as e:
        try:
            print(f"decide_sync: skip (error: {e})")
        except Exception:
            pass
        return "skip"

def _cloud_tz_offset_minutes() -> int:
    """Return offset in minutes to interpret naive cloud timestamps.
    Uses settings group 'time': keys 'auto' and 'offset_minutes'.
    Also removes legacy key sync2/tz_offset_min if present.
    """
    try:
        s = _app_settings()
        try:
            s.beginGroup("sync2")
            try:
                if s.contains("tz_offset_min"):
                    s.remove("tz_offset_min")
            finally:
                s.endGroup()
        except Exception:
            pass
        s.beginGroup("time")
        try:
            # QSettings.value() returns loosely-typed variants; keep parsing robust.
            raw_auto = s.value("auto", 1)
            try:
                use_auto = str(raw_auto).strip().lower() not in ("0", "false", "no", "off", "")
            except Exception:
                use_auto = True
            if use_auto:
                try:
                    ofs = datetime.now().astimezone().utcoffset() or timedelta(0)
                    return int(ofs.total_seconds() // 60)
                except Exception:
                    return 0
            else:
                raw_ofs = s.value("offset_minutes", 0)
                try:
                    return int(str(raw_ofs).strip() or 0)
                except Exception:
                    return 0
        finally:
            s.endGroup()
    except Exception:
        return 0

def parse_date_like(s: str, tz_offset_min: int | None = None) -> float:
    """Parse a cloud datetime into UTC epoch seconds.
    - If s is numeric (seconds or ms), return as seconds.
    - If ISO string with explicit TZ or 'Z' suffix, respect it.
    - If naive string (no TZ), add tz_offset_min minutes to the naive time, then treat as UTC.
      Example: offset +180, '07:00' -> 07:00 + 03:00 => 10:00 UTC.
    """
    if not s:
        return 0.0
    try:
        if isinstance(s, (int, float)) or (isinstance(s, str) and s.strip().isdigit()):
            val = float(s)
            if val > 1e12:
                val = val / 1000.0
            return float(val)
    except Exception:
        pass
    s = str(s).strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        from datetime import timezone, timedelta
        if dt.tzinfo is None:
            ofs = int(tz_offset_min or 0)
            dt2 = dt + timedelta(minutes=ofs)
            return dt2.replace(tzinfo=timezone.utc).timestamp()
        return dt.timestamp()
    except Exception:
        pass
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            from datetime import timezone, timedelta
            ofs = int(tz_offset_min or 0)
            dt2 = dt + timedelta(minutes=ofs)
            return dt2.replace(tzinfo=timezone.utc).timestamp()
        except (ValueError, TypeError):
            continue
    return 0.0

# ============================================================================

class ApiResult:
    __slots__ = ('ok', 'data', 'error')

    def __init__(self, ok: bool, data=None, error: str = ''):
        self.ok = ok
        self.data = data
        self.error = error

    def __repr__(self):
        if self.ok:
            n = len(self.data) if isinstance(self.data, list) else 'N/A'
            return f'ApiResult(ok=True, items={n})'
        return f'ApiResult(ok=False, error={self.error!r})'


def is_transient_upload_network_error(exc: BaseException) -> bool:
    """True when the upload HTTP response may have been lost (retry / cloud verify).

    Covers Windows reset (10054), remote hang-up, urllib3 ``Connection aborted``,
    and ``requests`` connection errors (possibly wrapping the above).
    """
    if exc is None:
        return False
    if isinstance(exc, ConnectionResetError):
        return True
    if isinstance(exc, OSError):
        if getattr(exc, "winerror", None) == 10054:
            return True
    if isinstance(exc, requests.exceptions.ConnectionError):
        inner = getattr(exc, "__cause__", None) or getattr(exc, "__context__", None)
        if inner is not None and inner is not exc and is_transient_upload_network_error(inner):
            return True
        for arg in getattr(exc, "args", ()) or ():
            if isinstance(arg, BaseException) and arg is not exc:
                if is_transient_upload_network_error(arg):
                    return True
            elif isinstance(arg, str):
                al = arg.lower()
                if "connection aborted" in al or "10054" in arg:
                    return True
        return True
    msg = str(exc).lower()
    if "connection aborted" in msg:
        return True
    if "10054" in str(exc):
        return True
    return False


def _network_error_message(exc: BaseException) -> str:
    """Return a user-safe network error label without exception details."""
    if isinstance(exc, requests.Timeout):
        return "Превышено время ожидания ответа сервера"
    if isinstance(exc, requests.ConnectionError):
        return "Не удалось установить соединение с сервером"
    return "Сетевая ошибка при обращении к серверу"


def _http_error_message(status: int) -> str:
    """Map an HTTP failure to a short UI-safe message."""
    if status in (401, 403):
        return "Ошибка авторизации или доступа"
    if status == 404:
        return "Файл или ресурс не найден"
    if status == 429:
        return "Сервер временно ограничил запросы"
    if status >= 500:
        return "Сервер временно недоступен"
    return f"Ошибка сервера (HTTP {status})"


def _upload_request_timeout_sec(file_size_bytes: int) -> float:
    """Seconds for ``requests`` timeout on multipart upload.

    A fixed short timeout breaks large files (e.g. Revit): the body send + server
    processing can take many minutes. Budget ~256 KiB/s effective throughput plus
    a fixed margin; clamp to a sane range.
    """
    try:
        n = int(file_size_bytes)
    except Exception:
        n = 0
    if n <= 0:
        return 600.0
    assumed_bps = 256 * 1024
    t = 180.0 + (float(n) / float(assumed_bps))
    return float(min(max(t, 300.0), 6 * 3600.0))


class _UploadCountingReader:
    """Binary file wrapper: counts bytes read for upload progress (supports seek for retries)."""

    __slots__ = ("_raw", "_total", "_cb", "_done")

    def __init__(self, raw, total: int, callback) -> None:
        self._raw = raw
        self._total = int(total or 0)
        self._cb = callback
        self._done = 0

    def read(self, n=-1):
        data = self._raw.read(n)
        if data and self._cb:
            self._done += len(data)
            try:
                self._cb(self._done, self._total)
            except Exception:
                pass
        return data

    def seek(self, offset, whence=0):
        pos = self._raw.seek(offset, whence)
        try:
            self._done = int(self._raw.tell())
        except Exception:
            pass
        return pos

    def tell(self):
        return self._raw.tell()

    def close(self):
        return self._raw.close()

    def __getattr__(self, name):
        return getattr(self._raw, name)


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
        
        try:
            self._load_auth()
        except Exception:
            pass

    def _save_auth(self) -> None:
        """Save auth tokens to keyring. Always saves credentials for auto-login."""
        try:
            if not self.current_username:
                logging.getLogger("auth").debug("_save_auth: no username, skipping")
                return

            logging.getLogger("auth").info("_save_auth: saving credentials")
            
            if self.token:
                save_credential(self.current_username, "access_token", self.token)
            
            if self.refresh_token:
                save_credential(self.current_username, "refresh_token", self.refresh_token)
            
            settings = load_settings()
            settings["last_username"] = self.current_username
            settings["remember_me"] = True
            settings["auto_login"] = True
            save_settings(settings)
            logging.getLogger("auth").debug("_save_auth: updated settings auto_login=True remember_me=True")
            
            debug_credentials_status(self.current_username)
        except Exception as e:
            logging.getLogger("auth").exception("_save_auth error: %s", e)
            pass

    def _load_auth(self) -> bool:
        """Load auth tokens from keyring. Returns True if tokens were loaded and validated.
        
        Tries in order:
        1. Refresh token → refresh to get new access token
        2. Password → login to get new tokens
        3. Access token → direct use (may be expired)
        """
        try:
            logging.getLogger("auth").info("_load_auth: starting auto-login")
            settings = load_settings()
            username = settings.get("last_username", "")
            
            if not username:
                logging.getLogger("auth").info("_load_auth: no last_username")
                return False

            logging.getLogger("auth").info("_load_auth: found last_username")
            
            debug_credentials_status(username)
            
            refresh_token = get_credential(username, "refresh_token")
            if refresh_token:
                self.current_username = username
                self.refresh_token = refresh_token
                
                if self._refresh_access_token():
                    logging.getLogger("auth").info("_load_auth: success via refresh_token")
                    return True
                else:
                    logging.getLogger("auth").warning("_load_auth: refresh_token refresh failed")
            else:
                logging.getLogger("auth").debug("_load_auth: no refresh_token")
            
            password = get_credential(username, "password")
            if password:
                if self.login(username, password, remember_me=True):
                    logging.getLogger("auth").info("_load_auth: success via password")
                    return True
                else:
                    logging.getLogger("auth").warning("_load_auth: password login failed")
            else:
                logging.getLogger("auth").debug("_load_auth: no password in keyring")
            
            access_token = get_credential(username, "access_token")
            if access_token:
                self.current_username = username
                self.token = access_token
                try:
                    self._sync_identity_from_token()
                except Exception:
                    pass
                logging.getLogger("auth").info("_load_auth: using access_token (may be expired)")
                return True
            else:
                logging.getLogger("auth").debug("_load_auth: no access_token")
            
            logging.getLogger("auth").info("_load_auth: failed - no valid credentials")
            return False
        except Exception as e:
            logging.getLogger("auth").exception("_load_auth error: %s", e)
            return False

    def _clear_auth(self, username: Optional[str] = None) -> None:
        """Clear credentials for *username* and disable persisted login."""
        username = username if username is not None else self.current_username
        try:
            if username:
                clear_all_credentials(username)
        except Exception as exc:
            logging.getLogger("auth").warning(
                "logout: credential cleanup failed (%s)", type(exc).__name__
            )

        try:
            settings = load_settings()
            settings["remember_me"] = False
            settings["last_username"] = ""
            if "auto_login" in settings:
                settings["auto_login"] = False
            save_settings(settings)
        except Exception as exc:
            logging.getLogger("auth").warning(
                "logout: settings cleanup failed (%s)", type(exc).__name__
            )

    def _refresh_access_token(self) -> bool:
        """Refresh access token using refresh token. Returns True if successful."""
        if not self.refresh_token:
            logging.getLogger("auth").info("_refresh_access_token: no refresh_token")
            return False

        logging.getLogger("auth").info("_refresh_access_token: attempting refresh")
        url = build_url(self.base_url, AUTH_REFRESH_PATH)
        try:
            r = requests.post(
                url,
                json=build_auth_refresh_payload(self.refresh_token),
                headers={"accept": "*/*", "Content-Type": "application/json"},
                timeout=12
            )
            
            logging.getLogger("auth").info("_refresh_access_token: status=%s", r.status_code)
            
            if r.status_code != 200:
                logging.getLogger("auth").warning("_refresh_access_token: failed status=%s", r.status_code)
                return False
            
            data = r.json()
            logging.getLogger("auth").debug("_refresh_access_token: response keys=%s", list(data.keys()) if isinstance(data, dict) else type(data))
            _log_api_response(url, "POST", r.status_code, data)
            
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
                
                self._save_auth()
                logging.getLogger("auth").info("_refresh_access_token: success")
                return True
            
            logging.getLogger("auth").warning("_refresh_access_token: failed - no access_token in response")
            return False
        except requests.RequestException as e:
            logging.getLogger("auth").warning("_refresh_access_token: RequestException: %s", e)
            return False

    def _decode_jwt(self, token: str) -> dict | None:
        """Decode JWT token without verification. Returns payload dict or None."""
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
        """Best-effort sync of user_id/workspace_id from JWT claims."""
        if not self.token:
            return
        decoded = self._decode_jwt(self.token)
        if not decoded or not isinstance(decoded, dict):
            return

        # workspace id
        ws = decoded.get("workspace_id") or decoded.get("workspaceId")
        if ws is not None:
            self.workspace_id = ws
            if self.selected_workspace_id is None:
                self.selected_workspace_id = ws

        # user id: platform uses MS 'userdata' claim
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

    def _headers(self):
        h = {"accept": "*/*"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _handle_401(self) -> bool:
        """Handle 401 error by trying to refresh token.
        
        Returns:
            True if token was refreshed successfully
        """
        if self.refresh_token:
            if self._refresh_access_token():
                return True

        self.token = None
        self.cache.clear()
        return False

    def _stringify_id(self, value) -> str:
        """Convert document/folder ID to string (handles int, str, or None)."""
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        try:
            return str(int(value))
        except (TypeError, ValueError):
            return str(value).strip()

    def is_available(self, timeout: int = 6) -> bool:
        """Lightweight availability check.
        Tries a tiny authenticated call; treats any non-network failure as available
        (e.g., 401 means server reachable but not authorized).
        """
        try:
            if not self.base_url:
                return False
            url = build_url(self.base_url, PROJECT_LIST_PATH)
            r = requests.get(url, headers=self._headers(), timeout=max(2, int(timeout)))
            return r.status_code < 500
        except requests.RequestException:
            return False

    def login(self, username: str, password: str, remember_me: bool = True) -> bool:
        """Login with username and password.

        Args:
            username: Username
            password: Password
            remember_me: If True, save credentials for auto-login on restart

        Returns:
            True if login successful
        """
        logging.getLogger("auth").info("login: attempting (remember_me=%s)", bool(remember_me))
        url = build_url(self.base_url, AUTH_LOGIN_PATH)
        payload = build_login_payload(username, password)
        try:
            r = requests.post(url, json=payload, headers={"accept": "*/*","Content-Type":"application/json"}, timeout=12)
            if r.status_code == 401:
                logging.getLogger("auth").warning("login: 401 Unauthorized")
                return False
            r.raise_for_status()
            data = r.json()
            _log_api_response(url, "POST", r.status_code, data)

            token = data.get("token") or data.get("accessToken") or data.get("access_token")
            refresh_token = data.get("refreshToken") or data.get("refresh_token")

            if not token:
                logging.getLogger("auth").warning("login: no token in response")
                return False

            self.token = token
            self.refresh_token = refresh_token
            self.current_username = username

            try:
                self._sync_identity_from_token()
            except Exception:
                pass

            logging.getLogger("auth").info("login: success")

            # Always save last_username for auto-fill in login dialog
            settings = load_settings()
            settings["last_username"] = username
            settings["remember_me"] = remember_me
            save_settings(settings)
            logging.getLogger("auth").debug("login: saved settings last_username/remember_me")

            if remember_me:
                save_credential(username, "password", password)
                logging.getLogger("auth").debug("login: saved password to keyring")
                # Save tokens for auto-login
                if self.token:
                    save_credential(username, "access_token", self.token)
                if self.refresh_token:
                    save_credential(username, "refresh_token", self.refresh_token)
            else:
                logging.getLogger("auth").info("login: remember_me=False, not saving credentials")

            return True
        except requests.RequestException as e:
            logging.getLogger("auth").warning("login: RequestException: %s", e)
            return False

    def logout(self):
        """Logout and clear all stored credentials."""
        username = self.current_username
        try:
            self._clear_auth(username)
        finally:
            self.token = None
            self.refresh_token = None
            self.current_username = None
            self.cache.clear()

    def list_projects(self):
        """List all projects. Filter by selected workspace_id if set. Auto-retries once on 401."""
        if not self.token: 
            return []
        
        url = build_url(self.base_url, PROJECT_LIST_PATH)
        logging.getLogger("auth").info("list_projects: requesting %s", url)
        logging.getLogger("auth").debug("list_projects: workspace_id=%s", self.selected_workspace_id)
        
        for attempt in range(2):
            try:
                r = requests.get(url, headers=self._headers(), timeout=12)
                logging.getLogger("auth").debug("list_projects: response status=%s", r.status_code)
                
                if r.status_code == 401:
                    if attempt == 0 and self._handle_401():
                        continue
                    return []
                
                r.raise_for_status()
                data = r.json()
                logging.getLogger("auth").debug("list_projects: response data type=%s", type(data))
                _log_api_response(url, "GET", r.status_code, data)
                
                projects = []
                
                if isinstance(data, list):
                    projects = data
                elif isinstance(data, dict) and "data" in data and isinstance(data.get("data"), list):
                    projects = data.get("data", [])
                
                if self.selected_workspace_id:
                    ws_id = str(self.selected_workspace_id)
                    # Log all workspace-related fields from first few projects
                    for i, p in enumerate(projects[:3]):
                        ws_field = p.get("workspaceId") or p.get("workspace_id")
                        logging.getLogger("auth").debug("list_projects: project[%d] id=%s, workspaceId=%s, workspace_id=%s", 
                                                       i, p.get("id"), p.get("workspaceId"), p.get("workspace_id"))
                    
                    # Try both field name variations
                    filtered = [p for p in projects if str(p.get("workspaceId")) == ws_id or str(p.get("workspace_id")) == ws_id]
                    logging.getLogger("auth").info("list_projects: filtered %d/%d projects for workspace=%s", len(filtered), len(projects), ws_id)
                    
                    # If no projects found with selected workspace, don't filter (return all)
                    if not filtered:
                        logging.getLogger("auth").warning("list_projects: no projects found for workspace=%s, returning all projects", ws_id)
                    else:
                        projects = filtered
                
                logging.getLogger("auth").info("list_projects: returning %d projects", len(projects))
                for i, p in enumerate(projects[:3]):
                    logging.getLogger("auth").debug("list_projects: project[%d] id=%s title=%s", i, p.get("id"), p.get("title"))
                
                return projects
            except requests.RequestException as e:
                logging.getLogger("auth").warning("list_projects: exception: %s", e)
                return []
        return []
    
    def list_workspaces(self):
        """List all workspaces. Auto-retries once on 401."""
        if not self.token:
            return []
        
        # Try multiple endpoint patterns - prioritize non-admin endpoint first
        endpoints = [build_url(self.base_url, path) for path in WORKSPACE_LIST_PATHS]
        
        for url in endpoints:
            logging.getLogger("auth").info("list_workspaces: trying %s", url)
            
            for attempt in range(2):
                try:
                    r = requests.get(url, headers=self._headers(), timeout=12)
                    logging.getLogger("auth").debug("list_workspaces: response status=%s", r.status_code)
                    
                    if r.status_code == 401:
                        if attempt == 0 and self._handle_401():
                            continue
                        break
                    
                    if r.status_code == 200:
                        data = r.json()
                        logging.getLogger("auth").debug("list_workspaces: response data type=%s", type(data))
                        
                        workspaces = []
                        
                        if isinstance(data, list):
                            workspaces = data
                        elif isinstance(data, dict) and "data" in data and isinstance(data.get("data"), list):
                            workspaces = data.get("data", [])
                        
                        if workspaces:
                            logging.getLogger("auth").info("list_workspaces: returning %d workspaces from %s", len(workspaces), url)
                            for i, ws in enumerate(workspaces[:3]):
                                ws_id = ws.get("id") or ws.get("workspace_id")
                                ws_name = ws.get("name") or ws.get("title")
                                logging.getLogger("auth").debug("list_workspaces: workspace[%d] id=%s name=%s", i, ws_id, ws_name)
                            return workspaces
                        else:
                            logging.getLogger("auth").warning("list_workspaces: empty workspace list from %s", url)
                    elif r.status_code == 403:
                        logging.getLogger("auth").warning("list_workspaces: 403 Forbidden from %s", url)
                        break
                    elif r.status_code == 404:
                        logging.getLogger("auth").debug("list_workspaces: 404 Not Found from %s", url)
                except requests.RequestException as e:
                    logging.getLogger("auth").warning("list_workspaces: exception for %s: %s", url, e)
                    break
        
        # All endpoints failed, try to get workspace from JWT token
        logging.getLogger("auth").info("list_workspaces: trying to extract workspace from JWT token")
        decoded = self._decode_jwt(self.token)
        if decoded and isinstance(decoded, dict):
            logging.getLogger("auth").debug("list_workspaces: JWT payload keys=%s", list(decoded.keys()))
            workspace_id = decoded.get("workspace_id") or decoded.get("workspaceId")
            if workspace_id:
                workspaces = [{"id": workspace_id, "name": f"Workspace {workspace_id}"}]
                logging.getLogger("auth").info("list_workspaces: returning %d workspaces from JWT", len(workspaces))
                return workspaces
        
        logging.getLogger("auth").warning("list_workspaces: failed to get any workspaces")
        return []

    def change_workspace(self, workspace_id):
        """Switch workspace and refresh auth tokens for it.

        Uses `/api/admin/workspace/change?workspaceId=...` which returns a new token pair.
        """
        if not self.token:
            logging.getLogger("auth").warning("change_workspace: no access token")
            return False

        try:
            self._sync_identity_from_token()
        except Exception:
            pass

        # Skip only if the current token already belongs to this workspace.
        if str(self.workspace_id) == str(workspace_id) and str(self.selected_workspace_id) == str(workspace_id):
            logging.getLogger("auth").info("change_workspace: workspace already active=%s", workspace_id)
            return True

        logging.getLogger("auth").info(
            "change_workspace: switching to workspace_id=%s (selected was %s, token ws was %s)",
            workspace_id,
            self.selected_workspace_id,
            self.workspace_id,
        )

        url_qs = build_workspace_change_query_url(self.base_url, workspace_id)
        url_body = build_url(self.base_url, WORKSPACE_CHANGE_PATH)
        for attempt in range(2):
            try:
                # API differs by deployment: POST (body) vs POST (query) vs GET (query).
                headers = dict(self._headers() or {})
                headers.setdefault("Content-Type", "application/json")

                candidates = [
                    ("PUT", url_qs, build_workspace_change_payload(workspace_id)),
                    ("PUT", url_body, build_workspace_change_payload(workspace_id)),
                    ("POST", url_qs, build_workspace_change_payload(workspace_id)),
                    ("POST", url_body, build_workspace_change_payload(workspace_id)),
                    ("GET", url_qs, None),
                ]

                r = None
                used_method = None
                used_url = None
                for method, url, payload in candidates:
                    used_method = method
                    used_url = url
                    logging.getLogger("auth").debug("change_workspace: trying %s %s", method, url)
                    if method == "PUT":
                        r = requests.put(url, headers=headers, json=payload, timeout=12)
                    elif method == "POST":
                        r = requests.post(url, headers=headers, json=payload, timeout=12)
                    else:
                        r = requests.get(url, headers=self._headers(), timeout=12)

                    logging.getLogger("auth").debug("change_workspace: %s %s -> status=%s", method, url, getattr(r, "status_code", None))
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
                _log_api_response(used_url or url_qs, used_method or "GET", r.status_code, data)

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
                    logging.getLogger("auth").warning("change_workspace: no access token in response")
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

                try:
                    self._save_auth()
                except Exception:
                    pass

                try:
                    settings = load_settings()
                    settings["workspace_id"] = workspace_id
                    save_settings(settings)
                except Exception:
                    pass

                logging.getLogger("auth").info("change_workspace: workspace switched")
                return True
            except requests.RequestException as e:
                logging.getLogger("auth").warning("change_workspace: exception: %s", e)
                return False

        return False

    def _cached_get(self, key: str):
        it = self.cache.get(key)
        if not it: return None
        ts, data = it
        if (time.time() - ts) < CACHE_TTL_SEC: return data
        return None

    def list_folders(self, project_id: int | str, force: bool = False):
        """List folders in a project. Auto-retries once on 401."""
        key = f"tree:{project_id}"
        
        # Clear cache entry if force=True
        if force:
            self.cache.pop(key, None)
        
        if not force:
            cached = self._cached_get(key)
            if cached is not None: 
                return cached
        
        if not self.token: 
            return []
        
        url = build_url(self.base_url, FOLDER_LIST_PATH, project_id=project_id)
        for attempt in range(2):
            try:
                r = requests.get(url, headers=self._headers(), timeout=20)
                if r.status_code == 401:
                    if attempt == 0 and self._handle_401():
                        continue
                        return []
                r.raise_for_status()
                data = r.json()
                _log_api_response(url, "GET", r.status_code, data)
                if isinstance(data, list):
                    self.cache[key] = (time.time(), data)
                    return data
                return []
            except requests.RequestException:
                return []
        return []

    def list_folders_result(self, project_id: int | str, force: bool = False) -> 'ApiResult':
        """Like list_folders but returns ApiResult to distinguish errors from empty results.

        Errors: session_expired, no_auth, forbidden, server_error, connection_lost, invalid_response.
        Success: ok=True with data=list (may be empty for a genuine empty project).
        Cache is only written on success; error results are never cached.
        """
        key = f"tree:{project_id}"

        if force:
            self.cache.pop(key, None)
        else:
            cached = self._cached_get(key)
            if cached is not None:
                return ApiResult(ok=True, data=cached)

        if not self.token:
            return ApiResult(ok=False, error='no_auth')

        url = build_url(self.base_url, FOLDER_LIST_PATH, project_id=project_id)
        last_error = 'connection_lost'

        for attempt in range(2):
            try:
                r = requests.get(url, headers=self._headers(), timeout=20)

                if r.status_code == 401:
                    if attempt == 0:
                        if self._handle_401():
                            continue
                    return ApiResult(ok=False, error='session_expired')

                if r.status_code == 403:
                    return ApiResult(ok=False, error='forbidden')

                if r.status_code == 404:
                    return ApiResult(ok=False, error='forbidden')

                if r.status_code == 429:
                    if attempt == 0:
                        import time as _time
                        _time.sleep(1)
                        continue
                    return ApiResult(ok=False, error='server_error')

                if r.status_code >= 500:
                    last_error = 'server_error'
                    if attempt == 0:
                        continue
                    return ApiResult(ok=False, error='server_error')

                if 400 <= r.status_code < 500:
                    return ApiResult(ok=False, error='invalid_response')

                r.raise_for_status()

                try:
                    data = r.json()
                except (ValueError, TypeError):
                    return ApiResult(ok=False, error='invalid_response')

                _log_api_response(url, "GET", r.status_code, data)

                if isinstance(data, list):
                    self.cache[key] = (time.time(), data)
                    return ApiResult(ok=True, data=data)

                if isinstance(data, dict):
                    if data.get("success") is False:
                        msg = str(data.get("message", ""))[:200]
                        _API_LOG.warning("list_folders_result: success=false project=%s msg=%s", project_id, msg)
                        return ApiResult(ok=False, error='server_error')
                    for _wrapper in ("data", "folders", "items"):
                        inner = data.get(_wrapper)
                        if isinstance(inner, list):
                            self.cache[key] = (time.time(), inner)
                            return ApiResult(ok=True, data=inner)
                    return ApiResult(ok=False, error='invalid_response')

                return ApiResult(ok=False, error='invalid_response')

            except (requests.Timeout, requests.ConnectionError):
                last_error = 'connection_lost'
                if attempt == 0:
                    continue
                return ApiResult(ok=False, error='connection_lost')

            except requests.RequestException:
                return ApiResult(ok=False, error='connection_lost')

        return ApiResult(ok=False, error=last_error)

    def get_document_types(self) -> dict:
        """Get document types mapping from the API.

        Endpoint: GET /api/document/types

        Returns:
            Dict like {"1": "BIM", "2": "BOP", ...} (keys may be str or int)
        """
        if not self.token:
            return {}

        url = build_url(self.base_url, DOCUMENT_TYPES_PATH)
        for attempt in range(2):
            try:
                r = requests.get(url, headers=self._headers(), timeout=12)
                if r.status_code == 401:
                    if attempt == 0 and self._handle_401():
                        continue
                    return {}
                r.raise_for_status()
                data = r.json()
                _log_api_response(url, "GET", r.status_code, data)

                if isinstance(data, dict) and isinstance(data.get("data"), dict):
                    return data.get("data") or {}

                # Some deployments return mapping directly.
                if isinstance(data, dict) and data and all(isinstance(v, str) for v in data.values()):
                    return data

                return {}
            except requests.RequestException:
                return {}
            except Exception:
                return {}
        return {}
    def get_document_details(self, document_id: int | str) -> dict | None:
        """Get document details by ID, returning a normalized flat dict."""
        if not self.token:
            return None
        doc_id = self._stringify_id(document_id)
        if not doc_id:
            return None
        
        url = build_url(self.base_url, DOCUMENT_DETAILS_PATH, document_id=doc_id)
        try:
            r = requests.get(url, headers=self._headers(), timeout=20)
            if r.status_code == 401:
                if self._handle_401():
                    r = requests.get(url, headers=self._headers(), timeout=20)
                else:
                    return None
            r.raise_for_status()
            data = r.json()
            _log_api_response(url, "GET", r.status_code, data)
            if not isinstance(data, dict):
                return None
            
            # Unwrap common API response wrappers
            for wrapper_key in ["data", "document", "item", "result", "doc"]:
                if wrapper_key in data and isinstance(data[wrapper_key], dict):
                    data = data[wrapper_key]
                    break
            
            # Normalize field names to match expected keys in FileDetailsDialog
            normalized = {}
            # Preserve existing valid fields
            for key in [
                "id", "originalName", "fileName", "name", "version",
                "folderId", "documentType", "documentTypeId", "document_type_id",
                "type", "size", "status", "fileUid", "documentId",
            ]:
                if key in data:
                    normalized[key] = data[key]
            
            # Normalize creation time fields
            for src_key in ["createTime", "createdAt", "created", "created_ts"]:
                if src_key in data and "createTime" not in normalized:
                    normalized["createTime"] = data[src_key]
                    break
            
            # Normalize modification time fields
            for src_key in ["modifTime", "updatedAt", "updated_at", "modifiedDate", "modified_ts"]:
                if src_key in data and "modifTime" not in normalized:
                    normalized["modifTime"] = data[src_key]
                    break
            
            # Normalize creator fields
            for src_key in ["createdBy", "created_by", "creator", "author"]:
                if src_key in data and "createdBy" not in normalized:
                    normalized["createdBy"] = data[src_key]
                    break
            
            # Normalize modifier fields
            for src_key in ["modifiedBy", "modified_by", "updater"]:
                if src_key in data and "modifiedBy" not in normalized:
                    normalized["modifiedBy"] = data[src_key]
                    break
            
            # Normalize size field
            for src_key in ["size", "file_size", "fileSize"]:
                if src_key in data and "size" not in normalized:
                    normalized["size"] = data[src_key]
                    break
            
            # Normalize name fields
            for src_key in ["originalName", "title", "filename", "fileName", "file_name", "name"]:
                if src_key in data and "originalName" not in normalized:
                    normalized["originalName"] = data[src_key]
                    break

            # Normalize document type fields
            for src_key in ["documentTypeId", "document_type_id", "documentType", "document_type", "typeId"]:
                if src_key in data and "documentTypeId" not in normalized:
                    normalized["documentTypeId"] = data[src_key]
                    break

            # Keep the original payload too so callers can use additional fields
            for k, v in data.items():
                if k not in normalized:
                    normalized[k] = v
            
            return normalized
        except requests.RequestException:
            return None

    def get_document_versions(self, document_id: int | str, force: bool = False) -> list | dict:
        """Get document versions by ID.

        Args:
            document_id: Document ID (int or str)
            force: If True, bypass cache and fetch fresh data

        Returns:
            List of versions or dict with 'versions' key and 'file_name' metadata
        """
        if not self.token:
            return []
        doc_id = self._stringify_id(document_id)
        if not doc_id:
            return []

        cache_key = f"docver:{doc_id}"

        if force:
            self.cache.pop(cache_key, None)
        else:
            cached = self._cached_get(cache_key)
            if cached is not None:
                return cached

        url = build_url(self.base_url, DOCUMENT_VERSIONS_PATH, document_id=doc_id)
        params = {}
        if self.selected_workspace_id:
            params["workspaceId"] = self.selected_workspace_id
        
        for attempt in range(2):
            try:
                r = requests.get(url, headers=self._headers(), params=params if params else None, timeout=12)
                if r.status_code == 401:
                    if attempt == 0 and self._handle_401():
                        continue
                    return []
                r.raise_for_status()
                data = r.json()
                _log_api_response(url, "GET", r.status_code, data)
                
                if isinstance(data, dict):
                    result = {
                        "file_name": data.get("file_name") or data.get("fileName") or "",
                        "versions": list(data.get("versions") or data.get("items") or []),
                    }
                elif isinstance(data, list):
                    result = {"file_name": "", "versions": data}
                else:
                    result = {"file_name": "", "versions": []}
                
                self.cache[cache_key] = (time.time(), result)
                return result
            except requests.RequestException:
                return []
        return []

    def list_file_versions(self, file_id: int | str, force: bool = False) -> list | None:
        """List all versions of a file via POST /api/versions/list/{fileId}.

        Returns a list of normalized version dicts with keys:
          version_id, version_number, file_name, created_by, created_ts,
          shared, status, _raw

        Return values:
          list — successful API response (may be [] if no versions)
          None — API/network/parse error or success:false
        """
        if not self.token:
            return None
        fid = self._stringify_id(file_id)
        if not fid:
            return None

        cache_key = f"versions:{fid}"
        if force:
            self.cache.pop(cache_key, None)
        else:
            cached = self._cached_get(cache_key)
            if cached is not None:
                return cached

        url = build_url(self.base_url, VERSIONS_LIST_PATH, file_id=fid)
        payload = {
            "filters": [],
            "sorts": [],
            "page": 1,
            "size": 25,
        }
        for attempt in range(2):
            try:
                r = requests.post(url, headers=self._headers(), json=payload, timeout=12)
                if r.status_code == 401:
                    if attempt == 0 and self._handle_401():
                        continue
                    _API_LOG.warning("list_file_versions: 401 for file_id=%s, refresh failed", fid)
                    return None
                if r.status_code in (403, 404, 500):
                    _API_LOG.warning("list_file_versions: HTTP %d for file_id=%s", r.status_code, fid)
                    return None
                r.raise_for_status()
                try:
                    data = r.json()
                except (ValueError, TypeError):
                    _API_LOG.warning("list_file_versions: invalid JSON for file_id=%s", fid)
                    return None
                _log_api_response(url, "POST", r.status_code, data)

                if isinstance(data, dict):
                    if data.get("success") is False:
                        msg = data.get("message", "")
                        _API_LOG.warning("list_file_versions: success=false for file_id=%s message=%s", fid, str(msg)[:200])
                        return None
                    response_data = data.get("data")
                    if isinstance(response_data, dict):
                        raw_list = response_data.get("items") or []
                    elif isinstance(response_data, list):
                        raw_list = response_data
                    elif response_data is None:
                        raw_list = []
                    else:
                        _API_LOG.warning("list_file_versions: unexpected data type for file_id=%s", fid)
                        return None
                elif isinstance(data, list):
                    raw_list = data
                else:
                    _API_LOG.warning("list_file_versions: unexpected response type=%s for file_id=%s", type(data).__name__, fid)
                    return None

                normalized = []
                for v in raw_list:
                    if not isinstance(v, dict):
                        continue
                    shared_val = v.get("shared")
                    if shared_val is True:
                        shared_norm = True
                    elif isinstance(shared_val, str) and shared_val.lower() == "true":
                        shared_norm = True
                    else:
                        shared_norm = False
                    normalized.append({
                        "version_id": v.get("versionId") or v.get("version_id") or v.get("id"),
                        "version_number": v.get("versionNumber") or v.get("version_number") or v.get("version") or v.get("versionId"),
                        "file_name": v.get("fileName") or v.get("file_name") or "",
                        "created_by": v.get("createdBy") or v.get("created_by") or "",
                        "modified_by": v.get("modifiedBy") or v.get("modified_by") or "",
                        "created_ts": v.get("createdTs") or v.get("created_ts") or v.get("createTime") or v.get("createdAt") or "",
                        "shared": shared_norm,
                        "status": v.get("status") or "",
                        "_raw": v,
                    })

                self.cache[cache_key] = (time.time(), normalized)
                return normalized
            except requests.RequestException as exc:
                _API_LOG.warning("list_file_versions: network error for file_id=%s: %s", fid, exc)
                return None
        return None

    def download_document_version(self, version_id: int | str, filename: str, progress_cb: Optional[Callable[[int, int], None]] = None) -> str:
        """Download a specific document version via GET /api/document/download/{versionId}?isVersion=true.

        Args:
            version_id: Version ID (not file/document ID)
            filename: Name to save the file as
            progress_cb: Optional callback(done, total) for progress updates

        Returns:
            Full path to downloaded file in a temp directory, or empty string on failure.
        """
        if not self.token:
            return ""
        vid = self._stringify_id(version_id)
        if not vid:
            return ""

        tmp_dir = os.path.join(tempfile.gettempdir(), "larix_nexus_versions")
        try:
            os.makedirs(tmp_dir, exist_ok=True)
        except Exception:
            tmp_dir = tempfile.gettempdir()

        safe = _sanitize_filename(filename or f"version_{vid}.bin")
        filepath = os.path.join(tmp_dir, safe)
        url = build_url(self.base_url, DOCUMENT_DOWNLOAD_PATH, document_id=vid)
        params = {"isVersion": "true"}

        def _check_error_response(resp) -> bool:
            ct = (resp.headers.get("Content-Type") or "").lower()
            if "application/json" in ct:
                _API_LOG.warning(
                    "download_document_version: JSON response rejected for version_id=%s status=%d content_type=%s",
                    vid, resp.status_code, ct,
                )
                return True
            return False

        try:
            with requests.get(url, headers=self._headers(), params=params, stream=True, timeout=60) as r:
                if r.status_code == 401:
                    if self._handle_401():
                        with requests.get(url, headers=self._headers(), params=params, stream=True, timeout=60) as r2:
                            if r2.status_code in (403, 404, 500):
                                _API_LOG.warning("download_document_version: HTTP %d for version_id=%s", r2.status_code, vid)
                                return ""
                            r2.raise_for_status()
                            ct2 = (r2.headers.get("Content-Type") or "").lower()
                            if "application/json" in ct2:
                                _API_LOG.warning("download_document_version: JSON response rejected for version_id=%s status=%d content_type=%s", vid, r2.status_code, ct2)
                                return ""
                            total = int(r2.headers.get("Content-Length") or 0)
                            done = 0
                            with open(filepath, "wb") as f:
                                for part in r2.iter_content(chunk_size=256 * 1024):
                                    if not part:
                                        continue
                                    f.write(part)
                                    if progress_cb and total:
                                        done += len(part)
                                        progress_cb(done, total)
                    else:
                        _API_LOG.warning("download_document_version: 401 for version_id=%s, refresh failed", vid)
                        return ""
                elif r.status_code in (403, 404, 500):
                    _API_LOG.warning("download_document_version: HTTP %d for version_id=%s", r.status_code, vid)
                    return ""
                else:
                    r.raise_for_status()
                    if _check_error_response(r):
                        return ""
                    _log_api_response(url, "GET", r.status_code, {"version_id": vid, "isVersion": True, "content_length": r.headers.get("Content-Length", 0)})
                    total = int(r.headers.get("Content-Length") or 0)
                    done = 0
                    with open(filepath, "wb") as f:
                        for part in r.iter_content(chunk_size=256 * 1024):
                            if not part:
                                continue
                            f.write(part)
                            if progress_cb and total:
                                done += len(part)
                                progress_cb(done, total)

            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                return filepath
            if os.path.exists(filepath):
                os.remove(filepath)
            return ""
        except requests.RequestException as exc:
            _API_LOG.warning("download_document_version: network error for version_id=%s: %s", vid, exc)
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except Exception:
                    pass
            return ""
        except Exception:
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except Exception:
                    pass
            return ""

    def get_folder_details(self, folder_id: int | str, force: bool = False) -> dict | None:
        """Get folder details by ID, returning a normalized flat dict.

        Args:
            folder_id: Folder ID (int or str)
            force: If True, bypass cache and fetch fresh data
        """
        if not self.token:
            return None
        fid = self._stringify_id(folder_id)
        if not fid:
            return None

        if force:
            self.cache.pop(f"folder:{fid}", None)

        url = build_url(self.base_url, FOLDER_DETAILS_PATH, folder_id=fid)
        try:
            r = requests.get(url, headers=self._headers(), timeout=20)
            if r.status_code == 401:
                if self._handle_401():
                    r = requests.get(url, headers=self._headers(), timeout=20)
                else:
                    return None
            r.raise_for_status()
            data = r.json()
            _log_api_response(url, "GET", r.status_code, data)
            if not isinstance(data, dict):
                return None
            
            for wrapper_key in ["data", "folder", "item", "result", "doc"]:
                if wrapper_key in data and isinstance(data[wrapper_key], dict):
                    data = data[wrapper_key]
                    break
            
            normalized = {}
            for key in ["id", "name", "title", "projectId", "parentFolderId", "type"]:
                if key in data:
                    normalized[key] = data[key]
            
            for src_key in ["createTime", "createdAt", "created", "created_ts"]:
                if src_key in data and "createTime" not in normalized:
                    normalized["createTime"] = data[src_key]
                    break
            
            for src_key in ["modifTime", "updatedAt", "updated_at", "modifiedDate", "modified_ts"]:
                if src_key in data and "modifTime" not in normalized:
                    normalized["modifTime"] = data[src_key]
                    break
            
            for src_key in ["createdBy", "created_by", "creator", "author"]:
                if src_key in data and "createdBy" not in normalized:
                    normalized["createdBy"] = data[src_key]
                    break
            
            for src_key in ["modifiedBy", "modified_by", "updater"]:
                if src_key in data and "modifiedBy" not in normalized:
                    normalized["modifiedBy"] = data[src_key]
                    break
            
            for src_key in ["name", "title"]:
                if src_key in data and "name" not in normalized:
                    normalized["name"] = data[src_key]
                    break

            # Preserve folder contents for callers (list_files_result method 2, post-upload verify).
            for key in ("children", "files", "documents", "items", "content", "folders"):
                if key in data and key not in normalized:
                    normalized[key] = data[key]
            
            return normalized
        except requests.RequestException:
            return None

    def list_documents_in_folder(self, folder_id: int | str, force: bool = False) -> list:
        """Get list of documents in a specific folder.

        Args:
            folder_id: Folder ID (int or str)
            force: If True, bypass cache and fetch fresh data

        Returns:
            List of document dicts or empty list on error
        """
        self._last_list_documents_error = None
        if not self.token:
            self._last_list_documents_error = "not_authenticated"
            return []
        fid = self._stringify_id(folder_id)
        if not fid:
            self._last_list_documents_error = "invalid_folder_id"
            return []

        cache_key = f"folder_docs:{fid}"

        if force:
            self.cache.pop(cache_key, None)
        else:
            cached = self._cached_get(cache_key)
            if cached is not None:
                print(f"[API DEBUG] list_documents_in_folder({fid}) from cache, items={len(cached)}")
                return cached

        url = build_url(self.base_url, DOCUMENT_LIST_PATH, folder_id=fid)
        try:
            r = requests.get(url, headers=self._headers(), timeout=20)
            if r.status_code == 401:
                if self._handle_401():
                    r = requests.get(url, headers=self._headers(), timeout=20)
                else:
                    return []
            r.raise_for_status()
            data = r.json()
            _log_api_response(url, "GET", r.status_code, data)
            print(f"[API DEBUG] list_documents_in_folder({fid}) type={type(data).__name__}")

            result = []
            if isinstance(data, list):
                result = data
            elif isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
                result = data["data"]
            elif isinstance(data, dict) and "documents" in data and isinstance(data["documents"], list):
                result = data["documents"]
            elif isinstance(data, dict) and "items" in data and isinstance(data["items"], list):
                result = data["items"]
            else:
                print(f"[API DEBUG] list_documents_in_folder({fid}) unexpected format, keys={list(data.keys()) if isinstance(data, dict) else 'N/A'}")
                self._last_list_documents_error = "unexpected_response_format"
                return []

            self.cache[cache_key] = (time.time(), result)
            print(f"[API DEBUG] list_documents_in_folder({fid}) cached, items={len(result)}")
            return result
        except requests.RequestException as e:
            print(f"[API DEBUG] list_documents_in_folder({fid}) error: {e}")
            self._last_list_documents_error = str(e)
            return []

    _FOLDER_TREE_TYPES = frozenset({"folder", "dir", "directory", "папка"})

    def _find_folder_node_in_tree(self, tree, target_id: str):
        """Find folder node by id; ignore file nodes with the same id (API id collision)."""
        if not isinstance(tree, list):
            return None
        for item in tree:
            if not isinstance(item, dict):
                continue
            if self._stringify_id(item.get("id")) == target_id:
                typ = str(item.get("type") or "").lower()
                if typ in self._FOLDER_TREE_TYPES:
                    return item
            children = item.get("children") or item.get("folders") or []
            found = self._find_folder_node_in_tree(children, target_id)
            if found:
                return found
        return None

    def list_files(self, folder_id: int | str, project_id: int | str | None = None) -> list:
        """List files in a folder.
        
        This function now tries two methods to get files:
        1. Get project tree and find folder in it (preferred, works correctly)
        2. Use get_folder_details directly (fallback, may not return files)

        Args:
            folder_id: Folder ID (int or str)
            project_id: Project ID (optional, but strongly recommended for method 1)

        Returns:
            List of file/directory dicts or empty list on error
        """
        folder_id_str = self._stringify_id(folder_id)
        if not folder_id_str:
            _api_dbg("list_files: invalid folder_id=%r", folder_id)
            return []

        # Method 1: Try to get files from project tree (works like sync engine)
        if project_id:
            try:
                _api_dbg("list_files: method1 list_folders project_id=%s folder_id=%s", project_id, folder_id_str)
                folders_tree = self.list_folders(project_id, force=True)
                if folders_tree:
                    folder_node = self._find_folder_node_in_tree(folders_tree, folder_id_str)
                    if folder_node:
                        children = folder_node.get("children") or folder_node.get("files") or []
                        if isinstance(children, list):
                            _api_dbg("list_files: method1 success items=%s", len(children))
                            sync_log("list_files: Method 1 - found {} items from project tree", len(children))
                            return children
                        else:
                            _api_dbg("list_files: method1 children not list type=%s", type(children))
                    else:
                        _api_dbg("list_files: method1 folder not found in tree")
                else:
                    _api_dbg("list_files: method1 list_folders empty")
            except Exception as e:
                _API_LOG.warning("list_files: method1 error: %s", e)
                sync_exc("list_files Method 1 error")

        # Method 2: Fallback to get_folder_details (original method)
        _api_dbg("list_files: method2 get_folder_details folder_id=%s", folder_id_str)
        folder_data = self.get_folder_details(folder_id_str)

        if not isinstance(folder_data, dict):
            _api_dbg("list_files: method2 folder_data not dict folder_id=%s type=%s", folder_id_str, type(folder_data))
            sync_log("list_files: Method 2 - folder_data is not a dict for folder_id={}", folder_id_str)
            return []

        _api_dbg("list_files: method2 folder_id=%s keys=%s", folder_id_str, list(folder_data.keys()))
        sync_log("list_files: Method 2 - folder_id={}, folder_data keys={}", folder_id_str, list(folder_data.keys()))

        # Check all possible field names that might contain files
        for field_name in ["children", "files", "documents", "items", "content", "folders"]:
            if field_name in folder_data:
                value = folder_data[field_name]
                _api_dbg(
                    "list_files: method2 field=%s type=%s len=%s",
                    field_name,
                    type(value),
                    (len(value) if isinstance(value, (list, dict)) else "N/A"),
                )

        # Extract files/children from folder data - check multiple possible field names
        children = (folder_data.get("children") or
                   folder_data.get("files") or
                   folder_data.get("documents") or
                   folder_data.get("items") or
                   folder_data.get("content") or
                   folder_data.get("folders") or [])

        if isinstance(children, list):
            _api_dbg("list_files: method2 success list items=%s", len(children))
            sync_log("list_files: Method 2 - found {} items in 'children'/'files'/'documents' list", len(children))
            return children

        # Sometimes data is returned as dict with IDs as keys
        if isinstance(folder_data, dict) and any(k.isdigit() for k in folder_data.keys()):
            result = list(folder_data.values())
            _api_dbg("list_files: method2 success dict items=%s", len(result))
            sync_log("list_files: Method 2 - found {} items as dict values", len(result))
            return result

        _api_dbg("list_files: both methods failed")
        sync_log("list_files: Both methods failed - no files found, returning empty list")
        return []

    def list_files_result(self, folder_id: int | str, project_id: int | str | None = None) -> 'ApiResult':
        """Like list_files but returns ApiResult to distinguish errors from empty results.

        Method 1 uses list_folders_result (with retry on auth/network errors).
        Method 2 uses get_folder_details (already has 401 retry).
        If both fail, returns ApiResult with the error from the primary method.
        Real empty folder or empty project returns ok=True, data=[].
        """
        folder_id_str = self._stringify_id(folder_id)
        if not folder_id_str:
            return ApiResult(ok=False, error='invalid_id')

        last_error = None

        if project_id:
            try:
                tree_result = self.list_folders_result(project_id, force=True)
                if not tree_result.ok:
                    last_error = tree_result.error
                else:
                    folders_tree = tree_result.data

                    if not folders_tree:
                        pid_str = self._stringify_id(project_id)
                        if folder_id_str == pid_str:
                            return ApiResult(ok=True, data=[])

                    if isinstance(folders_tree, list) and folders_tree:
                        folder_node = self._find_folder_node_in_tree(folders_tree, folder_id_str)
                        if folder_node:
                            children = folder_node.get("children") or folder_node.get("files") or []
                            if isinstance(children, list):
                                sync_log("list_files_result: Method 1 found {} items", len(children))
                                return ApiResult(ok=True, data=children)

                        pid_str = self._stringify_id(project_id)
                        if folder_id_str == pid_str:
                            return ApiResult(ok=True, data=[])
            except Exception:
                last_error = last_error or 'connection_lost'

        try:
            folder_data = self.get_folder_details(folder_id_str)
        except Exception:
            folder_data = None

        if isinstance(folder_data, dict):
            children = (folder_data.get("children") or
                       folder_data.get("files") or
                       folder_data.get("documents") or
                       folder_data.get("items") or
                       folder_data.get("content") or
                       folder_data.get("folders") or [])

            if isinstance(children, list):
                sync_log("list_files_result: Method 2 found {} items", len(children))
                return ApiResult(ok=True, data=children)

            if isinstance(folder_data, dict) and any(k.isdigit() for k in folder_data.keys()):
                result = list(folder_data.values())
                return ApiResult(ok=True, data=result)

            return ApiResult(ok=True, data=[])

        if last_error:
            return ApiResult(ok=False, error=last_error)
        return ApiResult(ok=False, error='connection_lost')

    def download_file(self, file_id: int | str, filename: str, progress_cb: Optional[Callable[[int, int], None]] = None, cloud_mtime: float | None = None) -> str:
        """Download file from cloud and save to DOWNLOAD_DIR.

        Args:
            file_id: Document ID to download
            filename: Name to save the file as
            progress_cb: Optional callback function(done, total) for progress updates
            cloud_mtime: Optional cloud modification time to set on downloaded file (Unix timestamp)

        Returns:
            Full path to downloaded file, or empty string on failure
        """
        if not self.token:
            return ""

        doc_id = self._stringify_id(file_id)
        if not doc_id:
            return ""

        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        safe = _sanitize_filename(filename or f"file_{doc_id}.bin")
        filepath = os.path.join(DOWNLOAD_DIR, safe)
        url = build_url(self.base_url, DOCUMENT_DOWNLOAD_PATH, document_id=doc_id)

        try:
            with requests.get(url, headers=self._headers(), stream=True, timeout=60) as r:
                r.raise_for_status()
                _log_api_response(url, "GET", r.status_code, {"filename": safe, "content_length": r.headers.get("Content-Length", 0)})
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                chunk = 256 * 1024
                with open(filepath, "wb") as f:
                    for part in r.iter_content(chunk_size=chunk):
                        if not part:
                            continue
                        f.write(part)
                        if progress_cb and total:
                            done += len(part)
                            progress_cb(done, total)

            if cloud_mtime is not None and cloud_mtime > 0:
                try:
                    os.utime(filepath, (cloud_mtime, cloud_mtime))
                except Exception as e:
                    print(f"[API DEBUG] Failed to set mtime on {filepath}: {e}")

            return filepath
        except requests.RequestException:
            return ""
        except Exception:
            return ""

    def write_file_to(self, file_id: int | str, out_fp, progress_cb=None, max_retries: int = 3) -> bool:
        """Stream file from API directly into a writable file-like object out_fp.
        Avoids saving to DOWNLOAD_DIR. Returns True on success.
        """
        if not self.token:
            return False
        doc_id = self._stringify_id(file_id)
        if not doc_id:
            return False
        url = build_url(self.base_url, DOCUMENT_DOWNLOAD_PATH, document_id=doc_id)

        for attempt in range(max_retries):
            try:
                with requests.get(url, headers=self._headers(), stream=True, timeout=60) as r:
                    # Handle 401 Unauthorized - try to refresh token and retry once
                    if r.status_code == 401 and attempt == 0:
                        sync_log("write_file_to: got 401, trying to refresh token...")
                        if self._handle_401():
                            continue
                        return False

                    r.raise_for_status()
                    _log_api_response(url, "GET", r.status_code, {"file_id": doc_id, "content_length": r.headers.get("Content-Length", 0)})
                    total = int(r.headers.get("Content-Length") or 0)
                    done = 0
                    chunk = 256 * 1024
                    for part in r.iter_content(chunk_size=chunk):
                        if not part:
                            continue
                        out_fp.write(part)
                        if progress_cb:
                            done += len(part)
                            if total > 0:
                                progress_cb(done, total)
                            else:
                                progress_cb(done, 0)
                return True
            except requests.Timeout:
                sync_log("write_file_to: timeout on attempt {}/{}", attempt + 1, max_retries)
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                return False
            except requests.RequestException as e:
                sync_log("write_file_to: request exception: {}", _network_error_message(e))
                return False
        return False

    def _post_multipart_with_fallback(self, url: str, *, file_field: str, filename: str, file_obj, metadata_field: str, metadata_json: str, content_type: str = DOCUMENT_UPLOAD_CONTENT_TYPE, timeout: int = 120, log_prefix: str = "upload"):
        """POST multipart with proxy-aware fallback for unstable environments."""
        headers = self._headers()
        files = {file_field: (filename, file_obj, content_type)}
        data = {metadata_field: metadata_json}

        try:
            return requests.post(url, headers=headers, files=files, data=data, timeout=timeout)
        except (requests.exceptions.ProxyError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as first_exc:
            sync_log("{}: native multipart failed ({})", log_prefix, type(first_exc).__name__)

            try:
                if file_obj and hasattr(file_obj, "seek"):
                    file_obj.seek(0)
            except Exception:
                pass

            try:
                session = requests.Session()
                session.trust_env = False
                return session.post(url, headers=headers, files=files, data=data, timeout=timeout)
            except requests.RequestException as second_exc:
                sync_log("{}: no-proxy multipart failed ({})", log_prefix, type(second_exc).__name__)

            try:
                if file_obj and hasattr(file_obj, "seek"):
                    file_obj.seek(0)
            except Exception:
                pass

            if MultipartEncoder is None:
                raise

            enc = MultipartEncoder(
                fields={
                    metadata_field: metadata_json,
                    file_field: (filename, file_obj, content_type),
                }
            )
            enc_headers = {**headers, "Content-Type": enc.content_type}
            return requests.post(url, headers=enc_headers, data=enc, timeout=timeout)

    def _build_streaming_upload_headers(self, headers: dict, body) -> dict:
        """Headers for toolbelt multipart: explicit Content-Length, no chunked TE."""
        out = {**dict(headers or {})}
        try:
            ct = getattr(body, "content_type", None) or ""
        except Exception:
            ct = ""
        if ct:
            out["Content-Type"] = ct
        for k in list(out.keys()):
            if isinstance(k, str) and k.lower() == "transfer-encoding":
                try:
                    del out[k]
                except Exception:
                    pass
        bl = 0
        try:
            bl = int(getattr(body, "len", 0) or 0)
        except Exception:
            bl = 0
        if bl > 0:
            out["Content-Length"] = str(bl)
        return out

    def _log_streaming_multipart_prepare(
        self,
        url: str,
        filename: str,
        file_size_bytes: int,
        body,
        enc_headers: dict,
        log_prefix: str,
        *,
        field_order: Optional[tuple] = None,
    ) -> None:
        """sync_log (large uploads) + DEBUG_API duplicate; never log Authorization value."""
        fs = int(file_size_bytes or 0)
        if fs < _LARGE_STREAMING_UPLOAD_LOG_BYTES and not _API_DEBUG:
            return
        safe_url = _safe_url_for_api_log(url)
        body_cls = type(body).__name__
        bl = 0
        try:
            bl = int(getattr(body, "len", 0) or 0)
        except Exception:
            bl = 0
        ct = enc_headers.get("Content-Type") or ""
        hdr_cl = enc_headers.get("Content-Length")
        prepared_cl = None
        prepared_te = None
        try:
            pr = requests.Session().prepare_request(
                requests.Request("POST", url, headers=enc_headers, data=body)
            )
            prepared_cl = pr.headers.get("Content-Length")
            prepared_te = pr.headers.get("Transfer-Encoding")
        except Exception:
            pass
        has_auth = bool(enc_headers.get("Authorization"))
        fo = repr(list(field_order)) if field_order else "[]"
        sync_log(
            "{} upload_multipart_prepare field_order={} filename={} file_size_bytes={} body_class={} body.len={} "
            "content_type={} header_content_length={} prepared_content_length={} "
            "prepared_transfer_encoding={} has_authorization_header={} url={}",
            log_prefix,
            fo,
            repr(filename),
            fs,
            body_cls,
            bl,
            repr(ct),
            repr(hdr_cl),
            repr(prepared_cl),
            repr(prepared_te),
            has_auth,
            safe_url,
            component="API",
            op="upload_prepare",
        )
        _api_dbg(
            "%s: streaming multipart url=%s field_order=%s filename=%r file_size_bytes=%s body.len=%s "
            "header_cl=%s prepared_cl=%s prepared_te=%s",
            log_prefix,
            safe_url,
            fo,
            filename,
            fs,
            bl,
            hdr_cl,
            prepared_cl,
            prepared_te,
        )

    def _send_streaming_multipart_request(
        self,
        url: str,
        enc_headers: dict,
        body,
        timeout: float,
        trust_env: bool,
        file_size_bytes: int,
    ):
        """Large uploads: Session + PreparedRequest + send (web-like CL). Small: requests.post."""
        fs = int(file_size_bytes or 0)
        if fs >= _LARGE_STREAMING_UPLOAD_SESSION_BYTES:
            sess = requests.Session()
            sess.trust_env = trust_env
            req = requests.Request("POST", url, headers=enc_headers, data=body)
            prepped = sess.prepare_request(req)
            if _env_bool("LARIX_UPLOAD_DIAG_ORIGIN", False):
                try:
                    base = str(self.base_url).rstrip("/")
                    prepped.headers["Origin"] = base
                    prepped.headers["Referer"] = base + "/"
                except Exception:
                    pass
            for hk in list(prepped.headers.keys()):
                if isinstance(hk, str) and hk.lower() == "transfer-encoding":
                    try:
                        del prepped.headers[hk]
                    except Exception:
                        pass
            return sess.send(prepped, timeout=timeout)
        if not trust_env:
            s = requests.Session()
            s.trust_env = False
            return s.post(url, headers=enc_headers, data=body, timeout=timeout)
        return requests.post(url, headers=enc_headers, data=body, timeout=timeout)

    def _post_multipart_streaming_encoder(
        self,
        url: str,
        *,
        file_field: str,
        filename: str,
        file_obj,
        metadata_field: str,
        metadata_json: str,
        content_type: str = DOCUMENT_UPLOAD_CONTENT_TYPE,
        timeout: int = 120,
        log_prefix: str = "upload",
        progress_cb: Optional[Callable[[int, int], None]] = None,
        file_size_bytes: int = 0,
    ):
        """Stream multipart with known total length (Content-Length), like browser uploads.

        Part order matches web FormData: ``metadata`` first, then ``file``.
        ``file_obj`` must be a real binary file object so MultipartEncoder can bound the file
        part; use ``MultipartEncoderMonitor`` + ``progress_cb`` for byte progress without
        wrapping the file (wrapping breaks encoder.len and forces chunked encoding).
        """
        if MultipartEncoder is None:
            raise RuntimeError("MultipartEncoder unavailable")

        def _build_enc():
            return MultipartEncoder(
                fields={
                    metadata_field: metadata_json,
                    file_field: (filename, file_obj, content_type),
                }
            )

        headers = self._headers()
        fs_arg = int(file_size_bytes or 0)
        part_order = (metadata_field, file_field)

        def _rewind_fileobj() -> None:
            try:
                if file_obj is not None and hasattr(file_obj, "seek"):
                    file_obj.seek(0)
            except Exception:
                pass

        def _body_for_post():
            enc = _build_enc()
            if progress_cb and MultipartEncoderMonitor is not None:

                def _mon_cb(monitor: Any) -> None:
                    try:
                        progress_cb(
                            int(getattr(monitor, "bytes_read", 0) or 0),
                            int(getattr(monitor, "len", 0) or 0),
                        )
                    except Exception:
                        pass

                return MultipartEncoderMonitor(enc, callback=_mon_cb)
            return enc

        try:
            body = _body_for_post()
            enc_headers = self._build_streaming_upload_headers(headers, body)
            self._log_streaming_multipart_prepare(
                url,
                filename,
                fs_arg,
                body,
                enc_headers,
                log_prefix,
                field_order=part_order,
            )
            return self._send_streaming_multipart_request(
                url, enc_headers, body, float(timeout), True, fs_arg
            )
        except (requests.exceptions.ProxyError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as first_exc:
            sync_log("{}: streaming multipart failed: {}", log_prefix, str(first_exc))
            _rewind_fileobj()
            try:
                body = _body_for_post()
                enc_headers = self._build_streaming_upload_headers(headers, body)
                self._log_streaming_multipart_prepare(
                    url,
                    filename,
                    fs_arg,
                    body,
                    enc_headers,
                    f"{log_prefix}:no_proxy",
                    field_order=part_order,
                )
                return self._send_streaming_multipart_request(
                    url, enc_headers, body, float(timeout), False, fs_arg
                )
            except requests.RequestException as second_exc:
                sync_log("{}: streaming multipart no-proxy failed: {}", log_prefix, str(second_exc))
                raise

    def upload_file(
        self,
        folder_id: int | str,
        local_path: str,
        filename: str,
        document_type_id: int | str | None = None,
        max_retries: int = 3,
        *,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> bool:
        """Upload a file to the specified folder.
        Multipart fields (same as web, **metadata part before file part**):
          - ``metadata``: JSON ``{"files":[{"fileName": "...", "documentType": "..."}]}``
          - ``file``: binary (``application/octet-stream``) + original filename
        Success: any 2xx. Response body is not required.
        After success, folder cache is invalidated. Stores last status in
        self._last_upload_status for logging by callers.

        Args:
            folder_id: Destination folder ID
            local_path: Local path to the file to upload
            filename: Name to use for the uploaded file
        document_type_id: Required selected type from /api/document/types.
            max_retries: Number of retry attempts on timeout (default 3)
            progress_cb: Optional ``(bytes_read, total_bytes)`` callback. When set and
                ``requests_toolbelt`` is available, upload uses ``MultipartEncoder`` +
                ``MultipartEncoderMonitor`` so the body has a known ``Content-Length`` (like the
                browser) and progress reflects bytes sent.

        Returns:
            True if successful, False otherwise
        """
        if not self.token:
            sync_log("upload_file: no token available")
            return False

        folder_id_str = self._stringify_id(folder_id)
        if not folder_id_str:
            sync_log("upload_file: invalid folder_id")
            return False

        if not os.path.exists(local_path):
            sync_log("upload_file: local file does not exist")
            return False

        url = build_url(self.base_url, DOCUMENT_UPLOAD_PATH, folder_id=folder_id_str)
        sync_log("upload_file: starting upload - folder_id={}, filename={}", folder_id_str, filename)

        try:
            setattr(self, "_last_upload_error", "")
            setattr(self, "_last_upload_transient", False)
        except Exception:
            pass

        for attempt in range(max_retries):
            status = 0
            try:
                # sanitize filename
                try:
                    safe_filename = _sanitize_filename(filename)
                except Exception:
                    safe_filename = (filename or "").strip()

                dt = document_type_id
                try:
                    if dt is None:
                        raise ValueError("document type is required")
                    dt = int(str(dt).strip())
                    if dt <= 0:
                        raise ValueError("document type must be positive")
                except Exception:
                    setattr(self, "_last_upload_error", "Не указан валидный тип документа для загрузки")
                    setattr(self, "_last_upload_body", "document_type=missing_or_invalid")
                    return False

                metadata_json = build_document_upload_metadata(safe_filename, dt)
                mime_type = mimetypes.guess_type(safe_filename)[0] or DOCUMENT_UPLOAD_CONTENT_TYPE

                sync_log(
                    "upload_file: attempt {}/{} url={} filename='{}' size={} mime={} documentType={} metadata={}",
                    attempt + 1,
                    max_retries,
                    url,
                    safe_filename,
                    os.path.getsize(local_path),
                    mime_type,
                    str(dt),
                    metadata_json,
                )

                try:
                    total_bytes = int(os.path.getsize(local_path))
                except Exception:
                    total_bytes = 0

                upload_timeout = _upload_request_timeout_sec(total_bytes)
                try:
                    sync_log(
                        "upload_file: size_bytes={} request_timeout_sec={:.0f}",
                        total_bytes,
                        float(upload_timeout),
                    )
                except Exception:
                    pass

                with open(local_path, "rb") as raw_f:
                    if progress_cb and MultipartEncoder is not None:
                        try:
                            r = self._post_multipart_streaming_encoder(
                                url,
                                file_field=DOCUMENT_UPLOAD_FILE_FIELD,
                                filename=safe_filename,
                                file_obj=raw_f,
                                metadata_field=DOCUMENT_UPLOAD_METADATA_FIELD,
                                metadata_json=metadata_json,
                                content_type=mime_type,
                                timeout=upload_timeout,
                                log_prefix="upload_file",
                                progress_cb=progress_cb,
                                file_size_bytes=total_bytes,
                            )
                        except RuntimeError:
                            r = self._post_multipart_with_fallback(
                                url,
                                file_field=DOCUMENT_UPLOAD_FILE_FIELD,
                                filename=safe_filename,
                                file_obj=raw_f,
                                metadata_field=DOCUMENT_UPLOAD_METADATA_FIELD,
                                metadata_json=metadata_json,
                                timeout=upload_timeout,
                                log_prefix="upload_file",
                            )
                    elif progress_cb:
                        file_obj = _UploadCountingReader(raw_f, total_bytes, progress_cb)
                        r = self._post_multipart_with_fallback(
                            url,
                            file_field=DOCUMENT_UPLOAD_FILE_FIELD,
                            filename=safe_filename,
                            file_obj=file_obj,
                            metadata_field=DOCUMENT_UPLOAD_METADATA_FIELD,
                            metadata_json=metadata_json,
                            content_type=mime_type,
                            timeout=upload_timeout,
                            log_prefix="upload_file",
                        )
                    else:
                        r = self._post_multipart_with_fallback(
                            url,
                            file_field=DOCUMENT_UPLOAD_FILE_FIELD,
                            filename=safe_filename,
                            file_obj=raw_f,
                            metadata_field=DOCUMENT_UPLOAD_METADATA_FIELD,
                            metadata_json=metadata_json,
                            content_type=mime_type,
                            timeout=upload_timeout,
                            log_prefix="upload_file",
                        )
                    status = int(r.status_code)
                    try:
                        setattr(self, "_last_upload_transient", False)
                    except Exception:
                        pass
                    sync_log("upload_file: response status={}", status)
                    sync_log("upload_file: response content length={}", len(r.content) if r.content else 0)
                    
                    response_data = None
                    try:
                        if r.content:
                            if not r.ok:
                                response_data = r.text[:1000]
                            else:
                                try:
                                    response_data = r.json()
                                except:
                                    response_data = r.text[:1000]
                        else:
                            response_data = {}
                        _log_api_response(url, "POST", status, response_data)
                    except Exception:
                        _log_api_response(url, "POST", status, r.text[:500])
                
                # Handle 401 Unauthorized - try to refresh token and retry once
                if status == 401 and attempt == 0:
                    sync_log("upload_file: got 401, trying to refresh token...")
                    if self._handle_401():
                        continue
                    else:
                        # Token refresh failed, logout
                        sync_log("upload_file: token refresh failed")
                        return False

                # store last status and body for external logging
                try:
                    setattr(self, "_last_upload_status", status)
                    body_trunc = r.text[:2048] if r.text else ""
                    setattr(self, "_last_upload_body", body_trunc)
                    # Also store parsed response for validation
                    setattr(self, "_last_upload_response", response_data)
                except Exception:
                    pass

                if 200 <= status < 300:
                    if not r.content:
                        setattr(self, "_last_upload_error", "Сервер вернул пустой ответ без подтверждения создания файла")
                        setattr(self, "_last_upload_body", f"status={status}; content_length=0")
                        return False
                    try:
                        response_data = r.json()
                    except ValueError as exc:
                        setattr(self, "_last_upload_error", "Сервер вернул некорректный JSON без подтверждения создания файла")
                        setattr(self, "_last_upload_body", f"status={status}; json_error={type(exc).__name__}")
                        return False

                    def _created_document_id(payload, success_context=False):
                        if isinstance(payload, dict):
                            if payload.get("success") is False:
                                return None
                            success_context = success_context or payload.get("success") is True
                            for field in ("id", "documentId", "fileUid", "fileId"):
                                value = payload.get(field)
                                if success_context and value not in (None, ""):
                                    return value
                            for field in ("data", "result", "document", "file", "fileInfo", "files"):
                                if field in payload:
                                    found = _created_document_id(payload[field], success_context)
                                    if found is not None:
                                        return found
                        elif isinstance(payload, list):
                            for item in payload:
                                found = _created_document_id(item, success_context)
                                if found is not None:
                                    return found
                        return None

                    created_id = _created_document_id(response_data)
                    if created_id is None:
                        setattr(self, "_last_upload_error", "Сервер не подтвердил создание файла: отсутствует идентификатор документа")
                        setattr(self, "_last_upload_body", f"status={status}; response_type={type(response_data).__name__}")
                        return False
                    sync_log("upload_file: response confirmed document id present")

                # Be strict - only 200-201 is success, not any 2xx
                # Also check if response contains valid file data
                ok = (200 <= status <= 201)
                if ok and response_data:
                    # Check if response indicates actual file was created
                    # Response should be array with file objects or object with file data
                    if isinstance(response_data, list) and response_data:
                        # List response - check first item has file-like structure
                        first_item = response_data[0]
                        if isinstance(first_item, dict):
                            success_flag = first_item.get("success")
                            has_id = bool(first_item.get("id") or first_item.get("fileUid") or first_item.get("documentId"))
                            has_name = bool(first_item.get("name") or first_item.get("originalName") or first_item.get("fileName"))
                            if success_flag is False:
                                ok = False
                            elif has_id or has_name or success_flag is True:
                                sync_log("upload_file: response has file structure - id={} name={}", 
                                         first_item.get("id") or first_item.get("documentId"), first_item.get("name") or first_item.get("originalName") or first_item.get("fileName"))
                            else:
                                sync_log("upload_file: WARNING - response list item missing id/name fields")
                    elif isinstance(response_data, dict):
                        # Object response - check for success flag or file data
                        if "data" in response_data:
                            data = response_data.get("data")
                            if isinstance(data, (list, dict)):
                                sync_log("upload_file: response has data field - {}", type(data).__name__)
                        elif "success" in response_data and not response_data["success"]:
                            sync_log("upload_file: WARNING - response success=false")
                            ok = False
                elif ok and not response_data:
                    sync_log("upload_file: empty response with successful status {}", status)
                
                sync_log("upload_file: upload {} - status={}, ok={}", "succeeded" if ok else "failed", status, ok)

                if ok:
                    try:
                        setattr(self, "_last_upload_error", "")
                        setattr(self, "_last_upload_transient", False)
                    except Exception:
                        pass
                    try:
                        # Invalidate any cached trees (folder/list is used for listing contents).
                        for k in list((self.cache or {}).keys()):
                            if isinstance(k, str) and k.startswith("tree:"):
                                try:
                                    self.cache.pop(k, None)
                                except Exception:
                                    pass
                        # Log response data for debugging
                        try:
                            response_data = r.json()
                            sync_log("upload_file: response data keys={}", list(response_data.keys()) if isinstance(response_data, dict) else type(response_data))
                            if isinstance(response_data, list) and response_data:
                                sync_log("upload_file: first item keys={}", list(response_data[0].keys()) if isinstance(response_data[0], dict) else type(response_data[0]))
                                item = response_data[0]
                                if isinstance(item, dict):
                                    sync_log("upload_file: id={}, fileUid={}", item.get("id"), item.get("fileUid"))
                        except Exception:
                            pass
                    except Exception:
                        pass
                    return ok
                elif not ok and 200 <= status < 300 and attempt < max_retries - 1:
                    sync_log("upload_file: retrying due to empty/invalid response, attempt {}/{}", attempt + 2, max_retries)
                    try:
                        _es = ""
                        try:
                            _es = (r.text or "")[:400]
                        except Exception:
                            _es = ""
                        setattr(self, "_last_upload_error", _http_error_message(status))
                    except Exception:
                        pass
                    time.sleep(1)
                    continue
                if not ok and (status == 429 or status >= 500) and attempt < max_retries - 1:
                    try:
                        _es = ""
                        try:
                            _es = (r.text or "")[:400]
                        except Exception:
                            _es = ""
                        setattr(self, "_last_upload_error", _http_error_message(status))
                    except Exception:
                        pass
                    delay = min(30.0, float(2 ** attempt))
                    sync_log(
                        "upload_file: retryable HTTP status={}, retry in {:.1f}s ({}/{})",
                        status,
                        delay,
                        attempt + 2,
                        max_retries,
                    )
                    time.sleep(delay)
                    continue
                if not ok:
                    try:
                        _es = ""
                        try:
                            _es = (r.text or "")[:400]
                        except Exception:
                            _es = ""
                        setattr(self, "_last_upload_error", _http_error_message(status))
                    except Exception:
                        pass
                return ok

            except requests.Timeout:
                sync_log("upload_file: timeout on attempt {}/{}", attempt + 1, max_retries)
                try:
                    setattr(self, "_last_upload_error", "Превышено время ожидания ответа сервера (timeout)")
                except Exception:
                    pass
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                # Final timeout - store status and return False
                try:
                    setattr(self, "_last_upload_status", 0)
                    setattr(self, "_last_upload_body", "Timeout")
                except Exception:
                    pass
                return False

            except requests.RequestException as e:
                sync_log(
                    "upload_file: request exception (attempt {}/{}): {}",
                    attempt + 1,
                    max_retries,
                    _network_error_message(e),
                )
                sync_exc("upload_file error")
                try:
                    setattr(self, "_last_upload_status", 0)
                    setattr(self, "_last_upload_body", "network error")
                    setattr(self, "_last_upload_error", _network_error_message(e))
                    setattr(
                        self,
                        "_last_upload_transient",
                        bool(is_transient_upload_network_error(e)),
                    )
                except Exception:
                    pass
                if attempt < max_retries - 1:
                    delay = min(30.0, float(2**attempt))
                    try:
                        sync_log("upload_file: network error, retry in {:.1f}s", delay)
                    except Exception:
                        pass
                    time.sleep(delay)
                    continue
                return False
            except Exception as e:
                sync_log("upload_file: unexpected exception ({})", type(e).__name__)
                sync_exc("upload_file unexpected error")
                try:
                    setattr(self, "_last_upload_status", status or 0)
                    setattr(self, "_last_upload_body", "unexpected error")
                    setattr(self, "_last_upload_error", "Ошибка при загрузке файла")
                    setattr(
                        self,
                        "_last_upload_transient",
                        bool(is_transient_upload_network_error(e)),
                    )
                except Exception:
                    pass
                if attempt < max_retries - 1:
                    delay = min(30.0, float(2**attempt))
                    time.sleep(delay)
                    continue
                return False

        return False

    def delete_document(self, document_id: int | str) -> bool:
        """Delete document from cloud by ID.

        Args:
            document_id: Document ID (int or str)

        Returns:
            True if deleted successfully, False otherwise
        """
        if not self.token:
            return False
        doc_id = self._stringify_id(document_id)
        if not doc_id:
            return False

        url = build_url(self.base_url, DOCUMENT_DELETE_PATH, document_id=doc_id)
        try:
            r = requests.delete(url, headers=self._headers(), timeout=20)
            _log_api_response(url, "DELETE", r.status_code, {"document_id": doc_id})

            if r.status_code == 401:
                if self._handle_401():
                    r = requests.delete(url, headers=self._headers(), timeout=20)
                    _log_api_response(url, "DELETE", r.status_code, {"document_id": doc_id, "retry": True})

            if r.status_code == 204:
                ok = True
            elif r.status_code == 200:
                ok = True
                # If backend uses JSON wrapper with success=false, treat as failure.
                try:
                    data = r.json()
                    if isinstance(data, dict) and data.get("success") is False:
                        ok = False
                except Exception:
                    ok = True
            else:
                ok = False

            if ok:
                # Invalidate caches that can keep the deleted file visible.
                try:
                    self.cache.pop(f"versions:{doc_id}", None)
                    self.cache.pop(f"docver:{doc_id}", None)
                    # Folder listings may contain this doc; clear broadly to avoid stale UI.
                    for k in list((self.cache or {}).keys()):
                        if isinstance(k, str) and (k.startswith("folder_docs:") or k.startswith("tree:")):
                            self.cache.pop(k, None)
                except Exception:
                    pass

            return bool(ok)
        except requests.RequestException:
            return False

    def delete_folder(self, folder_id: int | str) -> bool:
        """Delete folder from cloud by ID.

        Args:
            folder_id: Folder ID (int or str)

        Returns:
            True if deleted successfully, False otherwise
        """
        if not self.token:
            return False
        fid = self._stringify_id(folder_id)
        if not fid:
            return False

        url = build_url(self.base_url, FOLDER_DELETE_PATH, folder_id=fid)
        try:
            r = requests.delete(url, headers=self._headers(), timeout=20)
            _log_api_response(url, "DELETE", r.status_code, {"folder_id": fid})
            return r.status_code in (200, 204)
        except requests.RequestException:
            return False

    def move_document(self, document_id: int | str, dest_folder_id: int | str) -> bool:
        """Move document to another folder using PUT /api/document/move.

        Sends [{"documentId": ..., "targetFolderId": ...}] as JSON body.

        Args:
            document_id: Document ID to move
            dest_folder_id: Destination folder ID

        Returns:
            True if moved successfully, False otherwise
        """
        if not self.token:
            return False
        doc_id = self._stringify_id(document_id)
        if not doc_id:
            return False
        try:
            doc_id_int = int(doc_id)
        except (TypeError, ValueError):
            return False

        if dest_folder_id is None or dest_folder_id == "":
            return False
        dest_id = self._stringify_id(dest_folder_id)
        if not dest_id:
            return False
        try:
            dest_id_int = int(dest_id)
        except (TypeError, ValueError):
            return False

        url = build_url(self.base_url, DOCUMENT_MOVE_PATH)
        payload = build_document_move_payload(doc_id_int, dest_id_int)
        try:
            r = requests.put(url, headers={**self._headers(), "Content-Type": "application/json"}, json=payload, timeout=20)
            _log_api_response(url, "PUT", r.status_code, {"item_count": len(payload)})
            if r.status_code == 401:
                if self._handle_401():
                    r = requests.put(url, headers={**self._headers(), "Content-Type": "application/json"}, json=payload, timeout=20)
                    _log_api_response(url, "PUT", r.status_code, {"item_count": len(payload), "retry": True})
            if r.status_code in (200, 204):
                try:
                    data = r.json()
                except (ValueError, TypeError):
                    sync_log("move_document: invalid JSON in response, status={}", r.status_code, component="MOVE")
                    return False
                if isinstance(data, dict):
                    if data.get("success") is True:
                        ok = True
                    elif data.get("success") is False:
                        sync_log("move_document: API returned success=false", component="MOVE")
                        ok = False
                    else:
                        ok = True
                else:
                    ok = True

                if ok:
                    # Invalidate cached folder listings/trees so UI doesn't show stale placement.
                    try:
                        for k in list((self.cache or {}).keys()):
                            if isinstance(k, str) and (k.startswith("folder_docs:") or k.startswith("tree:")):
                                self.cache.pop(k, None)
                    except Exception:
                        pass

                return bool(ok)

            try:
                sync_log("move_document: FAILED status={}", r.status_code, component="MOVE")
            except Exception:
                pass
            return False
        except requests.RequestException:
            return False

    def move_documents(self, document_ids: list[int | str], dest_folder_id: int | str) -> bool:
        """Move multiple documents to another folder using PUT /api/document/move.

        Sends [{"documentId": ..., "targetFolderId": ...}, ...] as JSON body.

        Args:
            document_ids: List of document IDs to move
            dest_folder_id: Destination folder ID

        Returns:
            True if all moves were successful, False otherwise
        """
        if not self.token:
            return False
        if not document_ids:
            return False

        if dest_folder_id is None or dest_folder_id == "":
            return False
        dest_id = self._stringify_id(dest_folder_id)
        if not dest_id:
            return False
        try:
            dest_id_int = int(dest_id)
        except (TypeError, ValueError):
            return False

        normalized_ids = []
        for did in document_ids:
            sid = self._stringify_id(did)
            if not sid:
                return False
            try:
                normalized_ids.append(int(sid))
            except (TypeError, ValueError):
                return False

        if not normalized_ids:
            return False

        url = build_url(self.base_url, DOCUMENT_MOVE_PATH)
        payload = build_documents_move_payload(normalized_ids, dest_id_int)
        try:
            r = requests.put(url, headers={**self._headers(), "Content-Type": "application/json"}, json=payload, timeout=30)
            _log_api_response(url, "PUT", r.status_code, {"item_count": len(payload)})
            if r.status_code == 401:
                if self._handle_401():
                    r = requests.put(url, headers={**self._headers(), "Content-Type": "application/json"}, json=payload, timeout=30)
                    _log_api_response(url, "PUT", r.status_code, {"item_count": len(payload), "retry": True})
            if r.status_code in (200, 204):
                try:
                    data = r.json()
                except (ValueError, TypeError):
                    sync_log("move_documents: invalid JSON in response, status={}", r.status_code, component="MOVE")
                    return False
                if isinstance(data, dict):
                    if data.get("success") is True:
                        return True
                    if data.get("success") is False:
                        sync_log("move_documents: API returned success=false", component="MOVE")
                        return False
                return True
            try:
                sync_log("move_documents: FAILED status={}", r.status_code, component="MOVE")
            except Exception:
                pass
            return False
        except requests.RequestException:
            return False

    def check_folder_rights(self, folder_id: int | str) -> bool | None:
        """Check if current user has rights to move into a folder.

        GET /api/folder/check-rights/{folderId}

        Args:
            folder_id: Folder ID to check rights for

        Returns:
            True if move is allowed (success=True, data=True),
            False if move is explicitly denied (success=True, data=False or success=False),
            None on error or if rights could not be verified
        """
        if not self.token:
            return None
        fid = self._stringify_id(folder_id)
        if not fid:
            return None

        url = build_url(self.base_url, FOLDER_CHECK_RIGHTS_PATH, folder_id=fid)
        try:
            r = requests.get(url, headers=self._headers(), timeout=10)
            if r.status_code == 401:
                if self._handle_401():
                    r = requests.get(url, headers=self._headers(), timeout=10)
            if r.status_code == 200:
                try:
                    data = r.json()
                except (ValueError, TypeError):
                    sync_log("check_folder_rights: invalid JSON response", component="API")
                    return None
                if isinstance(data, dict):
                    success = data.get("success")
                    rights_data = data.get("data")
                    if success is True:
                        return bool(rights_data is True or rights_data)
                    if success is False:
                        return False
                    if success is None and rights_data is not None:
                        return bool(rights_data)
                return None
            if r.status_code in (403, 404, 500):
                sync_log("check_folder_rights: HTTP {}", r.status_code, component="API")
                return None
            return None
        except requests.RequestException:
            return None

    def create_folder(self, project_id: int | str, parent_id: int | str | None, name: str) -> int | str | None:
        """Create a new folder.

        Args:
            project_id: Project ID
            parent_id: Parent folder ID (optional)
            name: Folder name

        Returns:
            New folder ID if successful, None otherwise
        """
        if not self.token:
            return None

        url = build_url(self.base_url, FOLDER_ADD_PATH)
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json", "accept": "*/*"}
        payload = build_folder_create_payload(project_id, self._stringify_id(parent_id) if parent_id else None, name)
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=10)
            _log_api_response(url, "POST", r.status_code, payload)
            if r.status_code in (200, 201):
                try:
                    data = r.json()
                    return data.get("id") or data.get("Id") or True
                except Exception:
                    return True
        except requests.RequestException:
            pass
        return None

    def update_folder(self, folder_id: int | str, project_id: int | str, name: str, parent_folder_id: int | str | None) -> bool:
        """Update folder (rename or move).

        Args:
            folder_id: Folder ID to update
            project_id: Project ID
            name: Folder name
            parent_folder_id: New parent folder ID (for move operation)

        Returns:
            True if updated successfully, False otherwise
        """
        if not self.token:
            return False
        fid = self._stringify_id(folder_id)
        if not fid:
            return False

        url = build_url(self.base_url, FOLDER_UPDATE_PATH, folder_id=fid)
        # Root move should use parentFolderId=None (not project id).
        parent_norm = self._stringify_id(parent_folder_id)
        proj_norm = self._stringify_id(project_id)
        parent_payload = None if (not parent_norm or parent_norm == proj_norm) else parent_norm
        payload = build_folder_update_payload(fid, project_id, name, parent_payload)
        try:
            r = requests.put(url, headers={**self._headers(), "Content-Type": "application/json"}, json=payload, timeout=20)
            _log_api_response(url, "PUT", r.status_code, payload)
            return r.status_code in (200, 204)
        except requests.RequestException:
            return False

    def rename_folder(self, folder_id: int | str, new_name: str) -> bool:
        """Rename a folder.

        Args:
            folder_id: Folder ID to rename
            new_name: New folder name

        Returns:
            True if renamed successfully, False otherwise
        """
        if not self.token:
            return False
        fid = self._stringify_id(folder_id)
        if not fid:
            return False

        url = build_url(self.base_url, FOLDER_UPDATE_PATH, folder_id=fid)
        payload = build_folder_rename_payload(fid, new_name)
        try:
            r = requests.put(url, headers={**self._headers(), "Content-Type": "application/json"}, json=payload, timeout=20)
            _log_api_response(url, "PUT", r.status_code, payload)
            return r.status_code in (200, 204)
        except requests.RequestException:
            return False

    def rename_file(self, document_id: int | str, new_name: str) -> bool:
        """Rename a file/document.

        Args:
            document_id: Document ID to rename
            new_name: New document name

        Returns:
            True if renamed successfully, False otherwise
        """
        if not self.token:
            return False
        doc_id = self._stringify_id(document_id)
        if not doc_id:
            return False

        url = build_url(self.base_url, DOCUMENT_UPDATE_PATH, document_id=doc_id)
        payload = build_document_rename_payload(doc_id, new_name)
        try:
            r = requests.put(url, headers={**self._headers(), "Content-Type": "application/json"}, json=payload, timeout=20)
            try:
                resp_text = r.text[:500]
            except:
                resp_text = ""
            if r.status_code >= 400:
                sync_log("rename_file ERROR: status={}, url={}, payload={}, response={}", r.status_code, url, payload, resp_text, component="API", op="error")
            _log_api_response(url, "PUT", r.status_code, payload)
            return r.status_code in (200, 204)
        except requests.RequestException as e:
            sync_log("rename_file EXCEPTION: {}", str(e), component="API", op="error")
            return False

    def copy_folder(self, folder_id: int | str, dest_folder_id: int | str, new_name: str | None = None) -> int | str | None:
        """Copy folder to another folder.

        Args:
            folder_id: Source folder ID
            dest_folder_id: Destination folder ID
            new_name: Optional (ignored). Backend contract uses only ids.

        Returns:
            New folder ID if successful, None otherwise
        """
        if not self.token:
            return None
        src_id = self._stringify_id(folder_id)
        dest_id = self._stringify_id(dest_folder_id)
        if not src_id or not dest_id:
            return None

        url = build_url(self.base_url, FOLDER_COPY_PATH)
        try:
            # HAR contract:
            # POST /api/folder/copy {"sourceFolderIds":[...],"targetFolderId":...}
            payload = build_folder_copy_payload([src_id], dest_id)
            # Diagnostics (do not log headers/tokens).
            try:
                self._last_copy_folder_payload = dict(payload)
            except Exception:
                self._last_copy_folder_payload = payload
            r = requests.post(url, json=payload, headers=self._headers(), timeout=20)
            try:
                self._last_copy_folder_status = int(getattr(r, "status_code", 0) or 0)
            except Exception:
                self._last_copy_folder_status = 0
            try:
                self._last_copy_folder_body = (r.text or "")[:2048]
            except Exception:
                self._last_copy_folder_body = ""

            try:
                copy_log(
                    "[API] copy_folder: status={} url={} payload={} body={}",
                    getattr(r, "status_code", None),
                    url,
                    payload,
                    (getattr(self, "_last_copy_folder_body", "") or "")[:500],
                    component="API",
                )
            except Exception:
                pass
            try:
                sync_log(
                    "copy_folder: status={} url={} payload={} body={}",
                    getattr(r, "status_code", None),
                    url,
                    payload,
                    (getattr(self, "_last_copy_folder_body", "") or "")[:500],
                    component="API",
                    op="copy_folder",
                )
            except Exception:
                pass
            if r.status_code == 401:
                if self._handle_401():
                    r = requests.post(url, json=payload, headers=self._headers(), timeout=20)
                    try:
                        self._last_copy_folder_status = int(getattr(r, "status_code", 0) or 0)
                    except Exception:
                        self._last_copy_folder_status = 0
                    try:
                        self._last_copy_folder_body = (r.text or "")[:2048]
                    except Exception:
                        self._last_copy_folder_body = ""
                else:
                    return None

            if r.status_code in (200, 201, 204):
                if r.status_code == 204:
                    # HAR shows id in JSON body, but keep 204 as best-effort success.
                    return True

                try:
                    data = r.json()
                except Exception:
                    data = None

                if isinstance(data, dict):
                    try:
                        _log_api_response(url, "POST", r.status_code, data)
                    except Exception:
                        pass
                    if data.get("success") is False:
                        return None
                    ids = data.get("data")
                    if isinstance(ids, list) and ids:
                        return ids[0]

                # If backend returned something unexpected, don't claim success without id.
                return None

            return None
        except requests.RequestException as e:
            try:
                self._last_copy_folder_status = 0
                self._last_copy_folder_body = str(e)[:2048]
            except Exception:
                pass
            try:
                sync_log("copy_folder: exception {}", str(e), component="API", op="copy_folder", result="error")
            except Exception:
                pass
            return None

    def copy_document(self, document_id: int | str, dest_folder_id: int | str, new_name: str | None = None, document_type_id: int | str | None = None):
        """Copy document to another folder by downloading and uploading to destination."""
        from larix_nexus.utils.logging import sync_log
        from larix_nexus.utils.copy_logger import copy_log
        copy_log("[API] copy_document START: document_id={}, dest_folder_id={}, new_name={}", document_id, dest_folder_id, new_name, component="API")
        if not self.token:
            copy_log("[API] copy_document: NO TOKEN", component="API")
            return None

        doc_id = self._stringify_id(document_id)
        dest_id = self._stringify_id(dest_folder_id) if dest_folder_id else "0"
        copy_log("[API] copy_document: doc_id={}, dest_id={}", doc_id, dest_id, component="API")
        if not doc_id:
            copy_log("[API] copy_document: NO doc_id", component="API")
            return None

        tmp_path = None
        try:
            copy_log("[API] copy_document: Getting document details...", component="API")
            src_doc = self.get_document_details(doc_id)
            copy_log("[API] copy_document: src_doc={}", src_doc, component="API")
            if not src_doc:
                copy_log("[API] copy_document: NO src_doc", component="API")
                return None

            src_name = src_doc.get("originalName") or src_doc.get("name") or src_doc.get("file_name") or "file"
            if not new_name:
                new_name = src_name
            new_name = str(new_name)
            copy_log("[API] copy_document: final new_name={}", new_name, component="API")

            # Prefer an explicit/source type. If neither is usable, select a
            # server-confirmed type; never invent a fallback type for uploads.
            source_type = None
            for field in (
                "document_type_id",
                "documentTypeId",
                "documentType",
                "document_type",
                "fileTypeId",
            ):
                value = src_doc.get(field)
                if value not in (None, ""):
                    source_type = value
                    break
            candidate = document_type_id if document_type_id not in (None, "") else source_type
            try:
                document_type_id = int(str(candidate).strip())
                if document_type_id <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                document_type_id = None

            if document_type_id is None:
                available = self.get_document_types() or {}
                raw_ids = list(available.keys()) if isinstance(available, dict) else list(available or [])
                valid_ids = []
                for raw_id in raw_ids:
                    try:
                        value = int(str(raw_id).strip())
                    except (TypeError, ValueError):
                        continue
                    if value > 0 and value not in valid_ids:
                        valid_ids.append(value)
                if not valid_ids:
                    self._last_upload_error = "Не удалось определить валидный тип документа для копирования"
                    copy_log("[API] copy_document: no valid document type", component="API")
                    return False
                saved_id = None
                try:
                    saved_id = int(str(load_settings().get("last_document_type_id")).strip())
                except (AttributeError, TypeError, ValueError):
                    pass
                document_type_id = saved_id if saved_id in valid_ids else valid_ids[0]
                try:
                    settings = load_settings()
                    settings["last_document_type_id"] = document_type_id
                    save_settings(settings)
                except Exception:
                    pass
            copy_log("[API] copy_document: document_type_id={}", document_type_id, component="API")

            download_url = build_url(self.base_url, DOCUMENT_DOWNLOAD_PATH, document_id=doc_id)
            copy_log("[API] copy_document: downloading from {}", download_url, component="API")

            r = None
            try:
                r = requests.get(download_url, headers=self._headers(), stream=True, timeout=120)
                copy_log("[API] copy_document: download status_code={}", r.status_code, component="API")

                if r.status_code == 401:
                    copy_log("[API] copy_document: 401 - trying to handle", component="API")
                    if self._handle_401():
                        r = requests.get(download_url, headers=self._headers(), stream=True, timeout=120)
                    else:
                        copy_log("[API] copy_document: 401 - could not refresh token", component="API")
                        return None

                if r.status_code != 200:
                    copy_log("[API] copy_document: download FAILED with status={}", r.status_code, component="API")
                    return None

                r.raise_for_status()
                copy_log("[API] copy_document: download SUCCESS, content_length={}", r.headers.get('content-length', 'unknown'), component="API")
            except Exception as e:
                copy_log("[API] copy_document: DOWNLOAD ERROR: {}", str(e), component="API")
                import traceback
                copy_log("[API] copy_document: TRACEBACK: {}", traceback.format_exc(), component="API")
                return None

            if r is None:
                copy_log("[API] copy_document: ERROR - r is None after download", component="API")
                return None

            metadata_json = build_document_upload_metadata(new_name, document_type_id)

            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp_path = tmp.name
                copy_log("[API] copy_document: creating temp file {}", tmp_path, component="API")
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    tmp.write(chunk)
                tmp.flush()
                copy_log("[API] copy_document: temp file written", component="API")

            # Open file in binary mode for upload
            copy_log("[API] copy_document: opening temp file for upload", component="API")
            with open(tmp_path, 'rb') as upload_file:
                upload_url = build_url(self.base_url, DOCUMENT_UPLOAD_PATH, folder_id=dest_id)
                copy_log("[API] copy_document: uploading to {}", upload_url, component="API")
                try:
                    try:
                        _sz = int(os.path.getsize(tmp_path))
                    except Exception:
                        _sz = 0
                    _up_to = int(_upload_request_timeout_sec(_sz))
                    upload_r = self._post_multipart_with_fallback(
                        upload_url,
                        file_field=DOCUMENT_UPLOAD_FILE_FIELD,
                        filename=new_name,
                        file_obj=upload_file,
                        metadata_field=DOCUMENT_UPLOAD_METADATA_FIELD,
                        metadata_json=metadata_json,
                        timeout=_up_to,
                        log_prefix="copy_document.upload",
                    )
                except Exception as e:
                    copy_log("[API] copy_document: UPLOAD ERROR: {}", str(e), component="API")
                    import traceback
                    copy_log("[API] copy_document: TRACEBACK: {}", traceback.format_exc(), component="API")
                    return False
             
                copy_log("[API] copy_document: upload status_code={}", upload_r.status_code, component="API")
                try:
                    _log_api_response(upload_url, "POST", upload_r.status_code, upload_r.text[:500])
                except Exception:
                    pass

                if upload_r.status_code in (200, 201):
                    try:
                        data = upload_r.json()
                        copy_log("[API] copy_document: upload response data={}", data, component="API")
                        # API can return either a dict or a list[dict]
                        obj = None
                        if isinstance(data, dict):
                            obj = data
                        elif isinstance(data, list):
                            if data and isinstance(data[0], dict):
                                obj = data[0]
                                copy_log("[API] copy_document: response is list with {} items", len(data), component="API")
                            else:
                                # Empty array or invalid list - treat as failure
                                copy_log("[API] copy_document: upload FAILED - empty or invalid array response", component="API")
                                copy_log("[API] copy_document: response text={}", upload_r.text[:500], component="API")
                                return False
                        else:
                            copy_log("[API] copy_document: upload FAILED - unexpected response type: {}", type(data), component="API")
                            return False

                        new_doc_id = None
                        if isinstance(obj, dict):
                            success_flag = obj.get("success")
                            if success_flag is not True:
                                copy_log("[API] copy_document: upload FAILED - success is not true", component="API")
                                return False
                            # Try multiple ID fields including fileUid as fallback
                            id_val = obj.get("id") or obj.get("Id") or obj.get("documentId") or obj.get("fileId")
                            # If id is 0 or None, try fileUid
                            if not id_val:
                                id_val = obj.get("fileUid")
                            copy_log("[API] copy_document: obj keys={}", list(obj.keys()), component="API")
                            copy_log("[API] copy_document: id={}, fileUid={}, using_id={}", obj.get("id"), obj.get("fileUid"), id_val, component="API")
                            # If still no valid ID, treat as failure
                            if id_val:
                                new_doc_id = id_val
                            else:
                                copy_log("[API] copy_document: upload FAILED - no valid ID in response", component="API")
                                return False
                        else:
                            copy_log("[API] copy_document: upload FAILED - obj is not dict", component="API")
                            return False

                        copy_log("[API] copy_document: SUCCESS - new_doc_id={}", new_doc_id, component="API")
                        return new_doc_id
                    except Exception as e:
                        copy_log("[API] copy_document: upload ERROR parsing JSON: {}", str(e), component="API")
                        import traceback
                        copy_log("[API] copy_document: TRACEBACK: {}", traceback.format_exc(), component="API")
                        copy_log("[API] copy_document: response text={}", upload_r.text[:500], component="API")
                        return False
                copy_log("[API] copy_document: upload FAILED - status_code={}", upload_r.status_code, component="API")
                return False
        except requests.RequestException as e:
            copy_log("[API] ERROR in copy_document: {}", str(e), component="API")
            import traceback
            traceback.print_exc()
            return None
        except Exception as e:
            copy_log("[API] ERROR in copy_document (unexpected): {}", str(e), component="API")
            import traceback
            traceback.print_exc()
            return None
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                    copy_log("[API] copy_document: deleted temp file {}", tmp_path, component="API")
                except Exception as e:
                    copy_log("[API] ERROR deleting temp file: {}", str(e), component="API")
