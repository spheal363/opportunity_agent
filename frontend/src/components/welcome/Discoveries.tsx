import { Link } from 'react-router-dom';

import { SECTION, SECTION_LABEL, SECTION_LABEL_NOTE } from './styles';

const CARD =
  'border rounded-[13px] relative overflow-hidden transition-[border-color,transform] duration-200 ' +
  'hover:border-[#93a581] hover:-translate-y-[3px] pt-[28px] px-[28px] pb-[23px] ' +
  'lte1250:p-[23px] lte900:px-[18px] lte900:py-[23px] ' +
  'lte640:px-[27px] lte640:py-[24px]';

const GLYPH =
  'block text-[61px] leading-none mt-[27px] mb-[23px] lte640:absolute lte640:right-[28px] ' +
  'lte640:top-[33px] lte640:text-[64px] lte640:m-0 lte640:opacity-60';

const HEADING =
  'text-[24px] leading-[1.75] font-bold tracking-[.035em] my-[13px] ' +
  'lte1250:text-[22px] lte900:text-[21px] lte640:text-[25px]';

const EXAMPLES = [
  {
    to: '/app/results',
    label: 'MAKE SOMETHING',
    glyph: '♫',
    tags: ['AI', '音楽'],
    heading: ['好きな音楽を、', 'AIでつくる一日に。'],
    body: '共同制作で試す、はじめてのハッカソン。',
    surface: 'bg-[#eeefe3] border-[#e2e4d6]',
    glyphColor: 'text-[#9ba776]',
  },
  {
    to: '/app/results',
    label: 'MEET YOUR PEOPLE',
    glyph: '✳',
    tags: ['起業', '仲間'],
    heading: ['そのアイデアを、', '話せる仲間に会う。'],
    body: 'まだ形になっていない思いも、持ち寄って。',
    surface: 'bg-[#f2ece2] border-[#e6ded0]',
    glyphColor: 'text-[#b99572]',
  },
  {
    to: '/app/results',
    label: 'GO A LITTLE FURTHER',
    glyph: '◎',
    tags: ['海外', '英語'],
    heading: ['未来の海外生活へ、', '今ここから一歩。'],
    body: '自分のアイデアを、英語で伝えてみる。',
    surface: 'bg-[#eaf0f0] border-[#dce4e3]',
    glyphColor: 'text-[#85a3a3]',
  },
];

export function Discoveries() {
  return (
    <section
      id="possibilities"
      className={`${SECTION} pt-[32px] pb-[79px] lte900:pt-[55px] lte640:pt-[49px] lte640:pb-[38px]`}
    >
      <div className={SECTION_LABEL}>
        UNEXPECTED CONNECTIONS<span className={SECTION_LABEL_NOTE}>02 — 見つかる機会</span>
      </div>

      <div className="flex justify-between items-center gap-[35px] mb-[36px] lte900:block lte640:mb-[27px]">
        <h2 className="text-[32px] font-bold leading-[1.85] tracking-[.04em] m-0 lte1250:text-[28px] lte900:text-[31px] lte640:text-[25px] lte640:leading-[1.9]">
          「自分には関係ない」が、
          <br />
          「ちょっと、やってみたい」に。
        </h2>
        <p className="text-[16px] leading-[2.1] text-[#7c8472] m-0 lte1250:text-[15px] lte900:mt-[19px] lte900:text-[16px] lte640:leading-[2]">
          似ているものだけでなく、
          <br />
          これからの自分につながるものも。
        </p>
      </div>

      <div className="grid grid-cols-3 gap-[22px] lte640:grid-cols-1 lte640:gap-[18px]">
        {EXAMPLES.map((example) => (
          <Link key={example.label} className={`${CARD} ${example.surface}`} to={example.to}>
            <small className="text-[12px] tracking-[1.5px] text-[#828c72] lte900:tracking-[.6px]">
              {example.label}
            </small>
            <span className={`${GLYPH} ${example.glyphColor}`} aria-hidden="true">
              {example.glyph}
            </span>
            <div className="flex gap-[6px] lte640:mt-[29px]">
              {example.tags.map((tag) => (
                <span
                  key={tag}
                  className="text-[12px] leading-[1.6] px-[9px] py-[3px] bg-[#ffffff80] rounded-[20px] text-[#7c876c]"
                >
                  {tag}
                </span>
              ))}
            </div>
            <h3 className={HEADING}>
              {example.heading[0]}
              <br />
              {example.heading[1]}
            </h3>
            <p className="text-[16px] text-[#828974] leading-[1.95] m-0 mb-[23px] lte640:max-w-[95%]">
              {example.body}
            </p>
            <span className="text-[14px] block border-t border-[#ccd3ba80] pt-[16px] text-[#6c7958]">
              おすすめを見てみる ↗
            </span>
          </Link>
        ))}
      </div>

      <p className="text-[12px] text-[#909784] text-right mt-[15px] mb-0 lte640:text-left">
        掲載している機会は、体験用の架空のサンプルです。
      </p>
    </section>
  );
}
