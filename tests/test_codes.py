import pytest

from kamis_mcp.codes import codebook


def top(query):
    m = codebook().search(query)[0]
    return m.item_name, m.kind_name, m.item_code, m.kind_code


@pytest.mark.parametrize(
    "query, expected",
    [
        ("배추", ("배추", "봄", "211", "01")),
        ("대파", ("파", "대파", "246", "00")),  # 품목명은 '파', 품종명이 '대파'
        ("후지 사과", ("사과", "후지", "411", "05")),
        ("사과후지", ("사과", "후지", "411", "05")),
        ("청양고추", ("풋고추", "청양고추", "242", "03")),
        ("샤인머스켓", ("포도", "샤인머스켓", "414", "12")),
        ("돼지 삼겹살", ("돼지", "삼겹살", "4304", "27")),
    ],
)
def test_search_top_match(query, expected):
    assert top(query) == expected


def test_kinds_preferred_over_kindless_items():
    # 코드표엔 '대파'(274)라는 품종 없는 품목도 있는데, 조회 가능한 파/대파가 먼저 와야 한다.
    results = codebook().search("대파")
    assert results[0].kind_code is not None
    assert results[-1].item_code == "274" and results[-1].note


def test_livestock_flagged():
    m = codebook().search("삼겹살")[0]
    assert m.livestock and m.category_code == "500"


def test_unknown_returns_empty():
    assert codebook().search("없는품목") == []
    assert codebook().search("  ") == []


def test_rank_code_mapping():
    cb = codebook()
    assert cb.rank_name("04") == "상품"
    assert cb.graderank("04") == "1"  # 일별 API '04 상품' == 월별 API '1'
    assert cb.graderank("05") == "2"


def test_search_by_code_roundtrip():
    m = codebook().search_by_code("211", "03")[0]
    assert (m.item_name, m.kind_name, m.retail_unit) == ("배추", "가을", "1포기")
