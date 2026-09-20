const CLOUD = 'opo-cloud absolute w-[53%] isolate lte900:w-[56%] lte640:w-[55%]';

const CAPTION =
  'block text-center text-[13px] text-[#818771] whitespace-nowrap tracking-[.045em] ' +
  'font-medium mt-[15px] lte900:text-[12px] lte900:whitespace-normal lte640:mt-[8px]';

const PORTRAIT_IMG = 'absolute w-[78%] h-[78%] object-contain left-[11%] top-[11%]';
const FRAME_IMG = 'absolute [inset:-5%] w-[110%] h-[110%] object-contain z-[-1]';

/**
 * Two different drawings sit top-left and bottom-right inside scalloped frames
 * and drift gently. The images here never swap — this is the calm opening.
 */
export function HeroDuo() {
  return (
    <div
      aria-label="あなたの思いを聞き、可能性を見つけるマスコット"
      className={
        'h-[550px] relative min-w-0 isolate lte1250:h-[500px] lte900:h-[430px] ' +
        'lte640:h-[390px] lte640:w-full lte640:max-w-[390px] lte640:mt-[15px]'
      }
    >
      <div
        className={`${CLOUD} left-0 top-0 [transform:rotate(-4deg)] lte900:top-[5px] lte640:top-0`}
      >
        <div className="frame-portrait relative aspect-square isolate">
          <img className={FRAME_IMG} src="/assets/frame-listen.png" alt="" aria-hidden="true" />
          <img
            className={PORTRAIT_IMG}
            src="/assets/welcome-listen.png"
            width={1254}
            height={1254}
            alt="ノートを持って、あなたの話を聞くマスコット"
          />
        </div>
        <span className={CAPTION}>小さな「やってみたい」から。</span>
      </div>

      <div
        className={`${CLOUD} cloud-found right-0 top-[190px] [transform:rotate(3deg)] [animation-delay:-2.5s] lte1250:top-[180px] lte900:top-[180px] lte640:top-[158px]`}
      >
        <div className="frame-portrait relative aspect-square isolate">
          <img className={FRAME_IMG} src="/assets/frame-found.png" alt="" aria-hidden="true" />
          <img
            className={`${PORTRAIT_IMG} z-[1]`}
            src="/assets/welcome-found.png"
            width={1254}
            height={1254}
            alt="新しい可能性の星を見つけたマスコット"
          />
        </div>
        <span className={CAPTION}>その先に、きっと可能性。</span>
      </div>
    </div>
  );
}
