import type { AgentLogEntry, AgentRun, AgentRunCreated } from '../types';
import { api, USE_MOCK } from './client';
import { MOCK_AGENT_LOGS } from './mock';

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
    };
  }
  return api.get<AgentRun>(`/agent/runs/${runId}`);
}

export async function fetchAgentLogs(runId: string): Promise<AgentLogEntry[]> {
  if (USE_MOCK) return MOCK_AGENT_LOGS;
  return api.get<AgentLogEntry[]>(`/agent/runs/${runId}/logs`);
}
