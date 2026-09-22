import { useMemo, useState } from 'react';

import { useAppState } from '../../state/context';
import type { Opportunity, SearchWindow } from '../../types';
import {
  genreColors,
  isSpan,
  monthGrid,
  monthsBetween,
  occupiedDays,
  todayIn,
  weekSegments,
} from '../../utils/calendar';
import { EYEBROW } from './styles';

/**
 * 候補の開催日を月ごとに並べる（#47）。**検索候補の可視化。**
 *
 * - **Google Calendar への登録も空き時間の確認もしない。** 表示だけ。
 * - **追加の検索も LLM も呼ばない。** 保存済みの候補で完結する。
 * - 日付は run のタイムゾーンで扱う（日付だけの候補が前日へずれないように）。
 */

const WEEKDAYS = ['日', '月', '火', '水', '木', '金', '土'];
// 1 日に出すイベントの数。**これを超えたら「ほかN件」にまとめる。**
const PER_DAY = 2;

type Props = {
  /** 今回の run の候補すべて（おすすめ＋ほかの候補）。**重複は呼び出し側で除く。** */
  items: Opportunity[];
  /** おすすめの候補 ID。★を付ける。 */
  recommendedIds: Set<string>;
  window: SearchWindow;
  /** 日程を確認できていない候補。**日付へ無理に置かない。** */
  scheduleUnknown: Opportunity[];
};

