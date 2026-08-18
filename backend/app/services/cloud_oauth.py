"""OAuth helpers for user-owned Google Drive and OneDrive connections."""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from typing import Any, Dict, Literal
from urllib.parse import urlencode, urlsplit

import requests
from cryptography.fernet import Fernet, InvalidToken
from jose import JWTError, jwt

from app.core.config import settings
from app.models.setting import Setting
from app.utils.secret_store import SecretStoreError, decrypt_secret

CloudProvider = Literal["google", "microsoft"]

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
MICROSOFT_AUTHORIZE_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
MICROSOFT_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
OAUTH_STATE_TTL_SECONDS = 10 * 60
OAUTH_TIMEOUT = 30
OAUTH_STATE_PREFIX = "insightdoc:oauth-state:"
DEFAULT_MICROSOFT_OAUTH_SCOPE = "openid profile email offline_access User.Read Files.ReadWrite"
DEFAULT_GOOGLE_OAUTH_SCOPE = "https://www.googleapis.com/auth/drive"


class CloudOAuthError(Exception):
    """A user-facing OAuth setup or token exchange error."""


def _is_local_origin(value: str | None) -> bool:
    """Return whether an origin points to a local development host."""
    if not value:
        return True
    try:
        hostname = (urlsplit(value).hostname or "").lower()
    except ValueError:
        return False
    return hostname in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def resolve_public_app_url(request: Any = None) -> str:
    """Resolve the public origin, preferring the configured deployment URL.

    Localhost is the development default. When it is still configured in a
    deployed instance, use the origin forwarded by nginx so OAuth links do
    not point users back to localhost. Deployments can still pin a canonical
    origin with PUBLIC_APP_URL.
    """
    configured = (settings.PUBLIC_APP_URL or "").strip().rstrip("/")
    if request is not None and _is_local_origin(configured):
        forwarded_host = request.headers.get("x-forwarded-host") or request.headers.get("host")
        forwarded_proto = request.headers.get("x-forwarded-proto") or request.url.scheme
        host = (forwarded_host or "").split(",", 1)[0].strip()
        if host and not _is_local_origin(f"{forwarded_proto}://{host}"):
            return f"{forwarded_proto}://{host}".rstrip("/")
    return configured or "http://localhost:3000"


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


def get_microsoft_oauth_config(db: Any = None) -> Dict[str, str | None]:
    """Resolve admin DB settings first, then deployment env defaults."""
    stored = db.query(Setting).first() if db is not None else None
    client_secret = settings.MICROSOFT_OAUTH_CLIENT_SECRET
    encrypted_secret = getattr(stored, "microsoft_oauth_client_secret_encrypted", None)
    if encrypted_secret:
        try:
            client_secret = decrypt_secret(encrypted_secret)
        except SecretStoreError as exc:
            raise CloudOAuthError("ไม่สามารถถอดรหัส Microsoft OAuth Client Secret ได้") from exc
    return {
        "client_id": getattr(stored, "microsoft_oauth_client_id", None) or settings.MICROSOFT_OAUTH_CLIENT_ID,
        "client_secret": client_secret,
        "tenant": getattr(stored, "microsoft_oauth_tenant", None) or settings.MICROSOFT_OAUTH_TENANT,
        "redirect_uri": getattr(stored, "microsoft_oauth_redirect_uri", None) or settings.MICROSOFT_OAUTH_REDIRECT_URI,
        "scope": getattr(stored, "microsoft_oauth_scope", None) or settings.MICROSOFT_OAUTH_SCOPE or DEFAULT_MICROSOFT_OAUTH_SCOPE,
    }


def get_google_oauth_config(db: Any = None) -> Dict[str, str | None]:
    """Resolve admin DB settings first, then deployment env defaults."""
    stored = db.query(Setting).first() if db is not None else None
    client_secret = settings.GOOGLE_OAUTH_CLIENT_SECRET
    encrypted_secret = getattr(stored, "google_oauth_client_secret_encrypted", None)
    if encrypted_secret:
        try:
            client_secret = decrypt_secret(encrypted_secret)
        except SecretStoreError as exc:
            raise CloudOAuthError("ไม่สามารถถอดรหัส Google OAuth Client Secret ได้") from exc
    return {
        "client_id": getattr(stored, "google_oauth_client_id", None) or settings.GOOGLE_OAUTH_CLIENT_ID,
        "client_secret": client_secret,
        "redirect_uri": getattr(stored, "google_oauth_redirect_uri", None) or settings.GOOGLE_OAUTH_REDIRECT_URI,
        "scope": getattr(stored, "google_oauth_scope", None) or settings.GOOGLE_OAUTH_SCOPE or DEFAULT_GOOGLE_OAUTH_SCOPE,
    }


def _redirect_uri(provider: CloudProvider, db: Any = None, public_app_url: str | None = None) -> str:
    configured = (
        get_google_oauth_config(db)["redirect_uri"] if provider == "google"
        else get_microsoft_oauth_config(db)["redirect_uri"]
    )
    public_origin = public_app_url or resolve_public_app_url()
    # A stale localhost value can remain from an earlier development setup.
    # Do not send production users to localhost when a public origin is known.
    if configured and not (_is_local_origin(configured) and not _is_local_origin(public_origin)):
        return configured
    return f"{public_origin.rstrip('/')}{settings.API_V1_STR}/integrations/oauth/{provider}/callback"


def _client_config(provider: CloudProvider, db: Any = None) -> tuple[str, str]:
    if provider == "google":
        config = get_google_oauth_config(db)
        client_id, client_secret = config["client_id"], config["client_secret"]
    else:
        config = get_microsoft_oauth_config(db)
        client_id, client_secret = config["client_id"], config["client_secret"]
    if not client_id or not client_secret:
        label = "Google Drive" if provider == "google" else "OneDrive"
        raise CloudOAuthError(f"ยังไม่ได้ตั้งค่า OAuth สำหรับ {label} ใน Settings")
    return client_id, client_secret


def _scope_config(provider: CloudProvider, db: Any = None) -> str:
    scope = get_google_oauth_config(db)["scope"] if provider == "google" else get_microsoft_oauth_config(db)["scope"]
    if not scope or not scope.strip():
        label = "Google Drive" if provider == "google" else "OneDrive"
        raise CloudOAuthError(f"ยังไม่ได้ตั้งค่า OAuth scope สำหรับ {label} ใน Settings")
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


def authorization_url(
    provider: CloudProvider,
    user_id: str,
    db: Any = None,
    public_app_url: str | None = None,
) -> str:
    client_id, _ = _client_config(provider, db)
    scope = _scope_config(provider, db)
    redirect_uri = _redirect_uri(provider, db, public_app_url)
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
    tenant = get_microsoft_oauth_config(db)["tenant"]
    return f"{MICROSOFT_AUTHORIZE_URL.format(tenant=tenant)}?{urlencode(params)}"


def _exchange_code(
    provider: CloudProvider,
    code: str,
    db: Any = None,
    public_app_url: str | None = None,
) -> Dict[str, Any]:
    client_id, client_secret = _client_config(provider, db)
    redirect_uri = _redirect_uri(provider, db, public_app_url)
    if provider == "google":
        url = GOOGLE_TOKEN_URL
    else:
        url = MICROSOFT_TOKEN_URL.format(tenant=get_microsoft_oauth_config(db)["tenant"])
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


def complete_authorization(
    provider: CloudProvider,
    code: str,
    db: Any = None,
    public_app_url: str | None = None,
) -> Dict[str, Any]:
    tokens = _exchange_code(provider, code, db, public_app_url)
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
