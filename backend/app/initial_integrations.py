"""One-time normalization for integration records created by older releases."""

from sqlalchemy.orm import Session

from app.models.integration import Integration, IntegrationType
from app.utils.redact import is_masked
from app.utils.secret_store import encrypt_secret


SOFTNIX_GENAI_BASE_URL = "https://genai.softnix.ai/external/openai"


def migrate_softnix_integrations(db: Session) -> None:
    """Encrypt legacy Softnix keys and normalize their server-owned endpoint."""
    changed = False
    integrations = db.query(Integration).filter(
        Integration.type == IntegrationType.SOFTNIX_GENAI,
    ).all()

    for integration in integrations:
        config = dict(integration.config or {})
        api_key = str(config.get("apiKey") or "").strip()
        if api_key and not is_masked(api_key) and not config.get("apiKeyEncrypted"):
            config["apiKeyEncrypted"] = encrypt_secret(api_key)
            config.pop("apiKey", None)
            changed = True
        if config.get("apiKeyEncrypted") and config.get("baseUrl") != SOFTNIX_GENAI_BASE_URL:
            config["baseUrl"] = SOFTNIX_GENAI_BASE_URL
            changed = True
        if config != (integration.config or {}):
            integration.config = config

    if changed:
        db.commit()
