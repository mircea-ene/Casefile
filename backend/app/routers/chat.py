import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import tracing
from app.auth import CurrentUser, get_current_user
from app.conversations import ConversationNotFound, generate_title, owned_conversation, record_turn, turn_out
from app.db import get_db
from app.rag import DocumentNotFound, answer_question, parse_document_ids
from app.schemas import ChatRequest, ChatResponse

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Check the conversation before the (slow) answer, so a bad id fails fast.
    conversation = None
    if body.conversation_id is not None:
        try:
            conversation = owned_conversation(db, user.owner_id, body.conversation_id)
        except ConversationNotFound:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    # A new conversation's id is picked now so the trace can carry it as its session.
    conversation_id = conversation.id if conversation is not None else uuid.uuid4()
    with tracing.trace(
        "chat", user_id=user.owner_id, session_id=str(conversation_id), input=body.question
    ) as root:
        try:
            document_ids = parse_document_ids(body.document_ids)
            result = answer_question(db, user.owner_id, body.question, document_ids)
        except DocumentNotFound:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
        root.update(output=result.answer or "(insufficient evidence)")

    conversation, turn, created = record_turn(
        db, user.owner_id, conversation, body.question, document_ids, result, new_conversation_id=conversation_id
    )
    db.commit()
    if created:
        background_tasks.add_task(generate_title, conversation.id)
    return ChatResponse(**turn_out(turn).model_dump(), conversation_id=conversation.id)
