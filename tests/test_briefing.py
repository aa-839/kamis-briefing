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
