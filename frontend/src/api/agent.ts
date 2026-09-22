import type { AgentRunResult, AgentLogEntry, AgentRun, AgentRunCreated } from '../types';
import { api, USE_MOCK } from './client';
import {
  MOCK_OPPORTUNITY_SUMMARIES,
  MOCK_RUN_ID,
  mockAgentLogs,
  mockAgentRun,
  mockLatestAgentRun,
} from './mock';

export async function startAgentRun(): Promise<AgentRunCreated> {
  if (USE_MOCK) return { run_id: MOCK_RUN_ID, status: 'running' };
  return api.post<AgentRunCreated>('/agent/runs');
}

export async function fetchAgentRun(runId: string): Promise<AgentRun> {
  if (USE_MOCK) return mockAgentRun(runId);
  return api.get<AgentRun>(`/agent/runs/${runId}`);
}

/**
 * いちばん新しい run（状態は問わない）。まだ探索していなければ null。
 * Agent が自分で始めた探索（trigger が manual 以外）に気づくために使う。
 */
export async function fetchLatestAgentRun(): Promise<AgentRun | null> {
  if (USE_MOCK) return mockLatestAgentRun();
  return api.get<AgentRun | null>('/agent/runs/latest');
}

export async function fetchAgentLogs(runId: string): Promise<AgentLogEntry[]> {
  if (USE_MOCK) return mockAgentLogs(runId);
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
      error: null,
    };
  }
  return api.get<AgentRunResult>(`/agent/runs/${runId}/result`);
}
