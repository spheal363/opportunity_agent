import type { ReactNode } from 'react';
import { useFlowCarousel } from '../../hooks/useFlowCarousel';
import { SECTION, SECTION_LABEL, SECTION_LABEL_NOTE } from './styles';

const CARD =
  'flex-[0_0_100%] snap-start border-0 rounded-none bg-transparent grid ' +
  'grid-cols-[1.05fr_1fr] grid-rows-[auto_auto] gap-x-[65px] gap-y-[22px] ' +
  'min-h-[440px] [align-content:center] items-center pt-[28px] px-[20px] pb-[35px] ' +
  'lte1250:gap-x-[45px] lte1250:pt-[20px] lte1250:px-[10px] lte1250:pb-[30px] ' +
  'lte900:gap-x-[28px] ' +
  'lte640:grid-cols-[1fr] lte640:grid-rows-[auto_auto_auto] lte640:gap-[18px] ' +
  'lte640:min-h-[650px] lte640:[align-content:start] lte640:pt-[20px] lte640:px-0 lte640:pb-[15px]';

const CARD_HEADING =
  'text-[32px] leading-[1.7] font-bold tracking-[.035em] my-[18px] ' +
  'lte1250:text-[29px] lte900:text-[26px] lte640:my-[13px]';

const CARD_BODY = 'text-[16px] leading-[2.15] text-[#7b8570] m-0 lte900:[&_br]:hidden';

const ILLUSTRATION =
  'col-start-2 row-start-1 row-span-2 m-0 self-center min-w-0 ' +
  'lte640:col-start-1 lte640:row-start-2 lte640:row-span-1';

const ILLUSTRATION_IMG =
  'block w-full h-[360px] object-contain select-none ' +
  'lte1250:h-[330px] lte900:h-[290px] lte640:h-[245px]';

const EXAMPLE =
  'col-start-1 row-start-2 min-h-0 border-0 rounded-none p-0 mt-[5px] ' +
  'flex flex-col justify-center lte640:row-start-3 lte640:m-0';

const EXAMPLE_EYEBROW = 'text-[12px] tracking-[1.5px] text-[#788469] font-medium font-en';
const NOTE = 'text-[12px] text-[#949985] mt-[10px]';

const STEPS = [
  { number: '01', label: '思いを伝える' },
  { number: '02', label: '機会を探す' },
  { number: '03', label: '機会に出会う' },
];

interface FlowCardProps {
  index: number;
  heading: string;
  body: ReactNode;
  image: string;
  imageAlt: string;
  example: ReactNode;
}

function FlowCard({ index, heading, body, image, imageAlt, example }: FlowCardProps) {
  const step = STEPS[index];
  return (
    <article data-flow-card className={CARD} aria-label={`${index + 1} / 3 ${step.label}`}>
      <div className="col-start-1 row-start-1">
        <span className="text-[14px] tracking-[2px] text-[#a27c52] font-en">{step.number}</span>
        <h3 className={CARD_HEADING}>{heading}</h3>
        <p className={CARD_BODY}>{body}</p>
      </div>
      <figure className={ILLUSTRATION}>
        <img
          className={ILLUSTRATION_IMG}
          src={image}
          width={1254}
          height={1254}
          alt={imageAlt}
          loading="lazy"
          draggable={false}
        />
      </figure>
      <div className={EXAMPLE}>{example}</div>
    </article>
  );
}

/**
 * The three chapters advance on their own roughly every four seconds and also
 * respond to swipe, mouse drag, the arrows, the tabs and the keyboard.
 */
