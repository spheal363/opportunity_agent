import { useCallback, useEffect, useState } from 'react';

import { fetchLatestRunResult } from '../api';
import type { AgentRunResult } from '../types';

/**
 * 最新の完了 run の結果（#47）。**ホームはこれを見る。**
 *
 * `opportunities`（保存一覧の母集合）は複数 run の候補が混ざるので使わない。
 * `reloadKey` が変わると取り直す（新しい探索が終わったあとに更新するため）。
 */
export function useLatestResult(reloadKey?: string | null) {
  const [result, setResult] = useState<AgentRunResult | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setResult(await fetchLatestRunResult());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, reloadKey]);

  return { result, loading, reload: load };
}
