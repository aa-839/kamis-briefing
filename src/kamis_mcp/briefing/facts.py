"""KAMIS 응답 → 브리핑 재료(facts).

여기까지는 LLM 없이 결정적으로 계산한다. 어떤 품목을 '많이 오른 품목'에 넣을지,
변동률이 몇 %인지는 코드가 정하고, LLM은 이 facts를 문장으로 풀어 쓰기만 한다.
그래야 사실 검증 단계에서 '원본 숫자'가 무엇인지 명확하다.
"""

from dataclasses import asdict, dataclass

from ..client import pct_change
from .basket import BASKET, BasketItem

TOP_N = 3
MOVE_THRESHOLD_PCT = 3.0  # 1주 변동이 이보다 작으면 '많이 오른/내린' 품목에서 제외
NORMAL_THRESHOLD_PCT = 10.0  # 평년 대비 이 이상 벌어져야 '비싼/싼' 품목
GOOD_BUY_MAX_CHEAPER_DAYS_PCT = 50  # '사기 좋은 품목': 최근 1년 중 오늘보다 싼 날이 절반 이하


@dataclass
class ItemFact:
    label: str
    category_code: str
    item_code: str
    kind_code: str | None
    kind_name: str | None
    rank: str | None
    rank_code: str | None
    unit: str | None
    survey_date: str | None
    price: float
    price_1w_ago: float | None
    base_1w_date: str | None  # 1주 전 비교에 쓴 날짜. 공휴일이면 그 전 조사일(예: 10/09 휴일 → 10/08)
    price_1m_ago: float | None
    price_1y_ago: float | None
    price_normal: float | None
    change_1w_pct: float | None
    change_1m_pct: float | None
    change_1y_pct: float | None
    vs_normal_pct: float | None

    def to_dict(self) -> dict:
        return asdict(self)


def _pick_row(b: BasketItem, rows: list[dict]) -> dict | None:
    """품목에 해당하는 행 하나를 고른다. 품종은 kind_codes만 허용(앞쪽 우선), 등급은 rank_codes 우선.

    kind_codes에 없는 품종으로 대신하지 않는다: label이 품종을 말하고 있으면 허위가 되기 때문.
    """
    cands = [r for r in rows if r.get("item_code") == b.item_code and r["today"]["price"] is not None]
    if b.kind_codes:
        cands = [r for r in cands if r.get("kind_code") in b.kind_codes]

    def order(r: dict) -> tuple[int, int]:
        kind = b.kind_codes.index(r["kind_code"]) if b.kind_codes else 0
        rank = b.rank_codes.index(r["rank_code"]) if r.get("rank_code") in b.rank_codes else len(b.rank_codes)
        return kind, rank

    cands.sort(key=order)  # 안정 정렬: 같은 순위면 API가 준 순서 유지
    return cands[0] if cands else None


def build_facts(rows_by_category: dict[str, list[dict]]) -> tuple[list[ItemFact], list[str]]:
    """장바구니 품목별 facts와, 오늘 데이터가 없어 빠진 품목 목록."""
    facts, missing = [], []
    for b in BASKET:
        row = _pick_row(b, rows_by_category.get(b.category_code, []))
        if row is None:
            missing.append(b.label)
            continue
        now = row["today"]["price"]
        p = {k: row[k]["price"] for k in ("1w_ago", "1m_ago", "1y_ago", "normal_year")}
        facts.append(
            ItemFact(
                label=b.label,
                category_code=b.category_code,
                item_code=b.item_code,
                kind_code=row.get("kind_code"),
                kind_name=row.get("kind_name"),
                rank=row.get("rank"),
                rank_code=row.get("rank_code"),
                unit=row.get("unit"),
                survey_date=row["today"]["date"],
                price=now,
                price_1w_ago=p["1w_ago"],
                base_1w_date=row["1w_ago"]["date"] if p["1w_ago"] is not None else None,
                price_1m_ago=p["1m_ago"],
                price_1y_ago=p["1y_ago"],
                price_normal=p["normal_year"],
                change_1w_pct=pct_change(now, p["1w_ago"]),
                change_1m_pct=pct_change(now, p["1m_ago"]),
                change_1y_pct=pct_change(now, p["1y_ago"]),
                vs_normal_pct=pct_change(now, p["normal_year"]),
            )
        )
    return facts, missing


def set_1w_base(f: ItemFact, price: float, base_date: str) -> None:
    """1주 전 가격이 비어 있을 때(공휴일) 그 전 조사일 가격으로 채우고 변동률을 다시 계산한다."""
    f.price_1w_ago = price
    f.base_1w_date = base_date
    f.change_1w_pct = pct_change(f.price, price)


def good_buy(f: ItemFact, position: dict | None) -> bool:
    """1주 동안 내렸어도 1년 기준으로 비싸면 '지금 사기 좋은' 품목이 아니다.

    오늘보다 싼 날이 최근 1년 중 절반 이하여야 한다. 1년 자료가 모자라면 평년보다 싼지로 대신 본다.
    """
    if position is not None:
        return position["cheaper_days_pct"] <= GOOD_BUY_MAX_CHEAPER_DAYS_PCT
    return f.vs_normal_pct is not None and f.vs_normal_pct <= 0


def select(facts: list[ItemFact], positions: dict[str, dict | None] | None = None) -> dict:
    """브리핑 섹션별로 품목을 고른다. positions(1년 중 위치)를 주면 '사기 좋은 품목'을 1년 기준으로 거른다."""
    moved = [f for f in facts if f.change_1w_pct is not None]
    rising = sorted((f for f in moved if f.change_1w_pct >= MOVE_THRESHOLD_PCT), key=lambda f: -f.change_1w_pct)
    falling = sorted((f for f in moved if f.change_1w_pct <= -MOVE_THRESHOLD_PCT), key=lambda f: f.change_1w_pct)
    if positions is not None:
        falling = [f for f in falling if good_buy(f, positions.get(f.label))]
    normal = [f for f in facts if f.vs_normal_pct is not None]
    return {
        "rising": rising[:TOP_N],
        "falling": falling[:TOP_N],
        "expensive": sorted((f for f in normal if f.vs_normal_pct >= NORMAL_THRESHOLD_PCT), key=lambda f: -f.vs_normal_pct),
        "cheap": sorted((f for f in normal if f.vs_normal_pct <= -NORMAL_THRESHOLD_PCT), key=lambda f: f.vs_normal_pct),
    }
