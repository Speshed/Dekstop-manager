import json
import os
import time

import requests

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
