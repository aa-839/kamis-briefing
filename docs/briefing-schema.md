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
| `date` | `"YYYY-MM-DD"` | 브리핑 날짜 = 가격 조사일. 파일 이름도 이 날짜 |
| `survey_date` | `"YYYY-MM-DD"` \| null | KAMIS 가격 조사일. 출처 표기에 사용 |
| `generated_at` | ISO 8601 | 생성 시각 |
| `headline` | string | 한 줄 요약 |
| `sections.rising` | Item[] (0~3개) | 1주 전 대비 많이 오른 품목 |
| `sections.falling` | Item[] (0~3개) | 지금 사기 좋은 품목: 1주 전 대비 3% 이상 내렸고 + 최근 1년 중 오늘보다 싼 날이 절반 이하 |
| `sections.vs_normal.expensive` | `{item, vs_normal_pct}`[] | 평년보다 10% 이상 비싼 품목 |
| `sections.vs_normal.cheap` | `{item, vs_normal_pct}`[] | 평년보다 10% 이상 싼 품목 |
| `items` | Item[] | 장바구니 전체 품목(표로 보여줄 때). `comment`는 항상 null |
| `missing` | string[] | 그날 데이터가 없어 빠진 품목 |
| `history` | `{ [item]: {date, price}[] }` | rising·falling 품목의 최근 1년 가격(그래프용, 조사일만). 철마다 품종이 바뀌는 품목은 같은 단위 품종을 이어 붙임 |
| `verification` | `{checked, matched, passed, failures}` | 사실 검증 결과. 배지에 사용 |
| `writer` | string | 문장을 쓴 방식: `LLMWriter` 또는 `TemplateWriter` |
| `writing` | object \| null | LLM 작성 기록 `{model, rewrites, fallback, error?}`. `rewrites`=검증 실패로 다시 쓴 횟수, `fallback`=끝내 실패해 템플릿 문장으로 대체됐는지. 템플릿만 쓴 날은 `null` |
| `source` | string | 출처 문구. 화면에 그대로 표기 |
| `cause_search` | object \| null | 원인 찾기 기록 `{model, searched, found, rejected[], errors[]}`. `rejected`는 탈락한 인용과 이유 |

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
| `cause` | Cause \| null | 가격 변동 원인(rising·falling 품목만). 근거가 확인된 것만 있고, 없으면 `null` |
| `season` | Season \| null | 예년 저가철 정보. 축산물이나 월별 자료가 모자라면 `null` |
| `nutrition` | Nutrition \| null | 영양성분 100g당(rising·falling 품목만). 공식 성분표 값 그대로 |
| `year` | object \| null | 최근 1년 중 위치 `{cheaper_days_pct, avg, min, max, days, since}`. `cheaper_days_pct`=최근 1년 중 오늘보다 싼 날의 비율(%). rising·falling 품목만 |

### Nutrition

공공데이터포털 「전국통합식품영양성분정보(원재료성식품) 표준데이터」(농촌진흥청 국가표준식품성분표, 국립수산과학원 표준수산물성분표). 값은 원본 문자열 그대로, 효능 문구 없음.

| 필드 | 타입 | 설명 |
|---|---|---|
| `base` | string | 기준량 (`"100g"`) |
| `values` | `{name, value, unit}`[] | 성분 (열량·단백질·식이섬유·비타민C·칼륨 중 값이 있는 것). `value`는 원본 문자열 |
| `food_name` | string | 성분표에서 고른 식품명 (예: `"배추_생것"`). **화면에 기준으로 표시** |
| `source`, `reference_date` | string | 출처 기관, 데이터 기준일 |

### Season

KAMIS 월별 소매가격 최근 3년으로 계산한 '예년엔 이 달에 쌌다'(예측 아님, 제철과 다름).

| 필드 | 타입 | 설명 |
|---|---|---|
| `low_season` | boolean | 이번 달이 예년 저가철인지. 화면의 '예년 저가철' 표시 |
| `month_vs_year_avg_pct` | number \| null | 예년 이 달 가격이 연평균보다 몇 % 높았나(음수=쌌음) |
| `cheapest_months` | number[] | 예년에 가장 쌌던 달(연평균보다 낮은 달 중 최대 3개) |
| `years` | number[] | 계산에 쓴 연도 |

### Cause

기사 원문 한 문장을 그대로 인용한다. 인용문이 기사 본문에 있는지, 이 품목·이 방향·이 시기의 원인인지 검사를 통과한 것만 실린다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `summary` | string | 원인 요약 (예: `"산지 교체로 인한 공급 감소"`) |
| `quote` | string | 기사 원문 인용 (150자 이하) |
| `url`, `title` | string | 기사 주소·제목. **인용과 함께 항상 출처로 표시** |
| `publisher` | string | 언론사·기관 이름 |
| `published` | `"YYYY-MM-DD"` \| null | 기사 날짜 |
| `grade` | string | AI 심사가 적절하다고 본 이유(내부 기록용) |

## 주의

- `null`이 올 수 있는 필드는 실제로 `null`이 온다(비교 가격이 없는 날 등). 화면에서 처리할 것.
- 섹션 배열은 비어 있을 수 있다(크게 움직인 품목이 없는 날).
- 변동률은 이미 계산된 값이다. 화면에서 다시 계산하지 말고 그대로 표시한다.
- 주말·공휴일이나 당일 가격이 아직 안 나온 시각에 실행하면 가장 최근 조사일 브리핑이 만들어진다. 실제 생성 시각은 `generated_at`.
- `base_1w_date`는 schema_version 1에 나중에 추가된 필드다. 없으면 `null`로 취급한다.
