"""行動につながる情報を正しく抽出できているか（#65 で見つかった誤りへの回帰）。

**実 LLM は呼ばない。** A の run で保存した実際の出力を、そのまま
Schema と受付状況判定へ通し、**誤りが「受付中」「無料」として推薦へ
流れないこと**を確かめる。

## 正解と根拠

根拠は保存された「実際にモデルへ渡したテキスト」から取る。
取得元ページの全文ではなく、**切り詰め後の入力**に含まれていたもの。
入力に無い情報は補わない。

### https://www.isct.ac.jp/ja/news/mfgtg8c86wg2（三大学合同ハッカソン）

  入力の表記                                     期待する解釈
  「応募締切・募集人数 2026年2月9日（月）」        deadline 2026-02-09、kind=application
                                                 **時刻の記載なし** -> date_only=True
  「3月14日（土） 14:00 開会式」                  start_at 2026-03-14T14:00+09:00
  「3月16日（月） 11:30 表彰式・閉会式」           end_at 2026-03-16T11:30+09:00
  「参加費 無料 交通費・宿泊費は大学が負担」        cost 0、kind=free
  「東京科学大学、九州工業大学、APU の三大学で」    eligibility は三大学の学生

### https://www.xsum.jp/gai（GenAI/SUM）

  入力の表記                                     期待する解釈
  「応募締め切り ~~2026年8月21日(金)17時~~         これは**インパクトピッチ登壇者の募集**。
    応募を締め切りました」                         参加の締切ではない -> kind=speaker
  「早割り ¥8,000 (9/30迄)」                      **早割の期限**。kind=early_bird
  「10月7日のイベント終了後」                      日付のみ。**時刻の記載なし**
  「定価 ¥20,000 / ¥7,000 / ¥4,000」「無料」       区分で額が違う -> kind=partially_free、
                                                 cost は null（**0 ではない**）

  参加そのものの申込期限は入力に**書かれていない**ので deadline は null、
  kind=unknown が期待される解釈。
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from ai import availability
from ai.schemas.extraction import CostKind, DeadlineKind, ExtractedOpportunity

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


def _o(**overrides) -> ExtractedOpportunity:
    base = {"title": "t", "type": "event"}
    base.update(overrides)
    return ExtractedOpportunity(**base)


def _avail(item: ExtractedOpportunity, *, now: datetime = NOW):
    return availability.from_dates(
        opportunity_type=item.type,
        deadline=item.deadline,
        end_at=item.end_at,
        now=now,
        deadline_kind=item.deadline_kind,
        deadline_is_date_only=item.deadline_is_date_only,
    )


# --- 実際に観測された誤り ---------------------------------------------------


def test_early_bird_deadline_does_not_become_the_application_deadline():
    """**実測の誤り。** low 設定が早割の 9/30 を締切として拾った。

    そのまま通すと、登壇者募集が終了したイベントが
    「9/30 まで受付中」に見える。
    """
    item = _o(
        deadline=datetime(2026, 9, 30, 23, 59, 59, tzinfo=JST),
        deadline_kind=DeadlineKind.EARLY_BIRD,
    )
    status, reason = _avail(item, now=datetime(2026, 10, 5, tzinfo=UTC))

    assert status is availability.Availability.UNKNOWN
    assert "早割" in reason


def test_speaker_cfp_closing_does_not_close_general_participation():
    """**同じページで「登壇者募集は終了、一般参加は受付中」が起きる。**

    ページ全体を一括で終了と判断しない。
    """
    item = _o(
        deadline=datetime(2026, 8, 21, 17, 0, tzinfo=JST),
        deadline_kind=DeadlineKind.SPEAKER,
    )
    status, reason = _avail(item)

    assert status is availability.Availability.UNKNOWN
    assert "登壇者募集" in reason


def test_unidentified_deadline_does_not_close_the_opportunity():
    """**何に対する締切か特定できないものを、閉じる根拠にしない。**

    理由は残す。なぜ受付中扱いなのかが後から読めるように。
    """
    item = _o(
        deadline=datetime(2026, 1, 1, tzinfo=JST),
        deadline_kind=DeadlineKind.UNKNOWN,
    )
    status, reason = _avail(item)

    assert status is availability.Availability.UNKNOWN
    assert "特定できません" in reason


@pytest.mark.parametrize("kind", [DeadlineKind.APPLICATION, DeadlineKind.REGISTRATION])
def test_the_real_application_deadline_still_closes(kind):
    """**閉じるべきものは閉じる。** ここを緩めると #68 が効かなくなる。"""
    item = _o(deadline=datetime(2026, 2, 9, 23, 59, tzinfo=JST), deadline_kind=kind)
    status, reason = _avail(item)

    assert status is availability.Availability.CLOSED
    assert reason == "申込の締切が過ぎています"


