import type { AgentRunResult, AgentLogEntry, AgentRun, AgentRunCreated } from '../types';
import { api, USE_MOCK } from './client';
import { MOCK_AGENT_LOGS, MOCK_OPPORTUNITY_SUMMARIES } from './mock';

export async function startAgentRun(): Promise<AgentRunCreated> {
  if (USE_MOCK) return { run_id: 'run_mock', status: 'running' };
  return api.post<AgentRunCreated>('/agent/runs');
}

export async function fetchAgentRun(runId: string): Promise<AgentRun> {
  if (USE_MOCK) {
    return {
      run_id: runId,
      status: 'completed',
      current_step: 'completed',
      message: '探索が完了しました',
      progress: 100,
      error: null,
      cost_jpy: 0,
      expensive_model_calls: 0,
    };
  }
  return api.get<AgentRun>(`/agent/runs/${runId}`);
}

export async function fetchAgentLogs(runId: string): Promise<AgentLogEntry[]> {
  if (USE_MOCK) return MOCK_AGENT_LOGS;
  return api.get<AgentLogEntry[]>(`/agent/runs/${runId}/logs`);
}

/** この run の最終選定。結果画面はこれを使う。 */
export async function fetchAgentRunResult(runId: string): Promise<AgentRunResult> {
  if (USE_MOCK) {
    return {
      run_id: runId,
      status: 'completed',
      recorded: true,
      selected: MOCK_OPPORTUNITY_SUMMARIES,
      shortfall_reason: null,
      // Mock でも期間を返す。**画面側に「期間が無いとき」の分岐を増やさない。**
      search_window: { start: '2026-09-22', end: '2026-11-21', tz: 'Asia/Tokyo', days: 60 },
      others: [],
      error: null,
    };
  }
  return api.get<AgentRunResult>(`/agent/runs/${runId}/result`);
}
