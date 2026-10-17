import { describe, expect, it, vi } from 'vitest';
import { nextSpeech } from './chatPlayback';
import { claimAudio, registerAudio, stopAudioFocus } from './audioPlayback';
import type { Turn } from '../../../packages/contracts';

const fixture = (): Turn => ({
  id: 'turn',
  task_id: 'task',
  conversation_id: 'conversation',
  base_snapshot: 'base',
  expected_snapshot: 'head',
  playback_epoch: 7,
  budget: {},
  status: 'running',
  speech: [
    {
      epoch: 7,
      status: 'ready',
      asset_id: 'a'.repeat(32),
      segment: {
        id: 'sentence',
        revision: 'segment-revision',
        conversation_id: 'conversation',
        turn_id: 'turn',
        message_id: 'message',
        variant_revision: 'variant',
        start: 0,
        end: 4,
        text: '你好😀。',
        text_hash: 'hash',
        requested_emotion: 'neutral',
        voice: {},
      },
    },
  ],
});
describe('foreground chat audio invariants', () => {
  it('rejects late epochs, cancelled rounds and already played sentence identities', () => {
    const turn = fixture();
    expect(nextSpeech(turn, 7, new Set())?.segment.variant_revision).toBe('variant');
    expect(nextSpeech(turn, 8, new Set())).toBeUndefined();
    expect(nextSpeech({ ...turn, status: 'cancelled' }, 7, new Set())).toBeUndefined();
    expect(nextSpeech({ ...turn, speech_stopped: true }, 7, new Set())).toBeUndefined();
    expect(nextSpeech(turn, 7, new Set(['sentence']))).toBeUndefined();
    expect(
      nextSpeech({ ...turn, speech: turn.speech?.map((s) => ({ ...s, epoch: 6 })) }, 7, new Set()),
    ).toBeUndefined();
  });
  it('narration and chat share a single foreground focus and stop immediately', () => {
    const book = { pause: vi.fn(), currentTime: 4 } as unknown as HTMLAudioElement;
    const chat = { pause: vi.fn(), currentTime: 2 } as unknown as HTMLAudioElement;
    const removeBook = registerAudio(book),
      removeChat = registerAudio(chat);
    claimAudio(chat);
    expect(book.pause).toHaveBeenCalledOnce();
    expect(chat.pause).not.toHaveBeenCalled();
    stopAudioFocus();
    expect(chat.pause).toHaveBeenCalledOnce();
    expect(book.currentTime).toBe(0);
    expect(chat.currentTime).toBe(0);
    removeBook();
    removeChat();
  });
});
