/** ④ Opportunity TOP3。 */
import { useEffect, useState } from 'react';

import { fetchOpportunities } from '../api';
import ErrorMessage from '../components/ErrorMessage';
import OpportunityCard from '../components/OpportunityCard';
import type { Opportunity } from '../types';

export default function OpportunitiesPage() {
  const [items, setItems] = useState<Opportunity[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchOpportunities()
      .then(setItems)
      .catch((err) => setError(err instanceof Error ? err.message : '取得に失敗しました'));
  }, []);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">あなたへの TOP3</h1>
        <p className="mt-1 text-sm text-slate-600">
          自分では検索しなかったであろう機会（Serendipity）も含めています。
        </p>
      </div>

      <ErrorMessage error={error} />

      {items === null && !error && <p className="text-sm text-slate-500">読み込み中…</p>}
      {items?.length === 0 && (
        <p className="text-sm text-slate-500">
          まだ推薦がありません。プロフィール画面から探索を開始してください。
        </p>
      )}

      {items?.map((opportunity) => (
        <OpportunityCard key={opportunity.opportunity_id} opportunity={opportunity} />
      ))}
    </div>
  );
}
