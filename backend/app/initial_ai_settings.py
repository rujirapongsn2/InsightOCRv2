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
        existing.display_name = "Softnix GenAI"
        existing.api_url = provider_url
        existing.api_key = provider_key
        existing.is_active = True
        existing.is_default = True
        existing.description = existing.description or "Default Softnix GenAI provider for field suggestions"

        db.query(AISettings).filter(AISettings.name != "softnix_genai").update({"is_default": False})
        db.commit()
        print("Synced default AI setting: Softnix GenAI")
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