def test_rows_without_a_kind_keep_the_old_meaning():
    """区分を持たなかった頃の行。**後から意味を変えない。**

    当時の prompt は deadline を「申込締切」として書かせていた。
    """
    status, _ = availability.from_dates(
        opportunity_type="event",
        deadline=datetime(2026, 2, 9, tzinfo=UTC),
        end_at=None,
        now=NOW,
        deadline_kind=None,
    )
    assert status is availability.Availability.CLOSED


# --- 架空の時刻 --------------------------------------------------------------


def test_a_time_the_model_invented_is_dropped():
    """**実測の誤り。** 入力に時刻が無いのに 09:00 / 17:00 を入れた。

    日付だけと申告しているなら、時刻はこちらで落とす。
    **出典にある時刻と、こちらの正規化を混ぜない。**
    """
    item = _o(
        start_at=datetime(2026, 10, 7, 9, 0, tzinfo=JST),
        start_at_is_date_only=True,
        end_at=datetime(2026, 10, 7, 17, 0, tzinfo=JST),
        end_at_is_date_only=True,
    )
    assert item.start_at.hour == 0
    assert item.end_at.hour == 0


def test_a_time_written_in_the_source_is_kept():
    """**出典に時刻があるものは残す。** 一律に落とさない。"""
    item = _o(start_at=datetime(2026, 3, 14, 14, 0, tzinfo=JST), start_at_is_date_only=False)
    assert item.start_at.hour == 14


def test_a_date_only_deadline_does_not_close_on_the_day_itself():
    """**日付しか書かれていない締切を、当日中に打ち切らない。**

    00:00 はこちらの正規化であって、出典にあった時刻ではない。
    """
    item = _o(
        deadline=datetime(2026, 9, 21, tzinfo=UTC),
        deadline_kind=DeadlineKind.APPLICATION,
        deadline_is_date_only=True,
    )
    status, _ = _avail(item, now=datetime(2026, 9, 21, 23, 0, tzinfo=UTC))
    assert status is availability.Availability.UNKNOWN


def test_a_date_only_deadline_closes_the_next_day():
    item = _o(
        deadline=datetime(2026, 9, 21, tzinfo=UTC),
        deadline_kind=DeadlineKind.APPLICATION,
        deadline_is_date_only=True,
    )
    status, _ = _avail(item, now=datetime(2026, 9, 22, 0, 30, tzinfo=UTC))
    assert status is availability.Availability.CLOSED


def test_a_dated_and_timed_deadline_closes_at_that_time():
    """時刻まで書かれているものは、その時刻で閉じる。"""
    item = _o(
        deadline=datetime(2026, 9, 21, 17, 0, tzinfo=JST),
        deadline_kind=DeadlineKind.APPLICATION,
    )
    status, _ = _avail(item, now=datetime(2026, 9, 21, 9, 0, tzinfo=UTC))  # 18:00 JST
    assert status is availability.Availability.CLOSED


# --- 料金区分 ----------------------------------------------------------------


def test_partially_free_does_not_become_free():
    """**実測の誤り。** 定価 ¥20,000 のイベントに cost=0 が付いた。

    無料の区分が並んでいたため。区分で額が違うなら金額は持たない。
    """
    item = _o(cost=0, cost_kind=CostKind.PARTIALLY_FREE)
    assert item.cost is None
    assert item.cost_kind is CostKind.PARTIALLY_FREE


def test_unknown_cost_is_not_free():
    """記載が無いことと、無料であることは違う。"""
    item = _o(cost=0, cost_kind=CostKind.UNKNOWN)
    assert item.cost is None


def test_explicit_free_is_kept():
    """**無料と明記されているものは 0 のまま。** 一律に潰さない。"""
    item = _o(cost=0, cost_kind=CostKind.FREE)
    assert item.cost == 0


def test_a_paid_amount_is_kept():
    item = _o(cost=8000, cost_kind=CostKind.PAID)
    assert item.cost == 8000


# --- 保存された実際の出力をそのまま通す -------------------------------------
#
# A の run と予備実験で実際に返ってきた JSON。**作り変えない。**

OBSERVED_LOW_XSUM = {
    "title": "GenAI/SUM",
    "type": "event",
    "url": "https://www.xsum.jp/gai",
    "start_at": "2026-10-07T09:00:00+09:00",
    "end_at": "2026-10-07T17:00:00+09:00",
    "deadline": "2026-09-30T23:59:59+09:00",
    "location": "九段会館テラス",
    "format": "offline",
    "cost": 0,
}


