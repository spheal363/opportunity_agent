import type {
  CalendarAvailability,
  CalendarEventCreated,
  FeedbackInput,
  InterestResult,
  Opportunity,
  OpportunityDetail,
} from '../types';
import { api, USE_MOCK } from './client';
import { MOCK_OPPORTUNITIES, MOCK_OPPORTUNITY_SUMMARIES } from './mock';

export async function fetchOpportunities(): Promise<Opportunity[]> {
  if (USE_MOCK) return MOCK_OPPORTUNITY_SUMMARIES;
  return api.get<Opportunity[]>('/opportunities');
}

export async function fetchOpportunity(id: string): Promise<OpportunityDetail> {
  if (USE_MOCK) {
    const found = MOCK_OPPORTUNITIES.find((o) => o.opportunity_id === id);
    if (!found) throw new Error(`mock opportunity not found: ${id}`);
    return found;
  }
  return api.get<OpportunityDetail>(`/opportunities/${id}`);
}

/** 「参加したい」。Backend 側で status 更新と公式情報の再確認を行う。 */
export async function markInterested(id: string): Promise<InterestResult> {
  if (USE_MOCK) {
    const found = await fetchOpportunity(id);
    return {
      opportunity_id: id,
      status: 'interested',
      verified: found.verified,
      registration_url: found.url,
      warnings: [],
    };
  }
  return api.post<InterestResult>(`/opportunities/${id}/interest`);
}

export async function sendFeedback(id: string, input: FeedbackInput) {
  if (USE_MOCK) return { opportunity_id: id, recorded: true };
  return api.post<{ opportunity_id: string; recorded: boolean }>(
    `/opportunities/${id}/feedback`,
    input,
  );
}

// --- Calendar（Backend 未実装。接続後に有効になる） ---

export async function checkCalendarAvailability(id: string): Promise<CalendarAvailability> {
  return api.get<CalendarAvailability>(`/calendar/availability?opportunity_id=${id}`);
}

export async function addToCalendar(id: string): Promise<CalendarEventCreated> {
  return api.post<CalendarEventCreated>(`/opportunities/${id}/calendar`);
}
