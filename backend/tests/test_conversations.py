from app.conversations import fallback_title
from app.schemas import ConversationUpdate


def test_fallback_title_keeps_short_questions():
    assert fallback_title("  What is the   notice period? ") == "What is the notice period?"


def test_fallback_title_cuts_long_questions_at_a_word():
    question = "What does the agreement say about " + "termination for convenience, " * 5
    title = fallback_title(question)
    assert title.endswith("…") and len(title) <= 81
    assert question.startswith(title[:-1])


def test_blank_title_resets_to_generated():
    assert ConversationUpdate(title="   ").title is None
    assert ConversationUpdate(title=None).title is None
    assert ConversationUpdate(title=" Lease notes ").title == "Lease notes"
