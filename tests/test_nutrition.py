"""영양성분: 공식 성분표 값을 그대로 옮겼는지, 수산물은 그 달 값을 쓰는지."""

from kamis_mcp.briefing.basket import BASKET
from kamis_mcp.briefing.nutrition import _table, nutrition_for


def test_every_basket_item_has_official_nutrition():
    table = _table()["items"]
    assert {b.label for b in BASKET} == set(table)
    assert all(v["base"] == "100g" and v["source"] for v in table.values())


def test_values_are_copied_verbatim_and_empty_or_zero_dropped():
    n = nutrition_for("배추", 10)
    assert n["food_name"] == "배추_생것" and "국가표준식품성분표" in n["source"]
    assert {v["name"]: v["value"] for v in n["values"]}["열량"] == "15"  # 원본 문자열 그대로
    assert "비타민C" not in {v["name"] for v in nutrition_for("쌀(20kg)", 10)["values"]}  # 0.00은 뺀다


def test_seafood_uses_that_months_representative_value():
    assert nutrition_for("고등어", 10)["food_name"] == "고등어류_고등어_육_생것_대표_10월"
    assert nutrition_for("고등어", 1)["food_name"] == "고등어류_고등어_육_생것_부산_평균"  # 1월 대표값 없음
