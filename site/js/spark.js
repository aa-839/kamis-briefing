// 최근 30일 가격을 작은 선 그래프(스파크라인)로 그린다. 라이브러리 없이 SVG path만 쓴다.

import { won, shortDate } from './format.js';

const W = 200; // index.html의 viewBox="0 0 200 48"과 맞춘다
const H = 48;
const PAD = 4; // 선이 위아래 끝에 붙어 잘리지 않게
const SVG_NS = 'http://www.w3.org/2000/svg';

/**
 * @param {SVGSVGElement} svg  템플릿에 있는 빈 <svg>
 * @param {{date: string, price: number}[]} series
 * @param {string} name  품목 이름(대체 텍스트용)
 */
export function drawSparkline(svg, series, name) {
  const figure = svg.closest('.spark');
  if (!series || series.length < 2) {
    figure.hidden = true;
    return;
  }

  const prices = series.map((p) => p.price);
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const range = max - min || 1; // 가격이 30일 내내 같으면 0으로 나누지 않게

  const x = (i) => (i / (series.length - 1)) * W;
  const y = (v) => PAD + (1 - (v - min) / range) * (H - PAD * 2);

  const points = series.map((p, i) => `${x(i).toFixed(1)},${y(p.price).toFixed(1)}`);
  const line = `M${points.join('L')}`;
  const area = `${line}L${W},${H}L0,${H}Z`;

  // 선 색은 중립색. 카드의 ▲▼(1주 기준)와 30일 추세가 반대일 수 있어, 색으로 방향을 말하지 않는다.
  const first = series[0];
  const last = series[series.length - 1];

  // 그래프를 볼 수 없는 사용자(스크린리더)에게는 핵심만 말로 전달
  svg.querySelector('title').textContent =
    `${name} 최근 가격 추이: ${shortDate(first.date)} ${won(first.price)}에서 ` +
    `${shortDate(last.date)} ${won(last.price)}. 최저 ${won(min)}, 최고 ${won(max)}.`;

  for (const [cls, d] of [['spark__area', area], ['spark__line', line]]) {
    const path = document.createElementNS(SVG_NS, 'path'); // SVG 요소는 createElement가 아니라 NS 버전으로
    path.setAttribute('class', cls);
    path.setAttribute('d', d);
    svg.append(path);
  }
}
