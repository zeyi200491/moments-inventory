from moments_inventory.ai_kefu.indexing import split_document_to_chunks


def test_split_document_to_chunks_keeps_source_name_and_category():
    chunks = split_document_to_chunks(
        source_name="faq.txt",
        category="售后",
        text="ABCDEFGHIJ",
        chunk_size=4,
        chunk_overlap=1,
    )

    assert [chunk.source_name for chunk in chunks] == ["faq.txt", "faq.txt", "faq.txt"]
    assert [chunk.category for chunk in chunks] == ["售后", "售后", "售后"]
    assert [chunk.text for chunk in chunks] == ["ABCD", "DEFG", "GHIJ"]


def test_split_document_to_chunks_generates_stable_chunk_ids():
    first_chunks = split_document_to_chunks(
        source_name="manual.txt",
        category="参数",
        text="1234567890",
        chunk_size=5,
        chunk_overlap=2,
    )
    second_chunks = split_document_to_chunks(
        source_name="manual.txt",
        category="参数",
        text="1234567890",
        chunk_size=5,
        chunk_overlap=2,
    )

    assert [chunk.chunk_id for chunk in first_chunks] == [chunk.chunk_id for chunk in second_chunks]


def test_split_document_to_chunks_returns_empty_list_for_empty_text():
    chunks = split_document_to_chunks(
        source_name="faq.txt",
        category="售后",
        text="",
        chunk_size=4,
        chunk_overlap=1,
    )

    assert chunks == []


def test_split_document_to_chunks_supports_zero_overlap():
    chunks = split_document_to_chunks(
        source_name="faq.txt",
        category="物流",
        text="ABCDEFGH",
        chunk_size=4,
        chunk_overlap=0,
    )

    assert [chunk.text for chunk in chunks] == ["ABCD", "EFGH"]
