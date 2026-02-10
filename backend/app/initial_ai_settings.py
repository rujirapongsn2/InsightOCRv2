from sqlalchemy.orm import Session
from app.models.ai_settings import AISettings


def init_ai_settings(db: Session) -> None:
    """
    Initialize default AI settings for Softnix GenAI
    """
    # Check if default setting already exists
    existing = db.query(AISettings).filter(AISettings.name == "softnix_genai").first()
    if existing:
        print("AI settings already initialized")
        return

    # Create default Softnix GenAI setting
    default_setting = AISettings(
        name="softnix_genai",
        display_name="Softnix GenAI",
        api_url="https://genai.softnix.ai/external/api/completion-messages",
        api_key="eyJhbGciOiJIUzI1NiJ9.eyJuYW1lIjoib2NyIiwiYXBwX2lkIjoiNjkzMDNiOWM4MTFmN2JiNzIxY2Q3ZDllIiwib3duZXIiOiI2NzE3MzYxYTA5MTMzNWJlODA5NjBlMzAiLCJpYXQiOjE3NjQ3NjkxMjU2NzJ9.IXuWFOM7dhxHly2ypjeMgqiFHByp5UlSB5XkUy3iiP4",
        is_active=True,
        is_default=True,
        description="Default Softnix GenAI provider for field suggestions"
    )

    db.add(default_setting)
    db.commit()
    print(f"Created default AI setting: {default_setting.display_name}")
