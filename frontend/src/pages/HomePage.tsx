/** ② ホーム（見つける）。いまのおすすめと、探索への入り口。 */
import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { BottomNote, PageIntro } from '../components/app/Chrome';
import { CardGrid, ResultsHead } from '../components/app/CardGrid';
import { useLatestResult } from '../hooks/useLatestResult';
import { DiscoverySurface } from '../components/app/DiscoverySurface';
import ErrorMessage from '../components/ErrorMessage';
import { useAppState } from '../state/context';

export default function HomePage() {
  const navigate = useNavigate();
  const titleRef = useRef<HTMLHeadingElement>(null);
  const { profile, opportunitiesError, startRun, openGoal, showToast, lastRunId } =
    useAppState();
  const [starting, setStarting] = useState(false);

  const handleExplore = async () => {
    setStarting(true);
    try {
      const runId = await startRun();
      navigate(`/app/explore?run_id=${runId}`);
    } catch (err) {
      showToast(err instanceof Error ? err.message : '探索を開始できませんでした');
    } finally {
      setStarting(false);
    }
  };

  // **最新の完了 run のおすすめだけを出す（#47）。**
  // 以前は `opportunities`（保存一覧の母集合）をそのまま並べていたため、
  // 過去 run の候補まで全部出て、「3つの機会」の横が 59 になっていた。
  const { result, loading: resultLoading } = useLatestResult(lastRunId);
  const recommended = result?.recommended_count ?? 0;
  const items = (result?.selected ?? []).slice(0, recommended);
  const changed = result?.profile_changed_since ?? false;

  return (
    <>
      <PageIntro
        titleRef={titleRef}
        title="あなたの「次」が、見つかる場所。"
        copy="いまの興味から、まだ知らない可能性へ。"
      />

      <DiscoverySurface
        interests={profile?.interests ?? []}
        onExplore={() => void handleExplore()}
        starting={starting}
        onEditInterests={openGoal}
        onGo={navigate}
      />

      <ResultsHead
        eyebrow="CURATED FOR YOU"
        title={
          resultLoading
            ? '前回の探索結果を読み込んでいます'
            : items.length
              ? `あなたに届けたい、${items.length}件の機会`
              : result
                ? 'この探索ではおすすめが選ばれていません'
                : 'まだ探索していません'
        }
        count={items.length}
        note={
          changed
            ? '前回の探索結果です（そのあとに目標・興味を編集しています）'
            : 'Agent が選んだおすすめ'
        }
      />
      <ErrorMessage error={opportunitiesError} />
      {/* **評価できなかった run で、古いおすすめを最新の結果として出さない。** */}
      {items.length ? (
        <CardGrid items={items} />
      ) : !resultLoading && result ? (
        <p className="text-[14px] text-muted bg-[#f7f8f4] rounded-[7px] p-[14px]">
          この探索ではおすすめを選んでいません。候補は
          <button
            type="button"
            className="underline mx-[4px]"
            onClick={() => navigate(`/app/results?run_id=${result.run_id}`)}
          >
            探索結果
          </button>
          で見られます。
        </p>
      ) : null}
      <BottomNote />
    </>
  );
}
