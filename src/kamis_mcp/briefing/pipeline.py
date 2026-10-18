"""브리핑 생성 파이프라인: 조회 → facts → 작성 → 검증 → JSON 발행.

    uv run kamis-brief                        # 실제 KAMIS + LLM 작성기 (.env에 키 필요)
    uv run kamis-brief --model anthropic:claude-sonnet-5-5   # 모델만 바꿔서
    uv run kamis-brief --writer template      # LLM 없이 템플릿 문장
    uv run kamis-brief --mock --date 2026-10-13               # 가짜 데이터

출력: briefings/<날짜>.json, briefings/index.json (홈페이지가 읽는 파일)
"""

import argparse
import asyncio
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

from ..client import KamisClient, KamisError, load_dotenv
from ..codes import LIVESTOCK_CATEGORY
from .basket import BASKET, CATEGORIES
from .facts import ItemFact, build_facts, select, set_1w_base
from .mock import MockKamisClient
from .verify import verify
from .causes import CauseFinder
from .llm_writer import LLMWriter
from .writer import TemplateWriter, Writer

SCHEMA_VERSION = 1
HISTORY_DAYS = 30
SURVEY_LOOKBACK_DAYS = 7  # 오늘 조사가 없으면(주말·공휴일·아직 미발표) 며칠 전까지 거슬러 찾을지
MIN_COVERAGE = len(BASKET) // 2  # 토요일엔 축산물만 조사돼서, 절반 이상 있어야 '조사일'로 본다
SOURCE = "KAMIS 소매가격(전국 평균)"


def _rank_for_period(f: ItemFact) -> str | None:
    return None if f.category_code == LIVESTOCK_CATEGORY else f.rank_code  # 축산물은 등급을 보내면 001


async def _daily_series(client, f: ItemFact, start: date, end: date) -> list[dict]:
    """일별 전국 평균 가격 [{date, price}] (가격 없는 날 제외)."""
    try:
        rows = await client.period_prices(f.item_code, f.kind_code, f.category_code, _rank_for_period(f), start, end)
    except KamisError:
        return []
    return sorted(({"date": r["date"], "price": r["price"]} for r in rows if r["price"] is not None),
                  key=lambda r: r["date"])


async def _history(client, f: ItemFact, day: date) -> list[dict]:
    """최근 30일 가격(그래프용)."""
    return await _daily_series(client, f, day - timedelta(days=HISTORY_DAYS), day)


async def _fill_1w_gaps(client, facts: list[ItemFact]) -> None:
    """1주 전이 공휴일이라 가격이 없으면, 그 이전 가장 가까운 조사일 가격으로 비교한다(10/09 휴일 → 10/08)."""
    for f in facts:
        if f.price_1w_ago is not None or not f.survey_date:
            continue
        target = date.fromisoformat(f.survey_date) - timedelta(days=7)
        series = await _daily_series(client, f, target - timedelta(days=10), target)
        if series:
            set_1w_base(f, series[-1]["price"], series[-1]["date"])


async def _find_survey_day(client, day: date) -> tuple[date, list[ItemFact], list[str]]:
    """day부터 거슬러 올라가며 장바구니 절반 이상이 조사된 가장 최근 날을 찾는다.

    001(데이터 없음)은 주말·공휴일에 정상이라 넘어가지만, 인증 실패(900) 같은 오류는 바로 멈춘다.
    오류를 삼키면 '가격이 없습니다'만 남아 진짜 원인을 알 수 없게 된다.
    """
    for back in range(SURVEY_LOOKBACK_DAYS + 1):
        d = day - timedelta(days=back)
        rows_by_category = {}
        for cat in CATEGORIES:
            try:
                rows_by_category[cat] = await client.daily_by_category(cat, "retail", None, d)
            except KamisError as e:
                if e.code != "001":
                    raise
                rows_by_category[cat] = []
        facts, missing = build_facts(rows_by_category)
        if len(facts) >= MIN_COVERAGE:
            return d, facts, missing
    raise RuntimeError(f"{day} 이전 {SURVEY_LOOKBACK_DAYS}일 동안 조사된 가격이 없습니다(KAMIS 응답: 데이터 없음).")


def _section_item(f: ItemFact, comment: str | None, cause: dict | None = None) -> dict:
    return {
        "item": f.label,
        "kind": f.kind_name,
        "unit": f.unit,
        "price": f.price,
        "change_1w_pct": f.change_1w_pct,
        "base_1w_date": f.base_1w_date,
        "change_1y_pct": f.change_1y_pct,
        "vs_normal_pct": f.vs_normal_pct,
        "comment": comment,
        "cause": cause,
    }


