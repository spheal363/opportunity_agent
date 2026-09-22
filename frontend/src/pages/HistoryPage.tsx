import { useRef } from 'react';
import { Link } from 'react-router-dom';

import { PageIntro } from '../components/app/Chrome';
import { OUTLINE_BUTTON, TEXT_BUTTON } from '../components/app/styles';
import ErrorMessage from '../components/ErrorMessage';
import { useRunHistory } from '../hooks/useRunHistory';
import type { AgentRunStatus, AgentRunTrigger } from '../types';
import { formatDateTime } from '../utils/date';

const STATUS_LABEL: Record<AgentRunStatus, string> = {
  queued: '準備中',
  running: '探索中',
  completed: '完了',
  failed: '失敗',
};
const TRIGGER_LABEL: Record<AgentRunTrigger, string> = {
  manual: '手動で探索',
  feedback: '反応をもとに自動探索',
  stale: '締切切れを補う自動探索',
  scheduled: '定期的な自動探索',
};

export default function HistoryPage() {
  const titleRef = useRef<HTMLHeadingElement>(null);
  const { history, loading, error, load } = useRunHistory();

  return (
    <>
      <PageIntro
        titleRef={titleRef}
        title="これまでの探索を振り返る。"
        copy="自分で探した回も、Agent が見つけてきた回も、ここから見返せます。"
      />
      <div className="flex items-center justify-between gap-[16px] mb-[20px]">
        <h2 className="text-[18px] font-medium m-0">探索履歴</h2>
        <button
          type="button"
          className={OUTLINE_BUTTON}
          disabled={loading}
          onClick={() => void load()}
        >
          {loading ? '読み込み中…' : '履歴を更新'}
        </button>
      </div>
      <ErrorMessage error={error} />
      {!loading && !error && history.items.length === 0 ? (
        <div className="rounded-[16px] border border-line bg-[#fffefa] p-[28px]">
          <p className="text-[15px] text-muted mt-0">まだ探索履歴がありません。</p>
          <Link to="/app" className={TEXT_BUTTON}>
            最初の探索をはじめる ↗
          </Link>
        </div>
      ) : null}
      <ol className="grid gap-[14px] list-none p-0 m-0" aria-label="探索履歴" aria-busy={loading}>
        {history.items.map((run) => {
          const active = run.status === 'queued' || run.status === 'running';
          const id = encodeURIComponent(run.run_id);
          return (
            <li
              key={run.run_id}
              className="rounded-[14px] border border-line bg-[#fffefa] p-[22px] lte620:p-[16px]"
            >
              <div className="flex items-center justify-between gap-[12px] flex-wrap">
                <h3 className="text-[16px] font-medium m-0">
                  <time dateTime={run.created_at ?? undefined}>
                    {formatDateTime(run.created_at)}
                  </time>
                </h3>
                <span
                  className={`text-[12px] rounded-[20px] px-[10px] py-[4px] ${run.status === 'failed' ? 'bg-[#f5e9e2] text-[#9a5c4c]' : 'bg-[#edf0e5] text-[#526748]'}`}
                >
                  {STATUS_LABEL[run.status]}
                  {active ? ` · ${run.progress}%` : ''}
                </span>
              </div>
              <p className="text-[14px] text-[#6f5a3e] mb-[8px]">{TRIGGER_LABEL[run.trigger]}</p>
              {run.trigger_reason ? (
                <p className="text-[13px] text-muted leading-[1.8] my-[8px]">
                  {run.trigger_reason}
                </p>
              ) : null}
              {run.status === 'completed' ? (
                <p className="text-[14px] text-muted my-[8px]">
                  {run.selected_count === null
                    ? 'この探索には結果の記録がありません。'
                    : `${run.selected_count}件の機会を選びました。`}
                </p>
              ) : null}
              {run.status === 'failed' ? (
                <p className="text-[13px] text-[#9a5c4c] my-[8px]">
                  {run.error ?? '探索を完了できませんでした。'}
                </p>
              ) : null}
              <div className="flex gap-[20px] flex-wrap mt-[16px]">
                {run.status === 'completed' && run.selected_count !== null ? (
                  <Link to={`/app/results?run_id=${id}`} className={TEXT_BUTTON}>
                    この回の結果を見る ↗
                  </Link>
                ) : null}
                <Link to={`/app/explore?run_id=${id}`} className={TEXT_BUTTON}>
                  {active ? '探索のようすを見る' : '作業記録を見る'} ↗
                </Link>
              </div>
            </li>
          );
        })}
      </ol>
      {history.next_cursor ? (
        <div className="text-center mt-[24px]">
          <button
            type="button"
            className={OUTLINE_BUTTON}
            disabled={loading}
            onClick={() => void load(history.next_cursor ?? undefined)}
          >
            以前の探索をもっと見る
          </button>
        </div>
      ) : null}
      {history.items.length ? (
        <p className="text-[12px] text-muted leading-[1.8] mt-[24px]">
          過去に選んだ機会も、現在確認できている内容で表示します。
        </p>
      ) : null}
    </>
  );
}
