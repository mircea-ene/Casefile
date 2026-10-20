from app.routers.documents import _content_disposition


def test_content_disposition_keeps_non_ascii_names():
    header = _content_disposition("inline", 'Contrat "été".pdf')
    assert header == "inline; filename=\"Contrat '_t_'.pdf\"; filename*=UTF-8''Contrat%20%22%C3%A9t%C3%A9%22.pdf"
