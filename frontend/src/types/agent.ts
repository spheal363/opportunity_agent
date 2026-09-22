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
  /** **この run の入力原文。** 改行を保つ。古い run は null。 */
  wishes_source: string | null;
  region_source: string | null;
  /** AI が整理した探索方向。**原文の置き換えには使わない。** */
  goal_directions: string[];
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
/**
 * 検索で見つかった候補 1 件（#47）。
 *
 * **「読んでいない」と「日程が無い」と「終了した」を混ぜない。**
 * 読んでいない候補を受付中として扱わない。
 */
export type SearchCandidate = {
  title: string;
  url: string;
  /** 本文を読んで抽出できたか。false なら日時も受付状況も分からない */
  read: boolean;
  /** おすすめ（この run の最終選定）に入っているか */
  recommended: boolean;
  /** 抽出できた開催日だけ。**検索結果の公開日は使わない** */
  start_at: string | null;
  start_at_is_date_only: boolean | null;
  window_status: string | null;
  /** 読んでいない候補では null（unknown とも書かない） */
  availability: string | null;
  verified: boolean;
};

/** run の対象期間。**日付は `tz` で解釈する。** */
export type SearchWindow = { start: string; end: string; tz: string; days: number };

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
  search_window: SearchWindow | null;
  /**
   * 推薦しなかったが、**本文まで読んで抽出できた**候補。
   *
   * 検索しただけで未読の候補は入らない。未読の保留候補を、確認済みの推薦と
   * 同じ扱いにしないため。一覧を開くだけでは外部 API を呼ばない。
   */
  others: Opportunity[];
  /**
   * 検索で見つかった候補すべて（#47）。読んだ分も読んでいない分も入る。
   * この列が付く前の run では、読んだ分だけ復元して返る（水増ししない）。
   */
  search_candidates: SearchCandidate[];
  /** 失敗した理由。**「記録されていません」だけでは原因が分からない。** */
  error: string | null;
  /** **この run の入力原文。** 改行を保つ。古い run は null。 */
  wishes_source: string | null;
  region_source: string | null;
  /** AI が整理した探索方向。**原文の置き換えには使わない。** */
  goal_directions: string[];
  /** 新しい探索経路の run か。**旧経路の画面を変えないため。** */
  discovery_route: boolean;
  /** `selected` の先頭いくつが「おすすめ」か。**評価できなければ 0。** */
  recommended_count: number;
  /** **この探索のあとにプロフィールが編集されたか。** */
  profile_changed_since: boolean;
};
