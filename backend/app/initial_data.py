from sqlalchemy.orm import Session
from app.db.session import SessionLocal, engine
from app.db.base_class import Base
from app.models.user import User
from app.core.security import get_password_hash

def init_db(db: Session) -> None:
    # Create tables if they don't exist
    Base.metadata.create_all(bind=engine)
    
    user = db.query(User).filter(User.email == "admin@example.com").first()
    if not user:
        user = User(
            email="admin@example.com",
            hashed_password=get_password_hash("admin"),
            full_name="Initial Admin",
            is_superuser=True,
            role="admin"
        )
        db.add(user)
        db.commit()
        print("Superuser created")
    else:
        print("Superuser already exists")

if __name__ == "__main__":
    db = SessionLocal()
    init_db(db)
