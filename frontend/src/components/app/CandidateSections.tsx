import type { Opportunity } from '../../types';
import { splitCandidates } from '../../utils/candidates';
import { formatDateOrDateTime } from '../../utils/date';
import { availabilityLabel } from '../../utils/display';
import { EYEBROW } from './styles';

/**
 * 候補を「期間との関係」で分けて出す（#47）。
 *
 * **3 件を埋めるために枠を混ぜない。** 期間内と確認できたイベントが 0 件なら
 * 0 件と言う。日程未確認のものを期間内として並べると、「60 日以内のおすすめが
 * 3 件見つかった」と受け取られる。
 *
 * 期間外・開催終了・申込終了は**参加候補の一覧に混ぜない**。別枠にして、
 * なぜ外れたかを見せる。
 */

type Props = {
  selected: Opportunity[];
  /** 上の一覧で出した枠。**同じ候補を 2 度出さない。** */
  skipKeys?: string[];
  others: Opportunity[];
  /** 期間が分かる run か。分からない run では 0 件の断定をしない。 */
  hasWindow: boolean;
};

export function CandidateSections({ selected, others, hasWindow, skipKeys = [] }: Props) {
  const all = splitCandidates(selected, others);
  const buckets = all.filter((b) => !skipKeys.includes(b.key));
  // **上の一覧で出した枠も数に入れる。** ここから外しただけで
  // 「期間内は 0 件」と書くと、上に並べた候補と食い違う。
  const inWindow = all.find((b) => b.key === 'in_window');

  return (
    <div className="mt-[24px]">
      {/* **0 件を隠さない。** 別枠の候補で埋めたように見せない。 */}
      {hasWindow && !inWindow ? (
        <p role="status" className="text-[15px] bg-[#f3eee6] rounded-[7px] p-[14px] my-[16px]">
          この期間内と確認できるイベントは見つかりませんでした。
          <span className="block text-[14px] text-muted mt-[6px]">
            下の候補は、日程を確認できなかったものと、開催期間の条件を当てていないものです。
          </span>
        </p>
      ) : null}

      {buckets.map((b) => (
        <section key={b.key} className="mt-[22px]">
          <span className={EYEBROW}>{b.eyebrow}</span>
          <h3 className="text-[17px] mt-[6px] mb-[4px]">
            {b.title}（{b.items.length}件）
          </h3>
          <p className="text-[14px] text-muted mt-0 mb-[10px]">{b.note}</p>
          <ul className="list-none p-0 m-0 grid gap-[10px]">
            {b.items.map((o) => (
              <li
                key={o.opportunity_id}
                className="bg-[#f6f5f1] rounded-[7px] p-[14px] text-[14px]"
              >
                <p className="m-0 font-semibold">{o.title}</p>
                <dl className="grid grid-cols-[84px_1fr] gap-x-[10px] gap-y-[4px] m-0 mt-[8px]">
                  <dt className="text-muted">種類</dt>
                  <dd className="m-0">{o.type}</dd>
                  <dt className="text-muted">日時</dt>
                  <dd className="m-0">
                    {formatDateOrDateTime(o.start_at, o.start_at_is_date_only)}
                  </dd>
                  <dt className="text-muted">申込締切</dt>
                  <dd className="m-0">
                    {formatDateOrDateTime(o.deadline, o.deadline_is_date_only)}
                  </dd>
                  <dt className="text-muted">期間</dt>
                  <dd className="m-0">{o.window_note ?? '—'}</dd>
                  <dt className="text-muted">地域</dt>
                  <dd className="m-0">{o.region_note ?? '—'}</dd>
                  <dt className="text-muted">受付</dt>
                  <dd className="m-0">{availabilityLabel(o)}</dd>
                  <dt className="text-muted">確認</dt>
                  <dd className="m-0">{o.verified ? '公式ページで確認済み' : '未確認'}</dd>
                </dl>
                {/* **受付が不明なことを、参加できると読ませない。** */}
                {o.availability === 'unknown' ? (
                  <p className="m-0 mt-[8px] text-[13px] text-muted">
                    受付状況は確認できていません。参加できるとは限らないため、公式ページでご確認ください。
                  </p>
                ) : null}
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
        </section>
      ))}
    </div>
  );
}