def test_the_observed_bad_output_does_not_reach_a_recommendation_as_open_and_free():
    """**この 1 件がそのまま推薦に乗ると、製品の約束が崩れる。**

    「無料で 9/30 まで受付中」と出るが、実際は定価 ¥20,000 で、
    9/30 は早割の期限、参加の申込期限は入力に書かれていない。

    区分を正しく付ければ、金額は落ち、受付中とも言わなくなる。
    """
    item = ExtractedOpportunity.model_validate(
        {
            **OBSERVED_LOW_XSUM,
            "deadline_kind": DeadlineKind.EARLY_BIRD,
            "cost_kind": CostKind.PARTIALLY_FREE,
            "start_at_is_date_only": True,
            "end_at_is_date_only": True,
            "deadline_is_date_only": False,
        }
    )

    assert item.cost is None, "有料イベントが無料として残った"
    assert item.start_at.hour == 0, "入力に無い開始時刻が残った"
    assert item.end_at.hour == 0, "入力に無い終了時刻が残った"

    status, reason = _avail(item, now=datetime(2026, 10, 5, tzinfo=UTC))
    assert status is availability.Availability.UNKNOWN
    assert reason and "早割" in reason
    # **推薦から外しもしない。** 参加できないと確認したわけではない。
    assert availability.is_actionable(status) is True


def test_the_isct_case_keeps_the_information_it_should():
    """締切が明記されたページ。**落とさない。**"""
    item = ExtractedOpportunity.model_validate(
        {
            "title": "三大学合同ハッカソン 2026",
            "type": "hackathon",
            "start_at": "2026-03-14T14:00:00+09:00",
            "end_at": "2026-03-16T11:30:00+09:00",
            "deadline": "2026-02-09T00:00:00+09:00",
            "deadline_kind": DeadlineKind.APPLICATION,
            "deadline_is_date_only": True,
            "cost": 0,
            "cost_kind": CostKind.FREE,
            "eligibility": "東京科学大学、九州工業大学、立命館アジア太平洋大学の学生",
        }
    )

    assert item.cost == 0
    assert item.start_at.hour == 14  # 出典にある時刻
    assert item.eligibility
    status, _ = _avail(item)
    assert status is availability.Availability.CLOSED


# --- 区分が誤っていれば防げない ---------------------------------------------
#
# **Schema の検査は「区分が正しく付いた場合に整合性を保つ」だけ。**
# ここを取り違えると、防げていないものを防げたと読んでしまう。


def test_schema_cannot_stop_a_fabricated_time_when_the_flag_is_wrong():
    """`is_date_only=false` と申告されれば、時刻はそのまま残る。

    **区分もモデルの出力なので、Schema では防げない。**
    """
    item = _o(start_at=datetime(2026, 10, 7, 9, 0, tzinfo=JST), start_at_is_date_only=False)
    assert item.start_at.hour == 9  # 防げていない


def test_schema_cannot_stop_a_wrong_free_marking():
    """`cost_kind=free` と誤って申告されれば、0 円は残る。"""
    item = _o(cost=0, cost_kind=CostKind.FREE)
    assert item.cost == 0  # 防げていない


def test_source_check_catches_the_fabricated_time():
    """入力と突き合わせれば気づける。**Schema とは別の手当て。**"""
    from ai import evidence

    page = "開催日 10月7日（水）　会場 九段会館テラス"
    item = _o(start_at=datetime(2026, 10, 7, 9, 0, tzinfo=JST), start_at_is_date_only=False)

    assert "start_at の時刻 09:00 が入力に見つかりません" in evidence.check(item, page)


def test_unfounded_deadline_kind_is_downgraded_not_dropped():
    """根拠が入力に無い区分は `unknown` へ落とす。**候補は落とさない。**"""
    from ai import evidence

    page = "早割り ¥8,000 (9/30迄)"
    item = _o(
        deadline=datetime(2026, 9, 30, tzinfo=JST),
        deadline_kind=DeadlineKind.APPLICATION,
        deadline_quote="応募締切 9月30日",  # 入力に無い
    )
    grounded = evidence.ground_deadline_kind(item, page)

    assert grounded.deadline_kind is DeadlineKind.UNKNOWN
    status, _ = _avail(grounded, now=datetime(2026, 10, 5, tzinfo=UTC))
    assert availability.is_actionable(status) is True


