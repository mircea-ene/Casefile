import pytest

from app import chunking
from app.chunking import chunk_document, clause_label, is_definition
from app.config import get_settings
from app.parsing import Element


@pytest.fixture(autouse=True)
def word_tokens(monkeypatch):
    # Deterministic and offline: one token per word.
    monkeypatch.setattr(chunking, "count_tokens", lambda text: len(text.split()))
    settings = get_settings()
    monkeypatch.setattr(settings, "chunk_min_tokens", 20)
    monkeypatch.setattr(settings, "chunk_max_tokens", 60)


def text(t, page=1):
    return Element("text", t, page, page)


def heading(t, page=1):
    return Element("heading", t, page, page)


def words(n, word="lorem"):
    return " ".join([word] * n) + "."


@pytest.mark.parametrize(
    "line, label",
    [
        ("4. Term and Termination. (a) The initial term shall be one year.", "4. Term and Termination"),
        ("12.2 Notice. Either party may terminate.", "12.2 Notice"),
        ("§ 3 Payment: Fees are due monthly.", "§ 3 Payment"),
        ("ARTICLE IV CONFIDENTIALITY", "ARTICLE IV"),
        ("Section 5.1 The Supplier shall deliver.", "Section 5.1"),
        ("3.5 million dollars shall be paid.", None),
        ("2020 revenue was high.", None),
        ("The tenant shall pay rent.", None),
    ],
)
def test_clause_label(line, label):
    assert clause_label(line) == label


def test_definitions_are_recognised():
    assert is_definition('(a) "Auction" means a real-time auction.')
    assert is_definition("“Affiliate” shall mean any entity controlling a party.")
    assert not is_definition('The "Agreement" is binding.')


def test_clauses_become_chunks_with_breadcrumbs_and_pages():
    elements = [
        heading("MASTER SERVICES AGREEMENT"),
        text("4. Term and Termination. " + words(30)),
        text("(b) Either party may terminate on ninety (90) days' prior written notice. " + words(10), page=2),
        heading("14. General Provisions.", page=3),
        text("(a) This Agreement is governed by the laws of Delaware. " + words(25), page=3),
    ]
    chunks = chunk_document(elements, title="Lease")
    termination = next(c for c in chunks if "ninety (90) days" in c.content)
    assert termination.section == "4. Term and Termination"
    assert termination.heading_path == "MASTER SERVICES AGREEMENT > 4. Term and Termination"
    assert (termination.page_start, termination.page_end) == (1, 2)
    assert termination.embed_text.startswith("Lease > MASTER SERVICES AGREEMENT > 4. Term and Termination\n")
    # The title block has no body of its own, so it travels with the first clause.
    assert termination.content.startswith("MASTER SERVICES AGREEMENT\n4. Term and Termination.")
    governing = next(c for c in chunks if "Delaware" in c.content)
    assert governing.heading_path == "MASTER SERVICES AGREEMENT > 14. General Provisions."


def test_subsection_nests_under_its_parent():
    elements = [heading("3. DISTRIBUTION"), text(words(25)), heading("3.9 Reporting."), text(words(25, "report"))]
    chunks = chunk_document(elements, title="Deal")
    assert chunks[-1].heading_path == "3. DISTRIBUTION > 3.9 Reporting."


def test_small_sibling_clauses_merge_and_large_ones_split():
    elements = [
        text("5. Fees. Fees are due monthly."),
        text("6. Taxes. Each party pays its own taxes."),
        text("7. Liability. " + " ".join(f"Sentence {i} limits liability." for i in range(40))),
    ]
    chunks = chunk_document(elements, title="Deal")
    assert chunks[0].section == "5. Fees – 6. Taxes"
    assert "Fees are due" in chunks[0].content and "own taxes" in chunks[0].content
    liability = [c for c in chunks if c.section == "7. Liability"]
    assert len(liability) > 1
    assert all(c.token_count <= 60 for c in chunks)


