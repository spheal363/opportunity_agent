import { Link, NavLink } from 'react-router-dom';

import { DATA_SOURCE_LABEL } from '../../api';
import { POSE_SLOTS } from '../../utils/poses';
import { useAppState } from '../../state/context';
import { StillPose } from './Pose';
import { OUTLINE_BUTTON, TEXT_BUTTON } from './styles';

export function AppHeader() {
  const { openGoal } = useAppState();
  return (
    <header className="h-[88px] border-b border-line flex items-center px-[44px] gap-[22px] bg-[#fffefa] lte850:h-[72px] lte850:px-[23px] lte620:h-[68px] lte620:px-[18px] lte620:gap-[10px]">
      <Link to="/" className="shrink-0" aria-label="Opportunity トップへ">
        <img
          src="/assets/logo.png"
          alt="Opportunity"
          width={2048}
          height={768}
          className="block w-[200px] h-auto lte620:w-[160px]"
        />
      </Link>
      <span className="ml-auto text-[12px] text-muted tracking-[.04em] border border-line rounded-[5px] px-[10px] py-[4px] lte620:px-[5px] lte620:py-[3px]">
        {DATA_SOURCE_LABEL}
      </span>
      <button
        type="button"
        onClick={openGoal}
        aria-label="目標・興味を編集"
        className="bg-[#e9e1d8] w-[36px] h-[36px] rounded-[50%] border-0 text-[14px] lte620:hidden"
      >
        Y
      </button>
    </header>
  );
}

const NAV_ITEMS = [
  { to: '/app', icon: '⌂', label: 'ホーム', end: true },
  { to: '/app/explore', icon: '⌕', label: '探索のようす', end: false },
  { to: '/app/results', icon: '✧', label: '探索結果', end: false },
  { to: '/app/history', icon: '◷', label: '探索履歴', end: false },
  { to: '/app/saved', icon: '♡', label: '気になる', end: false, count: 'saved' as const },
  { to: '/app/steps', icon: '↗', label: '次の一歩', end: false, count: 'steps' as const },
];

export function Sidebar() {
  const { profile, savedCount, stepCount, openGoal } = useAppState();

  const goal = profile?.goals?.[0] ?? '目標はまだ設定されていません';
  const shortGoal = goal.length > 45 ? `${goal.slice(0, 45)}…` : goal;

  return (
    <aside className="border-r border-line pt-[42px] px-[24px] pb-[30px] flex flex-col min-h-[calc(100vh-88px)] lte1150:px-[14px] lte850:min-h-0 lte850:py-[10px] lte850:px-[20px] lte850:border-r-0 lte850:border-b lte620:px-[12px] lte620:py-[9px]">
      <div className="text-[12px] tracking-[1.8px] text-muted mt-0 mx-[12px] mb-[20px] font-en lte850:hidden">
        YOUR NEXT CHAPTER
      </div>

      <nav
        aria-label="メインメニュー"
        className="grid gap-[9px] lte850:flex lte850:gap-[4px] lte850:overflow-x-auto"
      >
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              `border-0 w-full px-[14px] py-[12px] rounded-[7px] text-left text-[14px] flex items-center gap-[13px] tracking-[.04em] hover:bg-[#eef0e9] lte850:w-auto lte850:flex-1 lte850:justify-center lte850:whitespace-nowrap lte850:text-[13px] lte850:gap-[6px] lte620:text-[12px] lte620:px-[5px] lte620:py-[8px] lte620:gap-[4px] ${
                isActive
                  ? 'bg-[#e9eee6] text-[#3c5747] font-semibold'
                  : 'bg-transparent font-medium'
              }`
            }
          >
            <span className="text-[23px] w-[22px] leading-none lte850:w-[18px] lte620:hidden">
              {item.icon}
            </span>
            {item.label}
            {item.count ? (
              <span className="ml-auto text-[12px] text-muted lte850:ml-0 lte620:text-[11px]">
                {item.count === 'saved' ? savedCount : stepCount}
              </span>
            ) : null}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-line mt-[33px] mx-[10px] pt-[25px] lte850:hidden">
        <span className="text-[12px] tracking-[.02em] font-semibold text-[#6b7c6f] font-en">
          いま向かっていること
        </span>
        <p className="text-[14px] leading-[1.9]">{shortGoal}</p>
        <button type="button" onClick={openGoal} className={TEXT_BUTTON}>
          目標を見直す ↗
        </button>
      </div>

      <div className="mt-auto mx-[10px] mb-0 pt-[36px] lte850:hidden">
        <StillPose
          slot={POSE_SLOTS.sidebar}
          size="w-[120px] h-[120px]"
          className="block mx-auto"
          label="案内役のマスコット"
        />
        <p className="text-[14px] leading-[1.9] tracking-[.045em] font-medium text-center">
          あなたの可能性を、
          <br />
          一緒に見つけよう。
        </p>
        <small className="text-[12px] text-[#8c938d] tracking-[.8px] block text-center">
          YOUR OPPORTUNITY GUIDE
        </small>
      </div>
    </aside>
  );
}

