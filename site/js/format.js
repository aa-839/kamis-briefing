// 숫자·날짜 표시 규칙을 한곳에 모은다. 화면 어디서든 같은 모양으로 보이게.

const wonFormat = new Intl.NumberFormat('ko-KR');
const dateFormat = new Intl.DateTimeFormat('ko-KR', {
  year: 'numeric', month: 'long', day: 'numeric', weekday: 'short',
});
const shortDateFormat = new Intl.DateTimeFormat('ko-KR', { month: 'numeric', day: 'numeric', weekday: 'short' });

/** 5820 → "5,820원" */
export const won = (v) => `${wonFormat.format(Math.round(v))}원`;

/** "2026-10-13" → Date. new Date("2026-10-13")은 UTC 자정으로 해석돼 날짜가 하루 밀릴 수 있어 직접 만든다 */
export function parseDate(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d);
}

export const longDate = (iso) => dateFormat.format(parseDate(iso));
export const shortDate = (iso) => shortDateFormat.format(parseDate(iso));

/**
 * 변동률 → 표시용 정보. 색만으로 구분하지 않도록 기호와 읽을 텍스트를 함께 만든다.
 * @returns {{text: string, label: string, dir: 'up'|'down'|'flat'|'none'}}
 */
export function change(pct) {
  if (pct === null || pct === undefined) return { text: '–', label: '비교 자료 없음', dir: 'none' };
  if (pct === 0) return { text: '0.0%', label: '변동 없음', dir: 'flat' };
  const up = pct > 0;
  const abs = Math.abs(pct).toFixed(1);
  return {
    text: `${up ? '▲' : '▼'} ${abs}%`,
    label: `${abs}% ${up ? '상승' : '하락'}`,
    dir: up ? 'up' : 'down',
  };
}
