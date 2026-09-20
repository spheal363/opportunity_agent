import type { CSSProperties } from 'react';

import type { AgentStep } from '../types';

/** 探索中アニメーションのコマ画像の種類。API の Schema ではなく表示用。 */
export type MotionMode = 'walk' | 'sniff' | 'look' | 'map';

/**
 * `assets/poses-new.png` is a 1254×1254 atlas: nine unique drawings laid out in a
 * 3×3 grid of 418px cells. Each placement in the UI owns one cell, so the same
 * drawing is never shown twice on a screen.
 */
export const POSE_SLOTS = {
  /** guide banner mascot */
  mascot: 0,
  sidebar: 1,
  homeExplore: 2,
  homeResults: 3,
  celebrate: 4,
  note: 5,
  detailCompanion: 6,
  emptySaved: 7,
  emptySteps: 8,
} as const;

export type PoseSlot = (typeof POSE_SLOTS)[keyof typeof POSE_SLOTS];

/**
 * Hand-measured [left, top, right, bottom] of the drawing inside its padded
 * 418px cell. A 300px viewport centred on each keeps props intact and the
 * character prominent.
 */
const STILL_BOUNDS: ReadonlyArray<readonly [number, number, number, number]> = [
  [114, 138, 322, 364],
  [113, 156, 315, 357],
  [103, 139, 307, 360],
  [113, 119, 343, 341],
  [118, 98, 310, 341],
  [110, 127, 304, 346],
  [111, 89, 351, 309],
  [114, 104, 312, 306],
  [106, 98, 311, 310],
];

const CELL = 418;
const VIEWPORT = 300;
/** (atlas 1254px − viewport 300px) — the denominator of a percentage background-position. */
const TRAVEL = 954;

/**
 * Background-position percentages that centre the chosen cell's drawing in a
 * square element scaled by `background-size: 418% 418%`.
 */
export function stillPoseStyle(slot: PoseSlot): CSSProperties {
  const [left, top, right, bottom] = STILL_BOUNDS[slot];
  const x = ((slot % 3) * CELL + (left + right) / 2 - VIEWPORT / 2) / TRAVEL;
  const y = (Math.floor(slot / 3) * CELL + (top + bottom) / 2 - VIEWPORT / 2) / TRAVEL;
  return { '--art-x': `${x * 100}%`, '--art-y': `${y * 100}%` } as CSSProperties;
}

/** Agent の各ステップで再生するコマ画像。 */
export const MOTION_BY_STEP: Record<AgentStep, MotionMode> = {
  analyzing_profile: 'look',
  planning: 'walk',
  searching: 'sniff',
  evaluating: 'map',
  verifying: 'map',
  completed: 'look',
};

export const MOTION_LABELS: Record<MotionMode, string> = {
  walk: '歩いて候補を探す',
  sniff: 'くんくんと手がかりを探す',
  look: 'きょろきょろと見渡す',
  map: '地図を広げて調べる',
};

export const MOTION_MODES: MotionMode[] = ['walk', 'sniff', 'look', 'map'];
