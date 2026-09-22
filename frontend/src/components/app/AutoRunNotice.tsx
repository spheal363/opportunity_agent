/**
 * Agent が自分で始めた探索の知らせ（trigger が manual 以外）。
 *
 * **勝手に画面を移らない。** 本人が「見る」を押したときだけ、探索中画面か結果へ進む。
 * 理由の文は Backend が決まった文面と数値だけで作ったもの（Web 由来の文は入らない）。
 */
import { Link } from 'react-router-dom';

import { useAppState } from '../../state/context';
import type { AgentRunTrigger } from '../../types';
import { TEXT_BUTTON } from './styles';

/** 理由の文が無いときの言い方。古い Backend などで trigger_reason が null のとき。 */
const FALLBACK_REASON: Record<AgentRunTrigger, string> = {
  manual: '',
  feedback: 'あなたの反応を踏まえて、探し直しています。',
  stale: '推薦中の機会が締切を迎えたため、新しく探しています。',
  scheduled: '前回の探索から時間がたったため、新着を探しています。',
};

interface AutoRunNoticeProps {
  /** このきっかけのときだけ出す。詳細ダイアログでは👎による探し直しだけを出す。 */
  only?: AgentRunTrigger;
  /** 「見る」を押したときに、あわせて行うこと（ダイアログを閉じるなど）。 */
  onOpen?: () => void;
}

export function AutoRunNotice({ only, onOpen }: AutoRunNoticeProps) {
  const { autoRun, openAutoRun, dismissAutoRun } = useAppState();
  if (!autoRun || (only && autoRun.trigger !== only)) return null;

  const active = autoRun.status === 'queued' || autoRun.status === 'running';
  const done = autoRun.status === 'completed';
  const runId = encodeURIComponent(autoRun.run_id);

  const title = active
    ? 'Agent が自分で探索を始めました'
    : done
      ? 'Agent が自分で探した結果が届きました'
      : 'Agent が自分で始めた探索は、うまくいきませんでした';
  // 完了していれば結果、それ以外（実行中・失敗）は探索中画面。失敗の理由もそこに出る。
  const to = done ? `/app/results?run_id=${runId}` : `/app/explore?run_id=${runId}`;
  const label = active ? '探索のようすを見る' : done ? '結果を見る' : 'くわしく見る';

  return (
    <section
      role="status"
      aria-live="polite"
      className="flex items-start gap-[12px] bg-[#f4eee5] border border-[#eadfcf] rounded-[12px] px-[18px] py-[14px] mb-[22px]"
    >
      <span aria-hidden="true" className="text-[20px] leading-none text-[#b39b71] mt-[2px]">
        ✧
      </span>
      <div className="min-w-0 flex-1">
        <strong className="block text-[14px] font-medium text-[#6f5a3e]">{title}</strong>
        <p className="text-[13px] leading-[1.8] text-[#726957] mt-[4px] mb-[6px]">
          {autoRun.trigger_reason ?? FALLBACK_REASON[autoRun.trigger]}
        </p>
        <Link
          to={to}
          onClick={() => {
            openAutoRun(autoRun.run_id);
            onOpen?.();
          }}
          className={TEXT_BUTTON}
        >
          {label} ↗
        </Link>
      </div>
      <button
        type="button"
        aria-label="この知らせを閉じる"
        onClick={() => dismissAutoRun(autoRun.run_id)}
        className="border-0 bg-transparent text-[20px] leading-none text-muted w-[28px] h-[28px] shrink-0"
      >
        ×
      </button>
    </section>
  );
}