def test_a_quote_that_is_in_the_source_is_kept():
    """**全角・半角の違いで「書かれていない」と誤判定しない。**"""
    from ai import evidence

    page = "応募締め切り：２０２６年８月２１日"
    item = _o(
        deadline=datetime(2026, 8, 21, tzinfo=JST),
        deadline_kind=DeadlineKind.SPEAKER,
        deadline_quote="応募締め切り：2026年8月21日",
    )
    assert evidence.ground_deadline_kind(item, page).deadline_kind is DeadlineKind.SPEAKER


# --- 旧データを確認済みと同じ確かさで扱わない -------------------------------


def test_legacy_rows_say_that_the_kind_is_unconfirmed():
    """旧い行も閉じるが、**確かさが違うことを文面で示す。**

    旧 prompt が申込締切を指示していたことは、保存された値が申込締切で
    ある保証にはならない。実際に早割の取り違えが観測されている。
    """
    _, reason = availability.from_dates(
        opportunity_type="event",
        deadline=datetime(2026, 2, 9, tzinfo=UTC),
        end_at=None,
        now=NOW,
        deadline_kind=None,
    )
    assert "種類は未確認" in reason


def test_confirmed_rows_do_not_carry_the_unconfirmed_note():
    _, reason = availability.from_dates(
        opportunity_type="event",
        deadline=datetime(2026, 2, 9, tzinfo=UTC),
        end_at=None,
        now=NOW,
        deadline_kind=DeadlineKind.APPLICATION,
    )
    assert "未確認" not in reason


# --- 日付の存在と、期限の意味を分ける --------------------------------------
#
# **引用が原文にあることは、分類の根拠にならない。**
# 「9月30日まで」は原文にあっても、参加申込の期限か早割の期限かを示さない。

# 実測で使った入力の一部（https://www.xsum.jp/gai）。
XSUM_PAGE = (
    "早割り\n:   ¥8,000  \n     (9/30迄)\n"
    "1. 定価2万円のチケットの早割価格での提供となります。（9月30日まで）\n"
    "5. 10月7日のイベント終了後、会場内で開催するアフターパーティに参加できます。\n"
    "応募締め切り\n:   ~~2026年8月21日(金)17時（日本時間）~~ 応募を締め切りました\n"
)

# 実測でモデルが返した出力（1 回目）。**作り変えていない。**
OBSERVED_MISCLASSIFICATION = {
    "title": "GenAI/SUM",
    "type": "event",
    "deadline": "2026-09-30T23:59:59+09:00",
    "deadline_kind": "registration",
    "deadline_quote": "9月30日まで",
    "deadline_is_date_only": True,
    "cost": None,
    "cost_kind": "partially_free",
}


def _grounded(payload: dict, page: str = XSUM_PAGE) -> ExtractedOpportunity:
    from ai import evidence

    return evidence.ground_deadline_kind(ExtractedOpportunity.model_validate(payload), page)


def test_a_quote_without_context_cannot_justify_a_gating_kind():
    """**実測の出力。** 日付は原文にあるが、何の期限かを示していない。"""
    item = _grounded(OBSERVED_MISCLASSIFICATION)
    assert item.deadline_kind is DeadlineKind.UNKNOWN


def test_context_from_another_kind_is_rejected():
    """周辺文が早割の話なら、参加申込の期限とは認めない。"""
    item = _grounded(
        {
            **OBSERVED_MISCLASSIFICATION,
            "deadline_context": "定価2万円のチケットの早割価格での提供となります。（9月30日まで）",
        }
    )
    assert item.deadline_kind is DeadlineKind.UNKNOWN


def test_a_context_the_model_invented_is_rejected():
    """**原文に無い周辺文は認めない。** 要約も言い換えも一致しない。"""
    item = _grounded(
        {
            **OBSERVED_MISCLASSIFICATION,
            "deadline_context": "参加申込の締切は9月30日です",  # 原文に無い
        }
    )
    assert item.deadline_kind is DeadlineKind.UNKNOWN


def test_a_supported_gating_kind_survives():
    """**根拠が示されていれば通す。** 一律に疑わない。"""
    page = "応募締切・募集人数\n\n2026年2月9日（月）、各大学20名程度"
    item = _grounded(
        {
            "title": "合同ハッカソン",
            "type": "hackathon",
            "deadline": "2026-02-09T00:00:00+09:00",
            "deadline_is_date_only": True,
            "deadline_kind": "application",
            "deadline_quote": "2026年2月9日（月）",
            "deadline_context": "応募締切・募集人数\n\n2026年2月9日（月）、各大学20名程度",
        },
        page,
    )
    assert item.deadline_kind is DeadlineKind.APPLICATION


