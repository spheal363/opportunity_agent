/**
 * ③ Agent 探索中。
 * GET /api/agent/runs/{run_id} をポーリングして、Agent が今何をしているかを表示する。
 */
import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { fetchAgentLogs, fetchAgentRun } from '../api';
import ErrorMessage from '../components/ErrorMessage';
import { AGENT_STEP_LABEL, type AgentLogEntry, type AgentRun } from '../types';

const POLL_INTERVAL_MS = 800;

export default function ExplorePage() {
  const [params] = useSearchParams();
  const runId = params.get('run_id');
  const navigate = useNavigate();

  const [run, setRun] = useState<AgentRun | null>(null);
  const [logs, setLogs] = useState<AgentLogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) {
      setError('run_id がありません。プロフィール画面からやり直してください。');
      return;
    }

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
          navigate('/opportunities');
          return;
        }
        if (current.status === 'failed') {
          setError(current.error ?? '探索に失敗しました');
          return;
        }
        timer = setTimeout(poll, POLL_INTERVAL_MS);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : '状態を取得できませんでした');
      }
    };

    void poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [runId, navigate]);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold">Agent が探索しています</h1>
        <p className="mt-1 text-sm text-slate-600">
          {run?.current_step ? AGENT_STEP_LABEL[run.current_step] : '準備中'}
          {run?.message ? ` — ${run.message}` : ''}
        </p>
      </div>

      <div className="h-2 w-full overflow-hidden rounded bg-slate-200">
        <div
          className="h-full bg-slate-900 transition-all"
          style={{ width: `${run?.progress ?? 0}%` }}
        />
      </div>

      <ErrorMessage error={error} />

      <ol className="space-y-2">
        {logs.map((log, index) => (
          <li key={index} className="rounded border border-slate-200 bg-white px-3 py-2 text-sm">
            <span className="mr-2 text-xs text-slate-500">{AGENT_STEP_LABEL[log.step]}</span>
            {log.message}
          </li>
        ))}
      </ol>
    </div>
  );
}
