"""OAuth helpers for user-owned Google Drive and OneDrive connections."""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from typing import Any, Dict, Literal
from urllib.parse import urlencode

import requests
from cryptography.fernet import Fernet, InvalidToken
from jose import JWTError, jwt

from app.core.config import settings

CloudProvider = Literal["google", "microsoft"]

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
MICROSOFT_AUTHORIZE_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
MICROSOFT_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
OAUTH_STATE_TTL_SECONDS = 10 * 60
OAUTH_TIMEOUT = 30
OAUTH_STATE_PREFIX = "insightdoc:oauth-state:"


class CloudOAuthError(Exception):
    """A user-facing OAuth setup or token exchange error."""


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_refresh_token(token: str) -> str:
    return _fernet().encrypt(token.encode("utf-8")).decode("utf-8")


def decrypt_refresh_token(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError) as exc:
        raise CloudOAuthError("ไม่สามารถถอดรหัส credential ของ cloud storage ได้") from exc


def _redirect_uri(provider: CloudProvider) -> str:
    configured = (
        settings.GOOGLE_OAUTH_REDIRECT_URI if provider == "google"
        else settings.MICROSOFT_OAUTH_REDIRECT_URI
    )
    return configured or f"{settings.PUBLIC_APP_URL.rstrip('/')}{settings.API_V1_STR}/integrations/oauth/{provider}/callback"


def _client_config(provider: CloudProvider) -> tuple[str, str]:
    if provider == "google":
        client_id, client_secret = settings.GOOGLE_OAUTH_CLIENT_ID, settings.GOOGLE_OAUTH_CLIENT_SECRET
    else:
        client_id, client_secret = settings.MICROSOFT_OAUTH_CLIENT_ID, settings.MICROSOFT_OAUTH_CLIENT_SECRET
    if not client_id or not client_secret:
        label = "Google Drive" if provider == "google" else "OneDrive"
        raise CloudOAuthError(f"ยังไม่ได้ตั้งค่า OAuth สำหรับ {label} ใน backend/.env")
    return client_id, client_secret


def _scope_config(provider: CloudProvider) -> str:
    scope = settings.GOOGLE_OAUTH_SCOPE if provider == "google" else settings.MICROSOFT_OAUTH_SCOPE
    if not scope or not scope.strip():
        label = "Google Drive" if provider == "google" else "OneDrive"
        raise CloudOAuthError(f"ยังไม่ได้ตั้งค่า OAuth scope สำหรับ {label} ใน backend/.env")
    return scope.strip()


def _state_token(provider: CloudProvider, user_id: str) -> str:
    now = int(time.time())
    claims = {
        "sub": str(user_id),
        "provider": provider,
        "nonce": secrets.token_urlsafe(24),
        "iat": now,
        "exp": now + OAUTH_STATE_TTL_SECONDS,
    }
    state = jwt.encode(claims, settings.SECRET_KEY, algorithm="HS256")
    try:
        from app.db.redis import get_redis_client
        get_redis_client().setex(
            f"{OAUTH_STATE_PREFIX}{claims['nonce']}",
            OAUTH_STATE_TTL_SECONDS,
            f"{provider}:{user_id}",
        )
    except Exception as exc:  # noqa: BLE001
        raise CloudOAuthError("ระบบ OAuth ยังไม่พร้อมใช้งาน กรุณาลองใหม่อีกครั้ง") from exc
    return state


def parse_state(state: str, provider: CloudProvider) -> str:
    try:
        claims = jwt.decode(state, settings.SECRET_KEY, algorithms=["HS256"])
    except JWTError as exc:
        raise CloudOAuthError("OAuth session หมดอายุหรือไม่ถูกต้อง กรุณาเริ่มเชื่อมต่อใหม่") from exc
    if claims.get("provider") != provider or not claims.get("sub"):
        raise CloudOAuthError("OAuth provider ไม่ตรงกับคำขอเดิม")
    return str(claims["sub"])


def consume_state(state: str, provider: CloudProvider) -> str:
    """Validate and consume a state token so it cannot be replayed."""
    user_id = parse_state(state, provider)
    try:
        claims = jwt.decode(state, settings.SECRET_KEY, algorithms=["HS256"])
        nonce = claims.get("nonce")
        if not nonce:
            raise CloudOAuthError("OAuth session ไม่ถูกต้อง กรุณาเริ่มเชื่อมต่อใหม่")
        from app.db.redis import get_redis_client
        stored = get_redis_client().getdel(f"{OAUTH_STATE_PREFIX}{nonce}")
    except CloudOAuthError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise CloudOAuthError("ไม่สามารถตรวจสอบ OAuth session ได้ กรุณาลองใหม่อีกครั้ง") from exc
    if stored != f"{provider}:{user_id}":
        raise CloudOAuthError("OAuth session หมดอายุหรือถูกใช้ไปแล้ว กรุณาเริ่มเชื่อมต่อใหม่")
    return user_id


