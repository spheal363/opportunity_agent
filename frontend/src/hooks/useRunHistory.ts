import { useCallback, useEffect, useRef, useState } from 'react';

import { fetchAgentRunHistory } from '../api';
import type { AgentRunHistory } from '../types';

export function useRunHistory() {
  const [history, setHistory] = useState<AgentRunHistory>({ items: [], next_cursor: null });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestRef = useRef(0);

  const load = useCallback(async (before?: string) => {
    const request = ++requestRef.current;
    setLoading(true);
    setError(null);
    try {
      const page = await fetchAgentRunHistory(before);
      if (request !== requestRef.current) return;
      setHistory((previous) => ({
        items: before ? [...previous.items, ...page.items] : page.items,
        next_cursor: page.next_cursor,
      }));
    } catch (err) {
      if (request === requestRef.current) {
        setError(err instanceof Error ? err.message : '探索履歴を取得できませんでした');
      }
    } finally {
      if (request === requestRef.current) setLoading(false);
    }
  }, []);

  const invalidate = useCallback(() => {
    requestRef.current++;
  }, []);

  useEffect(() => {
    void load();
    return invalidate;
  }, [load, invalidate]);

  return { history, loading, error, load };
}
