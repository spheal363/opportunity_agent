import type { CSSProperties } from 'react';
import { Link } from 'react-router-dom';
import { BUTTON, EYEBROW } from './styles';
import { HeroDuo } from './HeroDuo';

const TITLE_LINES = ['まだ知らない、', 'あなたの可能性へ。'] as const;
const TITLE_TEXT = TITLE_LINES.join('');

/** The headline arrives one character at a time; `--i` staggers each delay. */
function RevealTitle() {
  let charIndex = 0;
  return (
    <h1
      aria-label={TITLE_TEXT}
      className={
        'font-pop font-normal [font-synthesis:none] text-[clamp(36px,3.7vw,52px)] ' +
        'leading-[1.85] tracking-[0] m-0 mb-[21px] ' +
        'lte900:text-[clamp(25px,3.65vw,33px)] ' +
        'lte640:text-[clamp(25px,7.6vw,34px)] lte640:mb-[20px]'
      }
    >
      {TITLE_LINES.map((line, lineIndex) => (
        <span
          key={line}
          aria-hidden="true"
          className={`block whitespace-nowrap leading-[1.85] tracking-[0] ${
            lineIndex === 1 ? 'text-[#5c794e]' : 'text-home-ink'
          }`}
        >
          {[...line].map((char) => (
            <span
              key={`${char}-${charIndex}`}
              className="reveal-char tracking-[0]"
              style={{ '--i': charIndex++ } as CSSProperties}
            >
              {char}
            </span>
          ))}
        </span>
      ))}
    </h1>
  );
}

export function Hero({ onStart }: { onStart: () => void }) {
  return (
    <section
      className={
        'grid grid-cols-[1fr_1.1fr] gap-[25px] max-w-[1240px] mx-auto items-center ' +
        'min-h-[630px] pt-[60px] pb-[70px] ' +
        'lte1250:px-[38px] ' +
        'lte900:gap-[15px] lte900:px-[30px] ' +
        'lte900:pt-[40px] lte900:pb-[55px] ' +
        'lte640:flex lte640:flex-col lte640:gap-[16px] lte640:min-h-0 ' +
        'lte640:px-[25px] lte640:pt-[32px] lte640:pb-[45px]'
      }
    >
      <div className="pl-[24px] relative z-[1] lte1250:p-0 lte640:w-full">
        <p className={`${EYEBROW} m-0 mb-[21px] lte900:tracking-[1px] lte640:mb-[18px]`}>
          ✧ YOUR NEXT CHAPTER STARTS HERE
        </p>
        <RevealTitle />
        <p
          className={
            'text-[17px] leading-[2.05] tracking-[.045em] text-[#76806e] m-0 mb-[29px] ' +
            'lte900:text-[16px] lte640:mb-[24px]'
          }
        >
          あなたの目標と興味から、
          <br />
          次の一歩になる出会いが見つかります。
        </p>
        <div
          className={
            'flex items-center gap-[22px] flex-wrap lte1250:gap-[18px] ' +
            'lte900:gap-[13px] lte640:gap-[18px]'
          }
        >
          <button
            type="button"
            onClick={onStart}
            // gap-x (column-gap) is emitted after BUTTON's gap, so it reliably narrows the label–arrow gap.
            className={`${BUTTON} group gap-x-[20px] hover:-translate-y-[2px] active:translate-y-0 lte1250:text-[14px] lte1250:gap-x-[16px] lte640:text-[15px] lte640:px-[16px] lte640:py-[14px] lte640:gap-x-[12px]`}
          >
            探しに行く{' '}
            <span
              // On hover the arrow heads off the way it points, as if setting out.
              className="inline-block transition-transform duration-200 group-hover:translate-x-[3px] group-hover:-translate-y-[3px]"
            >
              ↗
            </span>
          </button>
          <Link to="/app" className="text-[14px] font-medium tracking-[.04em] hover:text-[#a76b4f]">
            まずは体験してみる →
          </Link>
        </div>
        <p className="text-[12px] text-[#8b927e] mt-[15px] lte640:mt-[13px]">
          登録不要・無料で体験できます
        </p>
      </div>
      <HeroDuo />
    </section>
  );
}
