import type { Opportunity } from '../types';

/**
 * 候補を「期間との関係」で分ける（#47）。
 *
 * **3 件を埋めるために枠を混ぜない。** 期間内と確認できたイベントが 0 件なら
 * 0 件と言う。日程未確認のものを期間内として並べると、「60 日以内のおすすめが
 * 3 件見つかった」と受け取られる。
 */
export type Bucket = {
  key: string;
  eyebrow: string;
  title: string;
  note: string;
  items: Opportunity[];
};

/** 参加候補から外すもの。**受付終了と開催終了は「候補」ではない。** */
function isDropped(o: Opportunity): boolean {
  return (
    o.availability === 'closed' || o.window_status === 'ended' || o.window_status === 'after_window'
  );
}

export function splitCandidates(selected: Opportunity[], others: Opportunity[]): Bucket[] {
  // 同じ候補を 2 度出さない。おすすめ側を優先する。
  const seen = new Set<string>();
  const all: Opportunity[] = [];
  for (const o of [...selected, ...others]) {
    if (seen.has(o.opportunity_id)) continue;
    seen.add(o.opportunity_id);
    all.push(o);
  }

  const live = all.filter((o) => !isDropped(o));
  return [
    {
      key: 'in_window',
      eyebrow: 'IN THE NEXT 60 DAYS',
      title: '今後60日以内と確認できたイベント',
      note: '開催日が対象期間の中にあると確認できたものです。',
      items: live.filter((o) => o.window_status === 'in_window'),
    },
    {
      key: 'ongoing',
      eyebrow: 'ALREADY RUNNING',
      title: '期間より前に始まり、いまも続いている候補',
      note: '開始は対象期間より前ですが、期間中も続いています。途中から参加できるかは公式ページでご確認ください。',
      items: live.filter((o) => o.window_status === 'ongoing'),
    },
    {
      key: 'schedule_unknown',
      eyebrow: 'DATE NOT CONFIRMED',
      title: '日程を確認できなかった候補',
      note: '開催日時を読み取れませんでした。期間内とは断定できません。公式ページでご確認ください。',
      items: live.filter((o) => o.window_status === 'schedule_unknown'),
    },
    {
      key: 'not_time_bound',
      eyebrow: 'PROGRAMS AND COMMUNITIES',
      title: '開催期間の条件を当てていない候補',
      note: 'コミュニティ・プログラム・求人など、開催日が 1 点に決まらない種別です。開催期間では絞っていませんが、申込締切と受付状況は下に出しています。',
      items: live.filter((o) => o.window_status === 'not_time_bound'),
    },
    {
      key: 'dropped',
      eyebrow: 'NOT AVAILABLE',
      title: '参加候補から外れたもの',
      note: '受付が終了している、開催が終わっている、または対象期間より先の開催です。',
      items: all.filter(isDropped),
    },
  ].filter((b) => b.items.length > 0);
}