export function OpportunityCalendar({ items, recommendedIds, window: win, scheduleUnknown }: Props) {
  const { openDetail } = useAppState();
  const [openDay, setOpenDay] = useState<string | null>(null);
  const [monthIndex, setMonthIndex] = useState(0);

  const tz = win.tz;
  const months = useMemo(() => monthsBetween(win.start, win.end), [win.start, win.end]);
  const today = todayIn(tz);

  // 日ごとの候補。**同じ候補 ID は 1 日に 1 度だけ。**
  const byDay = useMemo(() => {
    const map = new Map<string, Opportunity[]>();
    for (const o of items) {
      for (const d of occupiedDays(o, tz)) {
        const list = map.get(d);
        if (list) {
          if (!list.some((x) => x.opportunity_id === o.opportunity_id)) list.push(o);
        } else map.set(d, [o]);
      }
    }
    return map;
  }, [items, tz]);

  // **会期（複数日）と単日を分ける。** 会期は週ごとの帯にまとめる。
  const spans = useMemo(() => items.filter((o) => isSpan(o, tz)), [items, tz]);

  const wishes = useMemo(
    () => [...new Set(items.map((o) => o.wish).filter((w): w is string => !!w))],
    [items],
  );
  const colors = useMemo(() => genreColors(wishes), [wishes]);
  const colorOf = (o: Opportunity) =>
    colors.get(o.wish ?? '') ?? { chip: 'bg-[#eceee8] text-[#5b6157]', dot: 'bg-[#9aa294]' };

  if (months.length === 0) return null;

  return (
    <section className="mt-[26px]">
      <span className={EYEBROW}>WHEN THEY HAPPEN</span>
      <h2 className="text-[19px] font-medium mt-[5px] mb-[6px] tracking-[.02em]">開催日カレンダー</h2>
      <p className="text-[13px] text-muted m-0 mb-[12px]">
        検索結果に記載された日程です。変更・受付状況は掲載ページでご確認ください。
      </p>

      {/* 凡例。**色だけで区別させない。** */}
      <div className="flex flex-wrap gap-[10px] mb-[12px]">
        {wishes.map((w) => (
          <span key={w} className="flex items-center gap-[5px] text-[12px] text-[#5b6157]">
            <span className={`w-[9px] h-[9px] rounded-[3px] ${colorOf({ wish: w } as Opportunity).dot}`} />
            {w}
          </span>
        ))}
        <span className="flex items-center gap-[4px] text-[12px] text-[#5b6157]">★ おすすめ</span>
      </div>

      {/* スマホは 1 か月ずつ。**次の月があると分かるようにする。** */}
      <div className="hidden lte850:flex items-center justify-between mb-[8px]">
        <button
          type="button"
          className="text-[13px] text-[#4d6b52] disabled:opacity-40"
          disabled={monthIndex === 0}
          onClick={() => setMonthIndex((i) => Math.max(0, i - 1))}
        >
          ← {months[monthIndex - 1] ? monthLabel(months[monthIndex - 1]) : ''}
        </button>
        <span className="text-[13px] text-muted">
          {monthIndex + 1} / {months.length} か月
        </span>
        <button
          type="button"
          className="text-[13px] text-[#4d6b52] disabled:opacity-40"
          disabled={monthIndex >= months.length - 1}
          onClick={() => setMonthIndex((i) => Math.min(months.length - 1, i + 1))}
        >
          {months[monthIndex + 1] ? monthLabel(months[monthIndex + 1]) : ''} →
        </button>
      </div>

      <div
        className="grid gap-[14px] lte850:flex lte850:overflow-x-auto lte850:snap-x lte850:snap-mandatory"
        style={{ gridTemplateColumns: `repeat(${months.length}, minmax(0, 1fr))` }}
      >
        {months.map((ym, i) => (
          <div
            key={ym}
            className={`bg-[#fbfbf7] border border-[#e6e7df] rounded-[9px] p-[10px] lte850:min-w-[86%] lte850:snap-start ${
              i === monthIndex ? '' : 'lte850:hidden'
            }`}
          >
            <h3 className="text-[14px] font-medium m-0 mb-[8px] text-[#4d6b52]">{monthLabel(ym)}</h3>
            <div className="grid grid-cols-7 gap-[2px] mb-[3px]">
              {WEEKDAYS.map((w) => (
                <span key={w} className="text-[11px] text-center text-[#8b9287]">
                  {w}
                </span>
              ))}
            </div>
            {monthGrid(ym).map((week, wi) => {
              const segs = weekSegments(week, spans, tz);
              const lanes = segs.length ? Math.max(...segs.map((s) => s.lane)) + 1 : 0;
              return (
                <div key={wi} className="mb-[3px]">
                  {/* 日付の数字。**帯に隠れないよう、帯の上に置く。** */}
                  <div className="grid grid-cols-7 gap-[2px]">
                    {week.map((cell, idx) => {
                      if (!cell.day) return <div key={idx} />;
                      const outside = cell.day < win.start || cell.day > win.end;
                      const list = byDay.get(cell.day) ?? [];
                      return (
                        <div key={cell.day} className={outside ? 'opacity-40' : ''}>
                          {list.length ? (
                            <button
                              type="button"
                              onClick={() => setOpenDay(cell.day)}
                              aria-label={`${cell.day} の候補 ${list.length}件を見る`}
                              className={`text-[11px] block leading-none w-full text-left underline decoration-dotted text-[#4d6b52] ${
                                cell.day === today ? 'ring-1 ring-[#6f9a6a] rounded-[3px]' : ''
                              }`}
                            >
                              {Number(cell.day.slice(8))}
                            </button>
                          ) : (
                            <span
                              className={`text-[11px] block leading-none text-[#8b9287] ${
                                cell.day === today ? 'ring-1 ring-[#6f9a6a] rounded-[3px]' : ''
                              }`}
                            >
                              {Number(cell.day.slice(8))}
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>

                  {/* **会期の帯。** 隙間で途切れないよう、ここだけ gap を置かない。 */}
                  {lanes > 0 ? (
                    <div
                      className="grid grid-cols-7 mt-[2px]"
                      style={{ gridTemplateRows: `repeat(${lanes}, auto)` }}
                    >
                      {segs.map((s) => {
                        const c = colorOf(s.opportunity);
                        return (
                          <button
                            key={`${s.opportunity.opportunity_id}-${s.start}`}
                            type="button"
                            title={`${s.opportunity.title}（開催期間）`}
                            onClick={() => openDetail(s.opportunity.opportunity_id)}
                            style={{
                              gridColumn: `${s.start + 1} / span ${s.end - s.start + 1}`,
                              gridRow: s.lane + 1,
                            }}
                            className={`text-left text-[10px] leading-[1.4] px-[3px] py-[1px] mb-[1px] truncate ${c.chip} ${
                              s.realStart ? 'rounded-l-[4px]' : ''
                            } ${s.realEnd ? 'rounded-r-[4px]' : ''}`}
                          >
                            {s.realStart ? '' : '◂'}
                            {recommendedIds.has(s.opportunity.opportunity_id) ? '★' : ''}
                            {s.opportunity.title}
                            {s.realEnd ? '' : '▸'}
                          </button>
                        );
                      })}
                    </div>
                  ) : null}

                  {/* 単日のイベント。**帯と重ならないよう下に置く。** */}
                  <div className="grid grid-cols-7 gap-[2px] mt-[1px]">
                    {week.map((cell, idx) => {
                      if (!cell.day) return <div key={idx} />;
                      const outside = cell.day < win.start || cell.day > win.end;
                      const list = (byDay.get(cell.day) ?? []).filter((o) => !isSpan(o, tz));
                      const shown = list.slice(0, PER_DAY);
                      return (
                        <div key={cell.day} className={`min-h-[16px] ${outside ? 'opacity-40' : ''}`}>
                          {shown.map((o) => (
                            <button
                              key={o.opportunity_id}
                              type="button"
                              title={o.title}
                              onClick={() => openDetail(o.opportunity_id)}
                              className={`block w-full text-left text-[10px] leading-[1.3] rounded-[3px] px-[3px] py-[1px] mb-[1px] truncate ${colorOf(o).chip}`}
                            >
                              {recommendedIds.has(o.opportunity_id) ? '★' : ''}
                              {o.title}
                            </button>
                          ))}
                          {list.length > shown.length ? (
                            <button
                              type="button"
                              onClick={() => setOpenDay(cell.day)}
                              className="text-[10px] text-[#4d6b52] underline"
                            >
                              ほか{list.length - shown.length}件
                            </button>
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        ))}
      </div>

      {/* その日の全候補。**押したときだけ開く。追加の取得はしない。** */}
      {openDay ? (
        <div className="mt-[12px] border border-[#e6e7df] rounded-[9px] p-[12px] bg-[#fbfbf7]">
          <div className="flex justify-between items-center mb-[6px]">
            <strong className="text-[14px]">{openDay} の候補</strong>
            <button type="button" className="text-[13px] underline" onClick={() => setOpenDay(null)}>
              閉じる
            </button>
          </div>
          <ul className="list-none p-0 m-0">
            {(byDay.get(openDay) ?? []).map((o) => (
              <li key={o.opportunity_id} className="border-t border-[#e6e7df] py-[7px]">
                <button
                  type="button"
                  className="text-left text-[14px] hover:underline"
                  onClick={() => openDetail(o.opportunity_id)}
                >
                  {recommendedIds.has(o.opportunity_id) ? '★ ' : ''}
                  {o.title}
                </button>
                <span className="block text-[12px] text-muted">
                  {[o.wish, o.location].filter(Boolean).join(' · ')}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {/* **日付へ無理に置かない。** */}
      {scheduleUnknown.length ? (
        <p className="text-[13px] text-muted mt-[10px] mb-0">
          日程未確認 {scheduleUnknown.length}件（カレンダーには置いていません）
        </p>
      ) : null}
      <p className="text-[12px] text-muted mt-[6px] mb-0">
        帯は<strong>開催期間</strong>を示すものです。毎日参加できる、受付中という意味ではありません。
        両端の ◂ ▸ は、週や月の境目で続いていることを表します。
      </p>
    </section>
  );
}

function monthLabel(ym: string): string {
  const [y, m] = ym.split('-');
  return `${y}年${Number(m)}月`;
}