def test_the_same_date_is_not_tied_to_unrelated_text():
    """**同じ日付が複数箇所にあっても、周辺文で決める。**

    日付の一致だけで結びつけると、どちらの意味にも取れてしまう。
    """
    page = "早割価格の申込は9月30日までです。\nアーカイブ視聴の公開は9月30日から始まります。\n"
    payload = {
        "title": "t",
        "type": "event",
        "deadline": "2026-09-30T00:00:00+09:00",
        "deadline_is_date_only": True,
        "deadline_kind": "registration",
        "deadline_quote": "9月30日",
    }
    # 早割の文を根拠にした場合 -> 食い違いとして退ける
    assert (
        _grounded(
            {**payload, "deadline_context": "早割価格の申込は9月30日までです。"}, page
        ).deadline_kind
        is DeadlineKind.UNKNOWN
    )
    # 参加と無関係な文を根拠にした場合 -> 支える語が無いので退ける
    assert (
        _grounded(
            {**payload, "deadline_context": "アーカイブ視聴の公開は9月30日から始まります。"},
            page,
        ).deadline_kind
        is DeadlineKind.UNKNOWN
    )


# --- 日付が進んだときの誤除外 -----------------------------------------------
#
# **9/30 や特定のサイトに反応するルールにしない。** 区分と根拠だけで決める。

AFTER_EARLY_BIRD = datetime(2026, 10, 3, tzinfo=UTC)


def test_passing_an_early_bird_date_does_not_close_general_participation():
    """**これが今回いちばん避けたい誤り。**

    早割の期限を過ぎただけで、参加できるイベントを候補から外さない。
    """
    item = _grounded(OBSERVED_MISCLASSIFICATION)
    status, reason = _avail(item, now=AFTER_EARLY_BIRD)

    assert status is not availability.Availability.CLOSED
    assert availability.is_actionable(status) is True
    assert reason  # 理由は残す


def test_a_closed_speaker_call_does_not_close_general_participation():
    item = _o(
        deadline=datetime(2026, 8, 21, 17, 0, tzinfo=JST),
        deadline_kind=DeadlineKind.SPEAKER,
    )
    status, _ = _avail(item, now=AFTER_EARLY_BIRD)
    assert status is not availability.Availability.CLOSED


def test_a_clear_participation_deadline_closes_after_it_passes():
    """**閉じるべきものは閉じる。** 緩めすぎない。"""
    page = "参加申込の締切は2026年10月1日です。"
    item = _grounded(
        {
            "title": "t",
            "type": "event",
            "deadline": "2026-10-01T00:00:00+09:00",
            "deadline_is_date_only": True,
            "deadline_kind": "registration",
            "deadline_quote": "2026年10月1日",
            "deadline_context": "参加申込の締切は2026年10月1日です。",
        },
        page,
    )
    status, reason = _avail(item, now=AFTER_EARLY_BIRD)

    assert status is availability.Availability.CLOSED
    assert reason == "申込の締切が過ぎています"


def test_a_finished_event_closes_on_its_own_grounds():
    """**締切とは別の根拠。** 開催が終わっていれば閉じる。"""
    item = _o(
        type="event",
        end_at=datetime(2026, 10, 1, 18, 0, tzinfo=JST),
        deadline=None,
    )
    status, reason = _avail(item, now=AFTER_EARLY_BIRD)

    assert status is availability.Availability.CLOSED
    assert reason == "開催が終了しています"


def test_an_unsupported_kind_keeps_the_candidate_with_a_reason():
    """**候補を消さない。** 確認できていないと示すだけ。"""
    item = _grounded(OBSERVED_MISCLASSIFICATION)
    status, reason = _avail(item, now=AFTER_EARLY_BIRD)

    assert availability.is_actionable(status) is True
    assert "特定できません" in reason


# --- 登壇者募集は、推薦する行動によって扱いが変わる ------------------------
#
# **「登壇締切は何も閉じない」とは一般化できない。**


def test_a_speaker_deadline_closes_a_speaking_opportunity():
    """登壇機会そのものを薦めるなら、その締切が行動を閉ざす。"""
    from ai import evidence

    item = _o(
        title="GenAI/SUM インパクトピッチ 登壇者募集",
        deadline=datetime(2026, 8, 21, 17, 0, tzinfo=JST),
        deadline_kind=DeadlineKind.SPEAKER,
    )
    status, reason = availability.from_dates(
        opportunity_type=item.type,
        deadline=item.deadline,
        end_at=None,
        now=NOW,
        deadline_kind=item.deadline_kind,
        speaker_is_the_opportunity=evidence.is_a_call_for_speakers(item.title),
    )
    assert status is availability.Availability.CLOSED
    assert "登壇者募集の締切" in reason


