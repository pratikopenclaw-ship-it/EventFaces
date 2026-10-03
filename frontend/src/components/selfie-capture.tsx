"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Alert, Button, Card } from "@/components/ui";

export type SelfieSource = "camera" | "upload";

const ACCEPTED = "image/jpeg,image/png,image/heic,image/heif";

function cameraError(e: unknown): string {
  const name = e instanceof DOMException ? e.name : "";
  if (name === "NotAllowedError") return "Camera access was blocked. Allow it in your browser's site settings and try again.";
  if (name === "NotFoundError" || name === "OverconstrainedError") return "No camera was found on this device.";
  if (name === "NotReadableError") return "The camera is being used by another app.";
  return "The camera couldn't be started.";
}

export function SelfieCapture({
  allowUpload,
  busy,
  onSubmit,
}: {
  allowUpload: boolean;
  busy: boolean;
  onSubmit: (image: Blob, contentType: string, source: SelfieSource) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [camError, setCamError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [shot, setShot] = useState<{ blob: Blob; url: string } | null>(null);

  // Each start/stop bumps the generation. A start that finishes after being superseded
  // (React dev double-mount, retake, unmount while the permission prompt is open) must
  // stop its own stream, otherwise the camera would stay on with nothing showing it.
  const generation = useRef(0);

  const stopCamera = useCallback(() => {
    generation.current += 1;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setReady(false);
  }, []);

  const startCamera = useCallback(async () => {
    const gen = ++generation.current;
    setCamError(null);
    if (!navigator.mediaDevices?.getUserMedia) {
      setCamError("This browser can't use the camera here (a secure https connection is required).");
      return;
    }
    let stream: MediaStream | null = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 960 } },
        audio: false,
      });
      if (gen !== generation.current || !videoRef.current) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      streamRef.current = stream;
      videoRef.current.srcObject = stream;
      await videoRef.current.play();
      if (gen === generation.current) setReady(true);
    } catch (e) {
      if (gen !== generation.current) {
        stream?.getTracks().forEach((t) => t.stop());
        return; // superseded: an interrupted play() is expected, not an error
      }
      setCamError(cameraError(e));
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- starting an external device on mount
    void startCamera();
    return stopCamera;
  }, [startCamera, stopCamera]);

  // Release the object URL of a discarded capture.
  useEffect(() => () => (shot ? URL.revokeObjectURL(shot.url) : undefined), [shot]);

  function capture() {
    const video = videoRef.current;
    if (!video || !video.videoWidth) return;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")?.drawImage(video, 0, 0); // un-mirrored: the preview is mirrored with CSS only
    canvas.toBlob(
      (blob) => {
        if (!blob) return;
        stopCamera();
        setShot({ blob, url: URL.createObjectURL(blob) });
      },
      "image/jpeg",
      0.92,
    );
  }

  function retake() {
    setShot(null);
    void startCamera();
  }

  function onFile(file: File | undefined) {
    if (!file) return;
    // Some browsers report HEIC files with an empty type.
    const type = file.type || (/\.hei[cf]$/i.test(file.name) ? "image/heic" : "image/jpeg");
    stopCamera();
    onSubmit(file, type, "upload");
  }

  return (
    <Card className="mx-auto max-w-xl">
      <h2 className="font-display text-2xl">Take a selfie</h2>
      <p className="mt-1 text-sm text-muted">
        Face the camera in good light, without sunglasses. It&apos;s used once and never saved.
      </p>

      <div className="relative mt-5 aspect-[4/3] overflow-hidden rounded-xl bg-black">
        {shot ? (
          // eslint-disable-next-line @next/next/no-img-element -- local object URL preview
          <img src={shot.url} alt="Your selfie" className="h-full w-full -scale-x-100 object-cover" />
        ) : (
          <>
            <video ref={videoRef} playsInline muted className="h-full w-full -scale-x-100 object-cover" />
            {ready && (
              <div
                aria-hidden
                className="pointer-events-none absolute left-1/2 top-1/2 h-[70%] w-[42%] -translate-x-1/2 -translate-y-1/2 rounded-[50%] border-2 border-white/70 shadow-[0_0_0_9999px_rgba(0,0,0,0.25)]"
              />
            )}
            {!ready && !camError && (
              <p className="absolute inset-0 flex items-center justify-center text-sm text-white/70">Starting camera…</p>
            )}
          </>
        )}
      </div>

      {camError && (
        <div className="mt-4">
          <Alert>
            {camError}
            {!allowUpload && " This event requires a live selfie."}
          </Alert>
        </div>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        {shot ? (
          <>
            <Button className="flex-1" disabled={busy} onClick={() => onSubmit(shot.blob, "image/jpeg", "camera")}>
              {busy ? "Searching…" : "Find my photos"}
            </Button>
            <Button variant="secondary" disabled={busy} onClick={retake}>
              Retake
            </Button>
          </>
        ) : camError ? (
          <Button variant="secondary" onClick={() => void startCamera()}>
            Try camera again
          </Button>
        ) : (
          <Button className="flex-1" disabled={!ready} onClick={capture}>
            Take selfie
          </Button>
        )}
      </div>

      {allowUpload && !shot && (
        <label className="mt-4 block text-center text-sm text-muted">
          or{" "}
          <span className="cursor-pointer font-medium text-accent hover:underline">
            upload a photo of yourself
            <input type="file" accept={ACCEPTED} className="sr-only" disabled={busy} onChange={(e) => onFile(e.target.files?.[0])} />
          </span>
        </label>
      )}
    </Card>
  );
}
