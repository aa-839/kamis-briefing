"""API 키 없이 파이프라인을 돌리기 위한 가짜 KAMIS 클라이언트.

KamisClient와 같은 메서드·같은 반환 모양을 흉내 낸다. 날짜를 시드로 써서
같은 날짜엔 항상 같은 값이 나온다. 숫자는 그럴듯할 뿐 실제 시세가 아니다.
"""

import random
from datetime import date, timedelta

from ..codes import codebook
from .basket import BASKET

# 품목별 대략적인 소매가(원). 실제 시세 아님.
BASE_PRICE = {
    "111": 58000, "152": 4500, "151": 6000, "211": 4800, "212": 4200, "231": 2600, "246": 3900,
    "245": 2900, "258": 12500, "223": 9500, "224": 1600, "213": 1300, "214": 1200, "242": 1400,
    "232": 4800, "225": 6200, "411": 28000, "412": 38000, "415": 4500, "418": 330, "4304": 2700,
    "9903": 7200, "611": 4200, "619": 5900,
}  # fmt: skip
LIVESTOCK_UNIT = {"4304": "100g", "9903": "30구"}


class MockKamisClient:
    async def aclose(self) -> None:
        pass

    async def daily_by_category(self, category_code, price_type="retail", region_code=None, day=None) -> list[dict]:
        day = day or date.today()
        rng = random.Random(f"{day.isoformat()}:{category_code}")
        offsets = [("today", 0), ("1d_ago", 1), ("1w_ago", 7), ("2w_ago", 14), ("1m_ago", 30), ("1y_ago", 365)]
        rows = []
        for b in BASKET:
            if b.category_code != category_code:
                continue
            kind = self._kind_info(b)
            base = BASE_PRICE[b.item_code]
            row = {
                "item_name": kind["item_name"], "item_code": b.item_code,
                "kind_name": kind["kind_name"], "kind_code": kind["kind_code"],
                "rank": "상품", "rank_code": b.rank_codes[0], "unit": kind["unit"],
            }  # fmt: skip
            # 오늘 가격을 기준으로 과거 가격을 흔든다. 일부 품목은 크게 움직이게.
            swing = rng.choice([0.05, 0.05, 0.1, 0.25])
            today = base * rng.uniform(1 - swing, 1 + swing)
            for label, back in offsets:
                p = today if back == 0 else today / rng.uniform(1 - swing, 1 + swing)
                row[label] = {"date": (day - timedelta(days=back)).isoformat(), "price": float(round(p, -1))}
            row["normal_year"] = {"date": "평년", "price": float(round(base * rng.uniform(0.9, 1.1), -1))}
            rows.append(row)
        return rows

    async def monthly_prices(self, *args, **kwargs) -> list[dict]:
        return []  # 가짜 데이터에는 예년 저가철을 만들지 않는다

    async def period_prices(self, item_code, kind_code, category_code, rank_code, start, end,
                            price_type="retail", region_code=None) -> list[dict]:
        rng = random.Random(f"{item_code}:{start}:{end}")
        p = BASE_PRICE.get(item_code, 5000)
        rows, d = [], start
        while d <= end:
            if d.weekday() < 5:  # KAMIS는 주말 조사 없음
                p *= rng.uniform(0.97, 1.03)
                rows.append({"date": d.isoformat(), "region": "평균", "market": None, "price": float(round(p, -1))})
            d += timedelta(days=1)
        return rows

    @staticmethod
    def _kind_info(b) -> dict:
        """바구니 품목의 품종·단위. 지정 품종이 없으면 코드표의 첫 품종."""
        cb = codebook()
        if b.kind_codes:
            m = cb.search_by_code(b.item_code, b.kind_codes[0])[0]
        else:
            item = next(i for i in cb.items if i["item_code"] == b.item_code)
            m = cb.search_by_code(b.item_code, item["kinds"][0]["kind_code"])[0]
        return {"item_name": m.item_name, "kind_name": m.kind_name, "kind_code": m.kind_code,
                "unit": m.retail_unit or LIVESTOCK_UNIT.get(b.item_code)}
