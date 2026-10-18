"""실제 KAMIS 응답(2026-10-16 금요일 조회, tests/fixtures/)으로 파서와 파이프라인을 검사한다.

이 날의 특징: 1주 전(10/09)이 한글날이라 농산물의 '1주일전' 가격이 비어 있다.
"""

import asyncio
from datetime import date

import pytest

from kamis_mcp.briefing.basket import BASKET, BasketItem
from kamis_mcp.briefing.facts import _pick_row
from kamis_mcp.briefing.pipeline import build_briefing
from kamis_mcp.briefing.writer import TemplateWriter
from kamis_mcp.client import KamisError, clean_kind_name, parse_day_label

FRIDAY = date(2026, 10, 16)


def run(coro):
    return asyncio.run(coro)


def test_parse_day_label():
    assert parse_day_label("당일 (10/16)", FRIDAY) == "2026-10-16"
    assert parse_day_label("1년전", FRIDAY) is None  # 날짜가 안 붙어 오는 칸
    assert parse_day_label("1주일전 (12/29)", date(2027, 1, 5)) == "2026-12-29"  # 해 넘김


def test_clean_kind_name():
    assert clean_kind_name("여름(고랭지)(1포기)", "1포기") == "여름(고랭지)"
    assert clean_kind_name("20kg(20kg)", "20kg") == "20kg"
    assert clean_kind_name("특란30구", "30구") == "특란30구"


def test_daily_parser_reads_real_field_names(kamis):
    rows = run(kamis.daily_by_category("200", day=FRIDAY))
    cabbage = next(r for r in rows if r["item_code"] == "211")
    assert cabbage["kind_code"] == "02" and cabbage["kind_name"] == "여름(고랭지)"
    assert cabbage["rank_code"] == "04" and cabbage["unit"] == "1포기"
    assert cabbage["today"] == {"date": "2026-10-16", "price": 5557.0}
    assert cabbage["1w_ago"] == {"date": "2026-10-09", "price": None}  # 한글날
    assert cabbage["1y_ago"]["date"] is None and cabbage["1y_ago"]["price"] == 6197.0


def test_sunday_is_no_data(kamis):
    with pytest.raises(KamisError) as e:
        run(kamis.daily_by_category("200", day=date(2026, 10, 18)))
    assert e.value.code == "001"


def test_period_keeps_only_national_average(kamis):
    rows = run(kamis.period_prices("211", "02", "200", "04", date(2025, 10, 17), FRIDAY))
    assert rows and {r["region"] for r in rows} == {"평균"}
    assert rows[-1] == {"date": "2026-10-16", "region": "평균", "market": None, "price": 5557.0}


def test_monthly_parser(kamis):
    rows = run(kamis.monthly_prices("211", "02", "200", "1", 2026, 3))
    assert {r["year"] for r in rows} >= {"2026", "2025"}
    assert any(r["months"][9] for r in rows)


def test_kind_in_label_is_never_substituted(kamis):
    """'사과(후지)'처럼 품종을 이름에 쓴 품목은 그 품종이 없으면 다른 품종으로 대신하지 않는다."""
    rows = run(kamis.daily_by_category("400", day=FRIDAY))  # 10월엔 홍로·시나노골드만 조사됨
    assert _pick_row(BasketItem("사과(후지)", "400", "411", ("05",)), rows) is None
    picked = _pick_row(BasketItem("사과", "400", "411"), rows)
    assert picked["kind_name"] == "홍로" and picked["rank_code"] == "04"


def test_briefing_from_real_data_on_sunday(kamis):
    """일요일에 실행 → 금요일 조사분으로, 한글날 빈칸은 10/08 가격으로 비교."""
    b = run(build_briefing(kamis, TemplateWriter(), date(2026, 10, 18)))
    assert b["date"] == b["survey_date"] == "2026-10-16" and not b["is_mock"]
    assert len(b["items"]) == len(BASKET) and not b["missing"]
    assert b["verification"]["passed"], b["verification"]["failures"]

    items = {i["item"]: i for i in b["items"]}
    assert items["배추"]["base_1w_date"] == "2026-10-08"  # 휴일 전날로 대체
    assert items["배추"]["change_1w_pct"] is not None
    assert items["돼지 삼겹살"]["base_1w_date"] == "2026-10-09"  # 축산물은 휴일에도 조사
    assert items["감귤"]["change_1w_pct"] is None  # 노지 감귤은 10/15부터 조사 → 비교 불가
    assert items["사과"]["kind"] == "홍로"

    for s in b["sections"]["rising"] + b["sections"]["falling"]:
        assert b["history"][s["item"]], s["item"]


def test_already_published_survey_day_is_skipped(kamis):
    b = run(build_briefing(kamis, TemplateWriter(), date(2026, 10, 18), skip_dates={"2026-10-16"}))
    assert b is None


def test_auth_error_is_not_swallowed():
    """인증 실패를 '가격이 없다'로 뭉개지 않고 그대로 알린다(GitHub Actions에서 실제로 겪음)."""
    import httpx

    from kamis_mcp.client import KamisClient

    deny = httpx.MockTransport(lambda req: httpx.Response(200, json={"data": ["900"]}))
    client = KamisClient(cert_key="wrong", cert_id="id", transport=deny)
    with pytest.raises(KamisError) as e:
        run(build_briefing(client, TemplateWriter(), FRIDAY))
    assert e.value.code == "900"


def test_missing_env_names_the_variable(monkeypatch):
    from kamis_mcp.client import KamisClient

    monkeypatch.delenv("KAMIS_CERT_ID", raising=False)
    with pytest.raises(KamisError, match="KAMIS_CERT_ID"):
        run(KamisClient(cert_key=" key \n").daily_by_category("200", day=FRIDAY))


def test_html_response_is_reported():
    """차단 안내 같은 웹페이지가 오면 무슨 내용인지 보여 준다."""
    import httpx

    from kamis_mcp.client import KamisClient

    html = httpx.MockTransport(lambda req: httpx.Response(200, text="<html>\n접근이 차단되었습니다</html>"))
    with pytest.raises(KamisError, match="접근이 차단") as e:
        run(KamisClient(cert_key="k", cert_id="i", transport=html).daily_by_category("200", day=FRIDAY))
    assert e.value.code == "NOJSON"


def test_good_buys_are_cheap_on_a_one_year_view(kamis):
    """'지금 사기 좋은 품목'은 1주 동안 내렸고 + 최근 1년 중 오늘보다 싼 날이 절반 이하."""
    b = run(build_briefing(kamis, TemplateWriter(), date(2026, 10, 18)))
    for item in b["sections"]["falling"]:
        assert item["change_1w_pct"] <= -3
        assert item["year"]["cheaper_days_pct"] <= 50, item["item"]
        assert len(b["history"][item["item"]]) >= 60  # 1년치 그래프
