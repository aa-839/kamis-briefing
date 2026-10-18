"""품목별 영양성분(100g당) — 공식 식품성분표 값을 그대로 보여 준다.

데이터는 scripts/build_nutrition.py가 만든 data/nutrition.json. 값은 원본 문자열 그대로이고
계산·반올림하지 않는다. '면역력에 좋다' 같은 효능은 쓰지 않는다(식품 표시·광고법, 허위 기재 위험):
사실(성분 함량)만 출처와 함께.
"""

import json
from functools import cache
from importlib import resources


@cache
def _table() -> dict:
    text = resources.files("kamis_mcp").joinpath("data/nutrition.json").read_text(encoding="utf-8")
    return json.loads(text)


def nutrition_for(label: str, month: int) -> dict | None:
    """화면용 영양 정보. 수산물은 그 달 '대표' 값이 있으면 그것을 쓴다. 값이 없거나 0인 성분은 뺀다."""
    item = _table()["items"].get(label)
    if item is None:
        return None
    entry = item.get("monthly", {}).get(str(month), item)
    values = [
        {"name": name, "value": v["value"], "unit": v["unit"]}
        for name, v in entry["values"].items()
        if v["value"] is not None and float(v["value"]) > 0
    ]
    return {
        "base": entry["base"], "values": values, "food_name": entry["food_name"],
        "source": entry["source"], "reference_date": entry["reference_date"],
    }  # fmt: skip
