/**
 * Opportunity を、移植元プロトタイプのカード表現に落とすための対応表。
 *
 * ここで作るのは「見せ方」だけ。Web 上の事実（日時・場所・費用）は API が
 * 返した値をそのまま出し、取得できていない項目は推測せず「未定」と書く。
 */
import type { Availability, Opportunity, OpportunityStatus, OpportunityType } from '../types';
import { formatDateTime } from '../utils/date';

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

/** 取得できなかった事実は推測で埋めない。 */
export function scheduleLabel(opportunity: Opportunity): string {
  return formatDateTime(opportunity.start_at);
}

export function placeLabel(opportunity: Opportunity): string {
  return opportunity.location ?? '場所未定';
}

export function costLabel(cost: number | null | undefined): string {
  if (cost === null || cost === undefined) return '参加費未確認';
  return cost === 0 ? '無料' : `${cost.toLocaleString('ja-JP')}円`;
}

export function deadlineLabel(opportunity: Opportunity): string {
  return formatDateTime(opportunity.deadline);
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
