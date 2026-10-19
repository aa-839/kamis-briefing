// 브리핑 JSON을 불러와 화면을 채운다.
//
// 주소 규칙
//   ./                 → 최신 브리핑
//   ./?date=2026-10-13 → 해당 날짜 브리핑
//   ./?data=../samples/briefings/ → 다른 데이터 폴더(개발용 샘플)
//
// 원칙: 데이터는 항상 textContent로 넣는다. innerHTML에 데이터를 넣으면
// 문자열 속 태그가 실행될 수 있다(XSS). HTML 구조는 index.html의 <template>에 있다.

import { won, longDate, change, parseDate } from './format.js';
import { drawSparkline } from './spark.js';

const params = new URLSearchParams(location.search);
const DATA_BASE = safeDataBase(params.get('data')) ?? 'data/';

const $ = (sel) => document.querySelector(sel);

main();

async function main() {
  const status = $('#status');
  try {
    const index = await getJSON('index.json');
    const entries = index.briefings ?? [];
    if (entries.length === 0) throw new Error('아직 발행된 브리핑이 없습니다.');

    const wanted = params.get('date');
    const entry = entries.find((e) => e.date === wanted) ?? entries[0];
    if (wanted && entry.date !== wanted) {
      status.textContent = `${wanted} 브리핑이 없어 최신 브리핑을 보여 드립니다.`;
    } else {
      status.textContent = '';
    }

    const briefing = await getJSON(entry.file);
    renderBriefing(briefing);
    renderArchive(entries, entry.date);
  } catch (err) {
    status.textContent = `브리핑을 불러오지 못했습니다. ${err.message}`;
    status.classList.add('status--error');
    console.error(err);
  }
}

async function getJSON(file) {
  const res = await fetch(new URL(file, new URL(DATA_BASE, location.href)));
  if (!res.ok) throw new Error(`${file} (${res.status})`);
  return res.json();
}

