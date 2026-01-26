# -*- coding: utf-8 -*-

import os
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, Callable
import subprocess

from PySide6.QtCore import QSettings, Signal
from PySide6.QtWidgets import QComboBox

import requests
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
            use_auto = bool(int(s.value("auto", 1) or 1))
            if use_auto:
                try:
                    ofs = datetime.now().astimezone().utcoffset() or timedelta(0)
                    return int(ofs.total_seconds() // 60)
                except Exception:
                    return 0
            else:
                return int(s.value("offset_minutes", 0) or 0)
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
        
        try:
            self._load_auth()
        except Exception:
            pass

    def _save_auth(self) -> None:
        """Save auth tokens to keyring. Always saves credentials for auto-login."""
        try:
            if not self.current_username:
                print("[AUTH DEBUG] _save_auth: no username, skipping")
                return
            
            print(f"[AUTH DEBUG] _save_auth: saving credentials for user '{self.current_username}'")
            
            if self.token:
                save_credential(self.current_username, "access_token", self.token)
                print(f"[AUTH DEBUG] - saved access_token: {self.token[:20]}...")
            
            if self.refresh_token:
                save_credential(self.current_username, "refresh_token", self.refresh_token)
                print(f"[AUTH DEBUG] - saved refresh_token: {self.refresh_token[:20]}...")
            
            settings = load_settings()
            settings["last_username"] = self.current_username
            settings["remember_me"] = True
            settings["auto_login"] = True
            save_settings(settings)
            print(f"[AUTH DEBUG] - saved settings: auto_login=True, remember_me=True, last_username={self.current_username}")
            
            debug_credentials_status(self.current_username)
        except Exception as e:
            print(f"[AUTH DEBUG] _save_auth ERROR: {e}")
            pass

    def _load_auth(self) -> bool:
        """Load auth tokens from keyring. Returns True if tokens were loaded and validated.
        
        Tries in order:
        1. Refresh token → refresh to get new access token
        2. Password → login to get new tokens
        3. Access token → direct use (may be expired)
        """
        try:
            print("[AUTH DEBUG] _load_auth: starting auto-login attempt")
            settings = load_settings()
            username = settings.get("last_username", "")
            
            if not username:
                print("[AUTH DEBUG] _load_auth: no last_username found, skipping auto-login")
                return False
            
            print(f"[AUTH DEBUG] _load_auth: found last_username='{username}'")
            
            debug_credentials_status(username)
            
            refresh_token = get_credential(username, "refresh_token")
            if refresh_token:
                print(f"[AUTH DEBUG] _load_auth: found refresh_token: {refresh_token[:20]}...")
                self.current_username = username
                self.refresh_token = refresh_token
                
                if self._refresh_access_token():
                    print("[AUTH DEBUG] _load_auth: SUCCESS via refresh_token")
                    return True
                else:
                    print("[AUTH DEBUG] _load_auth: refresh_token failed, trying next method")
            else:
                print("[AUTH DEBUG] _load_auth: no refresh_token found")
            
            password = get_credential(username, "password")
            if password:
                print(f"[AUTH DEBUG] _load_auth: found password: {password[:3]}***")
                if self.login(username, password, remember_me=True):
                    print("[AUTH DEBUG] _load_auth: SUCCESS via password login")
                    return True
                else:
                    print("[AUTH DEBUG] _load_auth: password login failed, trying next method")
            else:
                print("[AUTH DEBUG] _load_auth: no password found in keyring")
            
            access_token = get_credential(username, "access_token")
            if access_token:
                print(f"[AUTH DEBUG] _load_auth: found access_token: {access_token[:20]}...")
                self.current_username = username
                self.token = access_token
                print("[AUTH DEBUG] _load_auth: SUCCESS via access_token (may be expired)")
                return True
            else:
                print("[AUTH DEBUG] _load_auth: no access_token found")
            
            print("[AUTH DEBUG] _load_auth: FAILED - no valid credentials found")
            return False
        except Exception as e:
            print(f"[AUTH DEBUG] _load_auth ERROR: {e}")
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
            print("[AUTH DEBUG] _refresh_access_token: no refresh_token available")
            return False
        
        print(f"[AUTH DEBUG] _refresh_access_token: attempting refresh with token: {self.refresh_token[:20]}...")
        url = f"{self.base_url}/api/auth/refresh"
        try:
            r = requests.post(
                url,
                json={"refresh_token": self.refresh_token},
                headers={"accept": "*/*", "Content-Type": "application/json"},
                timeout=12
            )
            
            print(f"[AUTH DEBUG] _refresh_access_token: got status {r.status_code}")
            
            if r.status_code != 200:
                print(f"[AUTH DEBUG] _refresh_access_token: FAILED - status {r.status_code}, response: {r.text[:200]}")
                return False
            
            data = r.json()
            print(f"[AUTH DEBUG] _refresh_access_token: response data keys: {list(data.keys())}")
            
            access_token = data.get("token") or data.get("accessToken") or data.get("access_token")
            refresh_token = data.get("refreshToken") or data.get("refresh_token")
            
            if access_token:
                self.token = access_token
                print(f"[AUTH DEBUG] _refresh_access_token: got new access_token: {access_token[:20]}...")
                
                if refresh_token:
                    self.refresh_token = refresh_token
                    print(f"[AUTH DEBUG] _refresh_access_token: got new refresh_token: {refresh_token[:20]}...")
                
                self._save_auth()
                print("[AUTH DEBUG] _refresh_access_token: SUCCESS")
                return True
            
            print("[AUTH DEBUG] _refresh_access_token: FAILED - no access_token in response")
            return False
        except requests.RequestException as e:
            print(f"[AUTH DEBUG] _refresh_access_token: RequestException - {e}")
            return False

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
        print(f"[AUTH DEBUG] login: attempting login for user '{username}', remember_me={remember_me}")
        url = f"{self.base_url}/api/admin/login"
        payload = {"username": username, "password": password, "app_code": ""}
        try:
            r = requests.post(url, json=payload, headers={"accept": "*/*","Content-Type":"application/json"}, timeout=12)
            if r.status_code == 401:
                print(f"[AUTH DEBUG] login: 401 Unauthorized for user '{username}'")
                return False
            r.raise_for_status()
            data = r.json()

            token = data.get("token") or data.get("accessToken") or data.get("access_token")
            refresh_token = data.get("refreshToken") or data.get("refresh_token")

            if not token:
                print(f"[AUTH DEBUG] login: no token in response for user '{username}'")
                return False

            self.token = token
            self.refresh_token = refresh_token
            self.current_username = username

            print(f"[AUTH DEBUG] login: SUCCESS for user '{username}'")
            print(f"[AUTH DEBUG] - token: {token[:20]}...")
            print(f"[AUTH DEBUG] - refresh_token: {refresh_token[:20] if refresh_token else 'None'}...")

            # Always save last_username for auto-fill in login dialog
            settings = load_settings()
            settings["last_username"] = username
            settings["remember_me"] = remember_me
            save_settings(settings)
            print(f"[AUTH DEBUG] - saved last_username and remember_me={remember_me}")

            if remember_me:
                save_credential(username, "password", password)
                print(f"[AUTH DEBUG] - saved password to keyring")
                # Save tokens for auto-login
                if self.token:
                    save_credential(username, "access_token", self.token)
                    print(f"[AUTH DEBUG] - saved access_token: {self.token[:20]}...")
                if self.refresh_token:
                    save_credential(username, "refresh_token", self.refresh_token)
                    print(f"[AUTH DEBUG] - saved refresh_token: {self.refresh_token[:20]}...")
            else:
                print(f"[AUTH DEBUG] - credentials NOT saved (remember_me=False)")

            return True
        except requests.RequestException as e:
            print(f"[AUTH DEBUG] login: RequestException - {e}")
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
        """List all projects. Auto-retries once on 401."""
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
                return data if isinstance(data, list) else []
            except requests.RequestException:
                return []
        return []

    def _cached_get(self, key: str):
        it = self.cache.get(key)
        if not it: return None
        ts, data = it
        if (time.time() - ts) < CACHE_TTL_SEC: return data
        return None

    def _stringify_id(self, raw_id) -> str:
        """Normalize document/folder identifiers that may now be opaque strings."""
        if raw_id is None:
            return ""
        if isinstance(raw_id, str):
            return raw_id.strip()
        try:
            return str(int(raw_id))
        except (TypeError, ValueError):
            return str(raw_id).strip()

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
                if isinstance(data, list):
                    self.cache[key] = (time.time(), data)
                    return data
                return []
            except requests.RequestException:
                return []
        return []

    def get_document_details(self, document_id: int | str):
        doc_id = self._stringify_id(document_id)
        if not doc_id:
            return None
        cache_key = f"doc:{doc_id}"
        cached = self._cached_get(cache_key)
        if cached is not None: return cached
        url = f"{self.base_url}/api/document/{doc_id}"
        try:
            r = requests.get(url, headers=self._headers(), timeout=12)
            if r.status_code == 401: self.logout(); return None
            r.raise_for_status()
            data = r.json()
            self.cache[cache_key] = (time.time(), data)
            return data
        except requests.RequestException:
            return None

    def generate_document_link(self, document_id: int | str, mode: str = "view"):
        doc_id = self._stringify_id(document_id)
        if not doc_id:
            return {"ok": False, "error": "bad-id"}
        mode = (mode or "view").lower()
        suffix = "download" if mode == "download" else "view"
        url = f"{self.base_url}/api/document/generate-link/{doc_id}/{suffix}"
        try:
            r = requests.get(url, headers=self._headers(), timeout=12)
            if r.status_code == 401:
                self.logout()
                return {"ok": False, "error": "unauthorized"}
            r.raise_for_status()
            try:
                data = r.json()
            except ValueError:
                return {"ok": False, "error": "invalid_json"}
            link = data.get("url") if isinstance(data, dict) else None
            if link:
                return {"ok": True, "url": str(link)}
            return {"ok": False, "error": "missing_url"}
        except requests.RequestException as exc:
            return {"ok": False, "error": "network", "detail": str(exc)}
        

    def get_document_versions(self, document_id: int | str):
        """Вернуть список версий документа.
        GET /api/document/versions/{id}
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
        try:
            r = requests.get(url, headers=self._headers(), timeout=12)
            if r.status_code == 401:
                self.logout()
                return []
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict):
                data = {
                    "file_name": data.get("file_name") or data.get("fileName") or "",
                    "versions": list(data.get("versions") or []),
                }
            elif isinstance(data, list):
                data = {"file_name": "", "versions": data}
            else:
                data = {"file_name": "", "versions": []}

            if isinstance(data, dict):
                versions = data.get("versions") or data.get("items") or []
            elif isinstance(data, list):
                versions = data
            else:
                versions = []
            self.cache[cache_key] = (time.time(), versions)
            return versions
        except requests.RequestException:
            return []

    def get_folder_details(self, folder_id: int | str, force: bool = False):
        fid = self._stringify_id(folder_id)
        if not fid:
            return None
        cache_key = f"folder:{fid}"
        if not force:
            cached = self._cached_get(cache_key)
            if cached is not None: return cached
        url = f"{self.base_url}/api/folder/{fid}"
        try:
            r = requests.get(url, headers=self._headers(), timeout=12)
            if r.status_code == 401: self.logout(); return None
            r.raise_for_status()
            data = r.json()
            self.cache[cache_key] = (time.time(), data)
            return data
        except requests.RequestException:
            return None

    def create_folder(self, project_id: int | str, parent_folder_id: int | str | None, name: str):
        url = f"{self.base_url}/api/folder/add"
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json", "accept": "*/*"}
        payload = {
            "projectId": project_id,
            "name": name.strip(),
            "id": 0,
            "parentFolderId": None if not parent_folder_id else self._stringify_id(parent_folder_id),
        }
        r = requests.post(url, headers=headers, json=payload, timeout=10)
        if r.status_code in (200, 201):
            try:
                data = r.json()
                return data.get("id") or data.get("Id") or True
            except Exception:
                return True
        return False

    def delete_folder(self, folder_id: int | str) -> bool:
        folder_id_str = self._stringify_id(folder_id)
        if not folder_id_str:
            return False
        url = f"{self.base_url}/api/folder/delete/{folder_id_str}"
        try:
            r = requests.delete(url, headers=self._headers(), timeout=20)
            return r.status_code in (200, 204)
        except requests.RequestException:
            return False

    def update_folder(self, folder_id: int | str, project_id: int | str, name: str, parent_folder_id: int | str) -> bool:
        folder_id_str = self._stringify_id(folder_id)
        parent_id_str = self._stringify_id(parent_folder_id) if parent_folder_id else "0"
        url = f"{self.base_url}/api/folder/update/{folder_id_str}"
        payload = {"projectId": project_id, "name": name, "id": folder_id_str, "parentFolderId": parent_id_str}
        try:
            r = requests.put(url, headers={**self._headers(),"Content-Type":"application/json"}, json=payload, timeout=20)
            return r.status_code in (200, 204)
        except requests.RequestException:
            return False

    def delete_document(self, document_id: int | str) -> bool:
        doc_id = self._stringify_id(document_id)
        if not doc_id:
            return False
        url = f"{self.base_url}/api/document/delete/{doc_id}"
        try:
            r = requests.delete(url, headers=self._headers(), timeout=20)
            return r.status_code in (200, 204)
        except requests.RequestException:
            return False

    def rename_document(self, document_id: int | str, new_name: str) -> bool:
        doc_id = self._stringify_id(document_id)
        if not doc_id:
            return False
        url = f"{self.base_url}/api/document/update/{doc_id}"
        payload = {"id": doc_id, "fileName": new_name}
        try:
            r = requests.put(url, headers={**self._headers(),"Content-Type":"application/json"}, json=payload, timeout=20)
            return r.status_code in (200, 204)
        except requests.RequestException:
            return False

    def download_file(self, file_id: int | str, file_name: str, progress_cb=None, max_retries: int = 3):
        """Download file from API to DOWNLOAD_DIR with retry logic.
        
        Args:
            file_id: ID of the file to download
            file_name: Original filename for sanitization
            progress_cb: Optional callback(done, total) for progress updates
            max_retries: Number of retry attempts (default 3)
        
        Returns:
            filepath on success, None on failure
        """
        if not self.token:
            return None
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        doc_id = self._stringify_id(file_id)
        if not doc_id:
            return None
        safe = _sanitize_filename(file_name or f"file_{doc_id}.bin")
        filepath = os.path.join(DOWNLOAD_DIR, safe)
        url = f"{self.base_url}/api/document/download/{doc_id}"
        
        for attempt in range(max_retries):
            try:
                with requests.get(url, headers=self._headers(), stream=True, timeout=60) as r:
                    # Handle 401 Unauthorized - try to refresh token and retry once
                    if r.status_code == 401 and attempt == 0:
                        print(f"download_file: got 401, trying to refresh token...")
                        if self._handle_401():
                            continue
                        else:
                            return None
                    
                    r.raise_for_status()
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
            except requests.Timeout:
                print(f"download_file: timeout on attempt {attempt + 1}/{max_retries}")
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                return None
            except requests.RequestException as e:
                print(f"download_file: request exception on attempt {attempt + 1}/{max_retries}: {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                return None
        return None

    def write_file_to(self, file_id: int | str, out_fp, progress_cb=None, max_retries: int = 3) -> bool:
        """Stream file from API directly into a writable file-like object out_fp.
        Avoids saving to DOWNLOAD_DIR. Returns True on success.
        """
        if not self.token:
            sync_log("write_file_to: NO TOKEN, returning False")
            return False
        doc_id = self._stringify_id(file_id)
        if not doc_id:
            sync_log("write_file_to: INVALID doc_id={}, returning False", doc_id)
            return False
        url = f"{self.base_url}/api/document/download/{doc_id}"
        
        sync_log("write_file_to: START - file_id={}, doc_id={}, url={}", file_id, doc_id, url)
        
        for attempt in range(max_retries):
            try:
                sync_log("write_file_to: attempt {}/{}", attempt + 1, max_retries)
                with requests.get(url, headers=self._headers(), stream=True, timeout=60) as r:
                    sync_log("write_file_to: HTTP status code = {}", r.status_code)
                    
                    if r.status_code == 401 and attempt == 0:
                        sync_log("write_file_to: got 401, trying to refresh token...")
                        if self._handle_401():
                            continue
                        else:
                            return False
                    
                    r.raise_for_status()
                    total = int(r.headers.get("Content-Length") or 0)
                    sync_log("write_file_to: Content-Length = {} bytes", total)
                    done = 0
                    chunk = 256 * 1024
                    sync_log("write_file_to: Starting to write {} bytes to file...", total)
                    for part in r.iter_content(chunk_size=chunk):
                        if not part:
                            continue
                        out_fp.write(part)
                        done += len(part)
                        if progress_cb and total:
                            progress_cb(done, total)
                    sync_log("write_file_to: Wrote {} bytes successfully", done)
                return True
            except requests.Timeout:
                sync_log("write_file_to: timeout on attempt {}/{}", attempt + 1, max_retries)
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                return False
            except requests.RequestException as e:
                sync_log("write_file_to: request exception: {}", str(e))
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                return False
        return False

    def upload_file(self, folder_id: int | str, local_path: str, filename: str, max_retries: int = 3):
        """Upload a single file to a specific cloud folder via multipart POST.
        Multipart fields:
          - files: binary
          - documentMetadata: JSON string like: [{"filename":"<name>","documentType":100}]
        Success: any 2xx. Response body is not required.
        After success, folder cache is invalidated. Stores last status in
        self._last_upload_status for logging by callers.
        
        Args:
            max_retries: Number of retry attempts on timeout (default 3)
        """
        if not self.token:
            return False
        folder_id_str = self._stringify_id(folder_id)
        if not folder_id_str:
            return False
        url = f"{self.base_url}/api/document/upload/{folder_id_str}"
        
        for attempt in range(max_retries):
            status = 0
            try:
                try:
                    safe_filename = _sanitize_filename(filename)
                except Exception:
                    safe_filename = (filename or "").strip()
                meta = [{"filename": safe_filename, "documentType": 100}]
                metadata_json = json.dumps(meta, ensure_ascii=False)
                
                with open(local_path, "rb") as f:
                    files = {
                        "files": (safe_filename, f, "application/octet-stream"),
                        "documentMetadata": (None, metadata_json),
                    }
                    r = requests.post(url, headers=self._headers(), files=files, timeout=120)
                    status = int(r.status_code)
                
                if status == 401 and attempt == 0:
                    sync_log("upload_file: got 401, trying to refresh token...")
                    if self._handle_401():
                        continue
                    else:
                        return False
                
                try:
                    setattr(self, "_last_upload_status", status)
                except Exception:
                    pass
                    
                ok = 200 <= status < 300
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
                try:
                    setattr(self, "_last_upload_status", 0)
                except Exception:
                    pass
                return False
                
            except requests.RequestException as e:
                sync_log("upload_file: request exception: {}", str(e))
                try:
                    setattr(self, "_last_upload_status", status or 0)
                except Exception:
                    pass
                return False
