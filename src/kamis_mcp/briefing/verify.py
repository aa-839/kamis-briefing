"""사실 검증: 브리핑 문장 속 숫자가 KAMIS 원본에서 나온 값인지 확인한다.

LLM이 쓴 글에서 '%'와 '원'이 붙은 숫자를 모두 뽑아,
- 품목 comment의 숫자는 그 품목의 facts에서,
- headline의 숫자는 브리핑에 나온 모든 품목의 facts에서
찾을 수 있어야 통과다. 가격은 정확히 일치, 변동률은 소수 첫째 자리 일치
또는 정수로 반올림한 값까지 허용한다("18.2%" → "18%"는 OK, "19%"는 실패).

한계: 숫자의 '방향'(올랐다/내렸다)과 '%·원' 없는 숫자는 아직 검사하지 않는다.
"""

import math
import re

from .facts import ItemFact

NUM_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(%|원)")
PCT_FIELDS = ("change_1w_pct", "change_1m_pct", "change_1y_pct", "vs_normal_pct")


def _allowed(facts: list[ItemFact]) -> tuple[set[float], set[float]]:
    prices, pcts = set(), set()
    for f in facts:
        prices.add(round(f.price))
        for name in ("price_1w_ago", "price_1m_ago", "price_1y_ago", "price_normal"):
            if (v := getattr(f, name)) is not None:
                prices.add(round(v))
        for name in PCT_FIELDS:
            if (v := getattr(f, name)) is not None:
                pcts.add(abs(v))
    return prices, pcts


def _pct_ok(x: float, allowed: set[float]) -> bool:
    for v in allowed:
        if abs(x - v) < 0.05:
            return True
        if x == int(x) and x == math.floor(v + 0.5):
            return True
    return False


def check_text(text: str, facts: list[ItemFact]) -> list[dict]:
    """text 속 숫자마다 {value, kind, ok}."""
    prices, pcts = _allowed(facts)
    results = []
    for m in NUM_RE.finditer(text):
        x = float(m.group(1).replace(",", ""))
        kind = "pct" if m.group(2) == "%" else "price"
        ok = _pct_ok(x, pcts) if kind == "pct" else round(x) in prices
        results.append({"text": m.group(0), "value": x, "kind": kind, "ok": ok})
    return results


def verify(written: dict, selection: dict[str, list[ItemFact]]) -> dict:
    shown = {f.label: f for key in ("rising", "falling", "expensive", "cheap") for f in selection[key]}
    checks = [{"where": "headline", **c} for c in check_text(written["headline"], list(shown.values()))]
    for label, comment in written["comments"].items():
        fact = shown.get(label)
        if fact is None:
            checks.append({"where": label, "text": "(브리핑에 없는 품목에 대한 comment)", "ok": False})
            continue
        checks.extend({"where": label, **c} for c in check_text(comment, [fact]))
    failed = [c for c in checks if not c["ok"]]
    return {"checked": len(checks), "matched": len(checks) - len(failed), "passed": not failed, "failures": failed}
