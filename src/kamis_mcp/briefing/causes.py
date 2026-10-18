"""'왜 올랐나/내렸나' — 뉴스에서 원인 문장을 찾아 원문 그대로 인용한다(근거 기반 생성).

LLM은 그럴듯한 원인("이상기후 때문")을 쉽게 지어낸다. 그래서 원인은 반드시
신뢰할 수 있는 언론·공공기관 기사에서 **원문 문장을 그대로 인용**해야 하고,
코드와 AI 심사가 그 인용이 진짜이고 알맞은 근거인지 확인한다. 근거를 못 찾으면 원인을 쓰지 않는다.

    START → search → extract → check → grade ─ 적절함 ─────────────────▶ END (원인 채택)
              ▲                  │                └─ 부적절 ─┐
              │                  ├─ 인용 불일치 → extract(피드백, 1번)
              └── next_query ◀───┴─ 근거 없음 ◀─────────────┘
                                 └─ 검색어 소진 ────────────────────────▶ END (원인 없음)

- check(코드): 인용문이 본문에 그대로 있는가, 품목 이름이 다른 낱말의 일부가 아닌가(방울토마토≠토마토),
  인용·기사 제목의 방향(치솟/급락)이 실제 변동과 맞는가, 요약이 인용에 근거하는가.
- grade(LLM 심사): 인용이 '이 품목의 이번 가격 변동' 원인을 정말 설명하는가.
  인용이 진짜여도 엉뚱한 근거일 수 있어서(실제로 겪음: 스마트팜 홍보 기사, 지난달 명절 수요) 따로 판정한다.

강의 노트북(CH03.02.02)의 Agentic RAG: retrieve → grade_documents → rewrite_question 루프와 같은 모양이다.
"""

import os
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TypedDict
from urllib.parse import urlparse

import httpx
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from .facts import ItemFact
from .llm_writer import model_name_from_env, structured_llm
from .verify import _direction

NEWS_LEAD_DAYS = 3  # 비교 시작일(1주 전) 3일 전부터 조사일까지의 기사만. 지난 일을 이번 변동 원인처럼 쓰지 않게
MAX_QUOTE_CHARS = 150  # 인용은 한 문장만 짧게 (저작권 존중: 짧은 인용 + 출처 링크)
MAX_EXTRACT_RETRIES = 1
QUOTE_STRIP = "\"'“”‘’ "

# 출처로 인정하는 곳: 언론사·농업 전문지·공공기관. 자동 생성 시세 사이트 등은 제외한다.
PUBLISHERS = {
    "yna.co.kr": "연합뉴스", "newsis.com": "뉴시스", "news1.kr": "뉴스1", "hankyung.com": "한국경제",
    "mk.co.kr": "매일경제", "chosun.com": "조선일보", "joongang.co.kr": "중앙일보", "donga.com": "동아일보",
    "hani.co.kr": "한겨레", "khan.co.kr": "경향신문", "kbs.co.kr": "KBS", "imbc.com": "MBC",
    "sbs.co.kr": "SBS", "ytn.co.kr": "YTN", "mt.co.kr": "머니투데이", "edaily.co.kr": "이데일리",
    "sedaily.com": "서울경제", "heraldcorp.com": "헤럴드경제", "asiae.co.kr": "아시아경제",
    "nocutnews.co.kr": "노컷뉴스", "agrinet.co.kr": "한국농어민신문", "nongmin.com": "농민신문",
    "aflnews.co.kr": "농수축산신문", "ikpnews.net": "한국농정신문", "fsnews.co.kr": "식품음료신문",
    "korea.kr": "대한민국 정책브리핑", "mafra.go.kr": "농림축산식품부", "mof.go.kr": "해양수산부",
    "krei.re.kr": "한국농촌경제연구원", "at.or.kr": "한국농수산식품유통공사",
}  # fmt: skip

EXTRACT_PROMPT = """당신은 농축수산물 가격 기사의 사실 확인 담당자입니다.
아래 기사들에서 '{name}'({kind}) 소매가격이 {start}~{end} 사이 {move}한 **원인**을 설명하는 문장을 찾으세요.

규칙
- quote: 기사 본문의 한 문장을 **글자 하나 바꾸지 말고 그대로** 복사합니다. {max_chars}자 이하.
- quote는 원인(출하량, 작황, 날씨, 수요, 수입 등)을 직접 말해야 합니다. 가격만 말하는 문장은 안 됩니다.
- quote는 '{name}' 자체에 대한 것이어야 합니다. 비슷한 다른 품목(예: 토마토 ↔ 방울토마토)은 안 됩니다.
- 품종·원산지가 다르면 안 됩니다(예: 국산 고등어의 원인으로 수입산 고등어 이야기).
- summary: quote가 말하는 원인을 15자 안팎 명사구로 (예: '고랭지 출하량 감소'). quote에 없는 내용을 더하지 않습니다.
- 알맞은 문장이 없으면 found=false. 억지로 찾지 않습니다. 원인을 추측하지 않습니다."""

