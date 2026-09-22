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
  'application' | 'registration' | 'early_bird' | 'speaker' | 'other' | 'unknown';

export type OpportunityStatus =
  'discovered' | 'recommended' | 'interested' | 'registered' | 'attended' | 'dismissed';

/**
 * `GET /api/opportunities`。ユーザーへ提示済みの候補**すべて**。
 *
 * **今回の探索が選んだ 3 件ではない。** 選定結果は
 * `GET /api/agent/runs/{run_id}/result` で取る。こちらは保存一覧・次の一歩の
 * 母集合なので、件数を絞らない。
 */
/** 詳細確認で直した 1 項目（#47）。 */
export type Correction = {
  field: string;
  before: string | null;
  after: string | null;
  source: string;
  checked_at: string | null;
};

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

  /**
   * **詳細確認を実行したかどうか。**
   * 日付・場所・受付・参加資格がすべて確認済みという意味ではない（#47）。
   * 何が確認できたかは `confirmed_fields` を見る。
   */
  verified: boolean;
  /** **複数日開催を期間として出すために一覧でも返す（#47）。** */
  end_at: string | null;
  end_at_is_date_only: boolean | null;
  /** どの希望から出た候補か。分割後の短いラベル。 */
  wish: string | null;
  /** **元の入力そのまま。** 分割で原文を失わないために持つ。 */
  wish_source: string | null;
  /** **詳細確認で実際に確認できた項目名。** 空なら未確認。 */
  confirmed_fields: string[];
  /** 訂正の履歴。**上書きせず積む。** */
  corrections: Correction[];
  detail_checked_at: string | null;
  /** **LLM 評価を行ったか。** false の候補は `score` を表示に使わない。 */
  evaluated: boolean;
  /** 会期の途中 1 日で参加できるか／全日必須か。**根拠が無ければ null。** */
  participation_span: string | null;
  /** 評価で挙がった、判断に必要な未確認事項。**推測で埋めない。** */
  unknowns: string[];

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
  /**
   * 出典に時刻が書かれていたか。**`null` は「分からない」**で、
   * `false`（出典に時刻があった）とは違う。どちらでもない限り時刻を出さない。
   */
  start_at_is_date_only: boolean | null;
  deadline_is_date_only: boolean | null;
  /**
   * 探索期間との関係（#47）。**受付状況とは別の軸。**
   * 期間内でも申込が締め切られていることがある。null は期間が分からない run。
   */
  window_status:
    | 'in_window'
    | 'ongoing'
    | 'after_window'
    | 'ended'
    | 'schedule_unknown'
    | 'not_time_bound'
    | null;
  window_note: string | null;
  /**
   * 希望した地域との照合（#47）。**受付・期間とはさらに別の軸。**
   * `unknown` を一致として扱わない。
   */
  region_match: 'match' | 'mismatch' | 'unknown' | null;
  region_note: string | null;
  /**
   * この URL は**申込先ではなく情報源**か。
   *
   * `true` のとき、申込先は確認できていない。取得元のページへのリンクとして
   * 見せ、「申込先は未確認」と添える。**情報源を申込先として見せない。**
   */
  url_is_source_only: boolean;
  /**
   * 検証で**本文から読み取れた**申込先。読み取れなければ null。
   *
   * **同一サイトであることは根拠にしない。** 外部の申込サービス
   * （Google Form、Peatix、connpass）を使う催しは多く、逆に同じサイトでも
   * 申込ページとは限らない。
   */
  application_url: string | null;
  /** 本人が取れる行動。特定できなければ null。 */
  recommended_action: string | null;
  status: OpportunityStatus;
};

/** GET /api/opportunities/{id}（詳細） */
export type OpportunityDetail = Opportunity & {
  source: string | null;
  format: OpportunityFormat | null;
  eligibility: string | null;
  cost: number | null;
  /**
   * 参加費の区分。**cost が null でも意味が違う。**
   * 記載が無いのか、区分によって額が違うのか。
   */
  cost_kind: CostKind | null;

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
