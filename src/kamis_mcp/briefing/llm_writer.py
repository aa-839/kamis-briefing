"""LLM 브리핑 작성기: LangGraph로 '작성 → 검증 → (틀리면) 재작성' 루프를 돈다.

    START → write → verify ─ 통과 ─────────────────────▶ END
                      ├─ 실패, 재시도 남음 → rewrite → verify
                      └─ 실패, 재시도 소진 → fallback(템플릿 문장) → END

강의 노트북(CH03.02.02 Part B)의 grade_documents → rewrite_question 루프와 같은 모양이다.
'문서 관련성 평가' 자리에 우리 사실 검증기(verify.py)가 들어간다.

모델은 "회사:모델" 문자열 하나로 고른다(LangChain init_chat_model).
    openai:gpt-4.1-mini, openai:gpt-5.4-mini, anthropic:claude-sonnet-5-5 ...
기본값은 환경변수 BRIEF_MODEL, 없으면 DEFAULT_MODEL.
"""

import json
import os
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from .facts import ItemFact
from .verify import verify
from .writer import TemplateWriter, since_1w

DEFAULT_MODEL = "openai:gpt-4.1-mini"
MAX_REWRITES = 2  # 첫 작성 + 재작성 2번 = 모델 호출 최대 3번

SYSTEM_PROMPT = """당신은 소비자를 위한 '오늘의 장바구니 물가' 브리핑 기자입니다.
주어진 사실(JSON)만으로 헤드라인 한 문장과 품목별 코멘트를 씁니다.

숫자 규칙 (자동 검증기가 한 글자씩 대조합니다)
- 숫자는 사실에 있는 값만 씁니다. 계산하거나 새 숫자를 만들지 않습니다.
- 변동률은 사실의 값 그대로(소수 첫째 자리) 또는 정수로 반올림해서 씁니다. 예: 16.9% 또는 약 17%
- 변동률 바로 뒤에 방향 단어를 붙입니다: 양수면 '올랐/상승/비쌉', 음수면 '내렸/하락/저렴'.
  예) 16.9% 올랐습니다 / 13.9% 내렸습니다 / 평년보다 4.6% 비쌉니다
- 부호(+, -)는 쓰지 않습니다. 방향은 단어로만 말합니다.
- 가격은 '4,694원'처럼 쉼표와 '원'을 붙입니다.
- 헤드라인에서 숫자를 말할 때는 그 숫자 바로 앞에 해당 품목 이름을 씁니다.

내용 규칙
- 1주 변동은 각 품목의 '1주_비교' 표현을 그대로 씁니다(예: '일주일 새', '10월 8일보다').
- 가격이 오르거나 내린 '이유'는 쓰지 않습니다. 날씨·작황 등 원인은 데이터에 없습니다.
- 1주 변동과 평년·작년 비교가 반대 방향이면 '~지만', '아직' 등으로 자연스럽게 잇습니다.
- '지금 사기 좋은' 품목은 장보기에 도움이 되게 쓰되, 과장하지 않습니다.

형식
- headline: 40자 안팎 한 문장. **가장 많이 내린 품목(지금 사기 좋은)을 먼저**, 그다음 가장 많이 오른 품목.
- comments: rising·falling에 있는 품목마다 정확히 하나씩, 1~2문장. item에는 사실의 label을 그대로 씁니다."""


def model_name_from_env(model: str | None = None) -> str:
    return model or os.environ.get("BRIEF_MODEL") or DEFAULT_MODEL


def structured_llm(model_name: str, schema: type[BaseModel]):
    """'회사:모델' 문자열로 모델을 만들고, 답을 schema(Pydantic) 모양으로 받게 한다."""
    from langchain.chat_models import init_chat_model

    # temperature=0(매번 비슷한 문장)은 지원하는 모델에만. gpt-5 계열·최신 Claude는 값을 바꾸면 오류가 난다
    kwargs = {"temperature": 0} if model_name.split(":")[-1].startswith("gpt-4") else {}
    return init_chat_model(model_name, **kwargs).with_structured_output(schema)


class ItemComment(BaseModel):
    item: str = Field(description="사실의 label 그대로 (예: '양배추', '배(신고)')")
    comment: str = Field(description="1~2문장 코멘트")


class Draft(BaseModel):
    headline: str = Field(description="브리핑 헤드라인 한 문장")
    comments: list[ItemComment]


class BriefState(TypedDict, total=False):
    selection: dict[str, list[ItemFact]]
    draft: dict  # {"headline": str, "comments": {label: str}}
    check: dict  # verify() 결과
    rewrites: int
    fell_back: bool


