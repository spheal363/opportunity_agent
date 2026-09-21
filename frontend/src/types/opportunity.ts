/** backend/schemas/opportunity.py と対応。 */

export type OpportunityType =
  | 'event'
  | 'hackathon'
  | 'job'
  | 'freelance'
  | 'community'
  | 'accelerator'
  | 'competition'
  | 'scholarship'
  | 'other';

export type OpportunityFormat = 'offline' | 'online' | 'hybrid';

/** 受付状況。`verified` とは別の軸。 */
export type Availability = 'open' | 'closed' | 'unknown';

/** 参加費の区分。backend/ai/schemas/extraction.py と対応。 */
export type CostKind = 'free' | 'paid' | 'partially_free' | 'unknown';

/** 締切が何に対するものか。backend/ai/schemas/extraction.py と対応。 */
export type DeadlineKind =
  | 'application'
  | 'registration'
  | 'early_bird'
  | 'speaker'
  | 'other'
  | 'unknown';

export type OpportunityStatus =
  | 'discovered'
  | 'recommended'
  | 'interested'
  | 'registered'
  | 'attended'
  | 'dismissed';

/**
 * `GET /api/opportunities`。ユーザーへ提示済みの候補**すべて**。
 *
 * **今回の探索が選んだ 3 件ではない。** 選定結果は
 * `GET /api/agent/runs/{run_id}/result` で取る。こちらは保存一覧・次の一歩の
 * 母集合なので、件数を絞らない。
 */
export type Opportunity = {
  opportunity_id: string;
  type: OpportunityType;
  title: string;
  description: string | null;
  url: string | null;
  start_at: string | null;
  location: string | null;
  deadline: string | null;

  /** AI による総合適合度 0-100 */
  score: number;
  /** 自分では検索しなかった可能性の度合い 0-100 */
  serendipity_score: number;
  reason: string | null;
  match_reasons: string[];

  verified: boolean;

  /**
   * いま応募・参加できるか。**`verified`（情報を確認できたか）とは別の軸。**
   * open は「受付中を確認できた」という意味で、参加資格や空き枠は保証しない。
   */
  availability: Availability;
  availability_reason: string | null;
  /** いつ時点の確認か。古い結果を今の状態として読まないために対で見る。 */
  availability_checked_at: string | null;

  /**
   * 出典に時刻が書かれていたか。**false のとき時刻を表示しない。**
   * 00:00 はこちら側の正規化であって、出典の値ではない。
   */
  start_at_is_date_only: boolean;
  deadline_is_date_only: boolean;
  status: OpportunityStatus;
};

/** GET /api/opportunities/{id}（詳細） */
export type OpportunityDetail = Opportunity & {
  source: string | null;
  end_at: string | null;
  format: OpportunityFormat | null;
  eligibility: string | null;
  cost: number | null;
  /**
   * 参加費の区分。**cost が null でも意味が違う。**
   * 記載が無いのか、区分によって額が違うのか。
   */
  cost_kind: CostKind | null;

  end_at_is_date_only: boolean;
  /** その締切が何に対するものか。**早割の期限を申込締切として見せない。** */
  deadline_kind: DeadlineKind | null;
  /** 判断の根拠になったページ上の表記。 */
  deadline_quote: string | null;
  verified_at: string | null;
  verification_source: string | null;
};

export type InterestResult = {
  opportunity_id: string;
  status: OpportunityStatus;
  verified: boolean;
  registration_url: string | null;
  warnings: string[];
};

export type Reaction = 'like' | 'dislike';

export type FeedbackInput = {
  reaction: Reaction;
  attended?: boolean | null;
  outcome_score?: number | null;
};
