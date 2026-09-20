/** 次の一歩（status: registered / attended）。 */
import { useRef } from 'react';
import { useNavigate } from 'react-router-dom';

import { PageIntro } from '../components/app/Chrome';
import { CardGrid, ResultsHead } from '../components/app/CardGrid';
import ErrorMessage from '../components/ErrorMessage';
import { isStep } from '../utils/display';
import { useAppState } from '../state/context';

export default function StepsPage() {
  const navigate = useNavigate();
  const titleRef = useRef<HTMLHeadingElement>(null);
  const { opportunities, opportunitiesError, statusOf } = useAppState();

  const items = (opportunities ?? []).filter((o) => isStep(statusOf(o)));

  return (
    <>
      <PageIntro
        titleRef={titleRef}
        title="小さな一歩を、現実に。"
        copy="参加に向けて、準備を進めましょう。"
      />
      <ResultsHead eyebrow="YOUR NEXT STEPS" title="参加を検討している機会" count={items.length} />
      <ErrorMessage error={opportunitiesError} />
      <CardGrid items={items} empty={{ kind: 'steps', onReturn: () => navigate('/app/results') }} />
    </>
  );
}
