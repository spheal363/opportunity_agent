import type { Opportunity } from '../types';

/**
 * 候補の開催日をカレンダーに並べるための計算（#47）。
 *
 * **日付は run のタイムゾーンで扱う。**
 * Backend は UTC の ISO で返すので、ブラウザの地域で素朴に変換すると
 * 日付だけの候補（現地 0 時）が前日へずれる。
 *
 * **追加の検索も LLM も呼ばない。** 保存済みの候補だけを使う。
 */

/** `2026-10-16` の形で、指定タイムゾーンの年月日を返す。 */
export function dayIn(iso: string, tz: string): string {
  // en-CA は YYYY-MM-DD を返す。
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: tz,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date(iso));
}

/** 今日（run のタイムゾーンで）。 */
export function todayIn(tz: string): string {
  return dayIn(new Date().toISOString(), tz);
}

/** `2026-09` の並び。**期間がまたがる月をすべて返す。** */
export function monthsBetween(start: string, end: string): string[] {
  const out: string[] = [];
  const [sy, sm] = start.split('-').map(Number);
  const [ey, em] = end.split('-').map(Number);
  let y = sy;
  let m = sm;
  while (y < ey || (y === ey && m <= em)) {
    out.push(`${y}-${String(m).padStart(2, '0')}`);
    m += 1;
    if (m > 12) {
      m = 1;
      y += 1;
    }
  }
  return out;
}

export type Cell = { day: string | null; inMonth: boolean };

/** 日曜はじまりの升目。**前後の月の分は空にする。** */
export function monthGrid(ym: string): Cell[][] {
  const [y, m] = ym.split('-').map(Number);
  const first = new Date(Date.UTC(y, m - 1, 1));
  const days = new Date(Date.UTC(y, m, 0)).getUTCDate();
  const lead = first.getUTCDay();
  const cells: Cell[] = [];
  for (let i = 0; i < lead; i += 1) cells.push({ day: null, inMonth: false });
  for (let d = 1; d <= days; d += 1) {
    cells.push({ day: `${ym}-${String(d).padStart(2, '0')}`, inMonth: true });
  }
  while (cells.length % 7 !== 0) cells.push({ day: null, inMonth: false });
  const weeks: Cell[][] = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return weeks;
}

function addDay(day: string, n: number): string {
  const [y, m, d] = day.split('-').map(Number);
  const t = new Date(Date.UTC(y, m - 1, d + n));
  return t.toISOString().slice(0, 10);
}

/**
 * その候補が占める日。
 *
 * **`end_at` があるときだけ会期として間の日も埋める。**
 * 別々の開催日（9/22 と 10/04 の 2 回開催）は Backend で `end_at` を
 * 入れていないので、間の日を開催日として埋めない。
 */
export function occupiedDays(o: Opportunity, tz: string): string[] {
  if (!o.start_at) return [];
  const start = dayIn(o.start_at, tz);
  if (!o.end_at) return [start];
  const end = dayIn(o.end_at, tz);
  if (end <= start) return [start];
  const out: string[] = [];
  for (let d = start; d <= end; d = addDay(d, 1)) out.push(d);
  return out;
}

/** 会期（複数日にまたがる）か。 */
export function isSpan(o: Opportunity, tz: string): boolean {
  return occupiedDays(o, tz).length > 1;
}

/** ジャンル（希望）ごとの色。**色だけで区別させないので、文字も併記する。** */
const PALETTE = [
  { chip: 'bg-[#e4eee0] text-[#3f6042]', dot: 'bg-[#6f9a6a]' },
  { chip: 'bg-[#e6ecf3] text-[#3c5670]', dot: 'bg-[#6d8cad]' },
  { chip: 'bg-[#f3e9dd] text-[#6b533a]', dot: 'bg-[#b08a5e]' },
  { chip: 'bg-[#efe3ec] text-[#66435f]', dot: 'bg-[#a1729a]' },
  { chip: 'bg-[#e8e9d9] text-[#5a5f3b]', dot: 'bg-[#93995f]' },
];

export function genreColors(wishes: string[]): Map<string, (typeof PALETTE)[number]> {
  const map = new Map<string, (typeof PALETTE)[number]>();
  wishes.forEach((w, i) => map.set(w, PALETTE[i % PALETTE.length]));
  return map;
}

/** 週の中での帯の一区間。**週や月の境界で切れた側は角を丸めない。** */
export type Segment = {
  opportunity: Opportunity;
  /** 0-6。週の何列目から何列目までか。 */
  start: number;
  end: number;
  /** 本当の開始日・終了日か。false なら前後に続いている。 */
  realStart: boolean;
  realEnd: boolean;
  /** 重なりを避けるための段。 */
  lane: number;
};

/**
 * 1 週ぶんの帯を組み立てる（#47）。
 *
 * **同じイベントを日ごとに繰り返さない。** 週の中では 1 本の帯にまとめ、
 * 名前と★は帯に 1 回だけ出す。
 *
 * `week` は日曜はじまりの 7 マス。月の外の日は `null` が入る。
 */
export function weekSegments(week: Cell[], spans: Opportunity[], tz: string): Segment[] {
  const out: Omit<Segment, 'lane'>[] = [];
  for (const o of spans) {
    const days = occupiedDays(o, tz);
    const first = days[0];
    const last = days[days.length - 1];
    let start = -1;
    let end = -1;
    week.forEach((cell, i) => {
      if (!cell.day) return;
      if (cell.day >= first && cell.day <= last) {
        if (start < 0) start = i;
        end = i;
      }
    });
    if (start < 0) continue;
    out.push({
      opportunity: o,
      start,
      end,
      realStart: week[start].day === first,
      realEnd: week[end].day === last,
    });
  }
  // 長い帯を上の段へ。**重なったら別の段に置く。**
  out.sort((a, b) => b.end - b.start - (a.end - a.start) || a.start - b.start);
  const lanes: number[] = []; // 段ごとの「使用済みの右端」
  return out.map((s) => {
    let lane = lanes.findIndex((rightmost) => rightmost < s.start);
    if (lane < 0) {
      lane = lanes.length;
      lanes.push(s.end);
    } else {
      lanes[lane] = s.end;
    }
    return { ...s, lane };
  });
}
