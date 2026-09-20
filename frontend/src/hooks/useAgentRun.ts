import { useEffect, useRef, useState } from 'react';

import { fetchAgentLogs, fetchAgentRun } from '../api';
import type { AgentLogEntry, AgentRun } from '../types';

const POLL_INTERVAL_MS = 800;

export type WatchState = 'watching' | 'paused' | 'stopped';

/**
 * 探索中画面のポーリング。
 *
 * Agent の実行を止める API は無いため、ここで止められるのは「画面の更新」だけ。
 * 一時停止してもサーバー側の探索は進み続ける。
 */
export function useAgentRun(runId: string | null) {
  const [run, setRun] = useState<AgentRun | null>(null);
  const [logs, setLogs] = useState<AgentLogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [watch, setWatch] = useState<WatchState>('watching');

  const finishedRef = useRef(false);

  useEffect(() => {
    setRun(null);
    setLogs([]);
    setError(null);
    finishedRef.current = false;
    setWatch(runId ? 'watching' : 'stopped');
  }, [runId]);

  useEffect(() => {
    if (!runId || watch !== 'watching' || finishedRef.current) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    const poll = async () => {
      try {
        const [current, currentLogs] = await Promise.all([
          fetchAgentRun(runId),
          fetchAgentLogs(runId),
        ]);
        if (cancelled) return;
        setRun(current);
        setLogs(currentLogs);

        if (current.status === 'completed') {
          finishedRef.current = true;
          return;
        }
        if (current.status === 'failed') {
          finishedRef.current = true;
          setError(current.error ?? '探索に失敗しました');
          return;
        }
        timer = setTimeout(poll, POLL_INTERVAL_MS);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : '状態を取得できませんでした');
      }
    };

    void poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [runId, watch]);

  return { run, logs, error, watch, setWatch };
}
