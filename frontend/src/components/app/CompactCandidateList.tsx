import { useAppState } from '../../state/context';
import type { Opportunity } from '../../types';
import type { CompactGroup } from '../../utils/candidates';
import { availabilityLabel } from '../../utils/display';

/**
 * おすすめ 3 件の下に出す、コンパクトな候補一覧（#47）。
 *
 * **カードは上位 3 件だけ。** 残りは開催日ごとに 1〜2 行で並べる。
 * 大きなイラストや英語のキャッチは一覧には要らない。
 *
 * **外部 API を呼ばない。** 開いても並べ替えても、保存済みのデータだけを使う。
 */

/** 行に出す開始時刻。**出典に時刻が無ければ出さない（0:00 と書かない）。** */
function startTime(o: Opportunity): string | null {
  if (!o.start_at || o.start_at_is_date_only !== false) return null;
  return new Intl.DateTimeFormat('ja-JP', { timeStyle: 'short' }).format(new Date(o.start_at));
}

function sameDay(a: string | null, b: string | null): boolean {
  if (!a || !b) return false;
  return new Date(a).toDateString() === new Date(b).toDateString();
}

/** 複数日開催は期間で出す。**日ごとに同じ企画を並べない。** */
function spanLabel(o: Opportunity): string | null {
  if (!o.start_at || !o.end_at || sameDay(o.start_at, o.end_at)) return null;
  const fmt = new Intl.DateTimeFormat('ja-JP', { month: 'numeric', day: 'numeric' });
  return `${fmt.format(new Date(o.start_at))}〜${fmt.format(new Date(o.end_at))}`;
}

/**
 * 確認状況。**未確認を「公式確認済み」「受付中」と書かない。**
 *
 * `verified` は「出典を見に行ったか」であって、全項目が確認済みという
 * 意味ではない。何を確認できたかは詳細画面に出す。
 */
function checkedLabel(o: Opportunity): string {
  if (!o.verified) return '未確認';
  const n = o.confirmed_fields.length;
  return n > 0 ? `出典を一部確認（${n}項目）` : '出典を取得できず';
}

function Row({ opportunity }: { opportunity: Opportunity }) {
  const { statusOf, toggleInterest, openDetail } = useAppState();
  const saved = statusOf(opportunity) === 'interested';
  const time = startTime(opportunity);
  const span = spanLabel(opportunity);
  const facts = [
    span ?? time,
    opportunity.location,
    opportunity.wish,
    availabilityLabel(opportunity),
    checkedLabel(opportunity),
  ].filter(Boolean);

  return (
    <li className="border-t border-[#e6e7df] py-[10px] flex items-start justify-between gap-[12px] lte620:flex-col lte620:gap-[6px]">
      <div className="min-w-0">
        <button
          type="button"
          onClick={() => openDetail(opportunity.opportunity_id)}
          className="text-left text-[15px] font-medium hover:underline block"
        >
          {opportunity.title}
        </button>
        <p className="m-0 mt-[2px] text-[13px] text-muted truncate lte620:whitespace-normal">
          {facts.join(' · ')}
        </p>
      </div>
      <div className="flex items-center gap-[10px] shrink-0">
        <button
          type="button"
          aria-pressed={saved}
          aria-label={`${opportunity.title}を${saved ? '「気になる」から外す' : '「気になる」に保存'}`}
          onClick={() => void toggleInterest(opportunity)}
          className={`text-[16px] leading-none ${saved ? 'text-[#ad614d]' : 'text-[#879084]'}`}
        >
          {saved ? '♥' : '♡'}
        </button>
        <button
          type="button"
          onClick={() => openDetail(opportunity.opportunity_id)}
          className="text-[13px] text-[#4d6b52] hover:underline whitespace-nowrap"
        >
          詳細を見る →
        </button>
      </div>
    </li>
  );
}

export function CompactCandidateList({ groups }: { groups: CompactGroup[] }) {
  if (groups.length === 0) return null;
  return (
    <div className="mt-[10px]">
      {groups.map((g) => (
        <section key={g.key} className="mb-[18px]">
          <h3 className="text-[14px] font-medium m-0 mb-[4px] text-[#4d6b52]">{g.heading}</h3>
          <ul className="list-none p-0 m-0">
            {g.items.map((o) => (
              <Row key={o.opportunity_id} opportunity={o} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
