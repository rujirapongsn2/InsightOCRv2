"""
Headless cloud-storage clients for Google Drive and OneDrive/SharePoint.

Auth model = service account / app credentials (no interactive OAuth):
  - Google Drive: service-account JSON. We sign a short-lived RS256 JWT with the
    account's private key and exchange it for an access token (JWT-bearer grant).
  - OneDrive/SharePoint: Azure app registration. We use the OAuth2
    client-credentials grant against Microsoft Graph.

All HTTP goes through `requests`, which honours the HTTP(S)_PROXY env vars so
outbound calls travel via the gateway container like the rest of the app.

Credentials live in an Integration row (config JSONB) and are referenced from a
workflow node by integration_id — never stored in the workflow definition.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

import requests
from jose import jwt
from app.core.config import settings

GOOGLE_SCOPE = "https://www.googleapis.com/auth/drive"
GOOGLE_DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"

DEFAULT_TIMEOUT = 60


class CloudDriveError(Exception):
    pass


# ── Google Drive ─────────────────────────────────────────────────────
class GoogleDriveClient:
    """Google Drive v3 via a service account (JWT-bearer flow)."""

    def __init__(self, config: Dict[str, Any], db: Any = None, integration: Any = None):
        self.db = db
        self.integration = integration
        self.auth_mode = config.get("auth_mode", "service_account")
        self.refresh_token_encrypted = config.get("refresh_token_encrypted")
        if self.auth_mode == "oauth":
            if not self.refresh_token_encrypted:
                raise CloudDriveError("Google Drive OAuth credential ไม่สมบูรณ์ กรุณาเชื่อมต่อบัญชีใหม่")
            return
        self.client_email = config.get("client_email")
        self.private_key = config.get("private_key")
        self.token_uri = config.get("token_uri") or GOOGLE_DEFAULT_TOKEN_URI
        if not self.client_email or not self.private_key:
            raise CloudDriveError(
                "Google Drive integration: ต้องมี client_email และ private_key ใน service-account JSON"
            )
        # PEM keys are often stored with literal \n — normalise them
        if "\\n" in self.private_key:
            self.private_key = self.private_key.replace("\\n", "\n")

    def _token(self) -> str:
        if self.auth_mode == "oauth":
            from app.services.cloud_oauth import CloudOAuthError, decrypt_refresh_token, encrypt_refresh_token

            try:
                refresh_token = decrypt_refresh_token(self.refresh_token_encrypted)
            except CloudOAuthError as exc:
                raise CloudDriveError(
                    "Google Drive OAuth credential ใช้งานไม่ได้ กรุณาเชื่อมต่อบัญชีใหม่"
                ) from exc
            try:
                resp = requests.post(
                    GOOGLE_DEFAULT_TOKEN_URI,
                    data={
                        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                        "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token",
                    },
                    timeout=DEFAULT_TIMEOUT,
                )
            except requests.RequestException as exc:
                raise CloudDriveError("ติดต่อ Google เพื่อขอ access token ไม่สำเร็จ") from exc
            if resp.status_code != 200:
                raise CloudDriveError(f"ต่ออายุ Google access token ไม่สำเร็จ: HTTP {resp.status_code} {resp.text[:300]}")
            try:
                body = resp.json()
            except ValueError as exc:
                raise CloudDriveError("Google ส่งข้อมูล access token กลับมาไม่ถูกต้อง") from exc
            access_token = body.get("access_token")
            if not access_token:
                raise CloudDriveError("Google ไม่ส่ง access token กลับมา")
            if body.get("refresh_token"):
                self._persist_refresh_token(body["refresh_token"], encrypt_refresh_token)
            return access_token
        now = int(time.time())
        claims = {
            "iss": self.client_email,
            "scope": GOOGLE_SCOPE,
            "aud": self.token_uri,
            "iat": now,
            "exp": now + 3600,
        }
        try:
            assertion = jwt.encode(claims, self.private_key, algorithm="RS256")
        except Exception as e:  # noqa: BLE001
            raise CloudDriveError(f"เซ็น JWT ของ Google service account ไม่สำเร็จ: {e}")
        resp = requests.post(
            self.token_uri,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
            timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code != 200:
            raise CloudDriveError(f"ขอ Google access token ไม่สำเร็จ: HTTP {resp.status_code} {resp.text[:300]}")
        return resp.json()["access_token"]

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._token()}"}

    def _persist_refresh_token(self, token: str, encrypt) -> None:
        if not self.db or not self.integration:
            return
        try:
            self.integration.config = {
                **(self.integration.config or {}),
                "refresh_token_encrypted": encrypt(token),
            }
            self.db.commit()
            self.refresh_token_encrypted = self.integration.config["refresh_token_encrypted"]
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            raise CloudDriveError("บันทึก OAuth credential ใหม่ไม่สำเร็จ") from exc

    def list_folder(self, folder_id: str) -> List[Dict[str, Any]]:
        if not folder_id:
            raise CloudDriveError("Google Drive: ต้องระบุ folder_id")
        # Follow nextPageToken so folders with more than one page (>1000 files)
        # are fully listed instead of silently truncated.
        headers = self._headers()  # reuse one token across all pages
        files: List[Dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params: Dict[str, Any] = {
                "q": f"'{folder_id}' in parents and trashed=false",
                "fields": "nextPageToken,files(id,name,mimeType,size)",
                "pageSize": 1000,
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            }
            if page_token:
                params["pageToken"] = page_token
            resp = requests.get(
                "https://www.googleapis.com/drive/v3/files",
                headers=headers, params=params, timeout=DEFAULT_TIMEOUT,
            )
            if resp.status_code != 200:
                raise CloudDriveError(f"Google Drive list ล้มเหลว: HTTP {resp.status_code} {resp.text[:300]}")
            body = resp.json()
            files.extend(body.get("files", []))
            page_token = body.get("nextPageToken")
            if not page_token:
                return files

    def list_children(self, folder_id: str = "root") -> List[Dict[str, Any]]:
        """List files and folders for the folder picker."""
        parent = "root" if not folder_id or folder_id == "root" else folder_id
        try:
            resp = requests.get(
                "https://www.googleapis.com/drive/v3/files",
                headers=self._headers(),
                params={
                    "q": f"'{parent}' in parents and trashed=false",
                    "fields": "files(id,name,mimeType,size,modifiedTime)",
                    "pageSize": 1000,
                    "orderBy": "folder,name",
                    "supportsAllDrives": "true",
                    "includeItemsFromAllDrives": "true",
                },
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise CloudDriveError("ติดต่อ Google เพื่ออ่านโฟลเดอร์ไม่สำเร็จ") from exc
        if resp.status_code != 200:
            raise CloudDriveError(f"Google Drive อ่านโฟลเดอร์ไม่สำเร็จ: HTTP {resp.status_code} {resp.text[:300]}")
        folder_mime = "application/vnd.google-apps.folder"
        try:
            items = resp.json().get("files", [])
        except ValueError as exc:
            raise CloudDriveError("Google ส่งรายการโฟลเดอร์กลับมาไม่ถูกต้อง") from exc
        return [{**item, "is_folder": item.get("mimeType") == folder_mime} for item in items]

    def download(self, file_id: str) -> bytes:
        resp = requests.get(
            f"https://www.googleapis.com/drive/v3/files/{file_id}",
            headers=self._headers(),
            params={"alt": "media", "supportsAllDrives": "true"},
            timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code != 200:
            raise CloudDriveError(f"Google Drive download ล้มเหลว: HTTP {resp.status_code} {resp.text[:300]}")
        return resp.content

    def upload(self, folder_id: str, filename: str, data: bytes, mime_type: str = "application/octet-stream") -> Dict[str, Any]:
        import json as _json

        metadata: Dict[str, Any] = {"name": filename}
        if folder_id:
            metadata["parents"] = [folder_id]
        files = {
            "metadata": ("metadata", _json.dumps(metadata), "application/json; charset=UTF-8"),
            "file": (filename, data, mime_type),
        }
        resp = requests.post(
            "https://www.googleapis.com/upload/drive/v3/files",
            headers=self._headers(),
            params={"uploadType": "multipart", "fields": "id,name,webViewLink", "supportsAllDrives": "true"},
            files=files,
            timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code not in (200, 201):
            detail = resp.text[:300]
            if resp.status_code == 403 and "storage quota" in resp.text.lower():
                raise CloudDriveError(
                    "Google Drive upload ล้มเหลว: service account ไม่มีพื้นที่เก็บไฟล์ของตัวเอง — "
                    "ต้องอัปโหลดไปยังโฟลเดอร์ที่อยู่ใน Shared Drive (Team Drive) แล้วแชร์ Shared Drive "
                    "นั้นให้อีเมล service account เป็นสมาชิก (สิทธิ์ Content manager ขึ้นไป). "
                    "โฟลเดอร์ใน My Drive ที่แชร์แบบธรรมดาจะอัปโหลดไม่ได้"
                )
            raise CloudDriveError(f"Google Drive upload ล้มเหลว: HTTP {resp.status_code} {detail}")
        body = resp.json()
        return {"file_id": body.get("id"), "name": body.get("name"), "link": body.get("webViewLink")}

    def check(self) -> Dict[str, Any]:
        """Lightweight connectivity check — verifies token issuance works."""
        self._token()
        return {"provider": "gdrive", "account": getattr(self, "client_email", None), "ok": True}


# ── OneDrive / SharePoint (Microsoft Graph) ──────────────────────────
class OneDriveClient:
    """OneDrive for Business / SharePoint via Graph app-only (client credentials)."""

    def __init__(self, config: Dict[str, Any], db: Any = None, integration: Any = None):
        self.db = db
        self.integration = integration
        self.auth_mode = config.get("auth_mode", "app")
        self.refresh_token_encrypted = config.get("refresh_token_encrypted")
        self.tenant_id = config.get("tenant_id")
        self.client_id = config.get("client_id")
        self.client_secret = config.get("client_secret")
        self.drive_id = config.get("drive_id")
        required = ("tenant_id", "drive_id") if self.auth_mode == "oauth" else ("tenant_id", "client_id", "client_secret", "drive_id")
        missing = [k for k in required
                   if not config.get(k)]
        if missing:
            raise CloudDriveError(f"OneDrive integration: ต้องระบุ {', '.join(missing)}")

    def _token(self) -> str:
        if self.auth_mode == "oauth":
            from app.services.cloud_oauth import CloudOAuthError, decrypt_refresh_token, encrypt_refresh_token

            try:
                refresh_token = decrypt_refresh_token(self.refresh_token_encrypted)
            except CloudOAuthError as exc:
                raise CloudDriveError(
                    "OneDrive OAuth credential ใช้งานไม่ได้ กรุณาเชื่อมต่อบัญชีใหม่"
                ) from exc
            tenant = self.tenant_id or settings.MICROSOFT_OAUTH_TENANT
            if not settings.MICROSOFT_OAUTH_SCOPE:
                raise CloudDriveError("ยังไม่ได้ตั้งค่า Microsoft OAuth scope ใน backend/.env")
            try:
                resp = requests.post(
                    f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
                    data={
                        "client_id": settings.MICROSOFT_OAUTH_CLIENT_ID,
                        "client_secret": settings.MICROSOFT_OAUTH_CLIENT_SECRET,
                        "refresh_token": refresh_token,
                        "scope": settings.MICROSOFT_OAUTH_SCOPE,
                        "grant_type": "refresh_token",
                    },
                    timeout=DEFAULT_TIMEOUT,
                )
            except requests.RequestException as exc:
                raise CloudDriveError("ติดต่อ Microsoft เพื่อขอ access token ไม่สำเร็จ") from exc
            if resp.status_code != 200:
                raise CloudDriveError(f"ต่ออายุ Microsoft access token ไม่สำเร็จ: HTTP {resp.status_code} {resp.text[:300]}")
            try:
                body = resp.json()
            except ValueError as exc:
                raise CloudDriveError("Microsoft ส่งข้อมูล access token กลับมาไม่ถูกต้อง") from exc
            access_token = body.get("access_token")
            if not access_token:
                raise CloudDriveError("Microsoft ไม่ส่ง access token กลับมา")
            if body.get("refresh_token"):
                self._persist_refresh_token(body["refresh_token"], encrypt_refresh_token)
            return access_token
        resp = requests.post(
            f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token",
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            },
            timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code != 200:
            raise CloudDriveError(f"ขอ Microsoft access token ไม่สำเร็จ: HTTP {resp.status_code} {resp.text[:300]}")
        return resp.json()["access_token"]

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._token()}"}

    def _persist_refresh_token(self, token: str, encrypt) -> None:
        if not self.db or not self.integration:
            return
        try:
            self.integration.config = {
                **(self.integration.config or {}),
                "refresh_token_encrypted": encrypt(token),
            }
            self.db.commit()
            self.refresh_token_encrypted = self.integration.config["refresh_token_encrypted"]
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            raise CloudDriveError("บันทึก OAuth credential ใหม่ไม่สำเร็จ") from exc

    def list_folder(self, folder_id: str) -> List[Dict[str, Any]]:
        # folder_id "root" or empty → drive root; otherwise an item id
        seg = "root" if not folder_id or folder_id == "root" else f"items/{folder_id}"
        # Follow @odata.nextLink so folders with more than one page (>999
        # items) are fully listed instead of silently truncated.
        headers = self._headers()  # reuse one token across all pages
        url: str | None = f"{GRAPH_BASE}/drives/{self.drive_id}/{seg}/children"
        params: Dict[str, Any] | None = {"$select": "id,name,size,file", "$top": 999}
        items: List[Dict[str, Any]] = []
        while url:
            resp = requests.get(url, headers=headers, params=params, timeout=DEFAULT_TIMEOUT)
            if resp.status_code != 200:
                raise CloudDriveError(f"OneDrive list ล้มเหลว: HTTP {resp.status_code} {resp.text[:300]}")
            body = resp.json()
            items.extend(body.get("value", []))
            # nextLink already carries the query string; don't re-send params.
            url = body.get("@odata.nextLink")
            params = None
        # keep files only (skip subfolders)
        return [{"id": it["id"], "name": it["name"], "size": it.get("size"),
                 "mimeType": (it.get("file") or {}).get("mimeType")}
                for it in items if "file" in it]

    def list_children(self, folder_id: str = "root") -> List[Dict[str, Any]]:
        """List files and folders for the folder picker."""
        seg = "root" if not folder_id or folder_id == "root" else f"items/{folder_id}"
        try:
            resp = requests.get(
                f"{GRAPH_BASE}/drives/{self.drive_id}/{seg}/children",
                headers=self._headers(),
                params={"$select": "id,name,size,file,folder,lastModifiedDateTime", "$top": 999},
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise CloudDriveError("ติดต่อ OneDrive เพื่ออ่านโฟลเดอร์ไม่สำเร็จ") from exc
        if resp.status_code != 200:
            raise CloudDriveError(f"OneDrive อ่านโฟลเดอร์ไม่สำเร็จ: HTTP {resp.status_code} {resp.text[:300]}")
        try:
            items = resp.json().get("value", [])
        except ValueError as exc:
            raise CloudDriveError("OneDrive ส่งรายการโฟลเดอร์กลับมาไม่ถูกต้อง") from exc
        return [
            {**item, "is_folder": "folder" in item, "mimeType": (item.get("file") or {}).get("mimeType")}
            for item in items
        ]

    def download(self, item_id: str) -> bytes:
        resp = requests.get(
            f"{GRAPH_BASE}/drives/{self.drive_id}/items/{item_id}/content",
            headers=self._headers(), timeout=DEFAULT_TIMEOUT, allow_redirects=True,
        )
        if resp.status_code != 200:
            raise CloudDriveError(f"OneDrive download ล้มเหลว: HTTP {resp.status_code} {resp.text[:300]}")
        return resp.content

    def upload(self, folder_id: str, filename: str, data: bytes, mime_type: str = "application/octet-stream") -> Dict[str, Any]:
        # Simple upload (≤4MB). For larger files an upload session would be needed.
        if folder_id and folder_id != "root":
            path = f"items/{folder_id}:/{filename}:"
        else:
            path = f"root:/{filename}:"
        url = f"{GRAPH_BASE}/drives/{self.drive_id}/{path}/content"
        headers = self._headers()
        headers["Content-Type"] = mime_type
        resp = requests.put(url, headers=headers, data=data, timeout=DEFAULT_TIMEOUT)
        if resp.status_code not in (200, 201):
            raise CloudDriveError(f"OneDrive upload ล้มเหลว: HTTP {resp.status_code} {resp.text[:300]}")
        body = resp.json()
        return {"file_id": body.get("id"), "name": body.get("name"), "link": body.get("webUrl")}

    def check(self) -> Dict[str, Any]:
        resp = requests.get(
            f"{GRAPH_BASE}/drives/{self.drive_id}/root?$select=id,name",
            headers=self._headers(), timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code != 200:
            raise CloudDriveError(f"OneDrive ตรวจสอบ drive ล้มเหลว: HTTP {resp.status_code} {resp.text[:300]}")
        return {"provider": "onedrive", "drive": resp.json(), "ok": True}


def get_drive_client(integration, db: Any = None) -> Any:
    """Return the right client for an Integration row based on its type."""
    config = integration.config or {}
    if integration.type == "gdrive":
        return GoogleDriveClient(config, db=db, integration=integration)
    if integration.type == "onedrive":
        return OneDriveClient(config, db=db, integration=integration)
    raise CloudDriveError(f"Integration type '{integration.type}' ไม่รองรับสำหรับ cloud drive")