def test_the_same_deadline_does_not_close_general_participation():
    """同じ締切でも、一般参加の機会なら閉じない。"""
    from ai import evidence

    item = _o(
        title="GenAI/SUM",  # イベントそのもの
        deadline=datetime(2026, 8, 21, 17, 0, tzinfo=JST),
        deadline_kind=DeadlineKind.SPEAKER,
    )
    status, _ = availability.from_dates(
        opportunity_type=item.type,
        deadline=item.deadline,
        end_at=None,
        now=NOW,
        deadline_kind=item.deadline_kind,
        speaker_is_the_opportunity=evidence.is_a_call_for_speakers(item.title),
    )
    assert status is not availability.Availability.CLOSED


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("AI Summit 登壇者募集", True),
        ("Call for Speakers - Tech Conf 2026", True),
        ("CFP: PyCon JP 2026", True),
        ("GenAI/SUM", False),
        ("AI Agent Hackathon 2026", False),
        # イベント紹介の中で登壇者募集にも触れているだけのページは拾わない。
        # そこは一般参加の機会として扱うほうが実態に近い。
        ("GenAI/SUM 開催のお知らせ", False),
    ],
)
def test_detecting_a_call_for_speakers(title, expected):
    from ai import evidence

    assert evidence.is_a_call_for_speakers(title) is expected


def test_a_page_with_both_can_only_hold_one():
    """**限界。** 一般参加と登壇募集を両方扱うページは、片方しか表せない。

    `deadline` が 1 つしか無く、2 つの締切を持てない。
    ここでは一般参加の機会として扱われ、登壇締切は閉じる根拠にならない。
    """
    from ai import evidence

    # 「登壇者募集」を含まないタイトル -> 一般参加として扱われる
    assert evidence.is_a_call_for_speakers("GenAI/SUM（登壇者も募集中）") is False


# --- 意味は一行上の見出しにあることが多い ----------------------------------
#
# **実測で踏んだ。** モデルが写した周辺文の中に語が無く、正しい分類を
# 退けてしまった。原文の前後まで見て判断する。

ISCT_PAGE = (
    "### 応募締切・募集人数\n\n"
    "2026年2月9日（月）、各大学20名程度  \n"
    " 先着順ですので定員に達し次第、募集を締め切らせていただく場合がございます。\n"
)


def test_a_heading_above_the_quote_counts_as_evidence():
    """周辺文そのものに語が無くても、**原文の直前の見出し**で支えられる。

    実測でモデルが写したのは「2026年2月9日（月）、各大学20名程度」で、
    応募締切だと分かるのは直前の見出しだった。
    """
    item = _grounded(
        {
            "title": "合同ハッカソン",
            "type": "hackathon",
            "deadline": "2026-02-09T00:00:00+09:00",
            "deadline_is_date_only": True,
            "deadline_kind": "application",
            "deadline_quote": "2026年2月9日（月）",
            "deadline_context": "2026年2月9日（月）、各大学20名程度",
        },
        ISCT_PAGE,
    )
    assert item.deadline_kind is DeadlineKind.APPLICATION

    status, _ = _avail(item, now=AFTER_EARLY_BIRD)
    assert status is availability.Availability.CLOSED


def test_a_conflicting_word_nearby_still_wins():
    """**食い違いの検査が先。** 近くに早割があれば、申込締切とは認めない。

    広く見るぶん無関係な語を拾いうるが、拾った側の誤りは `unknown` に
    落ちて閉じないので、**安全な方向に外れる。**
    """
    page = "早割価格でのお申込みはこちら\n\n2026年2月9日（月）まで\n"
    item = _grounded(
        {
            "title": "t",
            "type": "event",
            "deadline": "2026-02-09T00:00:00+09:00",
            "deadline_is_date_only": True,
            "deadline_kind": "application",
            "deadline_quote": "2026年2月9日（月）",
            "deadline_context": "2026年2月9日（月）まで",
        },
        page,
    )
    assert item.deadline_kind is DeadlineKind.UNKNOWN


def test_the_window_does_not_reach_across_a_whole_page():
    """**窓は限られている。** 遠くにある語は根拠にしない。"""
    from ai import evidence

    page = "応募締切はこちら\n" + "あ" * 400 + "\n2026年2月9日（月）\n"
    supported, why = evidence.context_supports_kind(
        "2026年2月9日（月）", DeadlineKind.APPLICATION, page
    )
    assert supported is False
    assert why and "示す語がありません" in why


# --- まだ過ぎていない締切を「過ぎている」と書かない --------------------------

EARLY_BIRD_DATE = datetime(2026, 9, 30, tzinfo=JST)
BEFORE_EARLY_BIRD = datetime(2026, 9, 21, 12, tzinfo=UTC)