GRADE_PROMPT = """당신은 깐깐한 편집장입니다. 아래 인용문이 '{name}'({kind}) 소매가격이 {start}~{end} 사이
{move}한 원인을 설명하는 근거로 적절한지 판정하세요.

적절하지 않은 예
- 다른 품목(예: 방울토마토, 다른 생선) 또는 다른 품종·원산지(예: 국산 ↔ 수입산) 이야기
- 원인이 아니라 가격·현상만 말하거나, 기업 홍보·정부 대책 이야기
- 시기가 다름(예: 지난달 명절 수요를 이번 주 변동의 원인으로)
- 방향이 반대(가격이 내렸는데 오른 이유)
애매하면 적절하지 않다고 판정합니다. 틀린 원인을 싣는 것보다 원인을 비우는 편이 낫습니다."""


@dataclass
class Source:
    url: str
    title: str
    published: str | None  # YYYY-MM-DD
    text: str

    @property
    def publisher(self) -> str:
        host = urlparse(self.url).hostname or ""
        return next((name for d, name in PUBLISHERS.items() if host == d or host.endswith("." + d)), host)


class Extraction(BaseModel):
    found: bool = Field(description="원인 문장을 찾았는지")
    source_index: int = Field(default=-1, description="인용한 기사 번호 [0], [1] …")
    quote: str = Field(default="", description="기사 본문 문장 그대로")
    summary: str = Field(default="", description="원인 요약 명사구")


class Grade(BaseModel):
    relevant: bool = Field(description="근거로 적절한지")
    reason: str = Field(description="한 문장 이유")


class CauseState(TypedDict, total=False):
    fact: ItemFact
    survey_day: date
    queries: list[str]
    query_index: int
    sources: list[Source]
    extraction: Extraction | None
    problem: str | None  # check에서 찾은 문제(재추출 피드백)
    extract_retries: int
    cause: dict | None


class ExaSearch:
    """Exa 뉴스 검색. 신뢰 도메인만, 기간 지정, 본문 포함."""

    URL = "https://api.exa.ai/search"

    def __init__(self, api_key: str | None = None, transport: httpx.BaseTransport | None = None):
        self.api_key = api_key or os.environ.get("EXA_API_KEY")
        self._http = httpx.Client(timeout=60, transport=transport)

    def search(self, query: str, start: date, end: date, n: int = 6) -> list[Source]:
        r = self._http.post(self.URL, headers={"x-api-key": self.api_key or ""}, json={
            "query": query, "numResults": n, "type": "auto",
            "includeDomains": list(PUBLISHERS),
            "startPublishedDate": f"{start.isoformat()}T00:00:00.000Z",
            "endPublishedDate": f"{end.isoformat()}T23:59:59.000Z",
            "contents": {"text": {"maxCharacters": 4000}},
        })  # fmt: skip
        r.raise_for_status()
        return [
            Source(url=x["url"], title=x.get("title") or "", text=x.get("text") or "",
                   published=(x.get("publishedDate") or "")[:10] or None)
            for x in r.json().get("results", [])
        ]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _name(f: ItemFact) -> str:
    return f.label.split("(")[0].strip()


def _move(f: ItemFact) -> str:
    return "상승" if f.change_1w_pct > 0 else "하락"


def news_start(f: ItemFact, survey_day: date) -> date:
    base = date.fromisoformat(f.base_1w_date) if f.base_1w_date else survey_day - timedelta(days=7)
    return base - timedelta(days=NEWS_LEAD_DAYS)


def mentions_item(text: str, name: str) -> bool:
    """name이 다른 한글 낱말의 뒷부분이 아닌 채로 나오는가. '대추방울토마토'는 토마토가 아니다."""
    return any(m.start() == 0 or not re.match(r"[가-힣]", text[m.start() - 1])
               for m in re.finditer(re.escape(name), text))


