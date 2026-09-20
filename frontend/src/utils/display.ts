/**
 * Opportunity を、移植元プロトタイプのカード表現に落とすための対応表。
 *
 * ここで作るのは「見せ方」だけ。Web 上の事実（日時・場所・費用）は API が
 * 返した値をそのまま出し、取得できていない項目は推測せず「未定」と書く。
 */
import type { Opportunity, OpportunityStatus, OpportunityType } from '../types';
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
