import asyncio
from datetime import date

from kamis_mcp.briefing.facts import ItemFact, select
from kamis_mcp.briefing.mock import MockKamisClient
from kamis_mcp.briefing.pipeline import build_briefing, publish
from kamis_mcp.briefing.verify import check_text, verify
from kamis_mcp.briefing.writer import TemplateWriter, josa


def fact(label="배추", price=5820.0, w=18.2, y=-3.0, normal=31.0) -> ItemFact:
    return ItemFact(
        label=label, category_code="200", item_code="211", kind_code="03", kind_name="가을", rank="상품",
        rank_code="04", unit="1포기", survey_date="2026-10-13", price=price, price_1w_ago=4920.0,
        base_1w_date="2026-10-06", price_1m_ago=None, price_1y_ago=6000.0, price_normal=4440.0,
        change_1w_pct=w, change_1m_pct=None, change_1y_pct=y, vs_normal_pct=normal,
    )


def test_josa():
    assert josa("배추", "이/가") == "배추가"
    assert josa("고등어", "은/는") == "고등어는"
    assert josa("감귤", "이/가") == "감귤이"
    assert josa("배(신고)", "은/는") == "배(신고)는"  # 괄호 앞 '배' 기준
    assert josa("계란(특란 30구)", "이/가") == "계란(특란 30구)이"


def test_check_text_accepts_exact_and_rounded():
    f = [fact()]
    assert all(c["ok"] for c in check_text("배추 5,820원, 18.2% 올라 평년보다 31% 비쌉니다", f))
    assert all(c["ok"] for c in check_text("약 18% 상승", f))  # 18.2 → 18 반올림 허용


def test_check_text_rejects_hallucinated_numbers():
    f = [fact()]
    bad = check_text("배추 6,000원으로 19% 올랐습니다", f)  # 6,000원은 1년 전 가격이라 허용, 19%는 틀림
    assert [c["ok"] for c in bad] == [True, False]
    assert not check_text("25.0% 급등", f)[0]["ok"]


def test_verify_flags_comment_on_wrong_item():
    sel = {"rising": [fact()], "falling": [], "expensive": [], "cheap": []}
    result = verify({"headline": "배추가 18.2% 올랐습니다.", "comments": {"배추": "평년보다 31.0% 비쌉니다.",
                                                                       "사과": "10% 내림"}}, sel)
    assert not result["passed"] and result["checked"] == 3


def test_select_thresholds():
    sel = select([fact("a", w=1.0), fact("b", w=10.0), fact("c", w=-5.0, normal=-12.0)])
    assert [f.label for f in sel["rising"]] == ["b"]
    assert [f.label for f in sel["falling"]] == ["c"]
    assert [f.label for f in sel["cheap"]] == ["c"]


def test_mock_pipeline_end_to_end(tmp_path):
    b = asyncio.run(build_briefing(MockKamisClient(), TemplateWriter(), date(2026, 10, 13), is_mock=True))
    assert b["is_mock"] and b["verification"]["passed"]
    assert len(b["items"]) == 24 and not b["missing"]
    for s in b["sections"]["rising"] + b["sections"]["falling"]:
        assert b["history"][s["item"]], s["item"]
    publish(b, tmp_path)
    b2 = asyncio.run(build_briefing(MockKamisClient(), TemplateWriter(), date(2026, 10, 14), is_mock=True))
    publish(b2, tmp_path)
    import json
    index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert [e["date"] for e in index["briefings"]] == ["2026-10-14", "2026-10-13"]


def test_verify_catches_flipped_direction():
    f = [fact()]  # 배추 1주 +18.2%, 1년 -3.0%, 평년 +31.0%
    assert check_text("배추가 18.2% 올랐습니다", f)[0]["ok"]
    flipped = check_text("배추가 18.2% 내렸습니다", f)[0]
    assert not flipped["ok"] and "방향" in flipped["reason"]
    assert check_text("평년보다 31.0% 비쌉니다", f)[0]["ok"]
    assert not check_text("평년보다 31.0% 저렴합니다", f)[0]["ok"]  # '싸'가 '비싸' 안에서 잘못 잡히지 않는지
    assert check_text("작년보다 3% 낮습니다", f)[0]["ok"]
    assert check_text("18.2%를 기록했습니다", f)[0]["ok"]  # 방향 단어가 없으면 값만 본다


def test_verify_headline_number_must_belong_to_named_item():
    cabbage, apple = fact("배추", w=18.2), fact("사과", w=-12.4, y=6.3, normal=-15.6)
    sel = {"rising": [cabbage], "falling": [apple], "expensive": [], "cheap": []}
    ok = verify({"headline": "배추가 18.2% 올랐고, 사과는 12.4% 내렸습니다.", "comments": {}}, sel)
    assert ok["passed"]
    swapped = verify({"headline": "사과가 18.2% 올랐습니다.", "comments": {}}, sel)
    assert not swapped["passed"] and swapped["failures"][0]["item"] == "사과"


def test_longer_item_name_wins():
    """'배추' 안의 '배'를 배(신고)로 착각하지 않는다."""
    cabbage, pear = fact("배추", w=18.2), fact("배(신고)", w=-5.0, y=1.0, normal=2.0)
    sel = {"rising": [cabbage], "falling": [pear], "expensive": [], "cheap": []}
    assert verify({"headline": "배추가 18.2% 올랐고 배는 5.0% 내렸습니다.", "comments": {}}, sel)["passed"]


def test_template_headline_leads_with_good_buys():
    up, down = fact("양배추", w=16.9), fact("시금치", w=-13.9)
    w = TemplateWriter()
    both = w.write({"rising": [up], "falling": [down], "expensive": [], "cheap": []})["headline"]
    assert both.index("시금치") < both.index("양배추")
    assert w.write({"rising": [up], "falling": [], "expensive": [], "cheap": []})["headline"].startswith("양배추가")


def test_falling_item_must_also_be_cheap_on_one_year_view():
    a, b = fact("a", w=-10.0), fact("b", w=-8.0)
    positions = {"a": {"cheaper_days_pct": 80}, "b": {"cheaper_days_pct": 20}}  # a는 내렸지만 1년 중 비싼 편
    assert [f.label for f in select([a, b], positions)["falling"]] == ["b"]
    assert [f.label for f in select([a, b])["falling"]] == ["a", "b"]  # 1년 정보가 없으면 기존 기준
    no_year = fact("c", w=-5.0, normal=12.0)  # 1년 자료가 모자라면 평년보다 싼지로 판단
    assert select([no_year], {"c": None})["falling"] == []


def test_style_rules_send_long_or_unformatted_headlines_back_for_rewrite():
    pear = fact("배(신고)", price=25660.0, w=-17.9)
    sel = {"rising": [], "falling": [pear], "expensive": [], "cheap": []}
    ok = verify({"headline": "배(신고)가 일주일 새 17.9% 내렸습니다.", "comments": {}}, sel)
    assert ok["passed"]
    long = verify({"headline": "최근 1년 중 매우 싼 편인 배(신고) 10개 25,660원 17.9% 내리고 그 밖에도 여러 품목이 크게 움직였습니다",
                   "comments": {}}, sel)
    assert not long["passed"] and "60자" in long["failures"][-1]["reason"]
    no_comma = verify({"headline": "배(신고) 25660원, 17.9% 내렸습니다.", "comments": {}}, sel)
    assert not no_comma["passed"] and no_comma["checked"] == 2  # 숫자 대조 개수에는 섞지 않는다