def test_definitions_and_tables_get_their_own_type():
    elements = [
        text("1. Definitions. Capitalized terms have these meanings."),
        text('(a) "Auction" means a real-time auction.'),
        text('(b) "Bid" means a price offered in an Auction.'),
        Element("table", "| Fee | Amount |\n|---|---|\n| Setup | $100 |", 2, 2),
    ]
    chunks = chunk_document(elements, title="Deal")
    definition = next(c for c in chunks if c.element_type == "definition")
    assert '"Auction"' in definition.content and '"Bid"' in definition.content
    table = next(c for c in chunks if c.element_type == "table")
    assert table.content.startswith("| Fee | Amount |") and table.page_start == 2


def test_oversized_table_repeats_its_header():
    rows = "\n".join(f"| item {i} | {i} dollars |" for i in range(60))
    elements = [Element("table", f"| Item | Price |\n|---|---|\n{rows}", 1, 1)]
    chunks = chunk_document(elements, title="Prices")
    assert len(chunks) > 1
    assert all(c.content.startswith("| Item | Price |\n|---|---|") for c in chunks)


def test_exhibit_resets_the_outline():
    elements = [text("9. Notices. " + words(25)), heading("EXHIBIT A"), text("1. Scope. " + words(25))]
    chunks = chunk_document(elements, title="Deal")
    assert chunks[-1].heading_path == "EXHIBIT A > 1. Scope"


def test_chunks_are_grouped_into_top_level_sections(monkeypatch):
    monkeypatch.setattr(get_settings(), "section_embed_max_tokens", 1000)
    monkeypatch.setattr(chunking, "_tokenizer", lambda: None)
    elements = [
        heading("SERVICES AGREEMENT"),
        text("This agreement is made between A and B. " + words(25)),
        heading("2. VENDOR OBLIGATIONS"),
        text("2.1 Privacy. " + words(30, "privacy")),
        text("2.2 Support. " + words(30, "support")),
        heading("3. CUSTOMER OBLIGATIONS"),
        text("3.1 Payment. " + words(30, "payment")),
        heading("EXHIBIT A"),
        text("1. Service Levels. " + words(30, "uptime")),
    ]
    drafts = chunk_document(elements, title="Agreement")
    assert [d.section_path for d in drafts] == [
        ("SERVICES AGREEMENT",),
        ("SERVICES AGREEMENT", "2. VENDOR OBLIGATIONS"),
        ("SERVICES AGREEMENT", "2. VENDOR OBLIGATIONS"),
        ("SERVICES AGREEMENT", "3. CUSTOMER OBLIGATIONS"),
        ("SERVICES AGREEMENT", "EXHIBIT A"),
    ]

    sections = chunking.build_sections(drafts, title="Agreement")
    assert [s.heading_path for s in sections] == [
        "SERVICES AGREEMENT",
        "SERVICES AGREEMENT > 2. VENDOR OBLIGATIONS",
        "SERVICES AGREEMENT > 3. CUSTOMER OBLIGATIONS",
        "SERVICES AGREEMENT > EXHIBIT A",
    ]
    assert sections[1].chunk_indexes == [1, 2]
    assert sections[1].token_count == drafts[1].token_count + drafts[2].token_count
    assert sections[1].embed_text.startswith("Agreement > SERVICES AGREEMENT > 2. VENDOR OBLIGATIONS\n2. VENDOR OBLIGATIONS")
    assert "support" in sections[1].embed_text


def test_section_embed_text_is_truncated(monkeypatch):
    monkeypatch.setattr(get_settings(), "section_embed_max_tokens", 10)
    monkeypatch.setattr(chunking, "_tokenizer", lambda: None)  # chars / 4
    drafts = chunk_document([text("1. Scope. " + words(30))], title="T")
    (section,) = chunking.build_sections(drafts, title="T")
    assert len(section.embed_text) == 40
