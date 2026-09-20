/** ② ホーム（見つける）。いまのおすすめと、探索への入り口。 */
import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { BottomNote, PageIntro } from '../components/app/Chrome';
import { CardGrid, ResultsHead } from '../components/app/CardGrid';
import { DiscoverySurface } from '../components/app/DiscoverySurface';
import ErrorMessage from '../components/ErrorMessage';
import { useAppState } from '../state/context';

export default function HomePage() {
  const navigate = useNavigate();
  const titleRef = useRef<HTMLHeadingElement>(null);
  const { profile, opportunities, opportunitiesError, startRun, openGoal, showToast } =
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

  const items = opportunities ?? [];

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
        title="あなたに届けたい、3つの機会"
        count={items.length}
        note="Agent が選んだおすすめ"
      />
      <ErrorMessage error={opportunitiesError} />
      <CardGrid items={items} />
      <BottomNote />
    </>
  );
}
