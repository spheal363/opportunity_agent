/**
 * この run の最終選定を取る。
 *
 * **`opportunities`（保存一覧の母集合）とは別経路。** 混ぜると、過去 run の
 * 高スコア候補が混ざったり、保存した候補が消えたりする。
 */

import { useEffect, useState } from 'react';

import { fetchAgentRunResult } from '../api';
import type { AgentRunResult } from '../types';

type State = {
  result: AgentRunResult | null;
  error: string | null;
  loading: boolean;
};

export function useRunResult(runId: string | null): State {
  const [result, setResult] = useState<AgentRunResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!runId) {
      setResult(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    fetchAgentRunResult(runId)
      .then((r) => {
        if (!cancelled) setResult(r);
      })
      .catch((err) => {
        if (!cancelled)
          setError(err instanceof Error ? err.message : '探索結果を取得できませんでした');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  return { result, error, loading };
}
