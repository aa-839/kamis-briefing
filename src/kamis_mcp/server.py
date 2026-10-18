"""KAMIS MCP 서버.

도구 설계 원칙
- LLM은 코드를 모른다: search_items로 이름→코드를 먼저 찾고, 나머지 도구는 그 코드를 받는다.
- 숫자는 원본 그대로 + 계산된 변동률을 같이 준다. LLM이 직접 나눗셈하다 틀리는 걸 막기 위해.
- API 제약(일별 1년 한정, 축산물 월별 불가 등)은 도구가 먼저 걸러서 사람이 읽을 수 있는 오류로 돌려준다.
"""

from datetime import date, timedelta
from typing import Literal

from mcp.server.mcpserver import MCPServer

from .client import DAILY_LOOKBACK_DAYS, KamisClient, KamisError, load_dotenv, pct_change
from .codes import RETAIL_REGIONS, WHOLESALE_REGIONS, Match, codebook

load_dotenv()

mcp = MCPServer(
    "kamis",
    instructions=(
        "한국농수산식품유통공사 KAMIS의 농축수산물 도·소매 가격을 조회한다. "
        "품목 코드를 모르면 먼저 search_items로 찾을 것. "
        "가격 단위는 품목마다 다르니(배추 1포기, 사과 10개 등) 답할 때 unit을 반드시 같이 말할 것."
    ),
)

PriceType = Literal["retail", "wholesale"]
CATEGORY_NAMES = {"100": "식량작물", "200": "채소류", "300": "특용작물", "400": "과일류", "500": "축산물", "600": "수산물"}

_client: KamisClient | None = None


def client() -> KamisClient:
    global _client
    if _client is None:
        _client = KamisClient()
    return _client


def _find_item(item_code: str, kind_code: str) -> Match | None:
    """item_code/kind_code로 코드표 항목을 찾아 부류·단위 정보를 채운다."""
    matches = codebook().search_by_code(item_code, kind_code)
    return matches[0] if matches else None


def _check_region(region_code: str | None, price_type: str) -> None:
    allowed = RETAIL_REGIONS if price_type == "retail" else WHOLESALE_REGIONS
    if region_code and region_code not in allowed:
        raise ValueError(f"{price_type} 가격은 이 지역 코드를 지원하지 않습니다: {region_code}. list_regions로 확인하세요.")


@mcp.tool()
def search_items(query: str, limit: int = 10) -> list[dict]:
    """품목·품종 이름으로 KAMIS 코드를 찾는다. 예: '배추', '대파', '후지 사과', '삼겹살'.

    반환값의 item_code·kind_code·등급 코드(wholesale_ranks/retail_ranks)를 다른 가격 도구에 넘긴다.
    결과가 여러 개면 품종(kind_name)과 단위가 질문 의도에 맞는 것을 고를 것.
    """
    return [m.to_dict() for m in codebook().search(query, limit)]


@mcp.tool()
def list_regions() -> dict:
    """가격 조회에 쓸 수 있는 지역 코드. 소매 24개 지역, 도매 5개 지역."""
    return {"retail": RETAIL_REGIONS, "wholesale": WHOLESALE_REGIONS}


@mcp.tool()
async def get_category_prices(
    category_code: Literal["100", "200", "300", "400", "500", "600"],
    price_type: PriceType = "retail",
    region_code: str | None = None,
    day: str | None = None,
) -> dict:
    """부류(100 식량작물, 200 채소류, 300 특용작물, 400 과일류, 500 축산물, 600 수산물) 전체 품목의
    가격과 1일/1주/1달/1년 전·평년 대비 변동률. '요즘 뭐가 많이 올랐나' 같은 질문과 주간 브리핑의 기본 재료.

    day: 'YYYY-MM-DD'. 생략하면 최근 조사일. region_code 생략 시 전국 평균.
    """
    _check_region(region_code, price_type)
    try:
        rows = await client().daily_by_category(
            category_code, price_type, region_code, date.fromisoformat(day) if day else None
        )
    except KamisError as e:
        return {"error": str(e)}
    for r in rows:
        now = r["today"]["price"]
        r["change_pct"] = {
            k: pct_change(now, r[k]["price"]) for k in ("1d_ago", "1w_ago", "1m_ago", "1y_ago", "normal_year")
        }
    return {"category": CATEGORY_NAMES[category_code], "price_type": price_type, "items": rows}


@mcp.tool()
async def get_price_history(
    item_code: str,
    kind_code: str,
    start: str,
    end: str,
    rank_code: str = "04",
    price_type: PriceType = "retail",
    region_code: str | None = None,
) -> dict:
    """품목 하나의 일별 가격 추이. start/end는 'YYYY-MM-DD', 오늘 기준 최근 1년 이내만 가능.
    rank_code는 search_items 결과의 등급 코드(보통 04 상품, 05 중품). 축산물은 등급을 무시한다.
    region_code가 없으면 전국 평균. 그보다 긴 기간은 get_monthly_prices.
    """
    _check_region(region_code, price_type)
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    oldest = date.today() - timedelta(days=DAILY_LOOKBACK_DAYS)
    if s < oldest:
        return {"error": f"일별 가격은 최근 1년({oldest} 이후)만 조회됩니다. 더 긴 기간은 get_monthly_prices를 쓰세요."}
    item = _find_item(item_code, kind_code)
    if item is None:
        return {"error": f"코드표에 없는 품목/품종입니다: {item_code}/{kind_code}. search_items로 확인하세요."}
    rank = None if item.livestock else rank_code  # 축산물은 등급을 보내면 데이터가 없다(001)
    try:
        rows = await client().period_prices(
            item_code, kind_code, item.category_code, rank, s, e, price_type, region_code
        )
    except KamisError as err:
        return {"error": str(err)}
    unit = item.retail_unit if price_type == "retail" else item.wholesale_unit
    rank_name = codebook().rank_name(rank) if rank else None
    return {"item": f"{item.item_name}/{item.kind_name}", "unit": unit, "rank": rank_name, "prices": rows}


@mcp.tool()
async def get_monthly_prices(
    item_code: str,
    kind_code: str,
    year: int,
    period_years: int = 3,
    rank_code: str = "04",
    region_code: str | None = None,
) -> dict:
    """품목의 월평균 가격을 year부터 거슬러 period_years년치. 명절·계절 패턴, 작년·평년과의 장기 비교용.
    축산물은 지원하지 않는다(축평원 데이터).
    """
    item = _find_item(item_code, kind_code)
    if item is None:
        return {"error": f"코드표에 없는 품목/품종입니다: {item_code}/{kind_code}. search_items로 확인하세요."}
    if item.livestock:
        return {"error": "축산물은 월별 가격 조회를 지원하지 않습니다. get_price_history를 쓰세요."}
    graderank = codebook().graderank(rank_code)
    try:
        rows = await client().monthly_prices(
            item_code, kind_code, item.category_code, graderank, year, period_years, region_code
        )
    except KamisError as err:
        return {"error": str(err)}
    return {"item": f"{item.item_name}/{item.kind_name}", "rank": codebook().rank_name(rank_code), "series": rows}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
