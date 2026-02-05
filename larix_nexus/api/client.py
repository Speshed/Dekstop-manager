# -*- coding: utf-8 -*-

import os
import json
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
    from requests_toolbelt.multipart.encoder import MultipartEncoder  # type: ignore
except Exception:
    MultipartEncoder = None  # type: ignore

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


def _api_dbg(msg: str, *args) -> None:
    if not _API_DEBUG:
        return
    try:
        _API_LOG.debug(msg, *args)
    except Exception:
        pass


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
                logging.getLogger("auth").info("_load_auth: using access_token (may be expired)")
                return True
            else:
                logging.getLogger("auth").debug("_load_auth: no access_token")
            
            logging.getLogger("auth").info("_load_auth: failed - no valid credentials")
            return False
        except Exception as e:
            logging.getLogger("auth").exception("_load_auth error: %s", e)
            return False

    def _clear_auth(self) -> None:
        """Clear all auth tokens from keyring."""
        try:
            if self.current_username:
                clear_all_credentials(self.current_username)
            
            settings = load_settings()
            settings["remember_me"] = False
            settings["last_username"] = ""
            save_settings(settings)
        except Exception:
            pass

    def _refresh_access_token(self) -> bool:
        """Refresh access token using refresh token. Returns True if successful."""
        if not self.refresh_token:
            logging.getLogger("auth").info("_refresh_access_token: no refresh_token")
            return False

        logging.getLogger("auth").info("_refresh_access_token: attempting refresh")
        url = f"{self.base_url}/api/auth/refresh"
        try:
            r = requests.post(
                url,
                json={"refresh_token": self.refresh_token},
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
        
        self.logout()
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
            url = f"{self.base_url}/api/project/list"
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
        url = f"{self.base_url}/api/admin/login"
        payload = {"username": username, "password": password, "app_code": ""}
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
        self.token = None
        self.refresh_token = None
        username = self.current_username
        self.current_username = None
        self.cache.clear()
        
        self._clear_auth()

    def list_projects(self):
        """List all projects. Filter by selected workspace_id if set. Auto-retries once on 401."""
        if not self.token: 
            return []
        
        url = f"{self.base_url}/api/project/list"
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
                    filtered = [p for p in projects if str(p.get("workspaceId")) == ws_id]
                    logging.getLogger("auth").info("list_projects: filtered %d/%d projects for workspace=%s", len(filtered), len(projects), ws_id)
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
        
        url = f"{self.base_url}/api/admin/workspace/list"
        logging.getLogger("auth").info("list_workspaces: requesting %s", url)
        
        for attempt in range(2):
            try:
                r = requests.get(url, headers=self._headers(), timeout=12)
                logging.getLogger("auth").debug("list_workspaces: response status=%s", r.status_code)
                
                if r.status_code == 401:
                    if attempt == 0 and self._handle_401():
                        continue
                    return []
                
                r.raise_for_status()
                data = r.json()
                logging.getLogger("auth").debug("list_workspaces: response data type=%s", type(data))
                _log_api_response(url, "GET", r.status_code, data)
                
                workspaces = []
                
                if isinstance(data, list):
                    workspaces = data
                elif isinstance(data, dict) and "data" in data and isinstance(data.get("data"), list):
                    workspaces = data.get("data", [])
                
                logging.getLogger("auth").info("list_workspaces: returning %d workspaces", len(workspaces))
                for i, ws in enumerate(workspaces[:3]):
                    logging.getLogger("auth").debug("list_workspaces: workspace[%d] id=%s name=%s", i, ws.get("id"), ws.get("name"))
                
                return workspaces
            except requests.RequestException as e:
                logging.getLogger("auth").warning("list_workspaces: exception: %s", e)
                return []
        return []

    def change_workspace(self, workspace_id):
        """Change current workspace and update tokens."""
        if not self.token:
            logging.getLogger("auth").warning("change_workspace: no token")
            return False
        
        url = f"{self.base_url}/api/admin/workspace/change?workspaceId={workspace_id}"
        logging.getLogger("auth").info("change_workspace: requesting %s", url)
        
        try:
            r = requests.post(url, headers=self._headers(), timeout=12)
            logging.getLogger("auth").debug("change_workspace: response status=%s", r.status_code)
            
            if r.status_code == 401:
                if self._handle_401():
                    return self.change_workspace(workspace_id)
                return False
            
            r.raise_for_status()
            data = r.json()
            _log_api_response(url, "POST", r.status_code, data)
            
            if isinstance(data, dict) and "data" in data:
                token_data = data.get("data", {})
                new_token = token_data.get("access")
                new_refresh = token_data.get("refresh")
                
                if new_token and self.current_username:
                    self.token = new_token
                    self.refresh_token = new_refresh
                    
                    decoded = self._decode_jwt(new_token)
                    if decoded:
                        self.user_id = decoded.get("user_id") or decoded.get("userId") or decoded.get("sub")
                        self.workspace_id = decoded.get("workspace_id") or decoded.get("workspaceId")
                        logging.getLogger("auth").debug("change_workspace: decoded user_id=%s workspace_id=%s", self.user_id, self.workspace_id)
                    
                    settings = load_settings()
                    save_credential(self.current_username, "access_token", new_token)
                    save_credential(self.current_username, "refresh_token", new_refresh)
                    
                    logging.getLogger("auth").info("change_workspace: success workspace_id=%s", workspace_id)
                    return True
            
            logging.getLogger("auth").warning("change_workspace: unexpected response format")
            return False
        except requests.RequestException as e:
            logging.getLogger("auth").warning("change_workspace: exception: %s", e)
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
                _log_api_response(url, "GET", r.status_code, data)
                if isinstance(data, list):
                    self.cache[key] = (time.time(), data)
                    return data
                return []
            except requests.RequestException:
                return []
        return []
    def get_document_details(self, document_id: int | str) -> dict | None:
        """Get document details by ID."""
        if not self.token:
            return None
        doc_id = self._stringify_id(document_id)
        if not doc_id:
            return None
        
        url = f"{self.base_url}/api/document/{doc_id}"
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
            return data if isinstance(data, dict) else None
        except requests.RequestException:
            return None

    def get_document_versions(self, document_id: int | str) -> list | dict:
        """Get document versions by ID.
        
        Returns:
            List of versions or dict with 'versions' key and 'file_name' metadata
        """
        if not self.token:
            return []
        doc_id = self._stringify_id(document_id)
        if not doc_id:
            return []
        
        cache_key = f"docver:{doc_id}"
        cached = self._cached_get(cache_key)
        if cached is not None:
            return cached
        
        url = f"{self.base_url}/api/document/versions/{doc_id}"
        for attempt in range(2):
            try:
                r = requests.get(url, headers=self._headers(), timeout=12)
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

    def get_folder_details(self, folder_id: int | str, force: bool = False) -> dict | None:
        """Get folder details by ID.

        Args:
            folder_id: Folder ID (int or str)
            force: If True, bypass cache and fetch fresh data
        """
        if not self.token:
            return None
        fid = self._stringify_id(folder_id)
        if not fid:
            return None

        # Force refresh: clear cache entry for this folder
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
            _log_api_response(url, "GET", r.status_code, data)
            return data if isinstance(data, dict) else None
        except requests.RequestException:
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
                    def find_folder_in_tree(tree, target_id):
                        if not isinstance(tree, list):
                            return None
                        for item in tree:
                            if self._stringify_id(item.get("id")) == target_id:
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

    def download_file(self, file_id: int | str, filename: str, progress_cb: Optional[Callable[[int, int], None]] = None) -> str:
        """Download file from cloud and save to DOWNLOAD_DIR.

        Args:
            file_id: Document ID to download
            filename: Name to save the file as
            progress_cb: Optional callback function(done, total) for progress updates

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
        url = f"{self.base_url}/api/document/download/{doc_id}"

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
        url = f"{self.base_url}/api/document/download/{doc_id}"

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
                        if progress_cb and total:
                            done += len(part)
                            progress_cb(done, total)
                return True
            except requests.Timeout:
                sync_log("write_file_to: timeout on attempt {}/{}", attempt + 1, max_retries)
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                return False
            except requests.RequestException as e:
                sync_log("write_file_to: request exception: {}", str(e))
                return False
        return False

    def upload_file(self, folder_id: int | str, local_path: str, filename: str, max_retries: int = 3) -> bool:
        """Upload a file to the specified folder.
        Multipart fields:
          - files: binary
          - documentMetadata: JSON string like: [{"filename":"<name>","documentType":100}]
        Success: any 2xx. Response body is not required.
        After success, folder cache is invalidated. Stores last status in
        self._last_upload_status for logging by callers.

        Args:
            folder_id: Destination folder ID
            local_path: Local path to the file to upload
            filename: Name to use for the uploaded file
            max_retries: Number of retry attempts on timeout (default 3)

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
            sync_log("upload_file: local_path does not exist: {}", local_path)
            return False

        url = f"{self.base_url}/api/document/upload/{folder_id_str}"
        sync_log("upload_file: starting upload - folder_id={}, local_path={}, filename={}, url={}", folder_id_str, local_path, filename, url)

        for attempt in range(max_retries):
            status = 0
            try:
                # sanitize filename
                try:
                    safe_filename = _sanitize_filename(filename)
                except Exception:
                    safe_filename = (filename or "").strip()

                meta = [{"filename": safe_filename, "documentType": 100}]
                metadata_json = json.dumps(meta, ensure_ascii=False)

                sync_log("upload_file: attempt {}/{} - safe_filename='{}'", attempt + 1, max_retries, safe_filename)

                with open(local_path, "rb") as f:
                    # NOTE: Some servers are picky about multipart parts.
                    # Send file as multipart "files" part and metadata as a regular form field.
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
                    sync_log("upload_file: response status={}", status)
                    try:
                        response_data = r.text if not r.ok else r.json() if r.content else {}
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

                # store last status for external logging
                try:
                    setattr(self, "_last_upload_status", status)
                except Exception:
                    pass

                ok = 200 <= status < 300
                sync_log("upload_file: upload {} - status={}, ok={}", "succeeded" if ok else "failed", status, ok)
                if ok:
                    try:
                        self.cache.pop(f"folder:{folder_id_str}", None)
                    except Exception:
                        pass
                return ok

            except requests.Timeout:
                sync_log("upload_file: timeout on attempt {}/{}", attempt + 1, max_retries)
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                # Final timeout - store status and return False
                try:
                    setattr(self, "_last_upload_status", 0)
                except Exception:
                    pass
                return False

            except requests.RequestException as e:
                sync_log("upload_file: request exception: {}", str(e))
                sync_exc("upload_file error")
                try:
                    setattr(self, "_last_upload_status", status or 0)
                except Exception:
                    pass
                return False
            except Exception as e:
                sync_log("upload_file: unexpected exception: {}", str(e))
                sync_exc("upload_file unexpected error")
                try:
                    setattr(self, "_last_upload_status", status or 0)
                except Exception:
                    pass
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

        url = f"{self.base_url}/api/document/delete/{doc_id}"
        try:
            r = requests.delete(url, headers=self._headers(), timeout=20)
            _log_api_response(url, "DELETE", r.status_code, {"document_id": doc_id})
            return r.status_code in (200, 204)
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

        url = f"{self.base_url}/api/folder/delete/{fid}"
        try:
            r = requests.delete(url, headers=self._headers(), timeout=20)
            _log_api_response(url, "DELETE", r.status_code, {"folder_id": fid})
            return r.status_code in (200, 204)
        except requests.RequestException:
            return False

    def move_document(self, document_id: int | str, dest_folder_id: int | str) -> bool:
        """Move document to another folder.

        Args:
            document_id: Document ID to move
            dest_folder_id: Destination folder ID

        Returns:
            True if moved successfully, False otherwise
        """
        if not self.token:
            return False
        doc_id = self._stringify_id(document_id)
        # API accepts folderId="0" to move to project root.
        dest_id = self._stringify_id(dest_folder_id) if dest_folder_id else "0"
        if not doc_id:
            return False

        url = f"{self.base_url}/api/document/update/{doc_id}"
        payload = {"id": doc_id, "folderId": dest_id}
        try:
            r = requests.put(url, headers={**self._headers(), "Content-Type": "application/json"}, json=payload, timeout=20)
            _log_api_response(url, "PUT", r.status_code, payload)
            ok = r.status_code in (200, 204)
            if not ok:
                try:
                    sync_log("move_document: FAILED status={} body={}", r.status_code, (r.text or "")[:300])
                except Exception:
                    pass
            return ok
        except requests.RequestException:
            return False

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

        url = f"{self.base_url}/api/folder/add"
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json", "accept": "*/*"}
        payload = {
            "projectId": project_id,
            "name": name.strip(),
            "id": 0,
            "parentFolderId": None if not parent_id else self._stringify_id(parent_id),
        }
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

        url = f"{self.base_url}/api/folder/update/{fid}"
        # Root move should use parentFolderId=None (not project id).
        parent_norm = self._stringify_id(parent_folder_id)
        proj_norm = self._stringify_id(project_id)
        parent_payload = None if (not parent_norm or parent_norm == proj_norm) else parent_norm
        payload = {"projectId": project_id, "name": name, "id": fid, "parentFolderId": parent_payload}
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

        url = f"{self.base_url}/api/folder/update/{fid}"
        payload = {"id": fid, "name": new_name}
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

        url = f"{self.base_url}/api/document/update/{doc_id}"
        payload = {"id": doc_id, "originalName": new_name, "name": new_name}
        try:
            r = requests.put(url, headers={**self._headers(), "Content-Type": "application/json"}, json=payload, timeout=20)
            _log_api_response(url, "PUT", r.status_code, payload)
            return r.status_code in (200, 204)
        except requests.RequestException:
            return False

    def copy_folder(self, folder_id: int | str, dest_folder_id: int | str, new_name: str) -> int | str | None:
        """Copy folder to another folder.

        Args:
            folder_id: Source folder ID
            dest_folder_id: Destination folder ID
            new_name: Name for the new folder

        Returns:
            New folder ID if successful, None otherwise
        """
        if not self.token:
            return None
        src_id = self._stringify_id(folder_id)
        dest_id = self._stringify_id(dest_folder_id)
        if not src_id or not dest_id:
            return None

        url = f"{self.base_url}/api/folder/{src_id}/copy"
        try:
            payload = {"destFolderId": dest_id, "name": new_name}
            r = requests.post(url, json=payload, headers=self._headers(), timeout=20)
            if r.status_code == 401:
                if self._handle_401():
                    r = requests.post(url, json=payload, headers=self._headers(), timeout=20)
                else:
                    return None
            r.raise_for_status()
            data = r.json()
            _log_api_response(url, "POST", r.status_code, data)
            new_id = data.get("id") or data.get("Id") or data.get("folderId")
            return new_id
        except requests.RequestException:
            return None

    def copy_document(self, document_id: int | str, dest_folder_id: int | str, new_name: str | None = None):
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
            src_doc = self.get_document_details(doc_id)
            copy_log("[API] copy_document: src_doc={}", src_doc, component="API")
            if not src_doc:
                copy_log("[API] copy_document: NO src_doc", component="API")
                return None

            src_name = src_doc.get("originalName") or src_doc.get("name") or "file"
            if not new_name:
                new_name = src_name
            new_name = str(new_name)
            copy_log("[API] copy_document: final new_name={}", new_name, component="API")

            download_url = f"{self.base_url}/api/document/download/{doc_id}"
            copy_log("[API] copy_document: downloading from {}", download_url, component="API")
            r = requests.get(download_url, headers=self._headers(), stream=True, timeout=120)
            copy_log("[API] copy_document: download status_code={}", r.status_code, component="API")
            
            if r.status_code == 401:
                copy_log("[API] copy_document: 401 - trying to handle", component="API")
                if self._handle_401():
                    return None
                return None
            
            r.raise_for_status()
            copy_log("[API] copy_document: download SUCCESS, content_length={}", r.headers.get('content-length', 'unknown'), component="API")

            meta = [{"filename": new_name, "documentType": 100}]
            metadata_json = json.dumps(meta, ensure_ascii=False)

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
                if MultipartEncoder is not None:
                    copy_log("[API] copy_document: using MultipartEncoder", component="API")
                    enc = MultipartEncoder(
                        fields={
                            "files": (new_name, upload_file, "application/octet-stream"),
                            "documentMetadata": metadata_json,
                        }
                    )
                    headers = {**self._headers(), "Content-Type": enc.content_type}
                    upload_url = f"{self.base_url}/api/document/upload/{dest_id}"
                    copy_log("[API] copy_document: uploading to {}", upload_url, component="API")
                    upload_r = requests.post(
                        upload_url,
                        headers=headers,
                        data=enc,
                        timeout=120,
                    )
                else:
                    copy_log("[API] copy_document: using simple upload (no MultipartEncoder)", component="API")
                    files = {"files": (new_name, upload_file, "application/octet-stream")}
                    data = {"documentMetadata": metadata_json}
                    upload_url = f"{self.base_url}/api/document/upload/{dest_id}"
                    copy_log("[API] copy_document: uploading to {}", upload_url, component="API")
                    upload_r = requests.post(
                        upload_url,
                        headers=self._headers(),
                        files=files,
                        data=data,
                        timeout=120,
                    )
            
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
                    elif isinstance(data, list) and data and isinstance(data[0], dict):
                        obj = data[0]
                    new_doc_id = None
                    if isinstance(obj, dict):
                        new_doc_id = obj.get("id") or obj.get("Id") or obj.get("documentId") or obj.get("fileId")
                    if not new_doc_id:
                        new_doc_id = True
                    copy_log("[API] copy_document: SUCCESS - new_doc_id={}", new_doc_id, component="API")
                    return new_doc_id
                except Exception as e:
                    copy_log("[API] copy_document: upload SUCCESS but cannot parse JSON: {}", str(e), component="API")
                    return True
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
