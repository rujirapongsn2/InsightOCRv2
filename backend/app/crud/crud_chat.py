from typing import List, Optional
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.chat import ChatConversation, ChatMessage


class CRUDChat:
    def create_conversation(
        self, db: Session, *, job_id: UUID, user_id: UUID, integration_id: Optional[UUID] = None
    ) -> ChatConversation:
        conversation = ChatConversation(
            job_id=job_id,
            user_id=user_id,
            integration_id=integration_id,
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        return conversation

    def get_conversation(self, db: Session, conversation_id: UUID) -> Optional[ChatConversation]:
        return db.query(ChatConversation).filter(ChatConversation.id == conversation_id).first()

    def get_conversations_by_job(
        self, db: Session, job_id: UUID, user_id: UUID
    ) -> List[ChatConversation]:
        return (
            db.query(ChatConversation)
            .filter(ChatConversation.job_id == job_id, ChatConversation.user_id == user_id)
            .order_by(ChatConversation.updated_at.desc())
            .all()
        )

    def delete_conversation(self, db: Session, conversation_id: UUID) -> bool:
        conv = self.get_conversation(db, conversation_id)
        if not conv:
            return False
        db.delete(conv)
        db.commit()
        return True

    def add_message(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        role: str,
        content: str,
        model_used: Optional[str] = None,
    ) -> ChatMessage:
        message = ChatMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            model_used=model_used,
        )
        db.add(message)
        db.commit()
        db.refresh(message)
        return message

    def get_messages(
        self, db: Session, conversation_id: UUID, limit: int = 50
    ) -> List[ChatMessage]:
        return (
            db.query(ChatMessage)
            .filter(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.created_at.asc())
            .limit(limit)
            .all()
        )

    def update_title(self, db: Session, conversation_id: UUID, title: str) -> None:
        conv = self.get_conversation(db, conversation_id)
        if conv:
            conv.title = title
            db.commit()

    def get_message_count(self, db: Session, conversation_id: UUID) -> int:
        return (
            db.query(func.count(ChatMessage.id))
            .filter(ChatMessage.conversation_id == conversation_id)
            .scalar()
        )


chat = CRUDChat()
