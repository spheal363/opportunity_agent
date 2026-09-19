/** ⑤ Opportunity 詳細 + ⑥「参加したい」+ ⑩ Feedback。 */
import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';

import { fetchOpportunity, markInterested, sendFeedback } from '../api';
import ErrorMessage from '../components/ErrorMessage';
import type { OpportunityDetail, Reaction } from '../types';
import { formatDateTime } from '../utils/date';

export default function OpportunityDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [item, setItem] = useState<OpportunityDetail | null>(null);
  const [registrationUrl, setRegistrationUrl] = useState<string | null>(null);
  const [reaction, setReaction] = useState<Reaction | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    fetchOpportunity(id)
      .then(setItem)
      .catch((err) => setError(err instanceof Error ? err.message : '取得に失敗しました'));
  }, [id]);

  const handleInterest = async () => {
    if (!id) return;
    try {
      const result = await markInterested(id);
      setRegistrationUrl(result.registration_url);
    } catch (err) {
      setError(err instanceof Error ? err.message : '処理に失敗しました');
    }
  };

  const handleFeedback = async (value: Reaction) => {
    if (!id) return;
    try {
      await sendFeedback(id, { reaction: value });
      setReaction(value);
    } catch (err) {
      setError(err instanceof Error ? err.message : '送信に失敗しました');
    }
  };

  if (error) return <ErrorMessage error={error} />;
  if (!item) return <p className="text-sm text-slate-500">読み込み中…</p>;

  return (
    <div className="space-y-5">
      <div>
        <p className="text-xs text-slate-500">{item.type}</p>
        <h1 className="text-xl font-semibold">{item.title}</h1>
        <p className="mt-2 text-sm text-slate-700">{item.description}</p>
      </div>

      <dl className="grid grid-cols-[8rem_1fr] gap-y-2 text-sm">
        <dt className="text-slate-500">開催日時</dt>
        <dd>{formatDateTime(item.start_at)}</dd>
        <dt className="text-slate-500">場所 / 形式</dt>
        <dd>
          {item.location ?? '-'} / {item.format ?? '-'}
        </dd>
        <dt className="text-slate-500">応募締切</dt>
        <dd>{formatDateTime(item.deadline)}</dd>
        <dt className="text-slate-500">参加条件</dt>
        <dd>{item.eligibility ?? '-'}</dd>
        <dt className="text-slate-500">参加費</dt>
        <dd>{item.cost === null ? '-' : item.cost === 0 ? '無料' : `${item.cost}円`}</dd>
        <dt className="text-slate-500">公式情報</dt>
        <dd>{item.verified ? `確認済み（${formatDateTime(item.verified_at)}）` : '未確認'}</dd>
      </dl>

      {item.reason && (
        <section className="rounded-lg border border-slate-200 bg-white p-4">
          <h2 className="text-sm font-semibold">なぜあなたにおすすめなのか</h2>
          <p className="mt-2 text-sm leading-relaxed text-slate-700">{item.reason}</p>
        </section>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <button
          onClick={handleInterest}
          className="rounded bg-slate-900 px-4 py-2 text-sm text-white"
        >
          参加したい
        </button>
        <button
          onClick={() => handleFeedback('like')}
          className={`rounded border px-3 py-2 text-sm ${reaction === 'like' ? 'border-slate-900' : 'border-slate-300'}`}
        >
          👍
        </button>
        <button
          onClick={() => handleFeedback('dislike')}
          className={`rounded border px-3 py-2 text-sm ${reaction === 'dislike' ? 'border-slate-900' : 'border-slate-300'}`}
        >
          👎
        </button>
      </div>

      {registrationUrl && (
        <p className="text-sm">
          {/* 外部サービスへの登録は Agent が代行せず、ユーザー本人が確認・実行する。 */}
          登録ページ:{' '}
          <a href={registrationUrl} target="_blank" rel="noreferrer" className="underline">
            {registrationUrl}
          </a>
        </p>
      )}
    </div>
  );
}
