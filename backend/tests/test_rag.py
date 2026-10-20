import uuid

from app.rag import Source, build_answer


def _sources():
    return [
        Source(uuid.uuid4(), uuid.uuid4(), "Lease.pdf", 14, "§12.2", None,
               "Either party may terminate this lease on ninety (90) days' prior written notice."),
        Source(uuid.uuid4(), uuid.uuid4(), "Lease.pdf", 20, None, None,
               "Notices shall be sent to the address in Schedule B."),
    ]


def test_markers_are_renumbered_to_citation_order():
    sources = _sources()
    raw = {
        "insufficient_evidence": False,
        "answer": "Notices go to Schedule B [2]. Termination needs 90 days' notice [1].",
        "citations": [
            {"source": 1, "quote": "ninety (90) days' prior   written notice"},
            {"source": 2, "quote": "the address in Schedule B"},
        ],
    }
    result = build_answer(raw, sources)
    assert result.answer == "Notices go to Schedule B [1]. Termination needs 90 days' notice [2]."
    assert [c.id for c in result.citations] == [str(sources[1].chunk_id), str(sources[0].chunk_id)]
    assert result.citations[1].quote == "ninety (90) days' prior written notice"


def test_unverifiable_quotes_are_dropped():
    raw = {
        "insufficient_evidence": False,
        "answer": "Termination needs 30 days' notice [1]. Notices go to Schedule B [2].",
        "citations": [
            {"source": 1, "quote": "thirty days' notice"},
            {"source": 2, "quote": "the address in Schedule B"},
        ],
    }
    result = build_answer(raw, _sources())
    assert result.answer == "Termination needs 30 days' notice. Notices go to Schedule B [1]."
    assert len(result.citations) == 1


def test_no_verified_citation_means_insufficient_evidence():
    raw = {"insufficient_evidence": False, "answer": "Probably 30 days [1].",
           "citations": [{"source": 1, "quote": "made up"}]}
    result = build_answer(raw, _sources())
    assert result.insufficient_evidence and result.citations == [] and result.answer == ""


def test_sources_list_every_chunk_with_its_citation_number():
    sources = _sources()
    raw = {
        "insufficient_evidence": False,
        "answer": "Notices go to Schedule B [2].",
        "citations": [{"source": 2, "quote": "the address in Schedule B"}],
    }
    result = build_answer(raw, sources)
    assert [s.id for s in result.sources] == [str(sources[0].chunk_id), str(sources[1].chunk_id)]
    assert [s.citation for s in result.sources] == [None, 1]
    assert result.sources[1].content == sources[1].content


def test_refusal_still_returns_the_sources():
    result = build_answer({"insufficient_evidence": True, "answer": "", "citations": []}, _sources())
    assert result.insufficient_evidence
    assert len(result.sources) == 2 and all(s.citation is None for s in result.sources)


def test_only_page_relative_bboxes_are_returned():
    source = _sources()[0]
    source.bboxes = [
        {"page": 14, "l": 50.0, "t": 700.0, "r": 540.0, "b": 650.0},  # pre parser_version 3
        {"page": 14, "x": 0.08, "y": 0.1, "width": 0.8, "height": 0.05},
    ]
    raw = {
        "insufficient_evidence": False,
        "answer": "Ninety days [1].",
        "citations": [{"source": 1, "quote": "ninety (90) days"}],
    }
    citation = build_answer(raw, [source]).citations[0]
    assert [b.model_dump() for b in citation.bboxes] == [
        {"page": 14, "x": 0.08, "y": 0.1, "width": 0.8, "height": 0.05}
    ]


def test_markdown_list_layout_survives_marker_removal():
    raw = {
        "insufficient_evidence": False,
        "answer": "Two rules apply:\n\n- **12.2 Notice:** ninety days [1]\n  - in writing [2]\n- Schedule B address [9] .",
        "citations": [{"source": 1, "quote": "ninety (90) days"}],
    }
    result = build_answer(raw, _sources())
    assert result.answer == "Two rules apply:\n\n- **12.2 Notice:** ninety days [1]\n  - in writing\n- Schedule B address."


def test_section_expansion_rules():
    from app.rag import _expand_reason

    question = "What are Votocast's obligations in the agreement?"
    q = {"votocast", "oblig", "agreement"}  # Postgres english lexemes
    assert _expand_reason(2, "6. WARRANTIES", {"6", "warranti"}, question, q, False) == "2 hits"
    assert _expand_reason(1, "2. VOTOCAST'S OBLIGATIONS", {"2", "votocast", "oblig"}, question, q, False) == "heading"
    assert _expand_reason(1, "3. LICENSEE'S OBLIGATIONS", {"3", "license", "oblig"}, question, q, False) == "heading"
    assert _expand_reason(1, "SERVICES AND HOSTING AGREEMENT", {"servic", "host", "agreement"}, question, q, False) is None
    assert _expand_reason(1, "EXHIBIT D", {"exhibit", "d"}, question, q, True) == "section embedding"
    assert _expand_reason(1, "10. TERM", {"10", "term"}, "What does section 10 say?", set(), False) == "section number"
    assert _expand_reason(1, "10. TERM", {"10", "term"}, "What does clause 10.3 say?", set(), False) is None