def _early_bird_reason(now: datetime) -> str | None:
    _, reason = availability.from_dates(
        opportunity_type="event",
        deadline=EARLY_BIRD_DATE,
        end_at=None,
        now=now,
        deadline_kind=DeadlineKind.EARLY_BIRD,
        deadline_is_date_only=True,
    )
    return reason


def test_a_future_early_bird_date_is_not_described_as_passed():
    """**9/30 が来ていないのに「過ぎている」と書かない。**"""
    reason = _early_bird_reason(BEFORE_EARLY_BIRD)
    assert "過ぎて" not in reason
    assert "早割" in reason


def test_the_wording_differs_before_and_after():
    """前後で説明を分ける。**同じ文面を使い回さない。**"""
    assert _early_bird_reason(BEFORE_EARLY_BIRD) != _early_bird_reason(AFTER_EARLY_BIRD)
    assert "過ぎて" in _early_bird_reason(AFTER_EARLY_BIRD)


def test_a_participation_deadline_not_yet_passed_needs_no_excuse():
    """**参加の締切そのものなら、説明は要らない。** まだ過ぎていないだけ。"""
    _, reason = availability.from_dates(
        opportunity_type="event",
        deadline=datetime(2026, 12, 1, tzinfo=JST),
        end_at=None,
        now=BEFORE_EARLY_BIRD,
        deadline_kind=DeadlineKind.APPLICATION,
    )
    assert reason is None


# --- 窓が別の募集の見出しを拾わないか ---------------------------------------
#
# 窓を広げたぶん、近くの別の募集を拾いうる。**拾った側の誤りは `unknown` に
# 落ちて閉じない**ので、安全な方向に外れる。そこを確かめる。


def test_a_nearby_early_bird_heading_blocks_a_wrong_application_claim():
    """近くに早割の見出しがあれば、申込締切とは認めない。"""
    page = "### 早割チケットのご案内\n\n2026年10月1日まで\n\n### CONCEPT\n"
    item = _grounded(
        {
            "title": "t",
            "type": "event",
            "deadline": "2026-10-01T00:00:00+09:00",
            "deadline_is_date_only": True,
            "deadline_kind": "application",
            "deadline_quote": "2026年10月1日",
            "deadline_context": "2026年10月1日まで",
        },
        page,
    )
    assert item.deadline_kind is DeadlineKind.UNKNOWN


def test_two_adjacent_calls_make_the_claim_unprovable():
    """**登壇募集と一般参加が隣り合うページは、区分を確かめられない。**

    窓が両方を含むため、食い違いとして退ける。閉じないので安全側だが、
    **正しい締切でも通らない。** これは取りこぼしとして残る限界。
    """
    page = "### 登壇者募集\n応募締切 2026年8月21日\n\n### 一般参加\n申込締切 2026年10月1日\n"
    item = _grounded(
        {
            "title": "t",
            "type": "event",
            "deadline": "2026-10-01T00:00:00+09:00",
            "deadline_is_date_only": True,
            "deadline_kind": "registration",
            "deadline_quote": "2026年10月1日",
            "deadline_context": "申込締切 2026年10月1日",
        },
        page,
    )
    assert item.deadline_kind is DeadlineKind.UNKNOWN

    # **閉じない。** 誤って除外するより、確認できていないと示す。
    status, _ = _avail(item, now=AFTER_EARLY_BIRD)
    assert availability.is_actionable(status) is True


def test_a_clean_page_still_validates():
    """**一律に疑わない。** 紛らわしい語が無ければ通す。"""
    page = "### お申し込み\n\n申込締切 2026年10月1日\n\n### アクセス\n東京都千代田区\n"
    item = _grounded(
        {
            "title": "t",
            "type": "event",
            "deadline": "2026-10-01T00:00:00+09:00",
            "deadline_is_date_only": True,
            "deadline_kind": "registration",
            "deadline_quote": "2026年10月1日",
            "deadline_context": "申込締切 2026年10月1日",
        },
        page,
    )
    assert item.deadline_kind is DeadlineKind.REGISTRATION


# --- 取得元のタイトルを捨てない ---------------------------------------------


def test_the_source_title_is_given_to_the_model():
    """**実測で Schema 不通過の原因になった。**

    本文の抜粋に催しの名称が見出しとして無く、「GenAI/SUM事務局」という
    組織名の一部としてしか現れない入力があった。検索結果は title を
    持っていたのに、モデルへ渡していなかった。
    """
    from ai.prompts import extraction as prompt

    user = prompt.build_user(
        "https://www.xsum.jp/gai",
        "定価\n:   ¥20,000\n",
        source_title="GenAI/SUM 2026 (生成AIサミット)",
    )
    assert "GenAI/SUM 2026" in user
    # **これも外部から取得したデータ。** 境界の中に入れる。
    assert user.index("<page_content>") < user.index("GenAI/SUM 2026")


