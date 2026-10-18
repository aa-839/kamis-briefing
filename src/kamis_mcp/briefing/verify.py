"""사실 검증: 브리핑 문장 속 숫자가 KAMIS 원본에서 나온 값인지 확인한다.

LLM이 쓴 글에서 '%'와 '원'이 붙은 숫자를 모두 뽑아 세 가지를 본다.
1. 값: 원본(facts)에 있는 숫자인가. 가격은 정확히 일치, 변동률은 소수 첫째 자리 일치
   또는 정수로 반올림한 값까지 허용한다("18.2%" → "18%"는 OK, "19%"는 실패).
2. 주인: 그 숫자가 문장에서 말하는 품목의 숫자인가.
   - 품목 comment는 그 품목의 facts에서만 찾는다.
   - headline은 숫자 바로 앞에 나온 품목 이름의 facts에서 찾는다("사과가 19.7% 올랐고" → 사과 facts).
3. 방향: 변동률 바로 뒤의 '올랐/상승/비싸…' 또는 '내렸/하락/저렴…'이 실제 부호와 맞는가.

한계: 방향 단어가 숫자 앞에 오거나("올라서 16.9%") 아예 없으면 방향은 검사하지 못한다.
      '%·원'이 없는 숫자("두 배")와 숫자 없는 주장("크게 올랐다")도 검사하지 않는다.
"""

import math
import re
from dataclasses import dataclass

from .facts import ItemFact

NUM_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(%|원)")
PRICE_FIELDS = ("price", "price_1w_ago", "price_1m_ago", "price_1y_ago", "price_normal")
PCT_FIELDS = ("change_1w_pct", "change_1m_pct", "change_1y_pct", "vs_normal_pct")

# 숫자 바로 뒤에서 찾을 방향 단어. '비싸'를 '싸'보다 먼저 봐야 하므로 상승 쪽을 먼저 검사한다.
UP_RE = re.compile(r"올랐|오른|올라|오름|상승|뛰었|뛴|급등|비싸|비쌉|비싼|높")
DOWN_RE = re.compile(r"내렸|내린|내려|내림|하락|떨어|급락|저렴|싸|쌉|싼|낮")
DIRECTION_WINDOW = 12  # 숫자 뒤 몇 글자 안에서 방향 단어를 찾을지
SENTENCE_END_RE = re.compile(r"[.,!?·]")


@dataclass
class _Mention:
    start: int
    end: int
    fact: ItemFact


def _name(f: ItemFact) -> str:
    return f.label.split("(")[0].strip()  # '배(신고)' → '배', '돼지 삼겹살' 그대로


def _mentions(text: str, facts: list[ItemFact]) -> list[_Mention]:
    """문장 속 품목 이름 위치. 긴 이름 우선: '배추' 안의 '배'는 배로 세지 않는다."""
    found: list[_Mention] = []
    for f in sorted(facts, key=lambda f: -len(_name(f))):
        for m in re.finditer(re.escape(_name(f)), text):
            if not any(m.start() < x.end and x.start < m.end() for x in found):
                found.append(_Mention(m.start(), m.end(), f))
    return sorted(found, key=lambda x: x.start)


def _direction(after: str) -> int:
    """숫자 뒤 짧은 구간의 방향: +1 상승, -1 하락, 0 모름."""
    window = SENTENCE_END_RE.split(after[:DIRECTION_WINDOW], maxsplit=1)[0]
    up, down = UP_RE.search(window), DOWN_RE.search(window)
    if up and (not down or up.start() <= down.start()):
        return 1
    return -1 if down else 0


def _pct_matches(x: float, f: ItemFact) -> list[tuple[str, float]]:
    """x%와 맞는 변동률 필드들 [(필드명, 부호 있는 원래 값)]."""
    out = []
    for name in PCT_FIELDS:
        v = getattr(f, name)
        if v is None:
            continue
        if abs(x - abs(v)) < 0.05 or (x == int(x) and x == math.floor(abs(v) + 0.5)):
            out.append((name, v))
    return out


def _price_ok(x: float, f: ItemFact) -> bool:
    return any((v := getattr(f, name)) is not None and round(v) == round(x) for name in PRICE_FIELDS)


def check_text(text: str, facts: list[ItemFact]) -> list[dict]:
    """text 속 숫자마다 {text, value, kind, item, ok, reason}.

    숫자의 주인은 그 숫자 앞에 마지막으로 나온 품목. 앞에 품목 이름이 없으면 facts 전체에서 찾는다.
    """
    mentions = _mentions(text, facts) if len(facts) > 1 else []
    nums = list(NUM_RE.finditer(text))
    results = []
    for i, m in enumerate(nums):
        before = [x for x in mentions if x.end <= m.start()]
        owners = [before[-1].fact] if before else facts
        x = float(m.group(1).replace(",", ""))
        kind = "pct" if m.group(2) == "%" else "price"
        result = {"text": m.group(0), "value": x, "kind": kind,
                  "item": owners[0].label if len(owners) == 1 else None, "ok": True, "reason": None}

        if kind == "price":
            if not any(_price_ok(x, f) for f in owners):
                result.update(ok=False, reason="원본에 없는 가격")
        else:
            matches = [v for f in owners for _, v in _pct_matches(x, f)]
            next_start = nums[i + 1].start() if i + 1 < len(nums) else len(text)
            direction = _direction(text[m.end():next_start])
            if not matches:
                result.update(ok=False, reason="원본에 없는 변동률")
            elif direction and not any(v != 0 and (v > 0) == (direction > 0) for v in matches):
                actual = "상승" if matches[0] > 0 else "하락"
                result.update(ok=False, reason=f"방향이 반대(실제로는 {actual})")
        results.append(result)
    return results


def verify(written: dict, selection: dict[str, list[ItemFact]]) -> dict:
    shown = {f.label: f for key in ("rising", "falling", "expensive", "cheap") for f in selection[key]}
    checks = [{"where": "headline", **c} for c in check_text(written["headline"], list(shown.values()))]
    for label, comment in written["comments"].items():
        fact = shown.get(label)
        if fact is None:
            checks.append({"where": label, "text": "(브리핑에 없는 품목에 대한 comment)", "ok": False,
                           "reason": "브리핑에 없는 품목"})
            continue
        checks.extend({"where": label, **c} for c in check_text(comment, [fact]))
    failed = [c for c in checks if not c["ok"]]
    return {"checked": len(checks), "matched": len(checks) - len(failed), "passed": not failed, "failures": failed}
