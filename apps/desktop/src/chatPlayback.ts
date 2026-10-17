import type { Turn } from '../../../packages/contracts';

export function nextSpeech(turn: Turn | undefined, epoch: number, consumed: ReadonlySet<string>) {
  if (
    !turn ||
    turn.playback_epoch !== epoch ||
    turn.speech_stopped ||
    turn.status === 'cancelled' ||
    turn.status === 'failed'
  )
    return undefined;
  return turn.speech?.find(
    (item) =>
      item.status === 'ready' &&
      !!item.asset_id &&
      !consumed.has(item.segment.id) &&
      item.epoch === epoch,
  );
}
