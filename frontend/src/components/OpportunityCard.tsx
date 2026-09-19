import { Link } from 'react-router-dom';

import type { Opportunity } from '../types';
import { formatDateTime } from '../utils/date';

export default function OpportunityCard({ opportunity }: { opportunity: Opportunity }) {
  return (
    <Link
      to={`/opportunities/${opportunity.opportunity_id}`}
      className="block rounded-lg border border-slate-200 bg-white p-5 hover:border-slate-400"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs text-slate-500">{opportunity.type}</p>
          <h2 className="font-semibold">{opportunity.title}</h2>
        </div>
        <div className="shrink-0 text-right text-xs text-slate-500">
          <p>score {opportunity.score}</p>
          <p>serendipity {opportunity.serendipity_score}</p>
        </div>
      </div>

      <p className="mt-2 text-sm text-slate-600">
        {formatDateTime(opportunity.start_at)} / {opportunity.location ?? '場所不明'}
      </p>

      {opportunity.reason && (
        <p className="mt-3 text-sm leading-relaxed text-slate-700">{opportunity.reason}</p>
      )}

      <div className="mt-3 flex flex-wrap gap-1">
        {opportunity.match_reasons.map((reason) => (
          <span key={reason} className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
            {reason}
          </span>
        ))}
      </div>
    </Link>
  );
}
