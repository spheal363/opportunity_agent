import { useEffect, useState } from 'react';

import { addToCalendar, ApiRequestError, checkCalendarAvailability } from '../../api';
import { useAppState } from '../../state/context';
import type { CalendarConflict, OpportunityDetail } from '../../types';
import { formatDateTime } from '../../utils/date';
import { EYEBROW, PRIMARY, TEXT_BUTTON } from './styles';

/**
 * 終了時刻が取れていない機会は、Backend がこの長さで予定に入れる。
 * backend/services/calendar_service.py の PLACEHOLDER_DURATION と合わせる（docs/api.md）。
 */
const PLACEHOLDER_HOURS = 1;
const MAX_CONFLICTS_SHOWN = 3;

export type CalendarOutcome = 'added' | 'already_added' | 'skipped';

type Availability =
  | { kind: 'loading' }
  | { kind: 'free' }
  | { kind: 'busy'; conflicts: CalendarConflict[] }
  | { kind: 'not_connected' }
  // 確認に失敗した。追加は試せる。
  | { kind: 'unknown' };

type Props = {
  item: OpportunityDetail;
  /** 次の一歩へ進めない理由。あれば、どのボタンを押してもカレンダーには触らず、これを知らせる。 */
  blockedReason: string | null;
  onProceed: (outcome: CalendarOutcome) => void;
};

/**
 * 参加準備の最後に、Google カレンダーへ入れる内容を見せてから追加する。
 * 空き確認は読み取りだけなので自動で行い、追加はボタンを押したときだけ行う（押すことが承認）。
 */
export function CalendarPanel({ item, blockedReason, onProceed }: Props) {
  const { showToast } = useAppState();
  const hasStart = Boolean(item.start_at);
  const [availability, setAvailability] = useState<Availability>({ kind: 'loading' });
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  useEffect(() => {
    // 開催日時が無い機会は Backend も確認しない（推測で埋めない）。
    if (!hasStart) return;
    let cancelled = false;
    checkCalendarAvailability(item.opportunity_id)
      .then((res) => {
        if (cancelled) return;
        setAvailability(
          res.available ? { kind: 'free' } : { kind: 'busy', conflicts: res.conflicts },
        );
      })
      .catch((err) => {
        if (cancelled) return;
        setAvailability(isNotConnected(err) ? { kind: 'not_connected' } : { kind: 'unknown' });
      });
    return () => {
      cancelled = true;
    };
  }, [item.opportunity_id, hasStart]);

  const canAdd = hasStart && availability.kind !== 'not_connected';

  const proceed = async (withCalendar: boolean) => {
    if (blockedReason) {
      showToast(blockedReason);
      return;
    }
    if (!withCalendar) {
      onProceed('skipped');
      return;
    }
    setAdding(true);
    setAddError(null);
    try {
      const res = await addToCalendar(item.opportunity_id);
      onProceed(res.status === 'already_exists' ? 'already_added' : 'added');
    } catch (err) {
      if (isNotConnected(err)) setAvailability({ kind: 'not_connected' });
      setAddError(addErrorMessage(err));
    } finally {
      setAdding(false);
    }
  };

  return (
    <>
      <section className="bg-[#edf0e7] rounded-[7px] p-[18px] mt-[22px] mb-[16px] text-[14px]">
        <span className={EYEBROW}>GOOGLE CALENDAR</span>
        {item.start_at ? (
          <>
            <p className="mt-[8px] mb-[12px]">
              この内容で、あなたの Google カレンダーに予定を入れます。
            </p>
            <dl className="grid grid-cols-[80px_1fr] gap-[8px] m-0">
              <dt className="text-muted">予定名</dt>
              <dd className="m-0">{item.title}</dd>
              <dt className="text-muted">日時</dt>
              <dd className="m-0">
                {rangeLabel(item.start_at, item.end_at)}
                {endIsPlaceholder(item.start_at, item.end_at) ? (
                  <span className="block text-muted text-[13px]">
                    終了時刻は分かっていないため、仮に {PLACEHOLDER_HOURS} 時間で入れます。
                  </span>
                ) : null}
              </dd>
              <dt className="text-muted">場所</dt>
              <dd className="m-0">{item.location ?? '場所未定'}</dd>
              <dt className="text-muted">空き状況</dt>
              <dd className="m-0">
                <AvailabilityLabel availability={availability} />
              </dd>
            </dl>
          </>
        ) : (
          <p className="mt-[8px] mb-0">
            開催日時が分かっていないため、カレンダーには入れられません。
          </p>
        )}
      </section>

      {addError ? <p className="text-[14px] text-[#8d4a37] my-[12px]">{addError}</p> : null}

      {canAdd ? (
        <>
          <button
            type="button"
            onClick={() => void proceed(true)}
            disabled={adding}
            className={`${PRIMARY} w-full`}
          >
            {adding ? 'カレンダーに追加しています…' : 'カレンダーに追加して、次の一歩へ ↗'}
          </button>
          <button
            type="button"
            onClick={() => void proceed(false)}
            disabled={adding}
            className={`${TEXT_BUTTON} block mx-auto mt-[14px]`}
          >
            カレンダーには入れずに、次の一歩へ
          </button>
        </>
      ) : (
        <button type="button" onClick={() => void proceed(false)} className={`${PRIMARY} w-full`}>
          次の一歩に追加する ↗
        </button>
      )}
      <p className="text-[14px] text-muted my-[22px]">
        応募は行いません。実際に参加するときは、公式ページで日時と申込方法をご確認ください。
      </p>
    </>
  );
}