def test_the_title_line_is_omitted_when_there_is_none():
    from ai.prompts import extraction as prompt

    user = prompt.build_user("https://e.jp/a", "本文")
    assert "取得元のページタイトル" not in user


SUBMISSION_PAGE = "### 応募方法\n\n提出締切: 2026 年 2 月 15 日（日）\n"


def _submission(opportunity_type: str) -> ExtractedOpportunity:
    return _grounded(
        {
            "title": "Agentic AI Hackathon",
            "type": opportunity_type,
            "deadline": "2026-02-15T00:00:00+09:00",
            "deadline_is_date_only": True,
            "deadline_kind": "submission",
            "deadline_quote": "2026 年 2 月 15 日（日）",
            "deadline_context": "提出締切: 2026 年 2 月 15 日（日）",
        },
        SUBMISSION_PAGE,
    )


def test_a_submission_deadline_is_not_an_application_deadline():
    """**「提出締切」は「参加申込の締切」ではない。**

    申込だけ先に締め切り、提出は後、という形がある。逆に、提出さえ
    間に合えば飛び入りを認める催しもある。同じものとして扱わない。
    """
    item = _submission("hackathon")
    assert item.deadline_kind is DeadlineKind.SUBMISSION


def test_a_past_submission_deadline_closes_a_hackathon():
    """**提出しなければ参加にならない種類**では、行動を閉ざす。"""
    status, reason = _avail(_submission("hackathon"))
    assert status is availability.Availability.CLOSED
    assert "提出締切" in reason


def test_a_past_submission_deadline_does_not_close_a_community():
    """**一般化しない。** 提出が参加の条件でない種類では閉じない。"""
    status, reason = _avail(_submission("community"))
    assert status is not availability.Availability.CLOSED
    assert "参加の締切ではありません" in reason


def test_a_claimed_application_kind_on_a_submission_context_is_rejected():
    """周辺文が提出の話なら、申込締切とは認めない。"""
    item = _grounded(
        {
            "title": "Agentic AI Hackathon",
            "type": "hackathon",
            "deadline": "2026-02-15T00:00:00+09:00",
            "deadline_is_date_only": True,
            "deadline_kind": "application",
            "deadline_quote": "2026 年 2 月 15 日（日）",
            "deadline_context": "提出締切: 2026 年 2 月 15 日（日）",
        },
        SUBMISSION_PAGE,
    )
    assert item.deadline_kind is DeadlineKind.UNKNOWN


def test_the_word_deadline_alone_is_not_enough():
    """**「締切」単体は語彙に入れない。**

    早割にも登壇募集にも付く。入れると支持の検査がほぼ素通りになる。
    """
    from ai import evidence

    supported, _ = evidence.context_supports_kind(
        "締切 2026年10月1日", DeadlineKind.APPLICATION, "締切 2026年10月1日"
    )
    assert supported is False


def test_a_finished_event_closes_even_when_another_deadline_passed():
    """**開催終了を、締切の判定で打ち切らない。**

    実測で踏んだ。参加の締切ではない締切（区分 unknown）が過ぎていると、
    そこで返してしまい、**終わったハッカソンが「受付中」のまま残った。**
    """
    status, reason = availability.from_dates(
        opportunity_type="hackathon",
        deadline=datetime(2026, 2, 14, 15, tzinfo=UTC),
        end_at=datetime(2026, 2, 14, 15, tzinfo=UTC),
        now=NOW,
        deadline_kind=DeadlineKind.UNKNOWN,
    )
    assert status is availability.Availability.CLOSED
    assert reason == "開催が終了しています"


def test_a_finished_event_closes_even_with_an_early_bird_deadline():
    status, reason = availability.from_dates(
        opportunity_type="competition",
        deadline=datetime(2026, 9, 30, tzinfo=UTC),
        end_at=datetime(2026, 8, 1, tzinfo=UTC),
        now=AFTER_EARLY_BIRD,
        deadline_kind=DeadlineKind.EARLY_BIRD,
    )
    assert status is availability.Availability.CLOSED
    assert reason == "開催が終了しています"


def test_a_community_that_started_long_ago_is_not_closed():
    """**終わらない種類は閉じない。** community / job は開始済みでも参加できる。"""
    status, _ = availability.from_dates(
        opportunity_type="community",
        deadline=None,
        end_at=datetime(2024, 1, 1, tzinfo=UTC),
        now=NOW,
    )
    assert status is not availability.Availability.CLOSED
