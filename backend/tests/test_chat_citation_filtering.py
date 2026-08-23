def test_only_sources_explicitly_cited_in_answer_are_visible():
    from processors.citations import select_cited_sources

    sources = [
        {"index": 1, "title": "贾龙飞论文"},
        {"index": 2, "title": "其他分割论文"},
        {"index": 3, "title": "FedSPCA"},
    ]

    assert select_cited_sources("结论只来自目标论文[来源1]。", sources) == [sources[0]]


def test_uncited_retrieval_candidates_are_not_presented_as_references():
    from processors.citations import select_cited_sources

    assert select_cited_sources("这是未引用来源的普通回答。", [{"index": 1}]) == []