def overall_direction(text: str) -> int:
    """글 전체에 '오름' 표현만 있으면 +1, '내림'만 있으면 -1, 둘 다 있거나 없으면 0."""
    up = bool(re.search(r"치솟|급등|올라|올랐|오른|상승|강세|뛰", text))
    down = bool(re.search(r"급락|떨어|내려|내렸|내린|하락|약세|폭락", text))
    return int(up and not down) - int(down and not up)


def origin_mismatch(quote: str, f: ItemFact) -> str | None:
    """품종이 국산인데 '수입산 고등어' 이야기(또는 그 반대)면 다른 상품이다.

    AI 심사에 맡겼더니 같은 인용을 한 번은 탈락, 한 번은 통과시켰다. 규칙으로 쓸 수 있는 건 코드로 고정한다.
    """
    kind, name = f.kind_name or "", re.escape(_name(f))
    if "국산" in kind and re.search(rf"수입(산)?\s*{name}", quote):
        return f"품종은 국산인데 quote는 수입산 {_name(f)} 이야기"
    if "수입" in kind and re.search(rf"국산\s*{name}", quote):
        return f"품종은 수입산인데 quote는 국산 {_name(f)} 이야기"
    return None


def check_extraction(e: Extraction, sources: list[Source], f: ItemFact) -> str | None:
    """인용이 믿을 만한지 코드로 확인한다. 문제가 없으면 None, 있으면 이유."""
    if not 0 <= e.source_index < len(sources):
        return "source_index가 기사 목록 범위를 벗어남"
    src = sources[e.source_index]
    quote = _norm(e.quote).strip(QUOTE_STRIP)
    if not quote or len(quote) > MAX_QUOTE_CHARS:
        return f"quote가 비었거나 {MAX_QUOTE_CHARS}자를 넘음"
    if quote not in _norm(src.text):
        return "quote가 기사 본문에 그대로 있지 않음(글자를 바꾸거나 요약함)"
    if not (mentions_item(quote, _name(f)) or mentions_item(src.title, _name(f))):
        return f"quote와 기사 제목에 '{_name(f)}'가 없음(다른 품목 이야기일 수 있음, 예: 방울토마토)"
    if problem := origin_mismatch(quote, f):
        return problem
    move = 1 if f.change_1w_pct > 0 else -1
    for where, said in (("quote", _direction(quote) or overall_direction(quote)),
                        ("기사 제목", overall_direction(src.title))):
        if said and said != move:
            return f"{where}는 가격이 {'오른' if said > 0 else '내린'} 이야기인데 실제로는 {'올랐음' if move > 0 else '내렸음'}"
    words = re.findall(r"[가-힣A-Za-z]{2,}", e.summary)
    if not words or sum(w[:2] in quote for w in words) < (len(words) + 1) // 2:
        return "summary의 낱말 대부분이 quote에 없음(인용에 없는 원인을 덧붙임)"
    return None


