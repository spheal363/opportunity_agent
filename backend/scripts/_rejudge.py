"""保存済みの応答を、現在の判定ロジックで評価し直す。**API は呼ばない。**"""

import json
import pathlib
import sys
from datetime import UTC, datetime

from ai import availability, evidence
from ai.schemas.extraction import ExtractedOpportunity

path = pathlib.Path(sys.argv[1])
for r in json.loads(path.read_text())["results"]:
    if "raw" not in r or "error" in r:
        print(f"  {r['url'][-20:]:22} {r['attempt']}回目  **Schema 不通過**")
        continue
    parsed = ExtractedOpportunity.model_validate(json.loads(r["raw"]))
    g = evidence.ground_deadline_kind(parsed, r["content"])
    _, why = evidence.context_supports_kind(
        parsed.deadline_context, parsed.deadline_kind, r["content"]
    )
    sp = evidence.is_a_call_for_speakers(g.title, g.description)
    out = []
    for label, now in (
        ("9/21", datetime(2026, 9, 21, 12, tzinfo=UTC)),
        ("10/3", datetime(2026, 10, 3, 12, tzinfo=UTC)),
    ):
        st, _ = availability.from_dates(
            opportunity_type=g.type,
            deadline=g.deadline,
            end_at=g.end_at,
            now=now,
            deadline_kind=g.deadline_kind,
            deadline_is_date_only=g.deadline_is_date_only,
            speaker_is_the_opportunity=sp,
        )
        out.append(f"{label}={st}")
    print(
        f"  {r['url'][-20:]:22} {r['attempt']}回目  生={parsed.deadline_kind.value:12}"
        f" -> {g.deadline_kind.value:12} {'  '.join(out)}   {why or ''}"
    )