export function FlowSection({ dialogOpen }: { dialogOpen: boolean }) {
  const flow = useFlowCarousel(STEPS.length, dialogOpen);

  return (
    <section
      id="how"
      ref={flow.sectionRef}
      aria-roledescription="カルーセル"
      aria-label="機会を見つける流れ"
      {...flow.sectionHandlers}
      className={`${SECTION} overflow-hidden pt-[90px] pb-[75px] lte900:pt-[65px] lte640:pt-[55px] lte640:pb-[45px]`}
    >
      <div className={SECTION_LABEL}>
        HOW IT WORKS<span className={SECTION_LABEL_NOTE}>次の一歩が見つかるまで</span>
      </div>

      <div className="flex items-center justify-between gap-[20px] mb-[30px] lte640:items-start lte640:gap-[10px] lte640:mb-[20px]">
        <h2 className="text-[32px] leading-[1.65] font-bold tracking-[.04em] m-0 lte900:text-[26px] lte640:text-[23px] lte640:max-w-[210px]">
          思いが、機会につながるまで。
        </h2>
        <div className="flex gap-[9px] shrink-0 lte640:gap-[5px]">
          <button
            type="button"
            aria-label="前のステップ"
            onClick={() => flow.goTo(flow.index - 1)}
            className="w-[42px] h-[42px] bg-transparent border-0 rounded-[50%] text-[#52694a] text-[18px] font-medium tracking-[.04em] hover:bg-[#eaf0e1] lte640:w-[32px] lte640:h-[32px] lte640:text-[16px]"
          >
            ←
          </button>
          <button
            type="button"
            aria-label="次のステップ"
            onClick={() => flow.goTo(flow.index + 1)}
            className="w-[42px] h-[42px] bg-transparent border-0 rounded-[50%] text-[#52694a] text-[18px] font-medium tracking-[.04em] hover:bg-[#eaf0e1] lte640:w-[32px] lte640:h-[32px] lte640:text-[16px]"
          >
            →
          </button>
          <button
            type="button"
            aria-label={flow.playing ? '自動送りを停止' : '自動送りを再開'}
            onClick={flow.togglePlay}
            className="w-[42px] h-[42px] bg-transparent border-0 rounded-[50%] text-[#52694a] text-[14px] font-medium tracking-[.04em] hover:bg-[#eaf0e1] lte640:w-[32px] lte640:h-[32px]"
          >
            {flow.playing ? 'Ⅱ' : '▶'}
          </button>
        </div>
      </div>

      <div
        role="group"
        aria-label="表示するステップ"
        className="flex gap-[28px] mb-[30px] lte640:gap-[14px] lte640:justify-between lte640:mb-[15px]"
      >
        {STEPS.map((step, i) => (
          <button
            key={step.number}
            type="button"
            aria-pressed={flow.index === i}
            onClick={() => flow.goTo(i)}
            className={`bg-transparent border-0 text-[14px] py-[10px] px-0 flex gap-[12px] tracking-[.04em] lte640:text-[12px] lte640:block lte640:text-left lte640:leading-[1.8] ${
              flow.index === i ? 'text-[#445e3b] font-semibold' : 'text-[#969d8c] font-medium'
            }`}
          >
            {step.number} <span className="lte640:block">{step.label}</span>
          </button>
        ))}
      </div>

      <div
        ref={flow.trackRef}
        tabIndex={0}
        aria-label="横にスクロールして3つのステップを見る"
        {...flow.trackHandlers}
        onPointerUp={flow.finishDrag}
        onPointerCancel={flow.finishDrag}
        onLostPointerCapture={flow.finishDrag}
        className={`flow-track flex gap-[70px] overflow-x-auto snap-x snap-mandatory [scrollbar-width:none] [overscroll-behavior-x:contain] relative pb-[15px] lte640:gap-[35px] focus-visible:outline-2 focus-visible:outline-[#9ba989] focus-visible:outline-offset-[4px] ${
          flow.dragging ? 'cursor-grabbing snap-none select-none' : 'cursor-grab'
        }`}
      >
        <FlowCard
          index={0}
          heading="思いを、ひとこと。"
          body={
            <>
              目標や好きなことを教えてください。
              <br />
              ぼんやりした「いつか」でも大丈夫。
              <br />
              小さな思いが、探索の手がかりになります。
            </>
          }
          image="/assets/flow-listen.png"
          imageAlt="耳に手を添え、あなたの思いに耳を傾けるマスコット"
          example={
            <>
              <span className={EXAMPLE_EYEBROW}>YOUR WISH</span>
              <blockquote className="text-[17px] font-semibold leading-[1.9] mx-0 mt-[12px] mb-0 text-[#687c55] lte900:text-[16px] [&_br]:hidden">
                AIで何か作りたい。
                <br />
                音楽も好きだし、
                <br />
                海外にも興味がある。
              </blockquote>
              <span className={NOTE}>まとまっていなくても、大丈夫。</span>
            </>
          }
        />
        <FlowCard
          index={1}
          heading="好きの、その先を探索。"
          body={
            <>
              興味の重なりや、意外な接点を手がかりに。
              <br />
              どこを探しているかも見守りながら、
              <br />
              自分だけでは見つからなかった選択肢へ。
            </>
          }
          image="/assets/flow-search.png"
          imageAlt="虫眼鏡で手がかりを探すマスコット"
          example={
            <>
              <span className={EXAMPLE_EYEBROW}>CONNECT THE DOTS</span>
              <div className="flex flex-wrap items-center gap-[12px] mt-[12px] mb-0">
                <span className="text-[19px] text-[#8f7656]">AI・開発</span>
                <b className="font-normal text-[15px] text-[#b7a286]">×</b>
                <span className="text-[19px] text-[#8f7656]">音楽</span>
                <b className="font-normal text-[15px] text-[#b7a286]">×</b>
                <span className="text-[19px] text-[#8f7656]">海外</span>
              </div>
              <span className={NOTE}>いつもの、少し外側まで。</span>
            </>
          }
        />
        <FlowCard
          index={2}
          heading="あなたに合う、3つの機会。"
          body={
            <>
              おすすめする理由と一緒に、お届けします。
              <br />
              「ちょっと、やってみたい」と思えたものから。
              <br />
              次の一歩を、自分のペースで選びましょう。
            </>
          }
          image="/assets/flow-guide.png"
          imageAlt="3つの可能性へ手を差し伸べるマスコット"
          example={
            <>
              <span className={EXAMPLE_EYEBROW}>YOUR NEXT CHAPTER</span>
              <div className="mt-[10px]">
                <small className="text-[13px] text-[#778d91]">✧ あなたへのおすすめ</small>
                <strong className="text-[21px] block text-[#566e74] my-[7px] font-semibold lte640:text-[20px]">
                  AI × Music Hackathon
                </strong>
                <p className="text-[14px] leading-[2.15] text-[#7b8570] m-0">
                  好きなことを、はじめての作品に。
                </p>
              </div>
              <span className={NOTE}>体験用の架空のサンプルです。</span>
            </>
          }
        />
      </div>

      <p className="text-[12px] text-[#909881] text-right mt-[12px] mb-0 lte640:text-left">
        横にスワイプ、または矢印で進めます。
      </p>
    </section>
  );
}
