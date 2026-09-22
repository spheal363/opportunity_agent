import type {
  AgentRunResult,
  AgentLogEntry,
  AgentRun,
  AgentRunCreated,
  AgentRunHistory,
} from '../types';
import { api, USE_MOCK } from './client';
import {
  MOCK_OPPORTUNITY_SUMMARIES,
  MOCK_RUN_ID,
  mockAgentLogs,
  mockAgentRun,
  mockLatestAgentRun,
  mockAgentRunHistory,
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

export async function fetchAgentRunHistory(before?: string): Promise<AgentRunHistory> {
  if (USE_MOCK) return mockAgentRunHistory(before);
  const query = new URLSearchParams({ limit: '20' });
  if (before) query.set('before', before);
  return api.get<AgentRunHistory>(`/agent/runs?${query}`);
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
    wishes_source: null,
    region_source: null,
    goal_directions: [],
    discovery_route: false,
    recommended_count: 0,
    profile_changed_since: false,
      selected: MOCK_OPPORTUNITY_SUMMARIES,
      shortfall_reason: null,
      // Mock でも期間を返す。**画面側に「期間が無いとき」の分岐を増やさない。**
      search_window: { start: '2026-09-22', end: '2026-11-21', tz: 'Asia/Tokyo', days: 60 },
      others: [],
      search_candidates: [],
      error: null,
    };
  }
  return api.get<AgentRunResult>(`/agent/runs/${runId}/result`);
}

/**
 * **そのユーザーの最新の完了 run** の結果（#47）。ホームが使う。
 *
 * `GET /api/opportunities` は**複数 run の候補が混ざる**ので、
 * ホームの「おすすめ」には使わない（実測で過去 run の候補まで並んでいた）。
 * 完了した探索がまだ無ければ null。
 */
export async function fetchLatestRunResult(): Promise<AgentRunResult | null> {
  if (USE_MOCK) return fetchAgentRunResult('run_mock');
  try {
    return await api.get<AgentRunResult>('/agent/runs/latest/result');
  } catch {
    return null;
  }
}
