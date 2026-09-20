import { isSerendipity } from '../../utils/display';
import { POSE_SLOTS } from '../../utils/poses';
import type { Opportunity } from '../../types';
import { StillPose } from './Pose';
import { EYEBROW, OUTLINE_BUTTON, PRIMARY, SPARK } from './styles';

interface ResultWelcomeProps {
  interests: string[];
  items: Opportunity[];
  onExplore: () => void;
  onGoExplore: () => void;
}

export function ResultWelcome({ interests, items, onExplore, onGoExplore }: ResultWelcomeProps) {
  const done = items.length > 0;
  const surprises = items.filter(isSerendipity).length;

  return (
    <section>
      <div className="bg-[#f0ede3] border border-[#e7e1d1] rounded-[18px] flex items-center gap-[28px] pt-[20px] pr-[32px] pb-[20px] pl-[12px] mb-[20px] overflow-hidden lte850:gap-[15px] lte850:p-[18px] lte620:flex-col lte620:gap-0 lte620:pt-[12px] lte620:px-[22px] lte620:pb-[25px]">
        <div className="celebrate-art relative flex-[0_0_220px] self-stretch flex items-center justify-center lte850:flex-[0_0_170px] lte620:flex-[0_0_auto] lte620:h-[180px] lte620:self-center">
          <StillPose
            slot={POSE_SLOTS.celebrate}
            size="w-[220px] h-[220px] lte620:w-[190px] lte620:h-[190px]"
            label="新しい可能性を見つけたマスコット"
          />
          <span className={`${SPARK} text-[34px] top-[18%] right-[12%]`}>✧</span>
          <span className={`${SPARK} text-[20px] bottom-[18%] left-[5%]`}>✦</span>
        </div>
        <div>
          <span className={EYEBROW}>
            {done ? 'YOUR DISCOVERY IS READY' : 'A GLIMPSE OF POSSIBILITY'}
          </span>
          <h2 className="text-[25px] font-medium my-[12px] lte850:text-[22px] lte620:text-[23px]">
            {done ? '「やってみたい」に、出会えたかな？' : 'こんな出会いが、待っているかも。'}
          </h2>
          <p className="text-[15px] leading-[1.9] text-[#7b7764] m-0 mb-[20px]">
            {done
              ? `${interests.join(' × ') || 'あなたの目標'} をヒントに選びました。気になる機会から、詳しく見てみましょう。`
              : 'まだ結果がありません。目標を入力して探索を始めると、ここにおすすめが並びます。'}
          </p>
          <div className="flex gap-[12px] flex-wrap">
            <button type="button" onClick={onExplore} className={PRIMARY}>
              {done ? 'もう一度、探索する' : '自分の目標で探索する'} ↗
            </button>
            <button type="button" onClick={onGoExplore} className={OUTLINE_BUTTON}>
              探索の道のりを見る
            </button>
          </div>
        </div>
      </div>

      {done ? (
        <div className="flex items-center gap-[24px] pt-[8px] pb-[24px] border-b border-line mb-[27px] text-[#7d856f] text-[13px] lte620:gap-[15px] lte620:flex-wrap">
          <span>
            <b className="text-[25px] text-[#5d6c4d] font-medium pr-[5px]">{items.length}</b>
            件のおすすめ
          </span>
          <span>
            <b className="text-[25px] text-[#5d6c4d] font-medium pr-[5px]">{surprises}</b>
            件の意外な接点
          </span>
          <span>
            <b className="text-[25px] text-[#5d6c4d] font-medium pr-[5px]">
              {items.filter((o) => o.verified).length}
            </b>
            件の公式情報を確認
          </span>
        </div>
      ) : null}
    </section>
  );
}
