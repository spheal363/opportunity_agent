/**
 * ④ 探索結果。**この run が選んだものを順位順で表示する。**
 *
 * `GET /api/agent/runs/{run_id}/result` を使う。保存一覧が使う
 * `opportunities`（status で絞った最新の一覧）とは別経路。混ぜると
 * 過去 run の高スコア候補が混ざり、Agent の選定と画面がずれる。
 *
 * `run_id` は URL に持つ。**直接開いても再読み込みしても対象 run が決まる。**
 * 無い場合は最後に実行した run（保存済み）へ委ねる。
 */
import { useEffect, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { BottomNote, PageIntro } from '../components/app/Chrome';
import { CardGrid, ResultsHead } from '../components/app/CardGrid';
import { ResultWelcome } from '../components/app/ResultWelcome';
import ErrorMessage from '../components/ErrorMessage';
import { OtherCandidates } from '../components/app/OtherCandidates';
import { useRunResult } from '../hooks/useRunResult';
import { useAppState } from '../state/context';

export default function ResultsPage() {
  const navigate = useNavigate();
  const titleRef = useRef<HTMLHeadingElement>(null);
  const [params, setParams] = useSearchParams();
  const { profile, lastRunId } = useAppState();

  const runId = params.get('run_id') ?? lastRunId;

  // 直接開かれたときも URL に run_id を残す。再読み込みで対象が変わらないように。
  useEffect(() => {
    if (!params.get('run_id') && lastRunId) {
      setParams({ run_id: lastRunId }, { replace: true });
    }
  }, [params, lastRunId, setParams]);

  const { result, error, loading } = useRunResult(runId);

  const items = result?.selected ?? [];
  const others = result?.others ?? [];
  const win = result?.search_window ?? null;
  const notRecorded = result !== null && !result.recorded;

  return (
    <>
      <PageIntro
        titleRef={titleRef}
        title="見つけたのは、あなたの新しい一歩。"
        copy={
          items.length
            ? 'あなたの目標と興味から、候補を選びました。'
            : 'まずは、どんな機会に出会えるか見てみましょう。'
        }
      />

      <ResultWelcome
        interests={profile?.interests ?? []}
        items={items}
        onExplore={() => navigate('/app')}
        onGoExplore={() => navigate('/app/explore')}
      />

      <ResultsHead
        eyebrow="CURATED FOR YOU"
        title={items.length ? `あなたに届けたい、${items.length}つの機会` : 'まだ結果がありません'}
        count={items.length}
      />
      <ErrorMessage error={error} />

      {/* 3 件に満たなかった理由を隠さない。期限切れで埋めるより正直に伝える。 */}
      {/* **失敗の理由を隠さない。** 設定不足なら直せる。 */}
      {result?.error ? (
        <p role="alert" className="text-[14px] text-[#9a5c4c] my-[12px]">
          探索に失敗しました：{result.error}
        </p>
      ) : null}
      {result?.shortfall_reason ? <p role="status">{result.shortfall_reason}</p> : null}

      {notRecorded && !loading ? (
        <p role="status">
          {result?.status === 'running'
            ? 'まだ探索中です。'
            : 'この探索の結果は記録されていません。'}
        </p>
      ) : null}

      {/* **この run が対象にした期間。** 結果の読み方に効くので隠さない。 */}
      {win ? (
        <p className="text-[14px] text-muted mt-[4px] mb-0">
          対象期間: {win.start} 〜 {win.end}（{win.days}日間 / {win.tz}）
        </p>
      ) : null}

      <CardGrid items={items} isResult />
      {/* **おすすめとは別枠。** 読んだが選ばなかったものを、件数埋めに使わない。 */}
      <OtherCandidates items={others} window={win} />
      <BottomNote />
    </>
  );
}