/** 各画面の見出し。文言は画面ごとに渡す。 */
export function PageIntro({
  title,
  copy,
  titleRef,
  editDisabled,
}: {
  title: string;
  copy: string;
  titleRef?: React.Ref<HTMLHeadingElement>;
  editDisabled?: boolean;
}) {
  const { openGoal } = useAppState();
  return (
    <section className="flex items-center justify-between gap-[20px] mb-[27px] lte850:items-start lte620:block lte620:mb-[20px]">
      <div>
        <div className="text-[12px] tracking-[.06em] font-semibold text-[#6b7c6f] font-en lte620:tracking-[.7px]">
          A LITTLE DISCOVERY, A NEW POSSIBILITY
        </div>
        <h1
          ref={titleRef}
          tabIndex={-1}
          className="text-[30px] font-bold tracking-[.04em] leading-[1.5] mt-[10px] mb-[7px] lte850:text-[27px] lte620:text-[29px]"
        >
          {title}
        </h1>
        <p className="text-[16px] text-muted m-0">{copy}</p>
      </div>
      <button
        type="button"
        onClick={openGoal}
        disabled={editDisabled}
        className={`${OUTLINE_BUTTON} lte620:mt-[16px]`}
      >
        目標・興味を編集 <span className="ml-[10px]">↗</span>
      </button>
    </section>
  );
}

export function AppFooter() {
  return (
    <footer className="border-t border-line pt-[15px] flex justify-between gap-[15px] text-[10px] text-[#899085] mt-[28px] lte620:block">
      まだ知らない自分に、出会いにいこう。
      <span className="text-[10px] lte620:block lte620:mt-[7px]">
        外部サイトへの応募は行いません。参加登録はご自身で行ってください。
      </span>
    </footer>
  );
}

export function Toast() {
  const { toastMessage, toastVisible } = useAppState();
  return (
    <div
      role="status"
      aria-live="polite"
      className={`fixed bottom-[25px] left-1/2 bg-[#344e3f] text-white px-[23px] py-[11px] rounded-[7px] text-[14px] transition-all duration-200 pointer-events-none z-10 max-w-[90vw] ${
        toastVisible
          ? 'opacity-100 -translate-x-1/2 translate-y-0'
          : 'opacity-0 -translate-x-1/2 translate-y-[20px]'
      }`}
    >
      {toastMessage}
    </div>
  );
}

/** 「気になる」や結果の下に出る案内。 */
export function BottomNote() {
  return (
    <div className="flex gap-[13px] items-center mt-[26px] mb-[23px]">
      <span className="text-[28px] text-[#b39b71]">✧</span>
      <p className="text-[12px] leading-[1.9] m-0 text-[#65725e]">
        気になるものを教えてください。
        <br />
        <span className="text-[11px] text-[#8a9283]">
          あなたの反応が、次の探索のヒントになります。
        </span>
      </p>
      <span className="h-px bg-line flex-1 ml-[10px]" />
    </div>
  );
}