async def build_briefing(client, writer: Writer, day: date, is_mock: bool = False,
                         skip_dates: set[str] = frozenset(), cause_finder=None) -> dict | None:
    """day 기준 가장 최근 조사일의 브리핑. 그 조사일이 skip_dates에 있으면(이미 발행) None."""
    survey_day, facts, missing = await _find_survey_day(client, day)
    if survey_day.isoformat() in skip_dates:
        return None
    await _fill_1w_gaps(client, facts)

    selection = select(facts)
    written = writer.write(selection)
    check = verify(written, selection)
    comments = written["comments"]

    # 많이 오르고 내린 품목의 원인: 기사 원문 인용 + 출처. 근거가 확인된 것만 싣는다
    causes, cause_log = {}, None
    if cause_finder is not None:
        causes, cause_log = cause_finder.find_all(selection["rising"] + selection["falling"], survey_day)

    history = {}
    for f in selection["rising"] + selection["falling"]:
        history[f.label] = await _history(client, f, survey_day)

    survey_dates = sorted({f.survey_date for f in facts if f.survey_date})
    return {
        "schema_version": SCHEMA_VERSION,
        # 가짜 데이터로 만든 브리핑. 실제 발행·보고서에 절대 쓰지 말 것(허위 기재는 실격).
        "is_mock": is_mock,
        # 브리핑 날짜 = 조사일. 주말·공휴일이나 하루 여러 번 실행해도 같은 조사일은 한 파일로 덮어쓴다
        "date": survey_day.isoformat(),
        "survey_date": survey_dates[-1] if survey_dates else None,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "headline": written["headline"],
        "sections": {
            "rising": [_section_item(f, comments.get(f.label), causes.get(f.label)) for f in selection["rising"]],
            "falling": [_section_item(f, comments.get(f.label), causes.get(f.label)) for f in selection["falling"]],
            "vs_normal": {
                "expensive": [{"item": f.label, "vs_normal_pct": f.vs_normal_pct} for f in selection["expensive"]],
                "cheap": [{"item": f.label, "vs_normal_pct": f.vs_normal_pct} for f in selection["cheap"]],
            },
        },
        "items": [_section_item(f, None) for f in facts],
        "missing": missing,
        "history": history,
        "verification": {k: check[k] for k in ("checked", "matched", "passed")} | {"failures": check["failures"]},
        "writer": type(writer).__name__,
        # LLM 작성기의 실행 기록: 어떤 모델이 썼고, 검증 실패로 몇 번 다시 썼고, 결국 템플릿으로 대체됐는지
        "writing": getattr(writer, "last_run", None) or None,
        # 원인 찾기 기록: 몇 품목을 찾아 몇 개를 실었고, 무엇을 왜 탈락시켰는지
        "cause_search": cause_log,
        "source": SOURCE,
    }


def publish(briefing: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{briefing['date']}.json"
    path.write_text(json.dumps(briefing, ensure_ascii=False, indent=2), encoding="utf-8")

    index_path = out_dir / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {"briefings": []}
    entries = [e for e in index["briefings"] if e["date"] != briefing["date"]]
    entries.append({
        "date": briefing["date"],
        "headline": briefing["headline"],
        "verified": briefing["verification"]["passed"],
        "is_mock": briefing["is_mock"],
        "file": path.name,
    })
    index["briefings"] = sorted(entries, key=lambda e: e["date"], reverse=True)
    index["updated_at"] = briefing["generated_at"]
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


async def _run(args) -> None:
    day = date.fromisoformat(args.date) if args.date else date.today()
    client = MockKamisClient() if args.mock else KamisClient()
    writer = TemplateWriter() if args.writer == "template" else LLMWriter(args.model)
    finder = None
    if args.writer == "llm" and not args.no_causes and os.environ.get("EXA_API_KEY"):
        finder = CauseFinder(args.model)
    out = Path(args.out)
    skip = {p.stem for p in out.glob("????-??-??.json")} if args.skip_existing else set()
    try:
        briefing = await build_briefing(client, writer, day, is_mock=args.mock, skip_dates=skip, cause_finder=finder)
    finally:
        await client.aclose()
    if briefing is None:
        print("가장 최근 조사일 브리핑이 이미 있습니다. 새 조사 가격이 나오면 다시 실행하세요.")
        return
    path = publish(briefing, out)
    v = briefing["verification"]
    print(f"{path}  검증 {v['matched']}/{v['checked']} {'통과' if v['passed'] else '실패'}")
    if w := briefing["writing"]:
        print(f"작성: {w['model']}, 재작성 {w['rewrites']}번{', 템플릿으로 대체' if w['fallback'] else ''}")
        if w.get("error"):
            print(f"  모델 오류: {w['error']}")
    if c := briefing["cause_search"]:
        print(f"원인: {c['found']}/{c['searched']}개 품목 근거 확인, 탈락 {len(c['rejected'])}건"
              + (f", 오류 {len(c['errors'])}건" if c["errors"] else ""))
    print(briefing["headline"])


def main() -> None:
    load_dotenv()
    p = argparse.ArgumentParser(description="KAMIS 물가 브리핑 생성")
    p.add_argument("--mock", action="store_true", help="API 키 없이 가짜 데이터로 실행")
    p.add_argument("--date", help="YYYY-MM-DD (기본: 오늘)")
    p.add_argument("--out", default="briefings", help="출력 폴더 (기본: briefings)")
    p.add_argument("--writer", choices=["llm", "template"], default="llm", help="문장 작성 방식 (기본: llm)")
    p.add_argument("--no-causes", action="store_true", help="원인 찾기(뉴스 검색) 생략")
    p.add_argument("--skip-existing", action="store_true",
                   help="가장 최근 조사일 브리핑이 출력 폴더에 이미 있으면 만들지 않음 (자동 실행용)")
    p.add_argument("--model", help="'회사:모델' (기본: .env의 BRIEF_MODEL, 없으면 openai:gpt-4.1-mini)")
    asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    main()
