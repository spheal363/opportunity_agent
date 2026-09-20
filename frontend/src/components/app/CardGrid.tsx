import { useAppState } from '../../state/context';
import type { Opportunity } from '../../types';
import { EmptyState, OpportunityCard } from './OpportunityCard';

const GRID =
  'grid grid-cols-[repeat(3,minmax(0,1fr))] gap-[17px] lte1150:gap-[12px] lte850:gap-[13px] lte620:grid-cols-1 lte620:gap-[19px]';

interface CardGridProps {
  items: Opportunity[];
  /** 探索結果の画面だけカードの見せ方が変わる。 */
  isResult?: boolean;
  empty?: { kind: 'saved' | 'steps'; onReturn: () => void };
}

export function CardGrid({ items, isResult = false, empty }: CardGridProps) {
  const { statusOf, toggleInterest, openDetail } = useAppState();

  return (
    <div className={GRID}>
      {items.length ? (
        items.map((opportunity, index) => (
          <OpportunityCard
            key={opportunity.opportunity_id}
            opportunity={opportunity}
            index={index}
            status={statusOf(opportunity)}
            isResult={isResult}
            onToggleSave={() => void toggleInterest(opportunity)}
            onOpenDetail={() => openDetail(opportunity.opportunity_id)}
          />
        ))
      ) : empty ? (
        <EmptyState kind={empty.kind} onReturn={empty.onReturn} />
      ) : null}
    </div>
  );
}

/** 「CURATED FOR YOU / あなたに届けたい、3つの機会 03」の見出し。 */
export function ResultsHead({
  eyebrow,
  title,
  count,
  note,
}: {
  eyebrow: string;
  title: string;
  count: number;
  note?: string;
}) {
  return (
    <div className="flex items-center justify-between mb-[20px] gap-[10px] lte620:items-start">
      <div>
        <span className="text-[12px] tracking-[.06em] font-semibold text-[#6b7c6f] font-en">
          {eyebrow}
        </span>
        <h2 className="text-[19px] font-medium mt-[5px] mb-0 tracking-[.02em] lte1150:text-[17px]">
          {title}
          <span className="font-['DM_Sans',sans-serif] text-[13px] text-[#879584] bg-[#edf0e8] rounded-[20px] px-[8px] py-[2px] ml-[12px] align-middle lte620:text-[11px] lte620:ml-[5px]">
            {String(count).padStart(2, '0')}
          </span>
        </h2>
      </div>
      {note ? <span className="text-[12px] text-[#879084] lte620:hidden">{note}</span> : null}
    </div>
  );
}
