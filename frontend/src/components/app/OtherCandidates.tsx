import { useState } from 'react';

import type { Opportunity } from '../../types';
import { formatDateTime } from '../../utils/date';
import { availabilityLabel } from '../../utils/display';
import { EYEBROW, TEXT_BUTTON } from './styles';

/**
 * 推薦しなかったが、本文まで読んで抽出できた候補（#47）。
 *
 * **おすすめ 3 件とは別の扱い。** 上は確認まで済ませた推薦で、ここは
 * 「読んだが選ばなかった」もの。件数を埋めるための枠ではないので、
 * 0 件のときは何も出さない。
 *
 * **開くだけでは何も呼ばない。** 表示するのは取得済みの結果だけで、
 * 追加の探索（有料 API）とは別のボタンにする。
 */
type Props = {
  items: Opportunity[];
  window: { start: string; end: string; days: number } | null;
};

export function OtherCandidates({ items, window: win }: Props) {
  const [open, setOpen] = useState(false);
  if (items.length === 0) return null;

  return (
    <section className="mt-[28px]">
      <span className={EYEBROW}>OTHER CANDIDATES</span>
      <h3 className="text-[18px] mt-[6px] mb-[4px]">ほかの候補（{items.length}件）</h3>
      <p className="text-[14px] text-muted mt-0 mb-[12px]">
        読み取れたけれど、おすすめには入れなかったものです。
        {win ? `対象期間は ${win.start} 〜 ${win.end}（${win.days}日間）。` : null}
        <br />
        開いても新しい探索は行いません。もう一度探すときは「もう一度、探索する」を押してください。
      </p>

      <button type="button" onClick={() => setOpen(!open)} className={TEXT_BUTTON}>
        {open ? '閉じる' : '候補をもっと見る ↓'}
      </button>

      {open ? (
        <ul className="list-none p-0 mt-[14px] mb-0 grid gap-[10px]">
          {items.map((o) => (
            <li key={o.opportunity_id} className="bg-[#f6f5f1] rounded-[7px] p-[14px] text-[14px]">
              <p className="m-0 font-semibold">{o.title}</p>
              <dl className="grid grid-cols-[76px_1fr] gap-x-[10px] gap-y-[4px] m-0 mt-[8px]">
                <dt className="text-muted">種類</dt>
                <dd className="m-0">{o.type}</dd>
                <dt className="text-muted">日時</dt>
                <dd className="m-0">{formatDateTime(o.start_at)}</dd>
                <dt className="text-muted">期間</dt>
                <dd className="m-0">{o.window_note ?? '—'}</dd>
                <dt className="text-muted">受付</dt>
                <dd className="m-0">{availabilityLabel(o)}</dd>
                <dt className="text-muted">確認</dt>
                <dd className="m-0">{o.verified ? '公式ページで確認済み' : '未確認'}</dd>
              </dl>
              {o.url ? (
                <a
                  href={o.url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="inline-block mt-[8px] break-all"
                >
                  取得元のページを見る ↗
                </a>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
