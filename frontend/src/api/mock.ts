/**
 * Backend 未完成でも画面を作れるようにするための Mock Data。
 * backend/agent/stub_data.py と内容を合わせてある。
 */
import type {
  AgentLogEntry,
  AgentRun,
  Opportunity,
  OpportunityDetail,
  Reaction,
  UserProfile,
} from '../types';

const day = (offset: number, hour: number) => {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  d.setHours(hour, 0, 0, 0);
  return d.toISOString();
};

/** 日本時間の日時。開催日などは固定する（stub_data.py の _jst と同じ値）。 */
const jst = (month: number, date: number, hour: number) =>
  new Date(Date.UTC(2026, month - 1, date, hour - 9)).toISOString();

export const MOCK_PROFILE: UserProfile = {
  user_id: 'user_001',
  name: 'Naoya',
  location: 'Tokyo, Japan',
  languages: ['Japanese', 'English'],
  occupation: 'Backend Engineer',
  skills: ['Java', 'Python', 'AWS', 'AI Agent'],
  experience: ['Backend development', 'Personal AI Agent development'],
  interests: ['AI', 'Startup', 'Entrepreneurship', 'Music', 'DJ'],
  goals: ['Build AI products', 'Start a company', 'Work internationally'],
  about: 'AI Agentや起業、音楽に興味があります。',
};

export const MOCK_OPPORTUNITIES: OpportunityDetail[] = [
  {
    opportunity_id: 'opp_001',
    type: 'hackathon',
    title: 'AI × Music Hackathon',
    description: 'AIと音楽をテーマにプロダクトを開発する2日間のハッカソン。',
    url: 'https://example.com/ai-music-hackathon',
    source: 'Web Search',
    start_at: jst(10, 12, 10),
    end_at: jst(10, 13, 18),
    deadline: jst(10, 7, 23),
    location: 'Tokyo',
    format: 'offline',
    eligibility: 'AI・音楽・プロダクト開発に興味がある人',
    cost: 0,
    score: 91,
    serendipity_score: 94,
    reason:
      'AI Agent開発への関心とDJ・音楽という2つの興味が交差するOpportunityです。普段の検索では見つけにくい領域ですが、プロダクト開発経験と新しいコミュニティの両方につながる可能性があります。',
    match_reasons: ['AI Agent', 'Product Development', 'Music', 'DJ', 'Community'],
    verified: true,
    availability: 'unknown',
    availability_reason: null,
    availability_checked_at: null,
    start_at_is_date_only: false,
    url_is_source_only: false,
    application_url: null,
    recommended_action: '参加登録する',
    end_at_is_date_only: false,
    deadline_is_date_only: false,
    deadline_kind: 'application',
    deadline_quote: null,
    cost_kind: 'free',
    verified_at: day(0, 13),
    verification_source: 'https://example.com/ai-music-hackathon',
    status: 'recommended',
  },
  {
    opportunity_id: 'opp_002',
    type: 'community',
    title: 'Tokyo AI Startup Builders',
    description: 'AI領域で起業を目指すエンジニア・ファウンダーが集まる月次コミュニティ。',
    url: 'https://example.com/tokyo-ai-startup-builders',
    source: 'Web Search',
    start_at: jst(10, 1, 19),
    end_at: jst(10, 1, 21),
    deadline: jst(9, 29, 23),
    location: 'Tokyo',
    format: 'hybrid',
    eligibility: '起業・AI開発に関心のあるエンジニア',
    cost: 0,
    score: 89,
    serendipity_score: 45,
    reason:
      '将来的に起業したいという目標に対して、実際に起業しているエンジニアとの接点を作れる場です。AI Agent開発の経験がそのまま話題になります。',
    match_reasons: ['Entrepreneurship', 'AI', 'Community'],
    verified: true,
    availability: 'unknown',
    availability_reason: null,
    availability_checked_at: null,
    start_at_is_date_only: false,
    url_is_source_only: false,
    application_url: null,
    recommended_action: '参加登録する',
    end_at_is_date_only: false,
    deadline_is_date_only: false,
    deadline_kind: 'application',
    deadline_quote: null,
    cost_kind: 'free',
    verified_at: day(0, 13),
    verification_source: 'https://example.com/tokyo-ai-startup-builders',
    status: 'recommended',
  },
  {
    opportunity_id: 'opp_003',
    type: 'accelerator',
    title: 'Global AI Founders Program (Remote Track)',
    description: '海外アクセラレータのリモート参加枠。英語でのメンタリングとデモデイつき。',
    url: 'https://example.com/global-ai-founders',
    source: 'Web Search',
    start_at: jst(11, 5, 9),
    end_at: null,
    deadline: jst(10, 21, 23),
    location: 'Remote / San Francisco',
    format: 'online',
    eligibility: 'プロトタイプがあるチーム・個人',
    cost: 0,
    score: 85,
    serendipity_score: 76,
    reason:
      '海外で活動したいという目標に直結し、かつリモート枠があるため現在の生活を変えずに挑戦できます。英語環境での実績づくりにもつながります。',
    match_reasons: ['International', 'Entrepreneurship', 'AI Product'],
    verified: true,
    availability: 'unknown',
    availability_reason: null,
    availability_checked_at: null,
    start_at_is_date_only: false,
    url_is_source_only: false,
    application_url: null,
    recommended_action: '参加登録する',
    end_at_is_date_only: false,
    deadline_is_date_only: false,
    deadline_kind: 'application',
    deadline_quote: null,
    cost_kind: 'free',
    verified_at: day(0, 13),
    verification_source: 'https://example.com/global-ai-founders',
    status: 'recommended',
  },
];

