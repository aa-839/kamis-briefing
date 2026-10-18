"""실제 KAMIS 응답을 tests/fixtures/에 저장한다. 테스트는 이 파일로 파서를 검사한다.

    uv run python scripts/save_fixtures.py 2026-10-16

KAMIS가 응답 형식을 바꾸면 이 스크립트로 다시 저장하고 테스트를 돌려 보면 된다.
- 응답의 condition(요청 파라미터 메아리)에는 인증키가 들어 있어서 지우고 저장한다.
- 일별 가격(periodProductList)은 장바구니 품목마다 1년치, '평균'·'평년' 행만 남긴다.
"""

import asyncio
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx

from kamis_mcp.briefing.basket import BASKET, CATEGORIES
from kamis_mcp.briefing.facts import build_facts
from kamis_mcp.briefing.pipeline import _rank_for_period, _year_series
from kamis_mcp.briefing.seasonal import seasonal_info
from kamis_mcp.client import KamisClient, KamisError, load_dotenv

OUT = Path("tests/fixtures")
KEEP_REGIONS = {"평균", "평년"}  # 평년 행은 걸러지는지 검사용


def fixture_name(params: dict) -> str:
    """요청 → 파일 이름. tests/conftest.py의 가짜 네트워크도 같은 규칙으로 파일을 찾는다."""
    a = params["action"]
    if a == "dailyPriceByCategoryList":
        return f"daily_{params['p_item_category_code']}_{params.get('p_regday')}.json"
    if a == "periodProductList":
        return f"period_{params['p_itemcode']}_{params['p_kindcode']}_{params['p_startday']}_{params['p_endday']}.json"
    if a == "monthlySalesList":
        return f"monthly_{params['p_itemcode']}_{params['p_kindcode']}_{params['p_yyyy']}.json"
    raise ValueError(a)


def _trim(body: dict) -> dict:
    body.pop("condition", None)
    data = body.get("data")
    if isinstance(data, dict) and isinstance(data.get("item"), list):
        items = data["item"]
        if items and "countyname" in items[0]:
            data["item"] = [x for x in items if x.get("countyname") in KEEP_REGIONS]
    return body


async def main(day: date) -> None:
    load_dotenv()
    OUT.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []

    async def save(request: httpx.Request, response: httpx.Response) -> None:
        params = dict(request.url.params)
        body = _trim(json.loads(response.content.decode("utf-8")))
        name = fixture_name(params)
        (OUT / name).write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
        saved.append(name)

    class Recorder(httpx.AsyncHTTPTransport):
        async def handle_async_request(self, request):
            response = await super().handle_async_request(request)
            await response.aread()
            await save(request, response)
            return response

    client = KamisClient(transport=Recorder())
    try:
        # 조사일 하루 + 그 다음 이틀(토·일 같은 '조사 없는 날' 모양도 남긴다)
        rows = {}
        for d in (day, day + timedelta(days=1), day + timedelta(days=2)):
            for cat in CATEGORIES:
                try:
                    r = await client.daily_by_category(cat, "retail", None, d)
                except Exception:
                    r = []
                if d == day:
                    rows[cat] = r
        facts, _ = build_facts(rows)
        end = day - timedelta(days=7)
        for f in facts:
            try:  # 공휴일 1주 전 대체용 짧은 기간
                await client.period_prices(f.item_code, f.kind_code, f.category_code, _rank_for_period(f),
                                           end - timedelta(days=10), end)
            except KamisError as e:
                print(f"  {f.label} {f.kind_name}/{f.rank}: {e}")
            await _year_series(client, f, day)  # 그래프·1년 중 위치용 1년치(품종별)
        await seasonal_info(client, facts, day)  # 예년 저가철용 월별 가격(품목·품종별)
    finally:
        await client.aclose()
    print(f"{len(saved)}개 저장 → {OUT}/  (장바구니 {len(BASKET)}개 중 {len(facts)}개 조사됨)")


if __name__ == "__main__":
    asyncio.run(main(date.fromisoformat(sys.argv[1])))
