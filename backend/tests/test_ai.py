from types import SimpleNamespace

import pytest

from app import ai


def _client_returning(content, reasoning_content=None):
    message = SimpleNamespace(content=content, reasoning_content=reasoning_content)
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    create = lambda **kwargs: response
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


@pytest.mark.parametrize(
    "content, reasoning, expected",
    [
        ('{"answer": "a"}', None, {"answer": "a"}),
        # LM Studio's reasoning parser can put a thinking model's whole output here.
        ("", '{"answer": "b"}', {"answer": "b"}),
        ("not json", None, {}),
    ],
)
def test_complete_json_reads_content_or_reasoning(monkeypatch, content, reasoning, expected):
    monkeypatch.setattr(ai, "_client", lambda: _client_returning(content, reasoning))
    assert ai.complete_json("system", "user", {}) == expected