export const MOCK_OPPORTUNITY_SUMMARIES: Opportunity[] = MOCK_OPPORTUNITIES;

export const MOCK_AGENT_LOGS: AgentLogEntry[] = [
  {
    step: 'analyzing_profile',
    message: 'AIプロダクト開発経験を増やしながら、起業や海外活動につながる経験・人脈を作る',
    created_at: null,
  },
  {
    step: 'planning',
    message: '探索対象に設定: AI agent hackathon Tokyo（AIプロダクト開発経験につながるため）',
    created_at: null,
  },
  {
    step: 'planning',
    message:
      '探索対象に設定: AI music technology event Japan（AIと音楽という複数の興味が交差するOpportunityを探索するため）',
    created_at: null,
  },
  { step: 'searching', message: '3件のOpportunityを発見', created_at: null },
  { step: 'evaluating', message: '3件からTOP3件に絞り込み', created_at: null },
  { step: 'verifying', message: 'TOP3の公式情報を確認しました', created_at: null },
];

// --- 自動探索（backend/services/auto_explore.py の feedback） ---

export const MOCK_RUN_ID = 'run_mock';
export const MOCK_FEEDBACK_RUN_ID = 'run_mock_feedback';

/** 探索中の見え方を確かめられるよう、探し直しを始めてからしばらくは running を返す。 */
const MOCK_FEEDBACK_RUNNING_MS = 4000;

const mockDisliked = new Set<string>();
let mockFeedbackRun: { startedAt: number; reason: string } | null = null;

/**
 * 👎を覚えておき、推薦の過半数（2 件以上）に付いたら探し直しを 1 回だけ始めたことにする。
 * 理由の文は Backend と同じ決まった文面と数値だけ。
 */
export function recordMockFeedback(opportunityId: string, reaction: Reaction): void {
  if (reaction !== 'dislike') return;
  mockDisliked.add(opportunityId);
  const total = MOCK_OPPORTUNITIES.length;
  const disliked = mockDisliked.size;
  if (mockFeedbackRun || disliked < 2 || disliked * 2 <= total) return;
  mockFeedbackRun = {
    startedAt: Date.now(),
    reason: `今回の推薦${total}件のうち${disliked}件に👎が付いたため、反応を踏まえて探し直します`,
  };
}

export function mockAgentRun(runId: string): AgentRun {
  const base = { run_id: runId, error: null, cost_jpy: 0, expensive_model_calls: 0 };
  if (runId === MOCK_FEEDBACK_RUN_ID && mockFeedbackRun) {
    const running = Date.now() - mockFeedbackRun.startedAt < MOCK_FEEDBACK_RUNNING_MS;
    return {
      ...base,
      status: running ? 'running' : 'completed',
      current_step: running ? 'searching' : 'completed',
      message: running ? 'Webを探索しています' : '探索が完了しました',
      progress: running ? 60 : 100,
      trigger: 'feedback',
      trigger_reason: mockFeedbackRun.reason,
    };
  }
  return {
    ...base,
    status: 'completed',
    current_step: 'completed',
    message: '探索が完了しました',
    progress: 100,
    trigger: 'manual',
    trigger_reason: null,
  };
}

/** GET /agent/runs/latest の Mock。探し直しを始めていればそれ、無ければ手動の run。 */
export function mockLatestAgentRun(): AgentRun {
  return mockAgentRun(mockFeedbackRun ? MOCK_FEEDBACK_RUN_ID : MOCK_RUN_ID);
}

/** 自動で始めた run は、最初の Log に「なぜ始めたか」が入る（Backend と同じ）。 */
export function mockAgentLogs(runId: string): AgentLogEntry[] {
  if (runId === MOCK_FEEDBACK_RUN_ID && mockFeedbackRun) {
    return [
      { step: 'analyzing_profile', message: mockFeedbackRun.reason, created_at: null },
      ...MOCK_AGENT_LOGS,
    ];
  }
  return MOCK_AGENT_LOGS;
}
