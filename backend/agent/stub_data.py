"""AGENT_STUB_MODE=true のときに Agent Loop が返す固定データ。

LLM / Web Search を実装するまでの間、Frontend が
「Profile → 探索中 → TOP3 → 詳細」まで通しで結合できるようにするためのもの。
frontend/src/api/mock.ts と内容を合わせてある。
"""

from datetime import UTC, datetime, timedelta, timezone

_JST = timezone(timedelta(hours=9))


def _jst(month: int, day: int, hour: int) -> str:
    """日本時間の日時を UTC で表す。

    日付は固定する。起動日からの相対にすると、起動し直すたびに同じ機会の日付がずれ、
    カレンダーへ入れた予定と食い違う。
    SQLite は tz を捨てて保存するため、+09:00 のままではなく UTC に直して渡す。
    """
    return datetime(2026, month, day, hour, tzinfo=_JST).astimezone(UTC).isoformat()


STUB_GOAL_ANALYSIS = {
    "goal_summary": "AIプロダクト開発経験を増やしながら、起業や海外活動につながる経験・人脈を作る",
    "goal_directions": [
        "AI product development",
        "Entrepreneurship",
        "International experience",
        "Community building",
    ],
    "interest_connections": [
        "AI × Startup",
        "AI × Music",
        "Technology × International Community",
    ],
}

STUB_SEARCH_DIRECTIONS = [
    {
        "category": "hackathon",
        "query": "AI agent hackathon Tokyo",
        "reason": "AIプロダクト開発経験につながるため",
        "serendipity": False,
    },
    {
        "category": "community",
        "query": "AI startup community Tokyo",
        "reason": "起業家・エンジニアとの接点を増やすため",
        "serendipity": False,
    },
    {
        "category": "event",
        "query": "AI music technology event Japan",
        "reason": "AIと音楽という複数の興味が交差するOpportunityを探索するため",
        "serendipity": True,
    },
]

STUB_OPPORTUNITIES = [
    {
        "opportunity_id": "opp_001",
        "type": "hackathon",
        "title": "AI × Music Hackathon",
        "description": "AIと音楽をテーマにプロダクトを開発する2日間のハッカソン。",
        "url": "https://example.com/ai-music-hackathon",
        "source": "Web Search",
        "start_at": _jst(10, 12, 10),
        "end_at": _jst(10, 13, 18),
        "deadline": _jst(10, 7, 23),
        "location": "Tokyo",
        "format": "offline",
        "eligibility": "AI・音楽・プロダクト開発に興味がある人",
        "cost": 0,
        "score": 91,
        "serendipity_score": 94,
        "reason": (
            "AI Agent開発への関心とDJ・音楽という2つの興味が交差するOpportunityです。"
            "普段の検索では見つけにくい領域ですが、プロダクト開発経験と新しいコミュニティの"
            "両方につながる可能性があります。"
        ),
        "match_reasons": ["AI Agent", "Product Development", "Music", "DJ", "Community"],
        "verified": True,
        "verification_source": "https://example.com/ai-music-hackathon",
        "status": "recommended",
    },
    {
        "opportunity_id": "opp_002",
        "type": "community",
        "title": "Tokyo AI Startup Builders",
        "description": "AI領域で起業を目指すエンジニア・ファウンダーが集まる月次コミュニティ。",
        "url": "https://example.com/tokyo-ai-startup-builders",
        "source": "Web Search",
        "start_at": _jst(10, 1, 19),
        "end_at": _jst(10, 1, 21),
        "deadline": _jst(9, 29, 23),
        "location": "Tokyo",
        "format": "hybrid",
        "eligibility": "起業・AI開発に関心のあるエンジニア",
        "cost": 0,
        "score": 89,
        "serendipity_score": 45,
        "reason": (
            "将来的に起業したいという目標に対して、実際に起業しているエンジニアとの"
            "接点を作れる場です。AI Agent開発の経験がそのまま話題になります。"
        ),
        "match_reasons": ["Entrepreneurship", "AI", "Community"],
        "verified": True,
        "verification_source": "https://example.com/tokyo-ai-startup-builders",
        "status": "recommended",
    },
    {
        "opportunity_id": "opp_003",
        "type": "accelerator",
        "title": "Global AI Founders Program (Remote Track)",
        "description": "海外アクセラレータのリモート参加枠。英語でのメンタリングとデモデイつき。",
        "url": "https://example.com/global-ai-founders",
        "source": "Web Search",
        "start_at": _jst(11, 5, 9),
        "end_at": None,
        "deadline": _jst(10, 21, 23),
        "location": "Remote / San Francisco",
        "format": "online",
        "eligibility": "プロトタイプがあるチーム・個人",
        "cost": 0,
        "score": 85,
        "serendipity_score": 76,
        "reason": (
            "海外で活動したいという目標に直結し、かつリモート枠があるため現在の生活を"
            "変えずに挑戦できます。英語環境での実績づくりにもつながります。"
        ),
        "match_reasons": ["International", "Entrepreneurship", "AI Product"],
        "verified": True,
        "verification_source": "https://example.com/global-ai-founders",
        "status": "recommended",
    },
]
