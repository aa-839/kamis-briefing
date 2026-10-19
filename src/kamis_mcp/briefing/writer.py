"""브리핑 문장 작성.

Writer는 select() 결과를 받아 headline과 품목별 comment를 돌려준다.
- TemplateWriter: LLM 없이 틀에 맞춰 쓴다. 오프라인 개발·테스트용이자 LLM 결과와 비교할 기준선.
- (예정) ClaudeWriter: LLM이 같은 facts로 자연스러운 문장을 쓴다.

규칙: 문장에 들어가는 숫자는 facts에 있는 값만 쓴다(verify.py가 검사).
"""

from datetime import date, timedelta
from typing import Protocol

from .facts import ItemFact, year_level


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
        # 사기 좋은(내린) 품목을 먼저 말한다. 화면도 '지금 사기 좋은 품목'이 위에 있다
        parts = []
        if falling:
            f = falling[0]
            head = f"{josa(f.label, '이/가')} {since_1w(f)} {pct(f.change_1w_pct)}"
            level = year_level(f.year_cheaper_pct)  # 지난주 대비만으로는 정말 싼지 몰라서 1년 위치를 함께 말한다
            parts.append(f"{head} 내려 최근 1년 중 {level}이고" if level else f"{head} 내렸고")
        if rising:
            f = rising[0]
            same_base = falling and since_1w(falling[0]) == since_1w(f)
            when = "" if same_base else f"{since_1w(f)} "
            subject = josa(f.label, "은/는" if falling else "이/가")  # 두 번째 절이면 '양배추는', 혼자면 '양배추가'
            parts.append(f"{subject} {when}{pct(f.change_1w_pct)} 올랐습니다")
        headline = ", ".join(parts) + "." if parts else "이번 주는 크게 움직인 품목이 없습니다."
        if falling and not rising:
            headline = headline.replace("내렸고.", "내렸습니다.").replace("편이고.", "편입니다.")

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
