import { POSE_SLOTS } from '../../utils/poses';
import {
  availabilityView,
  categoryLabel,
  coverLines,
  isSaved,
  isSerendipity,
  isStep,
  placeLabel,
  scheduleLabel,
} from '../../utils/display';
import type { Opportunity, OpportunityStatus } from '../../types';
import { CardPose, StillPose } from './Pose';
import { PRIMARY } from './styles';

/** 表紙の色は並び順で変わる。 */
const COVER = ['bg-[#f2eee7]', 'bg-[#edf0f4]', 'bg-[#f0ede5]'];
const COVER_TEXT = ['text-[#6d6755]', 'text-[#5c6a7e]', 'text-[#867758]'];

interface OpportunityCardProps {
  opportunity: Opportunity;
  index: number;
  status: OpportunityStatus;
  /** 探索結果の画面ではカードが高くなり、専用の絵が入る。 */
  isResult: boolean;
  onToggleSave: () => void;
  onOpenDetail: () => void;
}

export function OpportunityCard({
  opportunity,
  index,
  status,
  isResult,
  onToggleSave,
  onOpenDetail,
}: OpportunityCardProps) {
  const [coverTop, coverBottom] = coverLines(opportunity.type);
  const saved = isSaved(status);
  const inSteps = isStep(status);
  const serendipity = isSerendipity(opportunity);
  const availability = availabilityView(opportunity.availability);

  return (
    <article
      style={isResult ? ({ '--card-index': index } as React.CSSProperties) : undefined}
      className={`bg-white border border-[#e0e3da] rounded-[11px] overflow-hidden flex flex-col transition-[transform,box-shadow] duration-200 hover:-translate-y-[4px] hover:shadow-[0_12px_27px_#34402e0c] ${
        isResult ? 'result-card' : ''
      }`}
    >
      <div
        className={`px-[19px] pt-[20px] pb-[17px] relative lte620:px-[22px] lte620:py-[18px] ${
          COVER[index % 3]
        } ${isResult ? 'min-h-[158px]' : 'min-h-[134px] lte620:min-h-[117px]'}`}
      >
        <span className="text-[12px] tracking-[1.2px] text-[#716c61]">
          {categoryLabel(opportunity.type)}
        </span>
        <button
          type="button"
          onClick={onToggleSave}
          aria-pressed={saved}
          aria-label={`${opportunity.title}を${saved ? '「気になる」から外す' : '「気になる」に保存'}`}
          className={`absolute right-[12px] top-[13px] border border-[#fff9] rounded-[50%] h-[32px] w-[32px] text-[19px] leading-none ${
            saved ? 'text-[#ad614d] bg-white' : 'bg-[#ffffff9c]'
          }`}
        >
          {saved ? '♥' : '♡'}
        </button>
        <div
          className={`leading-[1.2] font-medium tracking-[-.6px] mt-[15px] ${COVER_TEXT[index % 3]} ${
            isResult
              ? 'text-[25px] max-w-[65%] lte620:text-[28px]'
              : 'text-[25px] max-w-[85%] lte850:text-[22px] lte620:text-[27px]'
          }`}
        >
          {coverTop}
          <br />
          {coverBottom}
        </div>
        {isResult ? <CardPose index={index} /> : null}
      </div>

      <div className="px-[18px] pt-[17px] pb-[18px] flex flex-1 flex-col lte1150:px-[13px] lte1150:py-[15px] lte620:px-[22px] lte620:py-[20px]">
        <span
          className={`text-[12px] flex items-center gap-[5px] ${
            serendipity ? 'text-[#996a37]' : 'text-[#4b6c58]'
          }`}
        >
          {serendipity ? '✧ 意外なつながり' : '✳ 目標につながる一歩'}
          {inSteps ? ' · 準備リスト入り' : ''}
        </span>
        <h3 className="text-[17px] leading-[1.65] mt-[9px] mb-[12px] font-semibold">
          {opportunity.title}
        </h3>
        <div className="text-[14px] text-[#707b73] grid gap-[4px]">
          <span>◷ {scheduleLabel(opportunity)}</span>
          {/* 参加費は一覧の Schema に無い。詳細で出す。 */}
          <span>⌖ {placeLabel(opportunity)}</span>
          {/* 確認できた範囲だけを書く。確認していない状態を「受付中」とは書かない。 */}
          <span className={availability.tone}>
            {availability.mark} {availability.label}
          </span>
        </div>
        {opportunity.reason ? (
          <div className="text-[14px] leading-[1.85] p-[12px] bg-[#f7f8f4] rounded-[5px] mt-[14px] mb-[17px] flex-1 text-[#596653]">
            {/* **マッチ度は「AI による希望との適合度の目安」。**
                正確さでも、受付中である確率でも、参加資格を満たす確率でもない。
                未評価の候補には出さない（架空の点を出さないため）。 */}
            {opportunity.evaluated ? (
              <span
                className="inline-block text-[12px] font-medium mb-[6px] px-[8px] py-[2px] rounded-[20px] bg-[#e7ede4] text-[#4d6b52]"
                title="AIによる希望との適合度の目安です。正確さ・受付状況・参加資格の判定ではありません。"
              >
                マッチ度 {opportunity.score}
                <span className="text-[#7a8977]">（適合度の目安）</span>
              </span>
            ) : null}
            <strong className="block text-[12px] tracking-[.04em] font-medium mb-[5px] text-[#7a8977]">
              あなたにおすすめする理由
            </strong>
            {opportunity.reason}
            {opportunity.match_reasons.length > 0 ? (
              <span className="block text-[12px] text-[#7a8977] mt-[6px]">
                合致した希望: {opportunity.match_reasons.join(' / ')}
              </span>
            ) : null}
            {opportunity.unknowns.length > 0 ? (
              <span className="block text-[12px] text-[#8a7f6d] mt-[4px]">
                判断に必要な未確認: {opportunity.unknowns.join(' / ')}
              </span>
            ) : null}
          </div>
        ) : (
          <div className="flex-1" />
        )}
        <button
          type="button"
          onClick={onOpenDetail}
          className="flex w-full justify-between items-center bg-transparent border-0 border-t border-line pt-[13px] px-0 pb-0 text-[14px] text-[#4b6352] font-medium tracking-[.04em]"
        >
          {inSteps ? '参加準備を確認' : 'この機会を見てみる'} <span>↗</span>
        </button>
      </div>
    </article>
  );
}

interface EmptyStateProps {
  kind: 'saved' | 'steps';
  onReturn: () => void;
}

/** 「気になる」「次の一歩」がまだ空のとき。 */
export function EmptyState({ kind, onReturn }: EmptyStateProps) {
  const saved = kind === 'saved';
  return (
    <div className="col-span-full py-[54px] px-[20px] text-center border border-dashed border-[#cbd4c5] rounded-[10px]">
      <StillPose
        slot={saved ? POSE_SLOTS.emptySaved : POSE_SLOTS.emptySteps}
        size="w-[150px] h-[150px]"
        className="block mx-auto"
        label="案内役のマスコット"
      />
      <span className="text-[30px] text-[#bc9370]">✧</span>
      <h3 className="font-medium text-[1.17em] my-[1em]">
        {saved ? '気になる機会は、これから。' : '最初の一歩を見つけましょう。'}
      </h3>
      <p className="text-muted text-[14px]">
        {saved
          ? 'カードのハートを押すと、ここにまとまります。'
          : '機会の詳細から、参加準備を始められます。'}
      </p>
      <button type="button" onClick={onReturn} className={PRIMARY}>
        おすすめを見る ↗
      </button>
    </div>
  );
}
