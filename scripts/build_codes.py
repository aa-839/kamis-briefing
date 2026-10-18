"""KAMIS 코드표(xlsx) → src/kamis_mcp/data/codes.json 변환.

런타임에 openpyxl 의존성을 두지 않으려고 JSON으로 미리 굽는다.
코드표가 갱신되면 다시 실행:  uv run python scripts/build_codes.py
"""

import json
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "reference" / "농축수산물_품목_및_등급_코드표.xlsx"
DST = ROOT / "src" / "kamis_mcp" / "data" / "codes.json"


def s(v) -> str | None:
    """셀 값을 문자열로. 엑셀이 숫자로 저장한 코드(18 등)도 문자열로 맞춘다."""
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def split_ranks(v) -> list[str]:
    v = s(v)
    return [r.strip().zfill(2) for r in v.split(",")] if v else []


def rows(ws, skip: int):
    for r in ws.iter_rows(values_only=True, min_row=skip + 1):
        if any(c is not None for c in r):
            yield r


def build(src: Path) -> dict:
    wb = openpyxl.load_workbook(src, read_only=True)

    categories = {
        s(r[1]): s(r[2]) for r in rows(wb["부류코드"], 2) if s(r[1]) and s(r[1]).isdigit()
    }

    items: dict[str, dict] = {}
    for r in rows(wb["코드통합(부류+품목+품종코드)"], 2):
        _, cat, cat_name, item, item_name, kind, kind_name, w_unit, w_size, r_unit, r_size, *_rest = r
        w_ranks, r_ranks = split_ranks(r[13]), split_ranks(r[14])
        item = s(item)
        if not item:
            continue
        entry = items.setdefault(
            item,
            {"category": s(cat), "item_code": item, "item_name": s(item_name), "kinds": []},
        )
        entry["kinds"].append(
            {
                "kind_code": s(kind),
                "kind_name": s(kind_name),
                "wholesale_unit": f"{s(w_size)}{s(w_unit)}" if s(w_unit) else None,
                "retail_unit": f"{s(r_size)}{s(r_unit)}" if s(r_unit) else None,
                "wholesale_ranks": w_ranks,
                "retail_ranks": r_ranks,
            }
        )

    # 품목코드 시트에만 있고 통합 시트에 품종이 없는 품목(쑥, 샤인머스켓 등).
    # 검색엔 걸리게 하되, 품종 정보가 없다는 걸 kinds=[]로 드러낸다.
    for r in rows(wb["품목코드"], 2):
        cat, item, item_name = s(r[1]), s(r[2]), s(r[3])
        if item and item.isdigit() and item not in items:
            items[item] = {"category": cat, "item_code": item, "item_name": item_name, "kinds": []}

    # 등급: 일별 API는 p_productrankcode(04), 월별/연도별 API는 p_graderank(1)를 쓴다.
    ranks = {}
    for r in rows(wb["등급코드"], 2):
        code = s(r[1])
        if code and code.isdigit():
            ranks[code.zfill(2)] = {"name": s(r[3]), "graderank": s(r[2])}

    # 축산물은 축평원 데이터라 별도 코드 체계. 등급명 없는 행은 등급 '00'(전체).
    livestock: dict[tuple, dict] = {}
    for r in rows(wb["축산물 코드"], 2):
        name, kind_name, rank_name, item, kind, rank = (s(c) for c in r[1:7])
        if not item:
            continue
        key = (item, kind)
        entry = livestock.setdefault(
            key,
            {"item_code": item, "item_name": name, "kind_code": kind, "kind_name": kind_name, "ranks": []},
        )
        if not any(x["code"] == rank for x in entry["ranks"]):
            entry["ranks"].append({"code": rank, "name": rank_name or "전체"})

    # 지역 목록은 여기서 뽑지 않는다. 시트엔 API가 받지 않는 지역(온라인, 목포 등)도 섞여 있어서,
    # API 문서에 명시된 지역 코드는 kamis_mcp.codes에 상수로 둔다.
    markets = []
    for r in rows(wb["지역 및 시장 코드"], 1):
        region, region_name, cls, cls_name, mtype, mtype_name, market, market_name = (s(c) for c in r[:8])
        # 01 소매, 02 중도매. 03/07 친환경은 이 프로젝트 범위 밖이라 제외.
        bucket = {"01": "retail", "02": "wholesale"}.get(cls)
        if not region or not bucket:
            continue
        markets.append(
            {
                "region_code": region,
                "region_name": region_name,
                "price_type": bucket,
                "market_type": mtype_name,
                "market_code": market,
                "market_name": market_name,
            }
        )

    return {
        "source": src.name,
        "categories": categories,
        "items": list(items.values()),
        "ranks": ranks,
        "livestock": list(livestock.values()),
        "markets": markets,
    }


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else SRC
    data = build(src)
    DST.parent.mkdir(parents=True, exist_ok=True)
    DST.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        f"items={len(data['items'])} kinds={sum(len(i['kinds']) for i in data['items'])} "
        f"ranks={len(data['ranks'])} livestock={len(data['livestock'])} "
        f"markets={len(data['markets'])} -> {DST.relative_to(ROOT)}"
    )


if __name__ == "__main__":
    main()
