import json


AUTH_REFRESH_PATH = "/api/auth/refresh"
AUTH_LOGIN_PATH = "/api/admin/login"
PROJECT_LIST_PATH = "/api/project/list"
WORKSPACE_LIST_PATHS = (
    "/api/workspace/list",
    "/api/admin/workspace/list",
    "/api/workspaces",
    "/api/user/workspaces",
)
WORKSPACE_CHANGE_PATH = "/api/admin/workspace/change"

FOLDER_LIST_PATH = "/api/folder/list/{project_id}"
FOLDER_DETAILS_PATH = "/api/folder/{folder_id}"
FOLDER_DELETE_PATH = "/api/folder/delete/{folder_id}"
FOLDER_ADD_PATH = "/api/folder/add"
FOLDER_UPDATE_PATH = "/api/folder/update/{folder_id}"
FOLDER_COPY_PATH = "/api/folder/{folder_id}/copy"

DOCUMENT_TYPES_PATH = "/api/document/types"
DOCUMENT_DETAILS_PATH = "/api/document/{document_id}"
DOCUMENT_VERSIONS_PATH = "/api/document/versions/{document_id}"
DOCUMENT_LIST_PATH = "/api/document/list/{folder_id}"
DOCUMENT_DOWNLOAD_PATH = "/api/document/download/{document_id}"
DOCUMENT_UPLOAD_PATH = "/api/document/upload/{folder_id}"
DOCUMENT_DELETE_PATH = "/api/document/delete/{document_id}"
DOCUMENT_UPDATE_PATH = "/api/document/update/{document_id}"

LINK_GENERATE_PATH = "/api/link/generate"
LINK_DELETE_PATH = "/api/link/delete"

DOCUMENT_UPLOAD_FILE_FIELD = "file"
DOCUMENT_UPLOAD_METADATA_FIELD = "metadata"
DOCUMENT_UPLOAD_CONTENT_TYPE = "application/octet-stream"


def build_url(base_url: str, path: str, **params) -> str:
    return f"{base_url}{path.format(**params)}"


def build_auth_refresh_payload(refresh_token: str) -> dict:
    return {"refresh_token": refresh_token}


def build_login_payload(username: str, password: str) -> dict:
    return {"username": username, "password": password, "app_code": ""}


def build_workspace_change_query_url(base_url: str, workspace_id: int | str) -> str:
    return f"{build_url(base_url, WORKSPACE_CHANGE_PATH)}?workspaceId={workspace_id}"


def build_workspace_change_payload(workspace_id: int | str) -> dict:
    return {"workspaceId": workspace_id}


def build_document_upload_metadata(filename: str, document_type_id: int | str) -> str:
    payload = {
        "files": [
            {
                "fileName": str(filename or ""),
                "documentType": str(document_type_id),
            }
        ]
    }
    return json.dumps(payload, ensure_ascii=False)


def build_document_move_payload(document_id: int | str, folder_id: int | str) -> dict:
    return {"id": str(document_id), "folderId": str(folder_id)}


def build_folder_create_payload(project_id: int | str, parent_id: int | str | None, name: str) -> dict:
    return {
        "projectId": project_id,
        "name": name.strip(),
        "id": 0,
        "parentFolderId": None if not parent_id else str(parent_id),
    }


def build_folder_update_payload(
    folder_id: int | str,
    project_id: int | str,
    name: str,
    parent_folder_id: int | str | None,
) -> dict:
    return {
        "projectId": project_id,
        "name": name,
        "id": str(folder_id),
        "parentFolderId": parent_folder_id,
    }


def build_folder_rename_payload(folder_id: int | str, new_name: str) -> dict:
    return {"id": str(folder_id), "name": new_name}


def build_document_rename_payload(document_id: int | str, new_name: str) -> dict:
    return {"id": str(document_id), "fileName": new_name}


def build_folder_copy_payload(dest_folder_id: int | str, new_name: str) -> dict:
    return {"destFolderId": str(dest_folder_id), "name": new_name}


def build_public_link_payload(
    file_ids: list[int] | list[str],
    folder_ids: list[int] | list[str] | None,
    validity_period: str,
    granted_access: str,
    file_version: str,
) -> dict:
    return {
        "files": [int(f) for f in file_ids] if file_ids else [],
        "folder": [int(f) for f in folder_ids] if folder_ids else [],
        "linkValidityPeriod": validity_period,
        "grantedAccess": granted_access,
        "grantedFileVersion": file_version,
    }


def build_delete_public_link_payload(
    document_ids: list[int] | list[str],
    folder_ids: list[int] | list[str] | None,
) -> dict:
    return {
        "document_id": [int(d) for d in document_ids] if document_ids else [],
        "folder_id": [int(f) for f in folder_ids] if folder_ids else [],
    }
