"""품목 이름 → KAMIS 코드 변환.

LLM이 '배추', '대파', '삼겹살' 같은 일상어로 물어도 정확한 부류·품목·품종·등급 코드를
찾을 수 있게 하는 게 목적이다. 코드표는 scripts/build_codes.py가 만든 data/codes.json.
"""

import json
from dataclasses import asdict, dataclass, field
from functools import cache
from importlib import resources

# API 문서에 명시된 지역 코드. 코드표 시트에는 API가 받지 않는 지역도 섞여 있어 따로 둔다.
RETAIL_REGIONS = {
    "1101": "서울", "2100": "부산", "2200": "대구", "2300": "인천", "2401": "광주",
    "2501": "대전", "2601": "울산", "3111": "수원", "3214": "강릉", "3211": "춘천",
    "3311": "청주", "3511": "전주", "3711": "포항", "3911": "제주", "3113": "의정부",
    "3613": "순천", "3714": "안동", "3814": "창원", "3145": "용인", "2701": "세종",
    "3112": "성남", "3138": "고양", "3411": "천안", "3818": "김해",
}  # fmt: skip
WHOLESALE_REGIONS = {"1101": "서울", "2100": "부산", "2200": "대구", "2401": "광주", "2501": "대전"}

# 축산물은 축평원 데이터라 코드 체계가 다르다(부류 500 아래 4301 등).
LIVESTOCK_CATEGORY = "500"


@dataclass
class Match:
    category_code: str
    category_name: str
    item_code: str
    item_name: str
    kind_code: str | None
    kind_name: str | None
    wholesale_unit: str | None = None
    retail_unit: str | None = None
    wholesale_ranks: list[dict] = field(default_factory=list)
    retail_ranks: list[dict] = field(default_factory=list)
    livestock: bool = False
    note: str | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in (None, [], False)}


def _norm(s: str | None) -> str:
    return "".join((s or "").split()).lower()


class CodeBook:
    def __init__(self, data: dict):
        self.categories: dict[str, str] = data["categories"]
        self.ranks: dict[str, dict] = data["ranks"]
        self.items: list[dict] = data["items"]
        self.livestock: list[dict] = data["livestock"]
        self.markets: list[dict] = data["markets"]

    @classmethod
    def load(cls) -> "CodeBook":
        text = resources.files("kamis_mcp").joinpath("data/codes.json").read_text(encoding="utf-8")
        return cls(json.loads(text))

    def rank_name(self, code: str) -> str | None:
        r = self.ranks.get(code)
        return r["name"] if r else None

    def graderank(self, productrankcode: str) -> str | None:
        """일별 API 등급코드(04) → 월별/연도별 API 등급코드(1)."""
        r = self.ranks.get(productrankcode)
        return r["graderank"] if r else None

    def _ranks(self, codes: list[str]) -> list[dict]:
        return [{"code": c, "name": self.rank_name(c)} for c in codes]

    def _crop_match(self, item: dict, kind: dict | None) -> Match:
        m = Match(
            category_code=item["category"],
            category_name=self.categories.get(item["category"], ""),
            item_code=item["item_code"],
            item_name=item["item_name"],
            kind_code=kind and kind["kind_code"],
            kind_name=kind and kind["kind_name"],
        )
        if kind:
            m.wholesale_unit = kind["wholesale_unit"]
            m.retail_unit = kind["retail_unit"]
            m.wholesale_ranks = self._ranks(kind["wholesale_ranks"])
            m.retail_ranks = self._ranks(kind["retail_ranks"])
            if not (kind["wholesale_ranks"] or kind["retail_ranks"]):
                m.note = "도·소매 등급 정보 없음(친환경 전용 품종일 수 있음)"
        else:
            m.note = "코드표에 품종 정보가 없어 가격 조회가 안 될 수 있음"
        return m

    def _livestock_match(self, e: dict) -> Match:
        return Match(
            category_code=LIVESTOCK_CATEGORY,
            category_name=self.categories.get(LIVESTOCK_CATEGORY, "축산물"),
            item_code=e["item_code"],
            item_name=e["item_name"],
            kind_code=e["kind_code"],
            kind_name=e["kind_name"],
            retail_ranks=e["ranks"],
            livestock=True,
            note="축평원 데이터: 일별 기간 조회(periodProductList)만 지원, 월별·연도별 조회 불가",
        )

    def search_by_code(self, item_code: str, kind_code: str) -> list[Match]:
        for item in self.items:
            if item["item_code"] == item_code:
                return [self._crop_match(item, k) for k in item["kinds"] if k["kind_code"] == kind_code]
        return [
            self._livestock_match(e)
            for e in self.livestock
            if e["item_code"] == item_code and e["kind_code"] == kind_code
        ]

    def search(self, query: str, limit: int = 10) -> list[Match]:
        """이름으로 품목·품종 후보를 찾는다. 점수 높은 순.

        '대파'처럼 품목명(파)과 품종명(대파)이 엇갈리는 경우가 많아서 둘 다 본다.
        품종이 있는 후보를 품종 없는 후보보다 우선한다(실제 조회가 되는 쪽).
        """
        q = _norm(query)
        if not q:
            return []
        scored: list[tuple[int, int, Match]] = []
        order = 0

        def add(score: int, m: Match) -> None:
            nonlocal order
            scored.append((score, order, m))
            order += 1

        for item in self.items:
            iname = _norm(item["item_name"])
            kinds = item["kinds"]
            if not kinds:
                if q == iname:
                    add(40, self._crop_match(item, None))
                elif q in iname:
                    add(10, self._crop_match(item, None))
                continue
            for kind in kinds:
                kname = _norm(kind["kind_name"])
                full = iname + kname
                if q == iname:
                    score = 100
                elif q == kname or q == full:
                    score = 90
                elif q in full or q in kname:
                    score = 60
                elif iname in q and (kname in q):
                    score = 80  # '사과후지', '후지 사과'
                else:
                    continue
                add(score, self._crop_match(item, kind))

        for e in self.livestock:
            iname, kname = _norm(e["item_name"]), _norm(e["kind_name"])
            if q == kname or q == iname + kname:
                score = 90
            elif q == iname:
                score = 85
            elif q in iname + kname:
                score = 60
            elif iname in q and kname in q:
                score = 80  # '돼지 삼겹살'
            else:
                continue
            add(score, self._livestock_match(e))

        scored.sort(key=lambda t: (-t[0], t[1]))
        return [m for _, _, m in scored[:limit]]


@cache
def codebook() -> CodeBook:
    return CodeBook.load()
