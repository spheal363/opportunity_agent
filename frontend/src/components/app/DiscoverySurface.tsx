import { POSE_SLOTS } from '../../utils/poses';
import { StillPose } from './Pose';
import { PRIMARY, TEXT_BUTTON } from './styles';

interface DiscoverySurfaceProps {
  interests: string[];
  /** 探索の入り口。いまのプロフィールのまま Agent を起動する。 */
  onExplore: () => void;
  starting: boolean;
  onEditInterests: () => void;
  onGo: (path: string) => void;
}

export function DiscoverySurface({
  interests,
  onExplore,
  starting,
  onEditInterests,
  onGo,
}: DiscoverySurfaceProps) {
  return (
    <section>
      <div className="bg-[#edf0e6] border border-[#e0e6d9] rounded-[14px] min-h-[284px] flex relative overflow-hidden gte1450:min-h-[300px] lte620:min-h-[345px]">
        <div className="py-[30px] px-[35px] z-[1] flex-1 lte1150:p-[26px] lte620:px-[20px] lte620:py-[22px] lte620:w-full">
          <span className="text-[12px] text-[#526748] bg-[#ffffff80] px-[10px] py-[5px] rounded-[4px]">
            あなたの興味から広がる可能性
          </span>
          <h2 className="text-[24px] font-medium leading-[1.7] mt-[13px] mb-[10px] tracking-[.03em] lte1150:text-[22px] lte850:text-[21px]">
            その興味、こんな一歩に
            <br />
            つながるかもしれません。
          </h2>
          <p className="text-[16px] leading-[1.85] text-[#687363] m-0 mb-[19px] lte620:text-[14px] lte620:max-w-[68%]">
            「AI」と「音楽」。ちょっと意外な組み合わせにも、
            <br className="lte620:hidden" />
            あなたらしい機会が隠れていました。
          </p>
          <button
            type="button"
            onClick={onExplore}
            disabled={starting}
            className={`${PRIMARY} lte620:mt-[8px] lte620:text-[13px] lte620:gap-[16px]`}
          >
            {starting ? '探索をはじめています…' : '新しい機会を探す'} <span>↗</span>
          </button>
        </div>

        <div className="w-[39%] min-w-[240px] flex items-center justify-center relative pt-[12px] px-[18px] pb-[24px] lte1150:min-w-[190px] lte620:absolute lte620:right-[-15px] lte620:bottom-[12px] lte620:w-[43%] lte620:min-w-[145px] lte620:p-0">
          <span className="absolute border border-[#d9dfcf] rounded-[50%] w-[270px] h-[270px] lte1150:w-[205px] lte1150:h-[205px] lte620:w-[140px] lte620:h-[140px]" />
          <span className="absolute border border-[#d9dfcf] rounded-[50%] w-[210px] h-[210px] lte1150:w-[160px] lte1150:h-[160px] lte620:w-[105px] lte620:h-[105px]" />
          <span className="absolute top-[30px] right-[27px] text-[38px] text-[#c49b54] lte620:top-0 lte620:right-[15px] lte620:text-[25px]">
            ✧
          </span>
          <StillPose
            slot={POSE_SLOTS.mascot}
            size="w-[270px] h-[270px] lte620:w-[170px] lte620:h-[170px]"
            className="gentle-welcome relative z-[1]"
            label="旅行かばんを持って手を振るマスコット"
          />
          <span className="absolute bottom-[14px] text-[10px] tracking-[.1em] text-[#7a836f] lte620:hidden">
            小さなきっかけを、一緒に。
          </span>
        </div>
      </div>

      <div className="flex items-center gap-[14px] mt-[17px] mb-[32px] text-[12px] text-muted lte620:items-start lte620:mb-[27px] lte620:gap-[9px]">
        <span className="lte620:whitespace-nowrap lte620:text-[12px] lte620:pt-[7px]">
          探索のヒント
        </span>
        <div className="flex gap-[7px] flex-wrap lte620:gap-[5px]">
          {interests.length === 0 ? (
            <span className="px-[11px] py-[4px] border border-line rounded-[20px] bg-white lte620:text-[12px] lte620:px-[8px]">
              まだ設定されていません
            </span>
          ) : null}
          {interests.map((interest) => (
            <span
              key={interest}
              className="px-[11px] py-[4px] border border-line rounded-[20px] bg-white lte620:text-[12px] lte620:px-[8px]"
            >
              {interest}
            </span>
          ))}
        </div>
        <button
          type="button"
          onClick={onEditInterests}
          aria-label="探索のヒントを編集"
          className={`${TEXT_BUTTON} ml-auto text-[20px]`}
        >
          ＋
        </button>
      </div>

      <div className="grid grid-cols-2 gap-[18px] mb-[34px] lte620:grid-cols-1 lte620:gap-[10px]">
        <HomeJourneyButton
          slot={POSE_SLOTS.homeExplore}
          onClick={() => onGo('/app/explore')}
          eyebrow="01 / EXPLORE"
          title="探索の過程を見る"
          note="探す・比べる・絞る過程を見る ↗"
        />
        <HomeJourneyButton
          slot={POSE_SLOTS.homeResults}
          onClick={() => onGo('/app/results')}
          eyebrow="02 / DISCOVER"
          title="次の一歩を見つける"
          note="あなたへの3つのおすすめ ↗"
        />
      </div>
    </section>
  );
}

interface HomeJourneyButtonProps {
  slot: 2 | 3;
  onClick: () => void;
  eyebrow: string;
  title: string;
  note: string;
}

function HomeJourneyButton({ slot, onClick, eyebrow, title, note }: HomeJourneyButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex text-left items-center gap-[16px] bg-white border border-line rounded-[13px] px-[20px] py-[12px] font-medium tracking-[.04em] transition-transform duration-200 hover:-translate-y-[3px] hover:border-[#a9b79d] lte1180:p-[10px] lte1180:gap-[8px] lte620:px-[20px] lte620:py-[10px] lte620:gap-[18px]"
    >
      <StillPose
        slot={slot}
        size="w-[108px] h-[108px] lte1180:w-[80px] lte1180:h-[80px] lte620:w-[88px] lte620:h-[88px]"
        className="shrink-0"
        label="案内役のマスコット"
      />
      <span>
        <small className="text-[12px] tracking-[1.3px] text-[#8b806c]">{eyebrow}</small>
        <strong className="block text-[17px] my-[5px] font-semibold lte1180:text-[15px] lte620:text-[17px]">
          {title}
        </strong>
        <span className="text-[13px] text-muted lte1180:text-[12px]">{note}</span>
      </span>
    </button>
  );
}
