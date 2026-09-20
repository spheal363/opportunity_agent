/** 気になる（status: interested）。 */
import { useRef } from 'react';
import { useNavigate } from 'react-router-dom';

import { PageIntro } from '../components/app/Chrome';
import { CardGrid, ResultsHead } from '../components/app/CardGrid';
import ErrorMessage from '../components/ErrorMessage';
import { isSaved } from '../utils/display';
import { useAppState } from '../state/context';

export default function SavedPage() {
  const navigate = useNavigate();
  const titleRef = useRef<HTMLHeadingElement>(null);
  const { opportunities, opportunitiesError, statusOf } = useAppState();

  const items = (opportunities ?? []).filter((o) => isSaved(statusOf(o)));

  return (
    <>
      <PageIntro
        titleRef={titleRef}
        title="心が動いた機会を、ここに。"
        copy="あとで、ゆっくり考えてみても大丈夫。"
      />
      <ResultsHead eyebrow="SAVED FOR LATER" title="気になる機会" count={items.length} />
      <ErrorMessage error={opportunitiesError} />
      <CardGrid items={items} empty={{ kind: 'saved', onReturn: () => navigate('/app/results') }} />
    </>
  );
}
