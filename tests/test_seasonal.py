"""예년 저가철: 계산 규칙(가짜 표)과 실제 KAMIS 월별 응답(fixture)."""

import asyncio
from datetime import date

from kamis_mcp.briefing.pipeline import build_briefing
from kamis_mcp.briefing.seasonal import low_season
from kamis_mcp.briefing.writer import TemplateWriter


FLAT = {m: 100.0 for m in range(1, 13)}


def test_cheap_month_every_year_is_low_season():
    cheap_oct = {**FLAT, 10: 80.0, 11: 85.0, 9: 90.0}
    info = low_season({2023: cheap_oct, 2024: cheap_oct, 2025: cheap_oct}, 10)
    assert info["low_season"] and info["month_vs_year_avg_pct"] < -10
    assert info["cheapest_months"] == [9, 10, 11]


def test_relative_to_each_year_so_inflation_does_not_matter():
    """해마다 물가 수준이 달라도 '그해 평균 대비'로 비교한다."""
    t = {y: {m: p * k for m, p in {**FLAT, 10: 80.0}.items()} for y, k in ((2023, 1.0), (2024, 1.5), (2025, 2.0))}
    assert low_season(t, 10)["low_season"]
    assert not low_season(t, 5)["low_season"]


def test_not_enough_data_gives_no_answer():
    short = {m: 100.0 for m in (7, 8, 9, 10)}  # 고랭지 배추처럼 4달만 조사
    assert low_season({2023: short, 2024: short, 2025: short}, 10) is None
    assert low_season({2025: {**FLAT, 10: 50.0}}, 10) is None  # 1년치로는 '예년'이 아니다


def test_real_monthly_data_flags_pear_in_october(kamis):
    b = asyncio.run(build_briefing(kamis, TemplateWriter(), date(2026, 10, 18)))
    items = {i["item"]: i for i in b["items"]}
    pear = items["배(신고)"]["season"]
    assert pear["low_season"] and 10 in pear["cheapest_months"] and pear["years"] == [2023, 2024, 2025]
    assert items["배추"]["season"]["low_season"] is False  # 10월 배추는 예년에 비쌌다
    assert items["돼지 삼겹살"]["season"] is None  # 축산물은 월별 자료 없음
