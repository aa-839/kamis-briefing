"""공식 식품성분표 CSV → src/kamis_mcp/data/nutrition.json (장바구니 품목만).

    uv run python scripts/build_nutrition.py reference/전국통합식품영양성분정보_원재료성식품_표준데이터.csv

원본: 공공데이터포털 「전국통합식품영양성분정보(원재료성식품) 표준데이터」 (data.go.kr 15100065)
      농촌진흥청 국가표준식품성분표 + 국립수산과학원 표준수산물성분표 등. 모두 100g당.

- 품목마다 '생것' 대표 항목 하나를 사람이 골라 FOOD에 적었다. 화면에는 고른 항목 이름을 그대로 밝힌다.
- 수산물은 달마다 성분이 달라(고등어 열량 121~246kcal) MONTHLY 패턴으로 달별 '대표' 값을 모두 담는다.
- 값은 원본 문자열 그대로 옮긴다(반올림·계산 없음). 빈칸은 null.
"""

import csv
import json
import re
import sys
from pathlib import Path

OUT = Path("src/kamis_mcp/data/nutrition.json")
DATASET = "공공데이터포털 전국통합식품영양성분정보(원재료성식품) 표준데이터"

NUTRIENTS = {  # 화면에 보여 줄 성분: 원본 열 이름 → (표시 이름, 단위)
    "에너지(kcal)": ("열량", "kcal"),
    "단백질(g)": ("단백질", "g"),
    "식이섬유(g)": ("식이섬유", "g"),
    "비타민 C(mg)": ("비타민C", "mg"),
    "칼륨(mg)": ("칼륨", "mg"),
}

FOOD = {  # 장바구니 label → 성분표 식품명 (KAMIS 품종에 가장 가까운 '생것')
    "쌀(20kg)": "멥쌀_백미_생것",
    "감자": "감자_수미_생것",  # KAMIS 감자 품종: 수미
    "고구마": "고구마_분질(밤) 고구마_생것",  # KAMIS 고구마 품종: 밤
    "배추": "배추_생것",
    "양배추": "양배추_생것",
    "무": "무_조선무_뿌리_생것",
    "대파": "파_대파_생것",
    "양파": "양파_생것",
    "깐마늘": "마늘_구근_생것",
    "오이": "오이_개량종_생것",
    "애호박": "호박_애호박_생것",
    "시금치": "시금치_생것",
    "상추": "상추_잎상추_적상추_생것",
    "풋고추": "고추_풋고추_생것",
    "당근": "당근_뿌리_생것",
    "토마토": "토마토_생것",
    "사과": "사과_생것",
    "배(신고)": "배_신고_생것",
    "감귤": "귤_온주밀감_생것",  # KAMIS 노지 감귤 = 온주밀감
    "바나나": "바나나_생것",
    "돼지 삼겹살": "돼지고기_삼겹살_생것",
    "계란(특란 30구)": "달걀_생것",
    "고등어": "고등어류_고등어_육_생것_부산_평균",  # 그 달 '대표' 값이 없을 때
    "오징어": "오징어류_살오징어_몸통_생것_부산_6월",  # 그 달 '대표' 값이 없을 때
}

MONTHLY = {  # 달마다 '대표' 값이 있는 수산물: {m}에 달
    "고등어": "고등어류_고등어_육_생것_대표_{m}월",
    "오징어": "오징어류_살오징어_수컷,전체_생것_대표_{m}월",
}


def _entry(row: dict) -> dict:
    values = {}
    for col, (name, unit) in NUTRIENTS.items():
        v = (row.get(col) or "").strip()
        values[name] = {"value": v if re.fullmatch(r"\d+(\.\d+)?", v) else None, "unit": unit}
    return {
        "food_name": row["식품명"], "food_code": row["식품코드"], "base": row["영양성분함량기준량"],
        "source": row["출처명"], "reference_date": row["데이터기준일자"], "values": values,
    }  # fmt: skip


def main(csv_path: str) -> None:
    raw = Path(csv_path).read_bytes()
    text = raw.decode("utf-8-sig") if raw[:3] == b"\xef\xbb\xbf" else raw.decode("cp949")
    by_name = {r["식품명"]: r for r in csv.DictReader(text.splitlines())}

    out = {"dataset": DATASET, "items": {}}
    for label, name in FOOD.items():
        if name not in by_name:
            sys.exit(f"성분표에 없음: {label} → {name}")
        item = _entry(by_name[name])
        if label in MONTHLY:
            item["monthly"] = {
                str(m): _entry(by_name[n]) for m in range(1, 13) if (n := MONTHLY[label].format(m=m)) in by_name
            }
        out["items"][label] = item

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    monthly = {k: sorted(map(int, v["monthly"])) for k, v in out["items"].items() if "monthly" in v}
    print(f"{len(out['items'])}개 품목 → {OUT}  (달별 값: {monthly})")


if __name__ == "__main__":
    main(sys.argv[1])
