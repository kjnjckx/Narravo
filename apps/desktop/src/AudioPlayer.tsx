import { useEffect, useRef, useState } from 'react';
import { Pause, Play, SkipBack, SkipForward, Square } from 'lucide-react';
import { audioUrl, claimAudio, registerAudio } from './audioPlayback';
import { message } from './store';
import type { AudioPlan } from '../../../packages/contracts';

export function AudioPlayer({
  plan,
  onError,
  stale = false,
}: {
  plan: AudioPlan;
  onError: (message: string) => void;
  stale?: boolean;
}) {
  const audio = useRef<HTMLAudioElement | null>(null);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);
  const [ready, setReady] = useState(false);
  const wanted = useRef(false);
  useEffect(() => {
    const player = audio.current;
    if (player) return registerAudio(player);
  }, []);
  const current = plan.segments[index];
  useEffect(() => {
    setIndex(0);
    wanted.current = false;
    setPlaying(false);
  }, [plan.revision, plan.text]);
  useEffect(() => {
    let cancelled = false;
    let objectUrl = '';
    const player = audio.current;
    player?.pause();
    setReady(false);
    if (!current || stale) {
      wanted.current = false;
      setPlaying(false);
      return;
    }
    audioUrl(current.asset_id)
      .then((url) => {
        if (cancelled || !player) {
          URL.revokeObjectURL(url);
          return;
        }
        objectUrl = url;
        player.src = objectUrl;
        player.playbackRate = rate;
        setReady(true);
        if (wanted.current)
          void player.play().catch((e) => {
            wanted.current = false;
            setPlaying(false);
            onError(message(e));
          });
      })
      .catch((e) => {
        if (!cancelled) {
          wanted.current = false;
          setPlaying(false);
          onError(message(e));
        }
      });
    return () => {
      cancelled = true;
      player?.pause();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [current?.asset_id, stale]);
  useEffect(() => {
    if (audio.current) audio.current.playbackRate = rate;
  }, [rate]);
  function toggle() {
    const player = audio.current;
    if (!player || !ready || stale) return;
    if (playing) {
      player.pause();
      wanted.current = false;
      setPlaying(false);
    } else {
      wanted.current = true;
      void player
        .play()
        .then(() => setPlaying(true))
        .catch((e) => {
          wanted.current = false;
          onError('播放未能开始，请再次点击播放。' + message(e));
        });
    }
  }
  return (
    <div className="audio-player">
      <audio
        ref={audio}
        onPlay={() => {
          if (audio.current) claimAudio(audio.current);
          setPlaying(true);
        }}
        onPause={() => setPlaying(false)}
        onEnded={() => {
          if (index + 1 < plan.segments.length) {
            setIndex(index + 1);
          } else {
            wanted.current = false;
            setPlaying(false);
          }
        }}
        onError={() => {
          if (ready) onError('此音频无法播放，请检查格式或重新合成。');
        }}
      />
      <div className="audio-controls">
        <button
          aria-label="上一段"
          disabled={index === 0 || stale}
          onClick={() => setIndex((i) => i - 1)}
        >
          <SkipBack size={16} />
        </button>
        <button
          aria-label={playing ? '暂停语音' : '播放语音'}
          disabled={!ready || stale}
          onClick={toggle}
        >
          {playing ? <Pause size={19} /> : <Play size={19} />}
        </button>
        <button
          aria-label="停止播放"
          onClick={() => {
            audio.current?.pause();
            wanted.current = false;
            setPlaying(false);
            if (audio.current) audio.current.currentTime = 0;
          }}
        >
          <Square size={14} />
        </button>
        <button
          aria-label="下一段"
          disabled={index + 1 >= plan.segments.length || stale}
          onClick={() => setIndex((i) => i + 1)}
        >
          <SkipForward size={16} />
        </button>
        <select
          aria-label="播放倍速"
          value={rate}
          onChange={(e) => setRate(Number(e.target.value))}
        >
          {[0.75, 1, 1.25, 1.5, 2].map((value) => (
            <option key={value} value={value}>
              {value}×
            </option>
          ))}
        </select>
      </div>
      <p>
        {stale
          ? '正文已修改，此音频基于旧修订，已暂停。'
          : `第 ${Math.min(index + 1, plan.segments.length)} / ${plan.segments.length} 段 · 已准备 ${plan.segments.length}/${plan.total_segments} 段`}
      </p>
      {current && !stale && (
        <blockquote>{[...plan.text].slice(current.start, current.end).join('')}</blockquote>
      )}
      <small>AI 合成声音 · 按片段显示正文；缓存命中不重复合成。</small>
    </div>
  );
}
