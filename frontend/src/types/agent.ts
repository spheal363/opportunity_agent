import type { Opportunity } from './opportunity';

/** backend/schemas/agent.py と対応。 */

export type AgentRunStatus = 'queued' | 'running' | 'completed' | 'failed';

export type AgentStep =
  'analyzing_profile' | 'planning' | 'searching' | 'evaluating' | 'verifying' | 'completed';

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

  /** この探索にかかった見積もり額。**請求額ではない**（backend/ai/cost.py の単価表）。 */
  cost_jpy: number;
  /** 高性能モデルを使った回数。全件を高性能モデルへ投げていないことを示す。 */
  expensive_model_calls: number;
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

/**
 * GET /api/agent/runs/{run_id}/result。**この run の最終選定。**
 *
 * `GET /api/opportunities`（保存一覧の母集合）とは別物。あちらは status で
 * 絞った最新の一覧で、こちらは**その run が選んだものを順位順**に返す。
 */
export type AgentRunResult = {
  run_id: string;
  status: AgentRunStatus;
  /** 結果が記録されているか。未完了・古い run では false */
  recorded: boolean;
  /** 順位順。**3 件に満たないことがある** */
  selected: Opportunity[];
  /** 3 件に満たなかった理由 */
  shortfall_reason: string | null;
  /** この run が対象にした期間（#47）。この列が付く前の run では null */
  search_window: { start: string; end: string; tz: string; days: number } | null;
  /**
   * 推薦しなかったが、**本文まで読んで抽出できた**候補。
   *
   * 検索しただけで未読の候補は入らない。未読の保留候補を、確認済みの推薦と
   * 同じ扱いにしないため。一覧を開くだけでは外部 API を呼ばない。
   */
  others: Opportunity[];
  /** 失敗した理由。**「記録されていません」だけでは原因が分からない。** */
  error: string | null;
};