function AvailabilityLabel({ availability }: { availability: Availability }) {
  switch (availability.kind) {
    case 'loading':
      return <>確認しています…</>;
    case 'free':
      return <>この時間帯に、ほかの予定はありません</>;
    case 'not_connected':
      return <>Google カレンダーとの連携が無いか切れているため、確認・追加できません</>;
    case 'unknown':
      return <>確認できませんでした（追加はできます）</>;
    case 'busy': {
      const shown = availability.conflicts.slice(0, MAX_CONFLICTS_SHOWN);
      const rest = availability.conflicts.length - shown.length;
      return (
        <>
          <span className="text-[#8d4a37]">重なる予定があります</span>
          <ul className="list-none p-0 m-0 mt-[4px] text-[13px] text-muted">
            {shown.map((c, i) => (
              <li key={`${c.start_at}-${i}`}>
                {c.title}（{rangeLabel(c.start_at, c.end_at)}）
              </li>
            ))}
            {rest > 0 ? <li>ほか {rest} 件</li> : null}
          </ul>
        </>
      );
    }
  }
}

function isNotConnected(err: unknown): boolean {
  return err instanceof ApiRequestError && err.code === 'CALENDAR_NOT_CONNECTED';
}

function addErrorMessage(err: unknown): string {
  if (isNotConnected(err))
    return 'Google カレンダーとの連携が無いか切れているため、追加できませんでした。';
  if (err instanceof ApiRequestError && err.code === 'SCHEDULE_UNKNOWN') {
    return '開催日時が分かっていないため、カレンダーには入れられません。';
  }
  return 'カレンダーに追加できませんでした。時間をおいてもう一度お試しください。';
}

/** Backend と同じ規則: end_at が無いか start_at 以前なら、仮の長さで入れる。 */
function endIsPlaceholder(start: string, end: string | null | undefined): boolean {
  return !end || new Date(end).getTime() <= new Date(start).getTime();
}

function rangeLabel(start: string, end: string | null | undefined): string {
  const s = new Date(start);
  const e = endIsPlaceholder(start, end)
    ? new Date(s.getTime() + PLACEHOLDER_HOURS * 60 * 60 * 1000)
    : new Date(end as string);
  const endText =
    s.toDateString() === e.toDateString()
      ? new Intl.DateTimeFormat('ja-JP', { timeStyle: 'short' }).format(e)
      : formatDateTime(e.toISOString());
  return `${formatDateTime(start)} 〜 ${endText}`;
}
