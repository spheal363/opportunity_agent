import type {
  CalendarAvailability,
  CalendarEventPreview,
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

// --- Calendar（docs/api.md の 7 / 8） ---

/**
 * 登録する内容だけを取る。**Google へは触らない。**
 *
 * 空き確認は Google を呼ぶので未連携だと落ちる。そのとき「何が登録されるのか」
 * まで見られなくなるのを避けるため、確認の表示はこちらで取る。
 */
export async function fetchCalendarPreview(id: string): Promise<CalendarEventPreview> {
  if (USE_MOCK) {
    return {
      title: 'AI × Music Hackathon',
      start_at: '2026-10-11T10:00:00Z',
      end_at: '2026-10-11T18:00:00Z',
      all_day: false,
      timezone: 'Asia/Tokyo',
      end_is_placeholder: false,
      location: 'Tokyo',
      source_url: 'https://example.com/ai-music-hackathon',
    };
  }
  return api.get<CalendarEventPreview>(
    `/calendar/preview?opportunity_id=${encodeURIComponent(id)}`,
  );
}

/** その機会の時間帯に重なる予定。読み取りだけなので、画面を開いたときに自動で呼んでよい。 */
export async function checkCalendarAvailability(id: string): Promise<CalendarAvailability> {
  if (USE_MOCK) return { available: true, conflicts: [], event: null };
  return api.get<CalendarAvailability>(
    `/calendar/availability?opportunity_id=${encodeURIComponent(id)}`,
  );
}

/**
 * ユーザーの Google カレンダーに予定を入れる。**ユーザーが追加内容を見てボタンを押したときだけ呼ぶ。**
 * 成功すると Backend 側でも status が registered（次の一歩）になる。
 * status は created / already_exists（同じ機会は何度押しても 1 件）。
 */
export async function addToCalendar(id: string): Promise<CalendarEventCreated> {
  if (USE_MOCK) return { calendar_event_id: `mock_${id}`, status: 'created' };
  return api.post<CalendarEventCreated>(`/opportunities/${encodeURIComponent(id)}/calendar`);
}
