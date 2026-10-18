"""KAMIS Open API 클라이언트.

엔드포인트는 하나(service/price/xml.do)고 action 파라미터로 기능을 고른다.
응답 모양이 action마다 조금씩 달라서, 원본 JSON은 그대로 두고 action별 파서가 평평한 행으로 바꾼다.

파서는 실제 응답(2026-10-16 조회, tests/fixtures/)에 맞췄다. 문서와 다른 점:
- 필드명이 item_code·kind_code·rank_code (문서의 itemcode·kindcode가 아님)
- 날짜가 '당일 (10/16)', '1주일전 (10/09)'처럼 글자로 온다. 1개월전·1년전·평년은 날짜가 없다.
- periodProductList는 지역을 안 주면 24개 지역 + '평균' + '평년' 행이 섞여 온다.
- p_cert_id가 비어 있으면 900. 일요일은 001, 토요일·공휴일은 농산물 가격이 '-'.
- monthlySalesList는 error_code가 data 안이 아니라 최상위에 온다.
"""

import os
import re
from datetime import date
from pathlib import Path

import httpx

BASE_URL = "https://www.kamis.or.kr/service/price/xml.do"

ERROR_MESSAGES = {
    "001": "해당 조건의 데이터가 없습니다",
    "200": "요청 파라미터가 잘못되었습니다",
    "900": "인증되지 않은 요청입니다(API 키 확인 필요)",
    "NOJSON": "KAMIS가 데이터 대신 다른 응답을 보냈습니다",
}

# 일별 데이터 API는 오늘 기준 최근 1년까지만 조회된다(API 문서).
DAILY_LOOKBACK_DAYS = 365


class KamisError(Exception):
    def __init__(self, code: str, action: str, detail: str | None = None):
        self.code = code
        msg = f"[{action}] {code}: {ERROR_MESSAGES.get(code, '알 수 없는 오류')}"
        super().__init__(f"{msg} ({detail})" if detail else msg)


