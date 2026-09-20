/** ④ 探索結果。Agent が選んだ TOP3。 */
import { useRef } from 'react';
import { useNavigate } from 'react-router-dom';

import { BottomNote, PageIntro } from '../components/app/Chrome';
import { CardGrid, ResultsHead } from '../components/app/CardGrid';
import { ResultWelcome } from '../components/app/ResultWelcome';
import ErrorMessage from '../components/ErrorMessage';
import { useAppState } from '../state/context';

export default function ResultsPage() {
  const navigate = useNavigate();
  const titleRef = useRef<HTMLHeadingElement>(null);
  const { profile, opportunities, opportunitiesError } = useAppState();

  const items = opportunities ?? [];

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
        title="あなたに届けたい、3つの機会"
        count={items.length}
      />
      <ErrorMessage error={opportunitiesError} />
      <CardGrid items={items} isResult />
      <BottomNote />
    </>
  );
}
