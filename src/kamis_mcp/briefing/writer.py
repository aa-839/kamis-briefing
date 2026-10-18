"""브리핑 문장 작성.

Writer는 select() 결과를 받아 headline과 품목별 comment를 돌려준다.
- TemplateWriter: LLM 없이 틀에 맞춰 쓴다. 오프라인 개발·테스트용이자 LLM 결과와 비교할 기준선.
- (예정) ClaudeWriter: LLM이 같은 facts로 자연스러운 문장을 쓴다.

규칙: 문장에 들어가는 숫자는 facts에 있는 값만 쓴다(verify.py가 검사).
"""

from datetime import date, timedelta
from typing import Protocol

from .facts import ItemFact


class Writer(Protocol):
    def write(self, selection: dict[str, list[ItemFact]]) -> dict: ...


def josa(word: str, pair: str) -> str:
    """받침에 맞는 조사를 붙인다. pair는 '이/가', '은/는' 형식. 괄호 속은 건너뛴다('사과(후지)' → '사과')."""
    with_final, without_final = pair.split("/")
    base = word.split("(")[0].strip() or word
    last = base[-1]
    has_final = "가" <= last <= "힣" and (ord(last) - ord("가")) % 28 != 0
    return word + (with_final if has_final else without_final)


def won(v: float) -> str:
    return f"{v:,.0f}원"


def pct(v: float) -> str:
    return f"{abs(v):.1f}%"


def since_1w(f: ItemFact) -> str:
    """'일주일 새' — 공휴일 때문에 비교일이 정확히 7일 전이 아니면 날짜를 밝힌다('10월 8일보다')."""
    if f.base_1w_date and f.survey_date:
        base = date.fromisoformat(f.base_1w_date)
        if base != date.fromisoformat(f.survey_date) - timedelta(days=7):
            return f"{base.month}월 {base.day}일보다"
    return "일주일 새"


class TemplateWriter:
    def write(self, selection: dict[str, list[ItemFact]]) -> dict:
        rising, falling = selection["rising"], selection["falling"]
        parts = []
        if rising:
            f = rising[0]
            parts.append(f"{josa(f.label, '이/가')} {since_1w(f)} {pct(f.change_1w_pct)} 올랐고")
        if falling:
            f = falling[0]
            same_base = rising and since_1w(rising[0]) == since_1w(f)
            when = "" if same_base else f"{since_1w(f)} "
            parts.append(f"{josa(f.label, '은/는')} {when}{pct(f.change_1w_pct)} 내렸습니다")
        headline = ", ".join(parts) + "." if parts else "이번 주는 크게 움직인 품목이 없습니다."
        if rising and not falling:
            headline = headline.replace("올랐고.", "올랐습니다.")

        comments = {}
        for f in rising + falling:
            comments[f.label] = self._comment(f)
        return {"headline": headline, "comments": comments}

    @staticmethod
    def _comment(f: ItemFact) -> str:
        bits = []
        if f.vs_normal_pct is not None:
            word = "비쌉니다" if f.vs_normal_pct > 0 else "저렴합니다"
            bits.append(f"평년보다 {pct(f.vs_normal_pct)} {word}.")
        if f.change_1y_pct is not None:
            word = "높습니다" if f.change_1y_pct > 0 else "낮습니다"
            bits.append(f"작년 이맘때보다 {pct(f.change_1y_pct)} {word}.")
        return " ".join(bits)
