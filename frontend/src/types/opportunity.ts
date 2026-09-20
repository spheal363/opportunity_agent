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

export type OpportunityStatus =
  | 'discovered'
  | 'recommended'
  | 'interested'
  | 'registered'
  | 'attended'
  | 'dismissed';

/** GET /api/opportunities（TOP3 一覧） */
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
  status: OpportunityStatus;
};

/** GET /api/opportunities/{id}（詳細） */
export type OpportunityDetail = Opportunity & {
  source: string | null;
  end_at: string | null;
  format: OpportunityFormat | null;
  eligibility: string | null;
  cost: number | null;
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
