import { useEffect, useRef, useState } from 'react';
import type { Turn } from '../../../packages/contracts';
import { audioUrl, claimAudio, registerAudio } from './audioPlayback';
import { nextSpeech } from './chatPlayback';

export function ChatAudio({
  turn,
  epoch,
  onPlayed,
  onError,
}: {
  turn: Turn | undefined;
  epoch: number;
  onPlayed: (turn: Turn, segmentId: string) => void;
  onError: (text: string) => void;
}) {
  const audio = useRef<HTMLAudioElement>(null);
  const consumed = useRef(new Set<string>());
  const [paused, setPaused] = useState(false);
  const [rate, setRate] = useState(1);
  const [volume, setVolume] = useState(1);
  const [retry, setRetry] = useState(0);
  const [blocked, setBlocked] = useState(false);
  const wanted = useRef(true);
  const current = nextSpeech(turn, epoch, consumed.current);
  useEffect(() => {
    const player = audio.current;
    if (player) return registerAudio(player);
  }, []);
  useEffect(() => {
    wanted.current = true;
    setPaused(false);
    consumed.current.clear();
  }, [turn?.id, epoch]);
  useEffect(() => {
    let disposed = false;
    let url = '';
    const player = audio.current;
    player?.pause();
    if (!player || !current?.asset_id) return;
    audioUrl(current.asset_id)
      .then((value) => {
        if (disposed) {
          URL.revokeObjectURL(value);
          return;
        }
        url = value;
        player.src = value;
        player.playbackRate = rate;
        player.volume = volume;
        if (wanted.current) {
          claimAudio(player);
          void player
            .play()
            .then(() => setBlocked(false))
            .catch(() => {
              setBlocked(true);
              setPaused(true);
              wanted.current = false;
            });
        }
      })
      .catch(() => {
        if (!disposed) onError('音频读取失败；文字已保存，可重播此条回复。');
      });
    return () => {
      disposed = true;
      player.pause();
      player.removeAttribute('src');
      if (url) URL.revokeObjectURL(url);
    };
  }, [current?.asset_id, turn?.id, epoch, retry]);
  useEffect(() => {
    if (audio.current) {
      audio.current.playbackRate = rate;
      audio.current.volume = volume;
    }
  }, [rate, volume]);
  return (
    <div className="chat-audio" aria-label="聊天语音播放器">
      <audio
        ref={audio}
        onPlay={() => {
          if (audio.current) claimAudio(audio.current);
        }}
        onEnded={() => {
          if (current && turn) {
            consumed.current.add(current.segment.id);
            onPlayed(turn, current.segment.id);
          }
        }}
        onError={() => {
          if (current) onError('此片段播放失败，请重播消息。');
        }}
      />
      <button
        disabled={!current}
        onClick={() => {
          const player = audio.current;
          if (!player) return;
          if (!paused) {
            wanted.current = false;
            player.pause();
            setPaused(true);
          } else {
            wanted.current = true;
            setPaused(false);
            setRetry((n) => n + 1);
          }
        }}
      >
        {blocked ? '点击开始播放' : paused ? '继续语音' : '暂停语音'}
      </button>
      <label>
        语速
        <select
          aria-label="聊天播放语速"
          value={rate}
          onChange={(e) => setRate(Number(e.target.value))}
        >
          {[0.75, 1, 1.25, 1.5, 2].map((value) => (
            <option key={value} value={value}>
              {value}×
            </option>
          ))}
        </select>
      </label>
      <label>
        音量
        <input
          aria-label="聊天音量"
          type="range"
          min="0"
          max="1"
          step="0.1"
          value={volume}
          onChange={(e) => setVolume(Number(e.target.value))}
        />
      </label>
      {current && <small>正在朗读：{current.segment.text} · AI 合成声音</small>}
    </div>
  );
}
