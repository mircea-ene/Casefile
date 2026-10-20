"""Chat history: conversations, their turns, and LLM-generated titles."""

import logging
import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import ai, tracing
from app.db import SessionLocal
from app.models import Conversation, Turn
from app.schemas import ChatAnswer, ConversationOut, TurnOut

log = logging.getLogger(__name__)

TITLE_MAX_CHARS = 120
FALLBACK_TITLE_CHARS = 80

TITLE_PROMPT = """Write a short title (3 to 8 words) for a conversation that starts with the user's question below.
Name the subject (document, clause, topic), not the act of asking. No quotes, no trailing period."""

TITLE_SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"}},
    "required": ["title"],
    "additionalProperties": False,
}


class ConversationNotFound(Exception):
    pass


def owned_conversation(db: Session, owner_id: str, raw_id: str) -> Conversation:
    """404 semantics: malformed ids and other owners' conversations look the same."""
    try:
        conversation_id = uuid.UUID(raw_id)
    except ValueError:
        raise ConversationNotFound
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.owner_id != owner_id:
        raise ConversationNotFound
    return conversation


def fallback_title(question: str) -> str:
    """The start of the first question, cut at a word boundary."""
    question = " ".join(question.split())
    if len(question) <= FALLBACK_TITLE_CHARS:
        return question
    cut = question[:FALLBACK_TITLE_CHARS].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "…"


def conversation_out(conversation: Conversation, first_question: str) -> ConversationOut:
    return ConversationOut(
        id=conversation.id,
        title=conversation.custom_title or conversation.generated_title or fallback_title(first_question),
        title_is_custom=conversation.custom_title is not None,
        title_pending=conversation.custom_title is None and conversation.generated_title is None,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def first_questions(db: Session, conversation_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    rows = db.execute(
        select(Turn.conversation_id, Turn.question)
        .where(Turn.conversation_id.in_(conversation_ids))
        .distinct(Turn.conversation_id)
        .order_by(Turn.conversation_id, Turn.created_at)
    )
    return dict(rows.tuples().all())


def record_turn(
    db: Session,
    owner_id: str,
    conversation: Conversation | None,
    question: str,
    document_ids: list[uuid.UUID] | None,
    result: ChatAnswer,
    new_conversation_id: uuid.UUID | None = None,
) -> tuple[Conversation, Turn, bool]:
    """Saves the answered question; creates the conversation on its first turn
    (with `new_conversation_id`, if given). Returns (conversation, turn, created).
    Not committed."""
    created = conversation is None
    if conversation is None:
        conversation = Conversation(id=new_conversation_id or uuid.uuid4(), owner_id=owner_id)
        db.add(conversation)
    turn = Turn(
        conversation=conversation,
        owner_id=owner_id,
        question=question,
        document_ids=document_ids,
        answer=result.answer,
        citations=[c.model_dump() for c in result.citations],
        sources=[s.model_dump() for s in result.sources],
        insufficient_evidence=result.insufficient_evidence,
    )
    db.add(turn)
    db.flush()
    # The turn's created_at is the transaction's now(); use the same for ordering the list.
    db.refresh(turn, ["created_at"])
    conversation.updated_at = turn.created_at
    return conversation, turn, created


def turn_out(turn: Turn) -> TurnOut:
    return TurnOut.model_validate(turn)


def generate_title(conversation_id: uuid.UUID) -> None:
    """Background task after a conversation's first turn. Falls back to the start
    of the question if the LLM fails, so the title never stays pending."""
    with SessionLocal() as db:
        first = db.execute(
            select(Turn.question, Turn.owner_id)
            .where(Turn.conversation_id == conversation_id)
            .order_by(Turn.created_at)
            .limit(1)
        ).first()
        if first is None:  # deleted meanwhile
            return
        question, owner_id = first
        title = ""
        try:
            with tracing.trace("title", user_id=owner_id, session_id=str(conversation_id), input=question) as root:
                raw = ai.complete_json(TITLE_PROMPT, question, TITLE_SCHEMA, name="title")
                root.update(output=raw)
            title = " ".join(str(raw.get("title") or "").split()).strip("\"'“”").rstrip(".")
        except Exception:
            log.exception("Title generation failed for conversation %s", conversation_id)
        if not title:
            title = fallback_title(question)
        db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(generated_title=title[:TITLE_MAX_CHARS])
        )
        db.commit()


def fill_interrupted_titles() -> None:
    """Title tasks don't survive a restart; don't leave titles pending forever."""
    with SessionLocal() as db:
        pending = db.scalars(select(Conversation).where(Conversation.generated_title.is_(None))).all()
        questions = first_questions(db, [c.id for c in pending])
        for conversation in pending:
            conversation.generated_title = fallback_title(questions.get(conversation.id, "Untitled conversation"))
        db.commit()
