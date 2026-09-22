import { createContext, useContext } from 'react';

import type {
  AgentRun,
  Opportunity,
  OpportunityStatus,
  Reaction,
  UserProfile,
  UserProfileInput,
} from '../types';

export interface AppState {
  profile: UserProfile | null;
  profileError: string | null;

  /**
   * ユーザーに提示済みの候補。**保存一覧・次の一歩の母集合。**
   *
   * **今回の選定結果ではない。** そちらは ResultsPage が
   * `GET /api/agent/runs/{run_id}/result` から取る。ここで絞ると、
   * 保存した候補が上位 3 件の外にあるときに保存一覧から消える。
   */
  /** 最後に実行した run。結果画面が URL に run_id を持たないときの既定。 */
  lastRunId: string | null;

  opportunities: Opportunity[] | null;
  opportunitiesError: string | null;
  refreshOpportunities: () => Promise<void>;

  /** サーバーの status に、この画面で行った操作を重ねた結果。 */
  statusOf: (opportunity: Opportunity) => OpportunityStatus;
  savedCount: number;
  stepCount: number;

  /** プロフィールを保存して探索を開始する。run_id を返す。 */
  saveProfileAndStart: (input: UserProfileInput) => Promise<string>;
  /** 今のプロフィールのまま探索を開始する。run_id を返す。 */
  startRun: () => Promise<string>;

  /** いちばん新しい run（GET /agent/runs/latest）。ホームと👎の後に取り直す。 */
  latestRun: AgentRun | null;
  /** 最新の run を取り直す。取れなければ null（知らせのための取得なので、失敗しても止めない）。 */
  refreshLatestRun: () => Promise<AgentRun | null>;
  /**
   * Agent が自分で始めた探索（trigger が manual 以外）のうち、まだ見ていないもの。
   * 最後に自分で始めた run（lastRunId）や、見た・閉じたものは含めない。
   */
  autoRun: AgentRun | null;
  /** 自動で始めた run を見る。結果画面の既定をその run にする。画面の移動はリンクが行う。 */
  openAutoRun: (runId: string) => void;
  /** 自動で始めた run の知らせを閉じる。 */
  dismissAutoRun: (runId: string) => void;

  toggleInterest: (opportunity: Opportunity) => Promise<void>;
  markAsStep: (opportunityId: string) => void;

  reactionOf: (opportunityId: string) => Reaction | undefined;
  /** POST /interest が返した登録先。詳細の url より優先して使う。 */
  registrationUrlOf: (opportunityId: string) => string | undefined;
  sendReaction: (opportunityId: string, reaction: Reaction) => Promise<void>;

  noteOf: (opportunityId: string) => string | undefined;
  setNote: (opportunityId: string, note: string) => void;

  /** 目標・興味の編集ダイアログ。ヘッダー・サイドバー・各画面から開く。 */
  goalOpen: boolean;
  openGoal: () => void;
  closeGoal: () => void;

  /** 機会の詳細ダイアログ。カードから開く。 */
  detailId: string | null;
  openDetail: (opportunityId: string) => void;
  closeDetail: () => void;

  toastMessage: string;
  toastVisible: boolean;
  showToast: (message: string) => void;
}

export const AppStateContext = createContext<AppState | null>(null);

export function useAppState(): AppState {
  const value = useContext(AppStateContext);
  if (!value) throw new Error('useAppState must be used inside <AppStateProvider>');
  return value;
}
