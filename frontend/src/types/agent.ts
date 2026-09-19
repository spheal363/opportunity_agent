/** backend/schemas/agent.py と対応。 */

export type AgentRunStatus = 'queued' | 'running' | 'completed' | 'failed';

export type AgentStep =
  | 'analyzing_profile'
  | 'planning'
  | 'searching'
  | 'evaluating'
  | 'verifying'
  | 'completed';

export type AgentRunCreated = {
  run_id: string;
  status: AgentRunStatus;
};

/** GET /api/agent/runs/{run_id}。探索中画面がポーリングする。 */
export type AgentRun = {
  run_id: string;
  status: AgentRunStatus;
  current_step: AgentStep | null;
  message: string | null;
  progress: number;
  error: string | null;
};

export type AgentLogEntry = {
  step: AgentStep;
  message: string;
  created_at: string | null;
};

/** 探索中画面でステップ名を日本語表示するためのラベル。 */
export const AGENT_STEP_LABEL: Record<AgentStep, string> = {
  analyzing_profile: 'プロフィールを分析中',
  planning: '探索計画を作成中',
  searching: 'Web を探索中',
  evaluating: 'Opportunity を評価中',
  verifying: '公式情報を確認中',
  completed: '完了',
};
