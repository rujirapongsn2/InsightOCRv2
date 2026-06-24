from sqlalchemy.orm import Session
from app.core.config import settings
from app.models.ai_settings import AISettings


def init_ai_settings(db: Session) -> None:
    """
    Initialize default AI settings for Softnix GenAI
    """
    provider_url = settings.AI_PROVIDER_URL or "https://genai.softnix.ai/external/api/completion-messages"
    provider_key = settings.AI_PROVIDER_KEY or ""

    # Check if default setting already exists
    existing = db.query(AISettings).filter(AISettings.name == "softnix_genai").first()
    if existing:
        # Only overwrite fields that are explicitly configured via env vars.
        # If env vars are not set, preserve whatever the admin saved through the UI.
        if settings.AI_PROVIDER_URL:
            existing.api_url = provider_url
        if settings.AI_PROVIDER_KEY:
            existing.api_key = provider_key
        existing.description = existing.description or "Default Softnix GenAI provider for field suggestions"

        db.commit()
        print("Checked default AI setting: Softnix GenAI (env-only fields synced)")
        return

    # Create default Softnix GenAI setting
    default_setting = AISettings(
        name="softnix_genai",
        display_name="Softnix GenAI",
        api_url=provider_url,
        api_key=provider_key,
        is_active=True,
        is_default=True,
        description="Default Softnix GenAI provider for field suggestions"
    )

    db.add(default_setting)
    db.commit()
    print(f"Created default AI setting: {default_setting.display_name}")