class CauseFinder:
    def __init__(self, model: str | None = None, search: ExaSearch | None = None):
        self.model_name = model_name_from_env(model)
        self.search = search or ExaSearch()
        self._extractor = None
        self._grader = None
        self.rejected: list[dict] = []  # 탈락시킨 인용과 이유(보고서·디버깅용)
        self.graph = self._build_graph()

    # --- 모델 호출 (테스트에서 바꿔 끼운다) ----------------------------------------

    def _extract_llm(self, messages: list[tuple[str, str]]) -> Extraction:
        if self._extractor is None:
            self._extractor = structured_llm(self.model_name, Extraction)
        return self._extractor.invoke(messages)

    def _grade_llm(self, messages: list[tuple[str, str]]) -> Grade:
        if self._grader is None:
            self._grader = structured_llm(self.model_name, Grade)
        return self._grader.invoke(messages)

    # --- 노드 -----------------------------------------------------------------------

    def _search(self, state: CauseState) -> CauseState:
        f, end = state["fact"], state["survey_day"]
        found = self.search.search(state["queries"][state["query_index"]], news_start(f, end), end)
        # 품목 이름이 (다른 낱말의 일부가 아닌 채로) 본문에 없는 기사는 버린다
        sources = [s for s in found if s.text and mentions_item(s.text, _name(f))]
        return {"sources": sources[:5], "extraction": None, "problem": None, "extract_retries": 0, "cause": None}

    def _extract(self, state: CauseState) -> CauseState:
        f, sources = state["fact"], state["sources"]
        if not sources:
            return {"extraction": Extraction(found=False)}
        docs = "\n\n".join(f"[{i}] {s.title} ({s.publisher}, {s.published})\n{s.text}" for i, s in enumerate(sources))
        prompt = EXTRACT_PROMPT.format(name=_name(f), kind=f.kind_name or _name(f), move=_move(f), max_chars=MAX_QUOTE_CHARS,
                                       start=f.base_1w_date or "1주 전", end=f.survey_date)
        messages = [("system", prompt), ("user", docs)]
        retries = state.get("extract_retries", 0)
        if state.get("problem"):
            messages.append(("user", f"이전 답의 문제: {state['problem']}. 규칙을 지켜 다시 답하세요."))
            retries += 1
        return {"extraction": self._extract_llm(messages), "extract_retries": retries}

    def _check(self, state: CauseState) -> CauseState:
        e = state["extraction"]
        if not e or not e.found:
            return {"problem": None, "cause": None}
        problem = check_extraction(e, state["sources"], state["fact"])
        if problem:
            self.rejected.append({"item": state["fact"].label, "quote": e.quote, "by": "check", "reason": problem})
            return {"problem": problem, "cause": None}
        src = state["sources"][e.source_index]
        return {"problem": None, "cause": {
            "summary": e.summary.strip(), "quote": _norm(e.quote).strip(QUOTE_STRIP),
            "url": src.url, "title": src.title, "publisher": src.publisher, "published": src.published,
        }}  # fmt: skip

    def _grade(self, state: CauseState) -> CauseState:
        f, cause = state["fact"], state.get("cause")
        if not cause:
            return {}
        prompt = GRADE_PROMPT.format(name=_name(f), kind=f.kind_name or _name(f), move=_move(f),
                                     start=f.base_1w_date or "1주 전", end=f.survey_date)
        evidence = (f"기사: {cause['title']} ({cause['publisher']}, {cause['published']})\n"
                    f"인용: {cause['quote']}\n요약: {cause['summary']}")
        g = self._grade_llm([("system", prompt), ("user", evidence)])
        if g.relevant:
            return {"cause": cause | {"grade": g.reason}}
        self.rejected.append({"item": f.label, "quote": cause["quote"], "by": "grade", "reason": g.reason})
        return {"cause": None, "problem": None}

    def _next_query(self, state: CauseState) -> CauseState:
        return {"query_index": state["query_index"] + 1}

    def _route(self, state: CauseState) -> str:
        if state.get("cause"):
            return "done"
        if state.get("problem") and state.get("extract_retries", 0) < MAX_EXTRACT_RETRIES:
            return "re_extract"
        if state["query_index"] + 1 < len(state["queries"]):
            return "next_query"
        return "give_up"

    def _build_graph(self):
        g = StateGraph(CauseState)
        g.add_node("search", self._search)
        g.add_node("extract", self._extract)
        g.add_node("check", self._check)
        g.add_node("grade", self._grade)
        g.add_node("next_query", self._next_query)
        g.add_edge(START, "search")
        g.add_edge("search", "extract")
        g.add_edge("extract", "check")
        g.add_edge("check", "grade")
        g.add_conditional_edges("grade", self._route, {
            "done": END, "re_extract": "extract", "next_query": "next_query", "give_up": END,
        })  # fmt: skip
        g.add_edge("next_query", "search")
        return g.compile()

    # --- 바깥에서 쓰는 메서드 -------------------------------------------------------

    @staticmethod
    def queries_for(f: ItemFact) -> list[str]:
        name, up = _name(f), f.change_1w_pct > 0
        return [
            f"{name} 가격 {'상승' if up else '하락'} 원인",
            f"{name} {'출하량 감소' if up else '출하량 증가'} 시세",
            f"{name} 작황 수급 전망",
        ]

    def find(self, f: ItemFact, survey_day: date) -> dict | None:
        if not f.change_1w_pct:
            return None
        final = self.graph.invoke({"fact": f, "survey_day": survey_day, "queries": self.queries_for(f), "query_index": 0})
        return final.get("cause")

    def find_all(self, facts: list[ItemFact], survey_day: date) -> tuple[dict[str, dict], dict]:
        """품목별 원인과 실행 기록. 한 품목이 실패해도 나머지는 계속한다."""
        causes, errors = {}, []
        self.rejected = []
        for f in facts:
            try:
                if cause := self.find(f, survey_day):
                    causes[f.label] = cause
            except Exception as e:  # 검색·모델 장애: 원인 없이 발행한다
                errors.append(f"{f.label}: {type(e).__name__}: {e}"[:200])
        return causes, {"model": self.model_name, "searched": len(facts), "found": len(causes),
                        "rejected": self.rejected, "errors": errors}
