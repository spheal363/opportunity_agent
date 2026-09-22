import { useState } from 'react';

import type { SearchCandidate } from '../../types';
import { EYEBROW, TEXT_BUTTON } from './styles';

/**
 * 検索で見つかった候補の一覧（#47）。
 *
 * **開くだけでは何も呼ばない。** 表示するのは run に保存済みの内容だけで、
 * 検索・本文取得・LLM は走らない。
 *
 * **確認できている範囲を分けて出す。**
 *
 *     本文未確認        検索で見つけたが、本文を読んでいない
 *     日程未確認        読んだが開催日を取れなかった／未読
 *     受付状況は要確認  読んだが受付を確認できなかった
 *
 * **未読だから受付中とは扱わない。** 未読の候補には受付の欄自体を出さない。
 * 検索結果の公開日や抜粋中の日付を開催日として流用しない（Backend も同じ）。
 */

type Props = {
  items: SearchCandidate[];
  /**
   * **画面上部のおすすめ欄に実際に出している URL。**
   *
   * run の最終選定（`recommended`）をそのまま使うと、上部に出していない
   * 候補にまで「おすすめ」が付く。実測で、期間の判定で上部から外れた
   * 候補が一覧では「おすすめ」のままだった。**表示を一致させる。**
   */
  recommendedUrls: string[];
};

/** 開催日の「日」だけ。**時刻は使わない**（並び替えと見出しのため）。 */
function dayKey(value: string): string {
  return new Date(value).toLocaleDateString('sv-SE', { timeZone: 'Asia/Tokyo' });
}

function dayLabel(value: string): string {
  return new Date(value).toLocaleDateString('ja-JP', {
    timeZone: 'Asia/Tokyo',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    weekday: 'short',
  });
}

/** 開催日の表示。**日付だけの候補に架空の時刻を付けない。** */
function whenLabel(c: SearchCandidate): string {
  if (!c.start_at) return '日程未確認';
  if (c.start_at_is_date_only !== false) return dayLabel(c.start_at);
  return `${dayLabel(c.start_at)} ${new Date(c.start_at).toLocaleTimeString('ja-JP', {
    timeZone: 'Asia/Tokyo',
    hour: '2-digit',
    minute: '2-digit',
  })}`;
}

/** 確認できている範囲。**分からないことを分からないと言う。** */
function statusLabels(c: SearchCandidate): string[] {
  if (!c.read) return ['本文未確認', '日程未確認'];
  // 日程は whenLabel が言うので、ここでは繰り返さない。
  const out: string[] = [c.verified ? '公式ページで確認済み' : '本文のみ読み取り'];
  if (c.availability === 'open') out.push('受付中を確認');
  else if (c.availability === 'closed') out.push('受付終了を確認');
  else out.push('受付状況は要確認');
  return out;
}

export function SearchCandidateList({ items, recommendedUrls }: Props) {
  const shown = new Set(recommendedUrls);
  const [open, setOpen] = useState(false);
  if (items.length === 0) return null;

  const ended = items.filter((c) => c.window_status === 'ended');
  const rest = items.filter((c) => c.window_status !== 'ended');
  // 開催中は「今後開催」と分ける。
  const ongoing = rest.filter((c) => c.window_status === 'ongoing');
  const dated = rest
    .filter((c) => c.start_at && c.window_status !== 'ongoing')
    .sort((a, b) => (a.start_at ?? '').localeCompare(b.start_at ?? ''));
  const undated = rest.filter((c) => !c.start_at && c.window_status !== 'ongoing');

  // 同じ開催日はひとつの見出しにまとめる。
  const byDay: { day: string; items: SearchCandidate[] }[] = [];
  for (const c of dated) {
    const key = dayKey(c.start_at as string);
    const last = byDay[byDay.length - 1];
    if (last && last.day === key) last.items.push(c);
    else byDay.push({ day: key, items: [c] });
  }

  return (
    <section className="mt-[26px]">
      <span className={EYEBROW}>ALL SEARCH RESULTS</span>
      <h3 className="text-[17px] mt-[6px] mb-[4px]">検索で見つかった候補（{items.length}件）</h3>
      <p className="text-[14px] text-muted mt-0 mb-[10px]">
        開催日が近い順。開いても新しい探索は行いません。
      </p>
      <button type="button" onClick={() => setOpen(!open)} className={TEXT_BUTTON}>
        {open ? '閉じる' : '一覧を開く ↓'}
      </button>

      {open ? (
        <div className="mt-[14px]">
          {byDay.map((g) => (
            <Group
              key={g.day}
              heading={dayLabel(g.items[0].start_at as string)}
              items={g.items}
              shown={shown}
            />
          ))}
          {ongoing.length ? (
            <Group heading="開催中（期間より前に開始）" items={ongoing} shown={shown} />
          ) : null}
          {undated.length ? <Group heading="日程未確認" items={undated} shown={shown} /> : null}
          {ended.length ? <Group heading="終了済み" items={ended} shown={shown} muted /> : null}
        </div>
      ) : null}
    </section>
  );
}

function Group({
  heading,
  items,
  shown,
  muted = false,
}: {
  heading: string;
  items: SearchCandidate[];
  shown: Set<string>;
  muted?: boolean;
}) {
  return (
    <div className="mt-[16px]">
      <h4 className={`text-[14px] m-0 mb-[6px] ${muted ? 'text-muted' : ''}`}>
        {heading}（{items.length}件）
      </h4>
      <ul className="list-none p-0 m-0 grid gap-[8px]">
        {items.map((c) => (
          <li
            key={c.url}
            className={`rounded-[7px] px-[13px] py-[10px] text-[14px] ${
              muted ? 'bg-[#f2f1ee] text-muted' : 'bg-[#f6f5f1]'
            }`}
          >
            <p className="m-0">
              {shown.has(c.url) ? (
                <span className="inline-block bg-[#e4ecdf] text-[#3d5734] rounded-[4px] px-[6px] py-[1px] text-[12px] mr-[6px]">
                  おすすめ
                </span>
              ) : null}
              {c.title}
            </p>
            <p className="m-0 mt-[4px] text-[13px] text-muted">
              {whenLabel(c)} ・ {statusLabels(c).join(' ・ ')}
            </p>
            {/* **未読の候補にカレンダー追加は出さない。** 情報源へのリンクだけ。 */}
            <a
              href={c.url}
              target="_blank"
              rel="noreferrer noopener"
              className="inline-block mt-[4px] text-[13px] break-all"
            >
              情報源を見る ↗
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