def load_dotenv(path: Path = Path(".env")) -> None:
    """의존성 없이 .env를 읽는다. 이미 설정된 환경변수는 덮어쓰지 않는다."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def parse_price(v) -> float | None:
    """'1,234' → 1234.0, '-'·빈값 → None."""
    if v is None or isinstance(v, (list, dict)):
        return None
    v = str(v).replace(",", "").strip()
    if v in ("", "-", "0"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def pct_change(now: float | None, before: float | None) -> float | None:
    """변동률(%), 소수 첫째 자리. 비교값이 없으면 None."""
    if now is None or not before:
        return None
    return round((now - before) / before * 100, 1)


_MMDD_RE = re.compile(r"\((\d{1,2})/(\d{1,2})\)")


def parse_day_label(label, ref: date) -> str | None:
    """'당일 (10/16)' → '2026-10-16'. 연도가 없으니 기준일(ref)로 정하고, ref보다 뒤 달이면 작년으로 본다."""
    m = _MMDD_RE.search(label) if isinstance(label, str) else None
    if not m:
        return None
    month, day = int(m.group(1)), int(m.group(2))
    year = ref.year - 1 if (month, day) > (ref.month, ref.day) else ref.year
    return date(year, month, day).isoformat()


def _as_list(v) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


class KamisClient:
    def __init__(self, cert_key: str | None = None, cert_id: str | None = None, timeout: float = 20.0,
                 transport: httpx.AsyncBaseTransport | None = None):
        # 복사·붙여넣기로 앞뒤 공백·줄바꿈이 섞여 들어와도 인증되도록 다듬는다
        self.cert_key = (cert_key or os.environ.get("KAMIS_CERT_KEY") or "").strip() or None
        self.cert_id = (cert_id or os.environ.get("KAMIS_CERT_ID") or "").strip() or None
        # transport: 테스트에서 저장해 둔 실제 응답을 돌려주는 가짜 네트워크를 끼울 때 쓴다
        self._http = httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "kamis-mcp/0.1"}, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def call(self, action: str, **params) -> dict:
        """action 호출 후 원본 JSON 반환. 오류 코드면 KamisError."""
        if not (self.cert_key and self.cert_id):
            missing = [n for n, v in (("KAMIS_CERT_KEY", self.cert_key), ("KAMIS_CERT_ID", self.cert_id)) if not v]
            raise KamisError("900", action, f"환경변수 {', '.join(missing)}가 비어 있습니다")
        query = {
            "action": action,
            "p_cert_key": self.cert_key,
            "p_cert_id": self.cert_id,
            "p_returntype": "json",
            **{k: v for k, v in params.items() if v is not None},
        }
        resp = await self._http.get(BASE_URL, params=query)
        resp.raise_for_status()
        try:
            body = resp.json()  # charset=utf-8로 온다(실제 응답 헤더 확인)
        except ValueError:
            # 정상이면 항상 JSON. 웹페이지가 오면 차단·점검 안내일 가능성이 크다(예: 해외 IP 차단)
            snippet = " ".join(resp.text[:120].split())
            raise KamisError("NOJSON", action, f"JSON이 아닌 응답(HTTP {resp.status_code}): {snippet}")
        code = _error_code(body)
        if code and code != "000":
            raise KamisError(code, action)
        return body

    # --- action별 래퍼 -------------------------------------------------------

    async def daily_by_category(
        self, category_code: str, price_type: str = "retail", region_code: str | None = None,
        day: date | None = None,
    ) -> list[dict]:
        """dailyPriceByCategoryList: 부류 전체의 당일/1일전/1주전/2주전/1달전/1년전/평년 가격."""
        body = await self.call(
            "dailyPriceByCategoryList",
            p_product_cls_code="01" if price_type == "retail" else "02",
            p_item_category_code=category_code,
            p_country_code=region_code,
            p_regday=day.isoformat() if day else None,
            p_convert_kg_yn="N",
        )
        labels = ["today", "1d_ago", "1w_ago", "2w_ago", "1m_ago", "1y_ago", "normal_year"]
        ref = day or date.today()
        rows = []
        for it in _items(body):
            row = {
                "item_name": it.get("item_name"),
                "item_code": it.get("item_code"),
                "kind_name": clean_kind_name(it.get("kind_name"), it.get("unit")),
                "kind_code": it.get("kind_code"),
                "rank": it.get("rank"),
                "rank_code": it.get("rank_code"),
                "unit": it.get("unit"),
            }
            for i, label in enumerate(labels, start=1):
                row[label] = {"date": parse_day_label(it.get(f"day{i}"), ref), "price": parse_price(it.get(f"dpr{i}"))}
            rows.append(row)
        return rows

    async def period_prices(
        self, item_code: str, kind_code: str, category_code: str, rank_code: str,
        start: date, end: date, price_type: str = "retail", region_code: str | None = None,
    ) -> list[dict]:
        """periodProductList: 품목 하나의 일별 가격(최근 1년 이내).

        region_code가 없으면 '평균'(전국 평균) 행만, 있으면 그 지역 행만 돌려준다.
        rank_code=None이면 등급을 보내지 않는다(축산물은 등급을 보내면 001이 온다).
        """
        body = await self.call(
            "periodProductList",
            p_productclscode="01" if price_type == "retail" else "02",
            p_startday=start.isoformat(),
            p_endday=end.isoformat(),
            p_itemcategorycode=category_code,
            p_itemcode=item_code,
            p_kindcode=kind_code,
            p_productrankcode=rank_code,
            p_countrycode=region_code,
            p_convert_kg_yn="N",
        )
        rows = []
        for it in _items(body):
            region = it.get("countyname")
            if region == "평년" or ((region == "평균") != (region_code is None)):
                continue
            yyyy, regday = it.get("yyyy"), it.get("regday")  # regday는 'MM/DD'
            if not (isinstance(yyyy, str) and isinstance(regday, str)):
                continue
            rows.append({
                "date": f"{yyyy}-{regday.replace('/', '-')}",
                "region": region,
                "market": it.get("marketname") if isinstance(it.get("marketname"), str) else None,
                "price": parse_price(it.get("price")),
            })
        return rows

    async def monthly_prices(
        self, item_code: str, kind_code: str, category_code: str, graderank: str,
        year: int, period_years: int = 3, region_code: str | None = None,
    ) -> list[dict]:
        """monthlySalesList: 연도별 1~12월 평균가격. 축산물 제외."""
        body = await self.call(
            "monthlySalesList",
            p_yyyy=str(year),
            p_period=str(period_years),
            p_itemcategorycode=category_code,
            p_itemcode=item_code,
            p_kindcode=kind_code,
            p_graderank=graderank,
            p_countycode=region_code,
            p_convert_kg_yn="N",
        )
        rows = []
        for block in _as_list(body.get("price")):
            if not isinstance(block, dict):
                continue
            price_type = {"01": "retail", "02": "wholesale"}.get(block.get("productclscode"))
            for it in _as_list(block.get("item")):
                rows.append({
                    "price_type": price_type,
                    "caption": block.get("caption"),
                    "year": it.get("yyyy"),
                    "months": {m: parse_price(it.get(f"m{m}")) for m in range(1, 13)},
                    "year_avg": parse_price(it.get("yearavg")),
                })
        return rows


def clean_kind_name(name, unit) -> str | None:
    """'여름(고랭지)(1포기)' → '여름(고랭지)'. 품종 이름 끝에 단위가 붙어 와서 뗀다."""
    if not isinstance(name, str):
        return None
    if isinstance(unit, str) and name.endswith(f"({unit})") and len(name) > len(unit) + 2:
        return name[: -len(unit) - 2]
    return name


def _error_code(body: dict) -> str | None:
    if isinstance(body.get("error_code"), str):
        return body["error_code"]  # monthlySalesList는 최상위에 온다
    data = body.get("data")
    if isinstance(data, dict):
        return data.get("error_code")
    if isinstance(data, list) and data and isinstance(data[0], str):
        return data[0]  # 오류 시 {"data": ["200"]} 형태로 온다
    return None


def _items(body: dict) -> list[dict]:
    data = body.get("data")
    if isinstance(data, dict):
        return [x for x in _as_list(data.get("item")) if isinstance(x, dict)]
    return []