def authorization_url(provider: CloudProvider, user_id: str) -> str:
    client_id, _ = _client_config(provider)
    scope = _scope_config(provider)
    redirect_uri = _redirect_uri(provider)
    state = _state_token(provider, user_id)
    if provider == "google":
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": scope,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{GOOGLE_AUTHORIZE_URL}?{urlencode(params)}"

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "response_mode": "query",
        "state": state,
    }
    return f"{MICROSOFT_AUTHORIZE_URL.format(tenant=settings.MICROSOFT_OAUTH_TENANT)}?{urlencode(params)}"


def _exchange_code(provider: CloudProvider, code: str) -> Dict[str, Any]:
    client_id, client_secret = _client_config(provider)
    redirect_uri = _redirect_uri(provider)
    if provider == "google":
        url = GOOGLE_TOKEN_URL
    else:
        url = MICROSOFT_TOKEN_URL.format(tenant=settings.MICROSOFT_OAUTH_TENANT)
    try:
        response = requests.post(
            url,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=OAUTH_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise CloudOAuthError("ติดต่อ OAuth provider ไม่สำเร็จ กรุณาลองใหม่อีกครั้ง") from exc
    if response.status_code != 200:
        try:
            detail = response.json().get("error_description") or response.text
        except ValueError:
            detail = response.text
        raise CloudOAuthError(f"แลก OAuth code ไม่สำเร็จ: {detail[:300]}")
    try:
        body = response.json()
    except ValueError as exc:
        raise CloudOAuthError("OAuth provider ส่งข้อมูลตอบกลับไม่ถูกต้อง") from exc
    if not body.get("access_token"):
        raise CloudOAuthError("OAuth provider ไม่ส่ง access token กลับมา")
    return body


def _profile(provider: CloudProvider, access_token: str) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}"}
    if provider == "google":
        try:
            response = requests.get("https://www.googleapis.com/oauth2/v3/userinfo", headers=headers, timeout=OAUTH_TIMEOUT)
        except requests.RequestException as exc:
            raise CloudOAuthError("ติดต่อ Google เพื่ออ่านบัญชีไม่สำเร็จ") from exc
        if response.status_code != 200:
            raise CloudOAuthError("อ่านบัญชี Google ไม่สำเร็จ")
        try:
            body = response.json()
        except ValueError as exc:
            raise CloudOAuthError("Google ส่งข้อมูลบัญชีกลับมาไม่ถูกต้อง") from exc
        return {"account_id": body.get("sub"), "account_email": body.get("email"), "account_name": body.get("name")}

    try:
        response = requests.get(
            "https://graph.microsoft.com/v1.0/me?$select=id,displayName,userPrincipalName,mail",
            headers=headers,
            timeout=OAUTH_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise CloudOAuthError("ติดต่อ Microsoft เพื่ออ่านบัญชีไม่สำเร็จ") from exc
    if response.status_code != 200:
        raise CloudOAuthError("อ่านบัญชี Microsoft ไม่สำเร็จ")
    try:
        body = response.json()
    except ValueError as exc:
        raise CloudOAuthError("Microsoft ส่งข้อมูลบัญชีกลับมาไม่ถูกต้อง") from exc
    return {
        "account_id": body.get("id"),
        "account_email": body.get("mail") or body.get("userPrincipalName"),
        "account_name": body.get("displayName"),
    }


def complete_authorization(provider: CloudProvider, code: str) -> Dict[str, Any]:
    tokens = _exchange_code(provider, code)
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise CloudOAuthError("ไม่ได้รับ refresh token จาก provider กรุณาอนุญาตการเข้าถึงอีกครั้ง")
    profile = _profile(provider, tokens["access_token"])
    result: Dict[str, Any] = {
        **profile,
        "refresh_token_encrypted": encrypt_refresh_token(refresh_token),
        "access_token_expires_at": int(time.time()) + int(tokens.get("expires_in", 3600)),
    }
    if provider == "microsoft":
        try:
            drive_response = requests.get(
                "https://graph.microsoft.com/v1.0/me/drive?$select=id,name,driveType",
                headers={"Authorization": f"Bearer {tokens['access_token']}"},
                timeout=OAUTH_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise CloudOAuthError("ติดต่อ Microsoft เพื่ออ่านพื้นที่ OneDrive ไม่สำเร็จ") from exc
        if drive_response.status_code != 200:
            raise CloudOAuthError("อ่านพื้นที่ OneDrive ไม่สำเร็จ")
        try:
            drive = drive_response.json()
        except ValueError as exc:
            raise CloudOAuthError("Microsoft ส่งข้อมูลพื้นที่ OneDrive กลับมาไม่ถูกต้อง") from exc
        if not drive.get("id"):
            raise CloudOAuthError("ไม่พบพื้นที่ OneDrive ของบัญชีนี้")
        result.update({"drive_id": drive.get("id"), "drive_name": drive.get("name"), "drive_type": drive.get("driveType")})
    return result
