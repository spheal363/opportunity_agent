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
