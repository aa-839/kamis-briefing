"""예년 저가철: KAMIS 월별 소매가격으로 '예년엔 이 달에 쌌다'를 계산한다(예측이 아니라 지난 기록).

    최근 3년(조사 연도 직전 3개 연도)의 월평균 소매가격
    → 해마다 '그해 평균 대비 몇 %'로 바꾼다(해마다 물가 수준이 달라서 그대로 비교하지 않는다)
    → 같은 달끼리 3년 평균
    → 이번 달이 연평균보다 10% 이상 낮았거나, 가장 싼 3개 달에 들면서 5% 이상 낮았으면 '예년 저가철'

- 배추·사과처럼 철마다 품종이 바뀌는 품목은 단위가 같은 품종을 합쳐 월평균을 낸다
  (고랭지 배추는 7~11월만 조사돼서 한 품종만으로는 1년 흐름이 안 보인다).
- '제철'과는 다르다. 값이 싼 시기일 뿐이라 화면에도 '예년 저가철'로만 표시한다.
- 축산물은 KAMIS 월별 API가 지원하지 않아 제외한다.
- 월별 값은 자주 바뀌지 않아 달마다 한 번만 계산해 out/seasonal/YYYY-MM.json에 보관한다.
"""

import json
from datetime import date
from pathlib import Path
from statistics import mean

from ..client import KamisError
from ..codes import LIVESTOCK_CATEGORY, codebook
from .basket import BASKET
from .facts import ItemFact

YEARS = 3
MIN_MONTHS_PER_YEAR = 6  # 그해 조사된 달이 이보다 적으면 '그해 평균'이 믿을 만하지 않아 뺀다
MIN_YEARS_PER_MONTH = 2  # 같은 달 자료가 2년 이상 있어야 '예년'이라 부른다
MIN_MONTHS = 6  # 1년 중 비교 가능한 달이 이보다 적으면 판단하지 않는다
CHEAPEST_N = 3
LOW_THRESHOLD = 0.95  # 가장 싼 3개 달이면 연평균보다 5% 이상 낮아야 저가철
CLEARLY_LOW = 0.90  # 3위 밖이어도 10% 이상 낮으면 저가철(감귤 10월처럼 싼 달이 여럿인 품목)


def _kinds_for(f: ItemFact) -> list[str]:
    """월평균에 합칠 품종: 바구니에서 품종을 정한 품목은 그 품종만, 아니면 단위가 같은 품종 전부."""
    b = next(b for b in BASKET if b.label == f.label)
    if b.kind_codes:
        return list(b.kind_codes)
    item = next((i for i in codebook().items if i["item_code"] == f.item_code), None)
    kinds = [k["kind_code"] for k in (item or {}).get("kinds", []) if k.get("retail_unit") == f.unit]
    return list(dict.fromkeys(kinds + ([f.kind_code] if f.kind_code else [])))


async def monthly_table(client, f: ItemFact, last_year: int) -> dict[int, dict[int, float]]:
    """{연도: {월: 가격}} 소매 월평균. 품종 여럿이면 같은 달끼리 평균."""
    graderank = codebook().graderank(f.rank_code or "04") or "1"
    collected: dict[tuple[int, int], list[float]] = {}
    for kind in _kinds_for(f):
        try:
            rows = await client.monthly_prices(f.item_code, kind, f.category_code, graderank, last_year, YEARS)
        except KamisError:
            continue
        for r in rows:
            if r["price_type"] != "retail" or not str(r["year"]).isdigit():
                continue
            y = int(r["year"])
            if not last_year - YEARS < y <= last_year:
                continue
            for m, p in r["months"].items():
                if p:
                    collected.setdefault((y, int(m)), []).append(p)
    table: dict[int, dict[int, float]] = {}
    for (y, m), ps in collected.items():
        table.setdefault(y, {})[m] = mean(ps)
    return table


def low_season(table: dict[int, dict[int, float]], month: int) -> dict | None:
    """월별 표 → 이번 달이 예년 저가철인지. 판단할 자료가 모자라면 None."""
    rel: dict[int, list[float]] = {}
    years = []
    for y, months in sorted(table.items()):
        if len(months) < MIN_MONTHS_PER_YEAR:
            continue
        years.append(y)
        avg = mean(months.values())
        for m, p in months.items():
            rel.setdefault(m, []).append(p / avg)
    by_month = {m: mean(v) for m, v in rel.items() if len(v) >= MIN_YEARS_PER_MONTH}
    if len(by_month) < MIN_MONTHS:
        return None
    cheapest = sorted(by_month, key=by_month.get)[:CHEAPEST_N]
    this = by_month.get(month)
    return {
        "low_season": this is not None and (this <= CLEARLY_LOW or (month in cheapest and this <= LOW_THRESHOLD)),
        "month_vs_year_avg_pct": round((this - 1) * 100, 1) if this is not None else None,
        "cheapest_months": sorted(m for m in cheapest if by_month[m] < 1),
        "years": years,
    }


async def seasonal_info(client, facts: list[ItemFact], survey_day: date, cache_dir: Path | None = None) -> dict:
    """품목별 예년 저가철 정보 {label: {...}}. 같은 달이면 cache_dir의 계산 결과를 다시 쓴다."""
    cache = cache_dir / f"{survey_day:%Y-%m}.json" if cache_dir else None
    if cache and cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    out = {}
    for f in facts:
        if f.category_code == LIVESTOCK_CATEGORY:
            continue
        info = low_season(await monthly_table(client, f, survey_day.year - 1), survey_day.month)
        if info:
            out[f.label] = info
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out
