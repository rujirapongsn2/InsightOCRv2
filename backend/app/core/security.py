from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any, Union, Optional
import secrets
from jose import jwt
from passlib.context import CryptContext
from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"
API_ACCESS_TOKEN_PREFIX = "sid_pat_"

def create_access_token(
    subject: Union[str, Any], expires_delta: Optional[timedelta] = None
) -> str:
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode = {"exp": expire, "sub": str(subject)}
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def generate_api_access_token() -> str:
    return f"{API_ACCESS_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def get_api_access_token_prefix(token: str, length: int = 12) -> str:
    return token[:length]


def hash_api_access_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)
