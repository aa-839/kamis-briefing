"""보고서에 쓸 실적 숫자를 발행된 브리핑 파일에서 그대로 집계한다(손으로 세지 않는다).

    uv run python scripts/report_stats.py site/data
"""

import collections
import json
import sys
from pathlib import Path


def reason_group(r: dict) -> str:
    k = r["reason"]
    if "수입산" in k or "국산" in k:
        return "다른 품종·원산지(국산↔수입산)"
    if "그대로" in k:
        return "인용문이 기사 원문과 다름"
    if "제목에" in k:
        return "다른 품목(방울토마토↔토마토 등)"
    if "이야기인데" in k:
        return "가격 방향이 반대"
    if "요약" in k:
        return "인용에 없는 원인을 덧붙임"
    if "수급" in k:
        return "원인이 아닌 설명 문장"
    if r.get("by") == "grade":
        return "AI 심사: 시기·관련성 부적절"
    return "기타(길이 등)"


def main(out_dir: str) -> None:
    files = sorted(Path(out_dir).glob("????-??-??.json"))
    s = collections.Counter()
    reasons = collections.Counter()
    excluded = []
    for f in files:
        b = json.loads(f.read_text(encoding="utf-8"))
        s["briefings"] += 1
        s["backfilled" if b.get("backfilled") else "auto"] += 1
        v = b["verification"]
        s["numbers"] += v["checked"]
        s["numbers_matched"] += v["matched"]
        s["passed"] += bool(v["passed"])
        w = b.get("writing") or {}
        s["rewrites"] += w.get("rewrites", 0)
        s["fallbacks"] += bool(w.get("fallback"))
        c = b.get("cause_search") or {}
        s["cause_items"] += c.get("searched", 0)
        s["cause_found"] += c.get("found", 0)
        s["cause_rejected"] += len(c.get("rejected", []))
        reasons.update(reason_group(r) for r in c.get("rejected", []))
        excluded += [f"{b['date'][5:]} {e['item']}" for e in b.get("excluded_good_buys") or []]

    dates = [f.stem for f in files]
    print(f"기간 {dates[0]} ~ {dates[-1]}")
    print(f"브리핑 {s['briefings']}개 (자동 발행 {s['auto']}, 소급 생성 {s['backfilled']})")
    print(f"AI 문장 속 숫자 {s['numbers']}개 검증, 원본 일치 {s['numbers_matched']}개, 검증 통과 브리핑 {s['passed']}개")
    print(f"AI 재작성 {s['rewrites']}회, 템플릿 대체 {s['fallbacks']}회")
    print(f"원인: {s['cause_items']}건 찾아 {s['cause_found']}건 게재, 자동 탈락 인용 {s['cause_rejected']}건")
    for k, n in reasons.most_common():
        print(f"  - {k}: {n}")
    print(f"지난주보다 내렸지만 1년 기준으로 비싸 추천 제외: {len(excluded)}건 ({', '.join(excluded)})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "site/data")