/** ?data= 는 같은 사이트 안의 상대 경로만 허용한다(다른 사이트의 JSON을 끌어오지 못하게). */
function safeDataBase(value) {
  if (!value || /^[a-z]+:|^\/\//i.test(value)) return null;
  return value.endsWith('/') ? value : `${value}/`;
}

// ---------------------------------------------------------------------------

function renderBriefing(b) {
  document.title = `${longDate(b.date)} 장바구니 물가 · 오늘의 장바구니 물가`;
  $('#mock-banner').hidden = !b.is_mock;
  // 소급 생성: 그날 발행한 게 아니라 나중에 과거 KAMIS 데이터로 만든 브리핑임을 숨기지 않는다
  const backfill = $('#backfill-badge');
  backfill.hidden = !b.backfilled;
  if (b.backfilled) backfill.textContent = `소급 생성 · ${b.generated_at.slice(0, 10)}에 과거 데이터로 작성`;

  setTime($('#briefing-date'), b.date, longDate(b.date));
  $('#headline').textContent = b.headline;
  $('#source').textContent = b.source;
  if (b.survey_date) setTime($('#survey-date'), b.survey_date, b.survey_date.replaceAll('-', '.'));

  renderBadge(b.verification);
  renderCards($('#rising-list'), b.sections.rising, b.history, b.survey_date);
  renderCards($('#falling-list'), b.sections.falling, b.history, b.survey_date);
  renderChips($('#expensive-list'), b.sections.vs_normal.expensive);
  renderChips($('#cheap-list'), b.sections.vs_normal.cheap);
  renderTable(b.items, b.survey_date);
  renderHowLog(b);

  const missing = $('#missing-note');
  missing.hidden = !b.missing?.length;
  missing.textContent = `오늘 조사되지 않은 품목: ${b.missing?.join(', ')}`;

  $('#briefing').hidden = false;
}

/**
 * 오늘의 검증 기록: 숫자 대조 결과, 1년 기준으로 뺀 품목, 걸러낸 원인 근거와 그 이유.
 * 이 브리핑의 가장 중요한 부분(AI가 틀린 것을 내보내지 않은 증거)이라 화면에 그대로 보여 준다.
 */
function renderHowLog(b) {
  const lines = [];
  const add = (strong, text, quote) => {
    const li = document.createElement('li');
    const s = document.createElement('strong');
    s.textContent = strong;
    li.append(s, ` ${text}`);
    if (quote) {
      const q = document.createElement('q');
      q.textContent = quote.length > 70 ? `${quote.slice(0, 70)}…` : quote;
      li.append(document.createElement('br'), q);
    }
    lines.push(li);
  };

  const v = b.verification;
  const w = b.writing;
  let wrote = 'AI 없이 정해진 문장으로 썼어요.';
  if (w) {
    wrote = w.fallback
      ? 'AI 문장이 끝내 검증을 통과하지 못해 정해진 문장으로 냈어요.'
      : w.rewrites
        ? `AI가 처음 쓴 문장이 검증에 걸려 ${w.rewrites}번 다시 썼어요.`
        : 'AI가 쓴 문장이 한 번에 통과했어요.';
  }
  add('숫자 대조', `문장 속 숫자 ${v.checked}개 중 ${v.matched}개가 KAMIS 원본과 일치. ${wrote}`);

  for (const e of b.excluded_good_buys ?? []) {
    const why = e.cheaper_days_pct != null
      ? `최근 1년 중 비싼 편(오늘보다 싼 날 ${e.cheaper_days_pct}%)이라`
      : '평년보다 싸지 않아';
    add('사기 좋은 품목에서 뺌', `${e.item}: 지난주보다 ${Math.abs(e.change_1w_pct).toFixed(1)}% 내렸지만 ${why} 추천하지 않았어요.`);
  }

  const c = b.cause_search;
  if (c) {
    add('원인 근거', `${c.searched}개 품목의 기사를 찾아 ${c.found}개 품목만 원인을 실었어요. 아래 근거는 검사에서 걸러냈어요.`);
    const seen = new Set();
    for (const r of c.rejected ?? []) {
      const key = `${r.item}|${r.reason}`;
      if (seen.has(key) || seen.size >= 8) continue;
      seen.add(key);
      const who = r.by === 'grade' ? 'AI 심사' : '코드 검사';
      add(`걸러냄 · ${r.item}`, `(${who}) ${r.reason}`, r.quote);
    }
  }
  $('#how-log').replaceChildren(...lines);
}

function renderBadge(v) {
  const badge = $('#verify-badge');
  if (v.passed) {
    badge.textContent = `✅ 숫자 ${v.checked}개 원본 대조 완료`;
    badge.title = '문장 속 가격과 변동률을 KAMIS 원본 데이터와 자동으로 대조했습니다.';
  } else {
    badge.textContent = `⚠️ 숫자 ${v.checked}개 중 ${v.checked - v.matched}개 불일치`;
    badge.classList.add('badge--fail');
  }
}

function renderCards(list, items, history, surveyDate) {
  const tpl = $('#card-template');
  list.replaceChildren(
    ...items.map((item) => {
      const card = tpl.content.firstElementChild.cloneNode(true);
      card.querySelector('.card__name').textContent = item.item;
      card.querySelector('.card__kind').textContent = item.kind && item.kind !== item.item ? item.kind : '';

      const price = card.querySelector('.card__price-value');
      price.value = item.price; // <data value>: 사람이 읽는 값과 기계가 읽는 값을 함께
      price.textContent = won(item.price);
      card.querySelector('.card__unit').textContent = item.unit ? `/ ${item.unit}` : '';

      const base = movedBase(item.base_1w_date, surveyDate);
      fillChange(card.querySelector('.card__change'), item.change_1w_pct, base ? `${base.long}보다` : '1주 전보다', base);
      fillYear(card.querySelector('.card__year'), item.year);
      drawSparkline(card.querySelector('.spark__svg'), history?.[item.item], item.item, item.year);
      fillSparkCaption(card.querySelector('.spark__caption'), history?.[item.item], item.year);
      card.querySelector('.card__comment').textContent = item.comment ?? '';
      fillNutrition(card.querySelector('.nutri'), item.nutrition);
      fillCause(card.querySelector('.cause'), item.cause);
      return card;
    }),
  );
  list.nextElementSibling.hidden = items.length > 0; // .empty 안내문
}

/**
 * '최근 1년 중 위치' — 카드에서 가격 바로 아래, 가장 먼저 보이게.
 * cheaper_days_pct = 최근 1년 중 오늘보다 싼 날의 비율. 등급 기준은 파이썬 facts.year_level과 같다.
 */
function fillYear(el, year) {
  if (!year) return;
  const p = year.cheaper_days_pct;
  const level = p <= 20 ? '매우 싼 편' : p <= 50 ? '싼 편' : p <= 80 ? '비싼 편' : '매우 비싼 편';
  const strong = document.createElement('strong');
  strong.className = `year-level year-level--${p <= 50 ? 'low' : 'high'}`;
  strong.textContent = level;
  const detail = document.createElement('span');
  detail.className = 'card__year-detail';
  detail.textContent = `오늘보다 싼 날 ${p}%`;
  el.replaceChildren('최근 1년 중 ', strong, ' ', detail);
  el.hidden = false;
}

/**
 * 그래프 설명: 고정 문구 대신 실제로 그린 데이터의 기간·조사일 수를 쓴다.
 * (데이터가 30일치인데 '최근 1년'이라고 쓰면 검증을 내세우는 페이지가 스스로 틀린 말을 하게 된다)
 */
function fillSparkCaption(caption, series, year) {
  if (!series || series.length < 2) return;
  const ym = (iso) => `${iso.slice(0, 4)}.${Number(iso.slice(5, 7))}월`;
  const avg = year?.avg ?? series.reduce((sum, p) => sum + p.price, 0) / series.length;
  caption.textContent =
    `${ym(series[0].date)}~${ym(series.at(-1).date)} · 조사 ${series.length}일 · 평균 ${won(avg)}(점선)`;
}

/** 영양성분 100g당. 값은 성분표 원본 그대로 보여 주고, 어떤 식품 항목 기준인지 밝힌다. */
function fillNutrition(box, n) {
  if (!n?.values?.length) return;
  box.querySelector('.nutri__base').textContent = `${n.base}당`;
  box.querySelector('.nutri__list').replaceChildren(
    ...n.values.map(({ name, value, unit }) => {
      const li = document.createElement('li');
      const b = document.createElement('b');
      b.textContent = `${value}${unit}`;
      li.append(`${name} `, b);
      return li;
    }),
  );
  box.querySelector('.nutri__source').textContent =
    `${n.source} · ${n.food_name.replaceAll('_', ' ')} 기준`;
  box.hidden = false;
}

/** 원인 인용 블록. 인용문·출처는 기사에서 온 글이라 반드시 textContent로 넣는다. */
function fillCause(box, cause) {
  if (!cause) return; // 근거가 확인되지 않은 품목은 원인을 보여 주지 않는다
  box.querySelector('.cause__summary strong').textContent = cause.summary;
  const quote = box.querySelector('.cause__quote');
  quote.cite = cause.url;
  quote.querySelector('p').textContent = cause.quote;
  const link = box.querySelector('.cause__source a');
  link.href = safeUrl(cause.url);
  const date = cause.published ? ` · ${cause.published.slice(5).replace('-', '/')}` : '';
  link.textContent = `${cause.publisher}${date} — ${cause.title}`;
  box.hidden = false;
}

/** http(s) 주소만 링크로 쓴다(javascript: 같은 주소가 섞여 들어와도 실행되지 않게). */
function safeUrl(url) {
  try {
    const u = new URL(url);
    return u.protocol === 'https:' || u.protocol === 'http:' ? u.href : '#';
  } catch {
    return '#';
  }
}

function renderChips(list, items) {
  if (items.length === 0) {
    const li = document.createElement('li');
    li.className = 'chip';
    li.textContent = '해당 없음';
    list.replaceChildren(li);
    return;
  }
  list.replaceChildren(
    ...items.map(({ item, vs_normal_pct }) => {
      const li = document.createElement('li');
      li.className = 'chip';
      const pct = document.createElement('b');
      pct.textContent = `${vs_normal_pct > 0 ? '+' : ''}${vs_normal_pct.toFixed(1)}%`;
      li.append(`${item} `, pct);
      return li;
    }),
  );
}

function renderTable(items, surveyDate) {
  $('#items-body').replaceChildren(
    ...items.map((item) => {
      const tr = document.createElement('tr');

      const name = document.createElement('th'); // 각 행의 제목 칸은 th scope="row"
      name.scope = 'row';
      name.textContent = item.item;
      if (item.season?.low_season) name.append(' ', seasonBadge(item.season, surveyDate));
      // 품종이 이름과 다르면 같이 보여 준다(사과 → "홍로 · 10개"). 철마다 품종이 바뀌는 품목이 있어서.
      const sub = [item.kind && item.kind !== item.item ? item.kind : null, item.unit].filter(Boolean).join(' · ');
      if (sub) {
        const unit = document.createElement('span');
        unit.className = 'item-unit';
        unit.textContent = sub;
        name.append(unit);
      }

      const price = document.createElement('td');
      price.className = 'num';
      price.textContent = won(item.price);

      tr.append(name, price);
      const base = movedBase(item.base_1w_date, surveyDate);
      for (const [pct, b] of [[item.change_1w_pct, base], [item.change_1y_pct], [item.vs_normal_pct]]) {
        const td = document.createElement('td');
        td.className = 'num';
        fillChange(td, pct, b ? `${b.long}보다` : '', b);
        tr.append(td);
      }
      return tr;
    }),
  );
}

/**
 * '예년 저가철' 표시. 근거(최근 몇 년, 연평균 대비 몇 %, 가장 싼 달)를 말풍선과 스크린리더 문장으로 함께 준다.
 * 제철과는 다르다: KAMIS 월별 가격에서 계산한 '예년엔 이 달에 쌌다'는 지난 기록이다.
 */
function seasonBadge(season, surveyDate) {
  const month = parseDate(surveyDate).getMonth() + 1;
  const years = season.years.length ? `${season.years[0]}~${season.years.at(-1)}년` : '최근 몇 년';
  const pct = Math.abs(season.month_vs_year_avg_pct).toFixed(1);
  const why = `${years} ${month}월 가격은 연평균보다 평균 ${pct}% 낮았어요.` +
    (season.cheapest_months.length ? ` 예년에 가장 싼 달: ${season.cheapest_months.join('·')}월.` : '');
  const badge = document.createElement('span');
  badge.className = 'season-badge';
  badge.title = why;
  const label = document.createElement('span');
  label.setAttribute('aria-hidden', 'true');
  label.textContent = '예년 저가철';
  const sr = document.createElement('span');
  sr.className = 'visually-hidden';
  sr.textContent = `예년 저가철. ${why}`;
  badge.append(label, sr);
  return badge;
}

/**
 * 1주 전이 공휴일이라 비교일이 7일 전이 아닐 때만 그 날짜를 돌려준다(아니면 null).
 * 예) 조사일 10/16, 비교일 10/08 → { short: '10/8', long: '10월 8일' }
 */
function movedBase(baseIso, surveyIso) {
  if (!baseIso || !surveyIso) return null;
  const weekAgo = parseDate(surveyIso);
  weekAgo.setDate(weekAgo.getDate() - 7);
  const base = parseDate(baseIso);
  if (base.getTime() === weekAgo.getTime()) return null;
  const [m, d] = [base.getMonth() + 1, base.getDate()];
  return { short: `${m}/${d}`, long: `${m}월 ${d}일` };
}

/** 변동률 표시. 화면에는 "▲ 18.2%", 스크린리더에는 "1주 전보다 18.2% 상승"으로 읽힌다. */
function fillChange(el, pct, prefix = '', base = null) {
  const c = change(pct);
  const pill = document.createElement('span');
  pill.className = `change change--${c.dir}`;
  const visible = document.createElement('span');
  visible.setAttribute('aria-hidden', 'true'); // 기호는 읽지 않고
  visible.textContent = c.text;
  const sr = document.createElement('span');
  sr.className = 'visually-hidden'; // 대신 문장으로 읽어 준다
  sr.textContent = `${prefix} ${c.label}`.trim();
  pill.append(visible, sr);
  el.replaceChildren(pill);
  if (base && c.dir !== 'none') {
    const note = document.createElement('span');
    note.className = 'change__base';
    note.setAttribute('aria-hidden', 'true'); // 스크린리더는 위 문장(prefix)으로 이미 들음
    note.textContent = `${base.short} 대비`;
    note.title = `1주 전이 공휴일이라 그 전 조사일(${base.long})과 비교했습니다.`;
    el.append(note);
  }
}

function renderArchive(entries, currentDate) {
  const list = $('#archive-list');
  list.replaceChildren(
    ...entries.map((e) => {
      const li = document.createElement('li');
      const a = document.createElement('a');
      const url = new URL(location.href);
      url.searchParams.set('date', e.date);
      a.href = url.search;
      if (e.date === currentDate) a.setAttribute('aria-current', 'page');

      const time = document.createElement('time');
      setTime(time, e.date, longDate(e.date));
      const headline = document.createElement('span');
      headline.textContent = e.headline;
      a.append(time, headline);
      if (e.backfilled) {
        const tag = document.createElement('span');
        tag.className = 'backfill-badge';
        tag.textContent = '소급 생성';
        time.after(' ', tag);
      }
      li.append(a);
      return li;
    }),
  );
  $('#archive').hidden = false;
}

function setTime(el, iso, text) {
  el.dateTime = iso;
  el.textContent = text;
}
