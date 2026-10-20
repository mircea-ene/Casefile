from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import CurrentUser, get_current_user
from app.conversations import (
    ConversationNotFound,
    conversation_out,
    first_questions,
    owned_conversation,
    turn_out,
)
from app.db import get_db
from app.models import Conversation
from app.schemas import ConversationDetail, ConversationList, ConversationOut, ConversationUpdate

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _owned(db: Session, user: CurrentUser, conversation_id: str) -> Conversation:
    try:
        return owned_conversation(db, user.owner_id, conversation_id)
    except ConversationNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")


@router.get("", response_model=ConversationList)
def list_conversations(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    conversations = db.scalars(
        select(Conversation)
        .where(Conversation.owner_id == user.owner_id)
        .order_by(Conversation.updated_at.desc())
    ).all()
    questions = first_questions(db, [c.id for c in conversations])
    return ConversationList(conversations=[conversation_out(c, questions.get(c.id, "")) for c in conversations])


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: str, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)
):
    conversation = _owned(db, user, conversation_id)
    turns = conversation.turns
    summary = conversation_out(conversation, turns[0].question if turns else "")
    return ConversationDetail(**summary.model_dump(), turns=[turn_out(t) for t in turns])


@router.patch("/{conversation_id}", response_model=ConversationOut)
def rename_conversation(
    conversation_id: str,
    body: ConversationUpdate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sets the user's title; null or blank goes back to the generated one.
    Doesn't change updated_at, so renaming doesn't reorder the list."""
    conversation = _owned(db, user, conversation_id)
    conversation.custom_title = body.title
    db.commit()
    return conversation_out(conversation, first_questions(db, [conversation.id]).get(conversation.id, ""))


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: str, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)
):
    db.delete(_owned(db, user, conversation_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
