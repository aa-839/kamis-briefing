# 🥬 오늘의 장바구니 물가 — AI 물가 브리핑 에이전트

KAMIS(한국농수산식품유통공사 농산물유통정보) Open API의 농축수산물 소매가격으로
**평일마다 장바구니 물가 브리핑을 자동으로 써서 웹페이지에 발행**합니다.
AI가 쓴 문장 속 **모든 가격과 변동률은 발행 전에 KAMIS 원본과 자동 대조**됩니다.

> 2026 KAMIS 활용사례 공모전 출품작

## 핵심 아이디어: 숫자는 코드가, 문장은 AI가

LLM은 그럴듯한 숫자를 지어내거나(환각) 계산을 틀릴 수 있습니다. 물가 정보에서 틀린 숫자는 곧 잘못된 장보기로 이어지기 때문에, 역할을 나눴습니다.

| 단계 | 담당 | 하는 일 |
|---|---|---|
| 조회 | 코드 | KAMIS API에서 24개 장바구니 품목의 전국 평균 소매가 |
| 사실 계산·선정 | 코드 | 1주·1년·평년 대비 변동률, "많이 오른/내린 품목" 선정 (항상 같은 기준) |
| 작성 | **AI** | 사실만 보고 헤드라인과 품목별 코멘트 작성 |
| 검증 | 코드 | 문장 속 숫자가 원본에 있는지, 그 품목의 숫자인지, 올랐다/내렸다 방향이 맞는지 |
| 재작성 | **AI** | 틀린 곳을 알려 주면 다시 작성 (최대 2번, 그래도 틀리면 템플릿 문장으로 발행) |
| 원인 찾기 | **AI 에이전트** | 많이 오르고 내린 품목의 원인을 언론·공공기관 기사에서 찾아 **원문 그대로 인용** |
| 원인 검증 | 코드 + AI 심사 | 인용이 기사에 실제로 있는지, 그 품목(방울토마토≠토마토, 국산≠수입산)·그 방향·그 시기의 원인인지. 근거가 없으면 원인을 비운다 |

```
START → 작성(LLM) → 검증 ─ 통과 ──────────────────────▶ 발행
                      ├─ 실패 → 재작성(틀린 숫자·이유 피드백) → 검증
                      └─ 2번 실패 → 템플릿 문장 ─────────▶ 발행
```

## 구성

```
src/kamis_mcp/
  client.py          KAMIS Open API 클라이언트
  codes.py           품목·품종·등급 코드표 검색
  server.py          MCP 서버 — Claude 등 AI 앱이 KAMIS 가격을 도구로 조회
  briefing/
    facts.py         가격 → 사실(변동률) 계산, 브리핑 품목 선정
    llm_writer.py    LangGraph 작성 → 검증 → 재작성 루프
    causes.py        LangGraph 원인 찾기: 검색 → 인용 추출 → 코드 검사 → AI 심사 → 재검색
    verify.py        사실 검증기
    pipeline.py      조회 → 작성 → 검증 → JSON 발행 (kamis-brief 명령)
site/                웹페이지 (순수 HTML/CSS/JS, 반응형, 다크 모드, 접근성)
.github/workflows/   평일 자동 발행, 테스트
tests/               실제 KAMIS 응답을 저장해 둔 fixture로 검사
```

## 직접 실행하기

[uv](https://docs.astral.sh/uv/)가 필요합니다.

```bash
cp .env.example .env          # KAMIS 키와 OpenAI 키 입력
uv sync
uv run kamis-brief --out site/data           # 오늘(또는 가장 최근 조사일) 브리핑
uv run kamis-brief --writer template         # LLM 없이
uv run kamis-brief --model openai:gpt-5.4-mini   # 모델 바꾸기
uv run pytest                                # 테스트 (키 불필요)
python -m http.server -d site 8000           # http://localhost:8000
```

MCP 서버를 Claude Code에 연결하면 "요즘 배추 얼마야?" 같은 질문에 AI가 KAMIS를 직접 조회합니다.

```bash
claude mcp add kamis -- uv run --directory /path/to/repo kamis-mcp
```

## 데이터 출처

가격 정보: [KAMIS 농산물유통정보](https://www.kamis.or.kr) (한국농수산식품유통공사) Open API
