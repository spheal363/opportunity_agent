/**
 * Opportunity を、移植元プロトタイプのカード表現に落とすための対応表。
 *
 * ここで作るのは「見せ方」だけ。Web 上の事実（日時・場所・費用）は API が
 * 返した値をそのまま出し、取得できていない項目は推測せず「未定」と書く。
 */
import type {
  Availability,
  CostKind,
  DeadlineKind,
  Opportunity,
  OpportunityStatus,
  OpportunityType,
} from '../types';
import { formatDateOrDateTime, formatDateTime } from '../utils/date';

/** カード表紙の大きな英字。type ごとに固定の装飾文言で、事実ではない。 */
const COVER_LINES: Record<OpportunityType, [string, string]> = {
  hackathon: ['Build something.', 'Make some noise.'],
  community: ['Small ideas.', 'Real beginnings.'],
  accelerator: ['Your ideas.', 'Beyond borders.'],
  event: ['A new place.', 'A new you.'],
  competition: ['Show your work.', 'Find your level.'],
  job: ['A different desk.', 'A different story.'],
  freelance: ['Your own pace.', 'Your own work.'],
  scholarship: ['A door opens.', 'Go a little further.'],
  other: ['A fresh look.', 'A new direction.'],
};

const CATEGORY: Record<OpportunityType, string> = {
  hackathon: 'HACKATHON',
  community: 'COMMUNITY',
  accelerator: 'ACCELERATOR',
  event: 'EVENT',
  competition: 'COMPETITION',
  job: 'JOB',
  freelance: 'FREELANCE',
  scholarship: 'SCHOLARSHIP',
  other: 'OPPORTUNITY',
};

/**
 * この値以上を「意外なつながり」として表示する。
 * serendipity_score は AI の評価であって事実ではないため、閾値も表示上の都合。
 */
export const SERENDIPITY_THRESHOLD = 70;

export function coverLines(type: OpportunityType): [string, string] {
  return COVER_LINES[type] ?? COVER_LINES.other;
}

export function categoryLabel(type: OpportunityType): string {
  return CATEGORY[type] ?? CATEGORY.other;
}

export function isSerendipity(opportunity: Opportunity): boolean {
  return opportunity.serendipity_score >= SERENDIPITY_THRESHOLD;
}

/**
 * Web 由来の URL は http / https 以外を表示しない。
 *
 * url は Agent が Web から抽出した Untrusted Data で、Backend の Schema でも
 * 形式は検証されていない。javascript: や data: をそのまま href に渡すと、
 * クリックでアプリのオリジンでスクリプトが走り得る。
 */
export function safeHttpUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const { protocol } = new URL(url);
    return protocol === 'http:' || protocol === 'https:' ? url : null;
  } catch {
    return null;
  }
}

/**
 * 取得できなかった事実は推測で埋めない。
 *
 * **出典に時刻が無かったものは、日付だけで見せる。** 00:00 はこちらの
 * 正規化であって、ページに書かれていた時刻ではない。
 */
export function scheduleLabel(opportunity: Opportunity): string {
  return formatDateOrDateTime(opportunity.start_at, opportunity.start_at_is_date_only);
}

export function placeLabel(opportunity: Opportunity): string {
  return opportunity.location ?? '場所未定';
}

/**
 * **「記載が無い」と「区分によって違う」を分ける。**
 *
 * 一部の区分だけ無料のページを「無料」と出すと、有料の催しを無料として
 * 伝えることになる（実測でそうなった）。金額を持てない理由まで見せる。
 */
export function costLabel(cost: number | null | undefined, kind?: CostKind | null): string {
  if (cost !== null && cost !== undefined) {
    return cost === 0 ? '無料' : `${cost.toLocaleString('ja-JP')}円`;
  }
  if (kind === 'partially_free') return '一部無料・区分により異なる';
  if (kind === 'paid') return '有料（金額は要確認）';
  return '参加費未確認';
}

export function deadlineLabel(opportunity: Opportunity): string {
  return formatDateOrDateTime(opportunity.deadline, opportunity.deadline_is_date_only);
}

/**
 * **その締切が何に対するものかを添える。**
 *
 * 早割の期限を「申込締切」として見せると、参加できる催しを
 * 締め切ったものに見せてしまう（逆もある）。
 */
const DEADLINE_KIND_LABEL: Record<DeadlineKind, string> = {
  application: '応募締切',
  registration: '参加申込の期限',
  early_bird: '早割の期限',
  speaker: '登壇者募集の締切',
  other: '締切',
  unknown: '締切（対象は要確認）',
};

export function deadlineKindLabel(kind: DeadlineKind | null | undefined): string {
  return kind ? (DEADLINE_KIND_LABEL[kind] ?? DEADLINE_KIND_LABEL.unknown) : '申込締切';
}

/**
 * 受付状況の見せ方。**`verified`（情報を確認できたか）とは別の軸。**
 *
 * open は「受付中を**確認できた**」であって、参加できることの保証ではない。
 * 参加資格や空き枠までは分からない。
 *
 * **確認できていない状態を「受付中」とは書かない。** 締切が未来というだけで
 * 申し込めるとは限らず、日時が取れていない候補も多い。
 */
const AVAILABILITY_VIEW: Record<Availability, { mark: string; label: string; tone: string }> = {
  open: { mark: '✓', label: '受付中を確認', tone: 'text-[#4b6c58]' },
  closed: { mark: '✕', label: '受付終了を確認', tone: 'text-[#9a5c4c]' },
  unknown: { mark: '?', label: '受付状況は要確認', tone: 'text-[#707b73]' },
};

export function availabilityView(availability: Availability) {
  return AVAILABILITY_VIEW[availability] ?? AVAILABILITY_VIEW.unknown;
}

/**
 * いつ時点の確認かを必ず添える。
 *
 * **古い結果を今の状態として読ませないため。** 確認時刻が無いということは
 * 一度も確認していないということで、そのときは時刻を書かない。
 */
export function availabilityLabel(opportunity: Opportunity): string {
  const { label } = availabilityView(opportunity.availability);
  const at = opportunity.availability_checked_at;
  return at ? `${label}（${formatDateTime(at)} 時点）` : label;
}

/** サイドバーの「気になる」に入る状態。 */
export const SAVED_STATUSES: OpportunityStatus[] = ['interested'];

/** サイドバーの「次の一歩」に入る状態。 */
export const STEP_STATUSES: OpportunityStatus[] = ['registered', 'attended'];

export function isSaved(status: OpportunityStatus): boolean {
  return SAVED_STATUSES.includes(status);
}

export function isStep(status: OpportunityStatus): boolean {
  return STEP_STATUSES.includes(status);
}


/**
 * リンクの意味。**情報源を申込先として見せない。**
 *
 * 実測で、応募できる催しほど本文から申込先 URL が取れず、応募できない
 * ページほど自分自身の URL を返した。取得元をそのまま申込先と呼ぶと、
 * 「ここから申し込める」という誤った案内になる。
 */
export function linkLabel(opportunity: Opportunity): string {
  return opportunity.url_is_source_only ? '情報を見る（申込先は未確認）' : '申し込む';
}

/** 次に取れる行動。特定できていなければ null。 */
export function actionLabel(opportunity: Opportunity): string | null {
  return opportunity.recommended_action;
}
