"use client";
import { useCallback, useRef, useState } from "react";

/** Record from the microphone. stop() resolves with the audio blob. */
export function useRecorder() {
  const [recording, setRecording] = useState(false);
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);

  const start = useCallback(async () => {
    if (recorder.current) return;
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const media = new MediaRecorder(stream);
    chunks.current = [];
    media.ondataavailable = (e) => chunks.current.push(e.data);
    media.start();
    recorder.current = media;
    setRecording(true);
  }, []);

  const stop = useCallback(() => new Promise<Blob | null>((resolve) => {
    const media = recorder.current;
    if (!media) return resolve(null);
    media.onstop = () => {
      media.stream.getTracks().forEach((t) => t.stop());
      resolve(new Blob(chunks.current, { type: media.mimeType }));
    };
    media.stop();
    recorder.current = null;
    setRecording(false);
  }), []);

  return { recording, start, stop };
}