def facts_for_prompt(selection: dict[str, list[ItemFact]]) -> str:
    """LLM에게 줄 사실. 필요한 칸만, 사람이 읽기 쉬운 이름으로."""
    def item(f: ItemFact) -> dict:
        return {
            "label": f.label, "품종": f.kind_name, "단위": f.unit, "오늘_가격": f.price,
            "1주_비교": since_1w(f), "1주_변동률": f.change_1w_pct,
            "1년전_대비": f.change_1y_pct, "평년_대비": f.vs_normal_pct,
        }  # fmt: skip

    payload = {
        "rising(많이 오른 품목)": [item(f) for f in selection["rising"]],
        "falling(많이 내린 품목, 지금 사기 좋은)": [item(f) for f in selection["falling"]],
        "평년보다_비싼": [{"label": f.label, "평년_대비": f.vs_normal_pct} for f in selection["expensive"]],
        "평년보다_싼": [{"label": f.label, "평년_대비": f.vs_normal_pct} for f in selection["cheap"]],
    }
    return json.dumps(payload, ensure_ascii=False, indent=1)


def feedback_for_prompt(check: dict) -> str:
    lines = [f"- [{c['where']}] '{c['text']}': {c.get('reason') or '불일치'}" for c in check["failures"]]
    return "자동 검증에서 아래 문제가 나왔습니다. 사실을 다시 보고 이 부분을 고쳐 전체를 다시 쓰세요.\n" + "\n".join(lines)


class LLMWriter:
    """Writer 프로토콜 구현. pipeline은 write()만 부른다."""

    def __init__(self, model: str | None = None, max_rewrites: int = MAX_REWRITES):
        self.model_name = model_name_from_env(model)
        self.max_rewrites = max_rewrites
        self._llm = None  # 처음 쓸 때 만든다(테스트에서는 _generate를 바꿔 끼워 모델 없이 돈다)
        self.graph = self._build_graph()
        self.last_run: dict = {}

    # --- 모델 호출 -----------------------------------------------------------------

    def _generate(self, messages: list[tuple[str, str]]) -> Draft:
        if self._llm is None:
            self._llm = structured_llm(self.model_name, Draft)
        return self._llm.invoke(messages)

    @staticmethod
    def _to_dict(d: Draft) -> dict:
        return {"headline": d.headline.strip(), "comments": {c.item: c.comment.strip() for c in d.comments}}

    # --- 그래프 노드 ---------------------------------------------------------------

    def _write(self, state: BriefState) -> BriefState:
        messages = [("system", SYSTEM_PROMPT), ("user", facts_for_prompt(state["selection"]))]
        return {"draft": self._to_dict(self._generate(messages)), "rewrites": 0, "fell_back": False}

    def _verify(self, state: BriefState) -> BriefState:
        return {"check": verify(state["draft"], state["selection"])}

    def _rewrite(self, state: BriefState) -> BriefState:
        messages = [
            ("system", SYSTEM_PROMPT),
            ("user", facts_for_prompt(state["selection"])),
            ("assistant", json.dumps(state["draft"], ensure_ascii=False)),
            ("user", feedback_for_prompt(state["check"])),
        ]
        return {"draft": self._to_dict(self._generate(messages)), "rewrites": state["rewrites"] + 1}

    def _fallback(self, state: BriefState) -> BriefState:
        draft = TemplateWriter().write(state["selection"])
        return {"draft": draft, "check": verify(draft, state["selection"]), "fell_back": True}

    def _route(self, state: BriefState) -> str:
        if state["check"]["passed"]:
            return "done"
        return "rewrite" if state["rewrites"] < self.max_rewrites else "fallback"

    def _build_graph(self):
        g = StateGraph(BriefState)
        g.add_node("write", self._write)
        g.add_node("verify", self._verify)
        g.add_node("rewrite", self._rewrite)
        g.add_node("fallback", self._fallback)
        g.add_edge(START, "write")
        g.add_edge("write", "verify")
        g.add_conditional_edges("verify", self._route, {"done": END, "rewrite": "rewrite", "fallback": "fallback"})
        g.add_edge("rewrite", "verify")
        g.add_edge("fallback", END)
        return g.compile()

    # --- Writer 프로토콜 ------------------------------------------------------------

    def write(self, selection: dict[str, list[ItemFact]]) -> dict:
        if not (selection["rising"] or selection["falling"]):
            return TemplateWriter().write(selection)  # 쓸 거리가 없는 날은 모델을 부르지 않는다
        try:
            final = self.graph.invoke({"selection": selection})
        except Exception as e:  # 모델 호출 실패(장애·키 오류 등): 그날 브리핑은 템플릿 문장으로라도 발행한다
            self.last_run = {"model": self.model_name, "rewrites": 0, "fallback": True,
                             "error": f"{type(e).__name__}: {e}"[:300]}
            return TemplateWriter().write(selection)
        self.last_run = {"model": self.model_name, "rewrites": final["rewrites"], "fallback": final["fell_back"]}
        return final["draft"]
