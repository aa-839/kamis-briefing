"""원인 찾기: 코드 검사(check)와 그래프 흐름(search → extract → check → grade → 재시도)을 모델·검색 없이 검사한다."""

from datetime import date

from kamis_mcp.briefing.causes import (
    CauseFinder, Extraction, Grade, Source, check_extraction, mentions_item, news_start, overall_direction,
)  # fmt: skip

from test_briefing import fact

SURVEY = date(2026, 10, 16)
CABBAGE = fact("양배추", w=16.9)  # 1주 +16.9%, 비교일 2026-10-06(fact 기본값)
ARTICLE = Source(
    url="https://www.nongmin.com/article/1", title="무·양배추 경락값 분석", published="2026-10-12",
    text="양배추는 산지 교체 영향으로 공급이 줄었다. 무는 보합세다.",
)
GOOD = Extraction(found=True, source_index=0, quote="양배추는 산지 교체 영향으로 공급이 줄었다.", summary="산지 교체로 공급 감소")


def test_mentions_item_respects_word_boundary():
    assert mentions_item("토마토 출하량이 늘었다", "토마토")
    assert not mentions_item("대추방울토마토 출하량이 늘었다", "토마토")
    assert mentions_item("방울토마토와 토마토 모두", "토마토")
    assert not mentions_item("양배추 값", "배추")


def test_overall_direction():
    assert overall_direction("오이값 치솟아도 품절 걱정 덜었다") == 1
    assert overall_direction("배추값 약세 지속") == -1
    assert overall_direction("오르다 내렸다 반복… 상승 후 하락") == 0


def test_news_window_starts_before_comparison_day():
    assert news_start(CABBAGE, SURVEY) == date(2026, 10, 3)  # 비교일 10/06 - 3일


def test_check_accepts_verbatim_quote():
    assert check_extraction(GOOD, [ARTICLE], CABBAGE) is None


def test_check_rejects_paraphrase_other_item_wrong_direction_and_unsupported_summary():
    paraphrase = GOOD.model_copy(update={"quote": "양배추는 산지가 바뀌어 공급이 줄었다."})
    assert "그대로" in check_extraction(paraphrase, [ARTICLE], CABBAGE)

    other = Source(url="https://www.agrinet.co.kr/1", title="[품목포커스/대추방울토마토] 출하 증가",
                   published="2026-10-13", text="대추방울토마토는 출하량이 늘었다.")
    tomato = fact("토마토", w=-9.7)
    e = Extraction(found=True, source_index=0, quote="대추방울토마토는 출하량이 늘었다.", summary="출하량 증가")
    assert "토마토" in check_extraction(e, [other], tomato)

    up_title = Source(url="https://www.mt.co.kr/1", title="오이값 치솟아도 품절 걱정 덜었다", published="2026-10-03",
                      text="오이는 스마트팜으로 공급이 안정됐다.")
    cucumber = fact("오이", w=-8.8)
    e = Extraction(found=True, source_index=0, quote="오이는 스마트팜으로 공급이 안정됐다.", summary="스마트팜 공급 안정")
    assert "기사 제목" in check_extraction(e, [up_title], cucumber)

    invented = GOOD.model_copy(update={"summary": "이상기후로 작황 부진"})
    assert "요약" in check_extraction(invented, [ARTICLE], CABBAGE)


class FakeSearch:
    def __init__(self, results):
        self.results, self.queries = results, []

    def search(self, query, start, end, n=6):
        self.queries.append(query)
        return self.results


def finder(search, extractions, grades):
    f = CauseFinder(model="test:fake", search=search)
    calls = {"extract": [], "grade": []}

    def extract(messages):
        calls["extract"].append(messages)
        return extractions[len(calls["extract"]) - 1]

    def grade(messages):
        calls["grade"].append(messages)
        return grades[len(calls["grade"]) - 1]

    f._extract_llm, f._grade_llm = extract, grade
    return f, calls


def test_accepts_verified_and_graded_cause():
    f, calls = finder(FakeSearch([ARTICLE]), [GOOD], [Grade(relevant=True, reason="적절")])
    cause = f.find(CABBAGE, SURVEY)
    assert cause["publisher"] == "농민신문" and cause["quote"] == GOOD.quote
    assert len(calls["extract"]) == 1 and len(calls["grade"]) == 1


def test_check_failure_gets_one_re_extract_with_feedback():
    bad = GOOD.model_copy(update={"quote": "양배추 공급이 줄었다고 함"})
    f, calls = finder(FakeSearch([ARTICLE]), [bad, GOOD], [Grade(relevant=True, reason="적절")])
    assert f.find(CABBAGE, SURVEY)
    assert "이전 답의 문제" in calls["extract"][1][-1][1]
    assert f.rejected[0]["by"] == "check"


def test_grade_rejection_moves_to_next_query_and_finally_gives_up():
    search = FakeSearch([ARTICLE])
    no = Grade(relevant=False, reason="시기가 다름")
    f, calls = finder(search, [GOOD] * 3, [no] * 3)
    assert f.find(CABBAGE, SURVEY) is None
    assert len(search.queries) == 3  # 검색어 3개 모두 시도
    assert [r["by"] for r in f.rejected] == ["grade"] * 3


def test_articles_without_the_item_never_reach_the_model():
    unrelated = Source(url="https://www.yna.co.kr/1", title="물가 동향", published="2026-10-10", text="사과값이 내렸다.")
    f, calls = finder(FakeSearch([unrelated]), [], [])
    assert f.find(CABBAGE, SURVEY) is None
    assert not calls["extract"]  # 기사가 없으면 모델을 부르지 않는다


def test_find_all_survives_errors():
    class Broken:
        def search(self, *a, **k):
            raise RuntimeError("검색 장애")

    f, _ = finder(Broken(), [], [])
    causes, log = f.find_all([CABBAGE], SURVEY)
    assert causes == {} and "검색 장애" in log["errors"][0]


def test_origin_mismatch_is_rejected_by_code_not_left_to_ai():
    """AI 심사가 같은 인용을 한 번은 통과, 한 번은 탈락시켰던 사례(실제 10/16 고등어)."""
    from dataclasses import replace

    mackerel = replace(fact("고등어", w=11.6), kind_name="국산(신선 냉장)")
    article = Source(url="https://www.mt.co.kr/1", title="수산물 할인 지원", published="2026-10-11",
                     text="수입산 고등어는 노르웨이 쿼터 감소로 가격이 크게 상승했다.")
    e = Extraction(found=True, source_index=0, quote="수입산 고등어는 노르웨이 쿼터 감소로 가격이 크게 상승했다.",
                   summary="노르웨이 쿼터 감소")
    assert "수입산" in check_extraction(e, [article], mackerel)


def test_description_without_supply_words_is_not_a_cause():
    """AI 심사가 통과시켰던 실제 10/16 고등어 인용: 원인이 아니라 설명."""
    mackerel = fact("고등어", w=11.6)
    article = Source(url="https://www.mk.co.kr/1", title="핵심 고등어 어업선 10년간 현대화", published="2026-10-14",
                     text="대형선망은 고등어 등을 잡는 대표적인 근해어업이다.")
    e = Extraction(found=True, source_index=0, quote="대형선망은 고등어 등을 잡는 대표적인 근해어업이다.",
                   summary="고등어 어업선 노후화")
    assert "수급" in check_extraction(e, [article], mackerel)
