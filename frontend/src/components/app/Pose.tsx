import { useEffect } from 'react';
import {
  MOTION_BY_STEP,
  MOTION_LABELS,
  MOTION_MODES,
  stillPoseStyle,
  type PoseSlot,
} from '../../utils/poses';
import type { AgentStep } from '../../types';

interface StillPoseProps {
  slot: PoseSlot;
  /** Width and height utilities for this placement. */
  size: string;
  label?: string;
  className?: string;
}

/** One of the nine drawings from the pose atlas. */
export function StillPose({ slot, size, label, className = '' }: StillPoseProps) {
  return (
    <span
      className={`still-pose max-w-full ${size} ${className}`}
      style={stillPoseStyle(slot)}
      {...(label ? { role: 'img', 'aria-label': label } : { 'aria-hidden': true })}
    />
  );
}

/** One of the three drawings sized for a result card's cover. */
export function CardPose({ index }: { index: number }) {
  return (
    <span
      className="card-new-pose absolute w-[105px] h-[105px] right-[6px] bottom-0 opacity-[.96] lte620:right-[15px]"
      aria-hidden="true"
      style={{ '--card-x': `${index * 50}%` } as React.CSSProperties}
    />
  );
}

interface MotionCompanionProps {
  step: AgentStep | null;
  /** 再生するのは実際に Agent が動いている間だけ。 */
  playing: boolean;
  done: boolean;
}

/**
 * 探索中のキャラクターは複数フレームの画像をコマ送りする。
 * ステップごとに再生する画像が変わる。
 */
export function MotionCompanion({ step, playing, done }: MotionCompanionProps) {
  const mode = MOTION_BY_STEP[step ?? 'analyzing_profile'];
  const caption = playing
    ? MOTION_LABELS[mode]
    : done
      ? '探索、おつかれさま。'
      : '探索の表示を止めています。';

  // Warm the other atlases so a stage change never flashes an empty frame.
  useEffect(() => {
    for (const other of MOTION_MODES) {
      const image = new Image();
      image.src = `/assets/motion-${other}.png`;
    }
  }, []);

  return (
    <div className="motion-companion w-full max-w-[270px] flex flex-col items-center relative z-[1]">
      <span
        className={`sprite-pose sprite-${mode} w-[230px] max-w-full lte1180:w-[215px] lte620:w-[215px] ${playing ? 'playing' : ''}`}
        role="img"
        aria-label={`${MOTION_LABELS[mode]}マスコット`}
      />
      <span className="text-[12px] text-[#64735b] leading-[1.5] text-center mt-0 mx-0 mb-[12px] min-h-[18px]">
        {caption}
      </span>
    </div>
  );
}
