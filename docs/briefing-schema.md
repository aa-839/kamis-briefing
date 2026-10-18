# 브리핑 JSON 형식 (schema_version 1)

홈페이지가 읽는 파일은 두 종류다. 샘플(가짜 데이터)은 `samples/briefings/`에 있다.

## `index.json`: 발행 목록 (최신순)

```json
{
  "briefings": [
    { "date": "2026-10-13", "headline": "…", "verified": true, "is_mock": false, "file": "2026-10-13.json" }
  ],
  "updated_at": "2026-10-13T09:05:12+09:00"
}
```

## `<날짜>.json`: 하루치 브리핑

| 필드 | 타입 | 설명 |
|---|---|---|
| `schema_version` | number | 형식이 바뀌면 올라감. 현재 `1` |
| `is_mock` | boolean | `true`면 가짜 데이터. 화면에 "샘플" 표시 권장 |
| `date` | `"YYYY-MM-DD"` | 발행일 |
| `survey_date` | `"YYYY-MM-DD"` \| null | KAMIS 가격 조사일. 출처 표기에 사용 |
| `generated_at` | ISO 8601 | 생성 시각 |
| `headline` | string | 한 줄 요약 |
| `sections.rising` | Item[] (0~3개) | 1주 전 대비 많이 오른 품목 |
| `sections.falling` | Item[] (0~3개) | 1주 전 대비 많이 내린 품목(지금 사기 좋은) |
| `sections.vs_normal.expensive` | `{item, vs_normal_pct}`[] | 평년보다 10% 이상 비싼 품목 |
| `sections.vs_normal.cheap` | `{item, vs_normal_pct}`[] | 평년보다 10% 이상 싼 품목 |
| `items` | Item[] | 장바구니 전체 품목(표로 보여줄 때). `comment`는 항상 null |
| `missing` | string[] | 그날 데이터가 없어 빠진 품목 |
| `history` | `{ [item]: {date, price}[] }` | rising·falling 품목의 최근 30일 가격(그래프용, 평일만) |
| `verification` | `{checked, matched, passed, failures}` | 사실 검증 결과. 배지에 사용 |
| `writer` | string | 문장을 쓴 방식: `LLMWriter` 또는 `TemplateWriter` |
| `writing` | object \| null | LLM 작성 기록 `{model, rewrites, fallback, error?}`. `rewrites`=검증 실패로 다시 쓴 횟수, `fallback`=끝내 실패해 템플릿 문장으로 대체됐는지. 템플릿만 쓴 날은 `null` |
| `source` | string | 출처 문구. 화면에 그대로 표기 |

### Item

| 필드 | 타입 | 설명 |
|---|---|---|
| `item` | string | 표시 이름 (예: `"사과(후지)"`) |
| `kind` | string \| null | 품종 (예: `"홍로"`, `"여름(고랭지)"`). 사과·배추처럼 철마다 바뀌는 품목은 그날 조사된 품종 |
| `unit` | string \| null | 가격 단위 (예: `"10개"`, `"1포기"`). **가격과 항상 함께 표시** |
| `price` | number | 원 단위 가격 |
| `change_1w_pct` | number \| null | 1주 전 대비 변동률(%). 양수=상승 |
| `base_1w_date` | `"YYYY-MM-DD"` \| null | 1주 전 비교에 쓴 날짜. 보통 조사일 7일 전이고, 그날이 공휴일이면 그 전 조사일. **7일 전이 아니면 화면에 날짜를 밝힌다** |
| `change_1y_pct` | number \| null | 1년 전 대비 |
| `vs_normal_pct` | number \| null | 평년 대비 |
| `comment` | string \| null | 품목 설명 문장 |

## 주의

- `null`이 올 수 있는 필드는 실제로 `null`이 온다(비교 가격이 없는 날 등). 화면에서 처리할 것.
- 섹션 배열은 비어 있을 수 있다(크게 움직인 품목이 없는 날).
- 변동률은 이미 계산된 값이다. 화면에서 다시 계산하지 말고 그대로 표시한다.
- `date`(발행일)와 `survey_date`(조사일)는 다를 수 있다. 주말·공휴일이나 당일 가격이 아직 안 나온 시각엔 가장 최근 조사일 가격을 쓴다.
- `base_1w_date`는 schema_version 1에 나중에 추가된 필드다. 없으면 `null`로 취급한다.
