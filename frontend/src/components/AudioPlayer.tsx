import { forwardRef, useImperativeHandle, useRef } from "react";
import type { TranscriptSegment } from "../types/meeting";

export interface AudioPlayerHandle { playSegment: (segment: TranscriptSegment) => Promise<void> }

export const AudioPlayer = forwardRef<AudioPlayerHandle, { src?: string; onError?: () => void }>(function AudioPlayer({ src, onError }, ref) {
  const audioRef = useRef<HTMLAudioElement>(null);
  useImperativeHandle(ref, () => ({
    async playSegment(segment) {
      const audio = audioRef.current;
      if (!audio || !src) return;
      audio.currentTime = segment.start_ms / 1000;
      await audio.play();
    },
  }), [src]);

  return (
    <section className="panel audio-panel" aria-labelledby="audio-heading">
      <div className="section-heading"><p className="eyebrow">Запись</p><h2 id="audio-heading">Аудио совещания</h2></div>
      {src ? <audio ref={audioRef} src={src} onError={onError} controls preload="metadata" aria-label="Запись совещания" />
        : <p className="muted">Аудиозапись недоступна. Чтобы прослушать источник в демо, загрузите аудиофайл на главной странице.</p>}
    </section>
  );
});
