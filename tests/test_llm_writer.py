"""LLM 작성기의 '작성 → 검증 → 재작성' 루프. 실제 모델 대신 정해 둔 답을 차례로 돌려준다."""

from kamis_mcp.briefing.llm_writer import Draft, ItemComment, LLMWriter

from test_briefing import fact

CABBAGE = fact("배추", w=18.2)  # 1주 +18.2%, 1년 -3.0%, 평년 +31.0%
SELECTION = {"rising": [CABBAGE], "falling": [], "expensive": [CABBAGE], "cheap": []}

GOOD = Draft(headline="배추가 일주일 새 18.2% 올랐습니다.",
             comments=[ItemComment(item="배추", comment="평년보다 31.0% 비쌉니다.")])
FLIPPED = Draft(headline="배추가 일주일 새 18.2% 내렸습니다.",  # 방향 반대
                comments=[ItemComment(item="배추", comment="평년보다 31.0% 비쌉니다.")])
INVENTED = Draft(headline="배추가 일주일 새 25% 올랐습니다.",  # 없는 숫자
                 comments=[ItemComment(item="배추", comment="평년보다 31.0% 비쌉니다.")])


def scripted(*drafts):
    """모델 대신 drafts를 순서대로 돌려주는 작성기. 받은 메시지도 기록한다."""
    w = LLMWriter(model="test:fake")
    calls = []

    def fake(messages):
        calls.append(messages)
        return drafts[len(calls) - 1]

    w._generate = fake
    return w, calls


def test_passes_first_time():
    w, calls = scripted(GOOD)
    assert w.write(SELECTION)["headline"] == GOOD.headline
    assert len(calls) == 1 and w.last_run == {"model": "test:fake", "rewrites": 0, "fallback": False}


def test_rewrites_with_feedback_until_it_passes():
    w, calls = scripted(FLIPPED, GOOD)
    assert w.write(SELECTION)["headline"] == GOOD.headline
    assert w.last_run["rewrites"] == 1 and not w.last_run["fallback"]
    feedback = calls[1][-1][1]  # 재작성 요청의 마지막 메시지
    assert "18.2%" in feedback and "방향이 반대" in feedback


def test_falls_back_to_template_after_max_rewrites():
    w, calls = scripted(INVENTED, FLIPPED, INVENTED)
    out = w.write(SELECTION)
    assert len(calls) == 3  # 첫 작성 + 재작성 2번
    assert w.last_run["fallback"] and "25%" not in out["headline"]


def test_no_model_call_when_nothing_moved():
    w, calls = scripted()
    w.write({"rising": [], "falling": [], "expensive": [], "cheap": []})
    assert not calls


def test_model_error_falls_back_to_template():
    w, _ = scripted()

    def broken(messages):
        raise RuntimeError("API 장애")

    w._generate = broken
    out = w.write(SELECTION)
    assert w.last_run["fallback"] and "API 장애" in w.last_run["error"]
    assert "18.2%" in out["headline"]  # 템플릿 문장
