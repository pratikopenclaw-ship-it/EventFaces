"use client";

import type { FaceLandmarker } from "@mediapipe/tasks-vision";
import { useCallback, useEffect, useRef, useState } from "react";

import { Alert, Button, Card } from "@/components/ui";
import {
  SHOT_INSTRUCTION,
  evaluate,
  faceHeightRatio,
  isStill,
  poseFromMatrix,
  regionBrightness,
  type FrameMeasure,
  type SelfieRequirements,
  type Shot,
} from "@/lib/face-guidance";

const SHOTS: Shot[] = ["front", "left", "right"];
const HOLD_MS = 700; // all checks must pass continuously this long
const MANUAL_AFTER_MS = 12000; // offer a manual shutter if auto-capture hasn't fired
const DETECT_INTERVAL_MS = 66; // ~15 fps is plenty for guidance
// After a server-side rejection the camera re-arms automatically this many times in a row;
// then it pauses for the user to fix the problem, instead of looping into the search
// rate limit (QA-002).
const AUTO_RETRIES_AFTER_REJECTION = 1;
const RETRY_TIPS = [
  "Face a window or a lamp; avoid bright light behind you.",
  "Hold the phone at eye level, about an arm's length away.",
  "Remove sunglasses, a mask or a hat.",
  "Make sure you're the only person in the picture.",
];

export interface CapturedShot {
  shot: Shot;
  blob: Blob;
}

/** What the parent tells us after submitting: done, or retake one/all shots. */
export type SubmitResult = { retake: Shot | "all"; message: string } | void;

// MediaPipe tasks-vision creates a usage-telemetry session for every task and POSTs it
// to Google every 60 s, with no opt-out in the API. The CSP (connect-src 'self') blocks
// it; this guard also stops it before it reaches the network, so no visitor IP address
// is ever sent to Google even if the CSP is loosened.
const BLOCKED_HOSTS = ["odml.pa.googleapis.com"];
let fetchGuardInstalled = false;

function installTelemetryGuard(): void {
  if (fetchGuardInstalled) return;
  fetchGuardInstalled = true;
  const original = window.fetch.bind(window);
  window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (BLOCKED_HOSTS.some((host) => url.includes(host))) {
      return Promise.resolve(new Response(null, { status: 204 }));
    }
    return original(input, init);
  };
}

async function loadLandmarker(): Promise<FaceLandmarker> {
  installTelemetryGuard();
  const { FaceLandmarker, FilesetResolver } = await import("@mediapipe/tasks-vision");
  // Self-hosted runtime + model: no requests to third parties.
  const fileset = await FilesetResolver.forVisionTasks("/mediapipe/wasm");
  const options = (delegate: "GPU" | "CPU") => ({
    baseOptions: { modelAssetPath: "/mediapipe/face_landmarker.task", delegate },
    runningMode: "VIDEO" as const,
    numFaces: 2,
    outputFacialTransformationMatrixes: true,
  });
  try {
    return await FaceLandmarker.createFromOptions(fileset, options("GPU"));
  } catch {
    return FaceLandmarker.createFromOptions(fileset, options("CPU"));
  }
}

function Requirements({ onStart }: { onStart: () => void }) {
  const items = [
    ["☀️", "Good, even light on your face", "Face a window or lamp; avoid bright light behind you."],
    ["🙂", "Face the camera", "We'll ask for one straight photo and two with your head turned slightly."],
    ["🕶️", "No sunglasses, mask or hat", "Normal glasses are fine."],
    ["👤", "Just you", "No other people in the picture."],
    ["✋", "Hold still", "Photos are taken automatically when everything looks good."],
  ];
  return (
    <Card className="mx-auto max-w-xl">
      <h2 className="font-display text-2xl">Before you take your selfies</h2>
      <p className="mt-1 text-sm text-ink/70">Three quick photos help us find you reliably. They&apos;re deleted right after matching.</p>
      <ul className="mt-5 space-y-3">
        {items.map(([icon, title, text]) => (
          <li key={title} className="flex gap-3">
            <span aria-hidden className="text-xl">
              {icon}
            </span>
            <span>
              <span className="block text-sm font-medium">{title}</span>
              <span className="text-sm text-ink/70">{text}</span>
            </span>
          </li>
        ))}
      </ul>
      <Button className="mt-6 w-full" onClick={onStart}>
        Start camera
      </Button>
    </Card>
  );
}

export function GuidedCapture({
  requirements,
  onSubmit,
  busy,
}: {
  requirements: SelfieRequirements;
  onSubmit: (shots: CapturedShot[]) => Promise<SubmitResult>;
  busy: boolean;
}) {
  const [started, setStarted] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const generation = useRef(0);
  const landmarkerRef = useRef<FaceLandmarker | null>(null);
  const sampleCanvas = useRef<HTMLCanvasElement | null>(null);
  const [status, setStatus] = useState<"loading" | "live" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [guidanceUnavailable, setGuidanceUnavailable] = useState(false);

  const [shotIndex, setShotIndex] = useState(0);
  const shots = useRef<Partial<Record<Shot, Blob>>>({});
  const [done, setDone] = useState<Shot[]>([]);
  const [hint, setHint] = useState("Center your face in the oval");
  const [holdProgress, setHoldProgress] = useState(0);
  const [serverMessage, setServerMessage] = useState<string | null>(null);
  const [showManual, setShowManual] = useState(false);
  const rejections = useRef(0); // consecutive server-side rejections
  const [paused, setPaused] = useState(false);

  const shot = SHOTS[Math.min(shotIndex, SHOTS.length - 1)];

  const stopCamera = useCallback(() => {
    generation.current += 1;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  const startCamera = useCallback(async () => {
    const gen = ++generation.current;
    setStatus("loading");
    setError(null);
    let stream: MediaStream | null = null;
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error("This browser can't use the camera here (https is required).");
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 960 } },
        audio: false,
      });
      if (gen !== generation.current || !videoRef.current) {
        stream.getTracks().forEach((t) => t.stop()); // superseded (dev double-mount, unmount)
        return;
      }
      streamRef.current = stream;
      videoRef.current.srcObject = stream;
      await videoRef.current.play();
      const v = videoRef.current;
      if (Math.max(v.videoWidth, v.videoHeight) < requirements.min_width || Math.min(v.videoWidth, v.videoHeight) < requirements.min_height) {
        throw new Error(`Your camera resolution is too low (${v.videoWidth}×${v.videoHeight}); at least 640×480 is needed.`);
      }
      if (!landmarkerRef.current) {
        try {
          landmarkerRef.current = await loadLandmarker();
        } catch {
          setGuidanceUnavailable(true); // still usable: manual shutter + server checks
          setShowManual(true);
        }
      }
      if (gen === generation.current) setStatus("live");
    } catch (e) {
      if (gen !== generation.current) {
        stream?.getTracks().forEach((t) => t.stop());
        return;
      }
      const name = e instanceof DOMException ? e.name : "";
      setError(
        name === "NotAllowedError"
          ? "Camera access was blocked. Allow it in your browser's site settings and try again."
          : name === "NotFoundError"
            ? "No camera was found on this device."
            : e instanceof Error
              ? e.message
              : "The camera couldn't be started.",
      );
      setStatus("error");
    }
  }, [requirements.min_height, requirements.min_width]);

  useEffect(() => {
    if (!started) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- starting an external device
    void startCamera();
    return stopCamera;
  }, [started, startCamera, stopCamera]);

  useEffect(() => () => landmarkerRef.current?.close(), []);

  const capture = useCallback(async (): Promise<Blob | null> => {
    const video = videoRef.current;
    if (!video?.videoWidth) return null;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")?.drawImage(video, 0, 0); // raw frame; the preview is mirrored by CSS only
    return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.92));
  }, []);

  const finishShot = useCallback(
    async (blob: Blob) => {
      shots.current[shot] = blob;
      setDone((d) => [...new Set([...d, shot])]);
      setHoldProgress(0);
      setServerMessage(null);
      const next = SHOTS.findIndex((s) => !shots.current[s]);
      if (next !== -1) {
        setShotIndex(next);
        return;
      }
      stopCamera();
      setShotIndex(SHOTS.length);
      const result = await onSubmit(SHOTS.map((s) => ({ shot: s, blob: shots.current[s] as Blob })));
      if (!result) {
        rejections.current = 0;
        return;
      }
      // Server rejected a shot: retake just that one (or all), then resubmit.
      if (result.retake === "all") shots.current = {};
      else delete shots.current[result.retake];
      setDone(SHOTS.filter((s) => shots.current[s]));
      setShotIndex(result.retake === "all" ? 0 : SHOTS.indexOf(result.retake));
      setServerMessage(result.message);
      rejections.current += 1;
      if (rejections.current > AUTO_RETRIES_AFTER_REJECTION) {
        setPaused(true); // camera stays off until the user taps "Try again"
        return;
      }
      void startCamera();
    },
    [onSubmit, shot, startCamera, stopCamera],
  );

  // Detection loop: live hints, hold-to-capture.
  useEffect(() => {
    // Paused after repeated rejections: the camera is off and nothing may auto-capture
    // (the video element would otherwise still show the last frozen frame).
    if (status !== "live" || shotIndex >= SHOTS.length || paused) return;
    const landmarker = landmarkerRef.current;
    const video = videoRef.current;
    const nose: { x: number; y: number }[] = [];
    let holdSince: number | null = null;
    let lastRun = 0;
    let frame = 0;
    let capturing = false;
    const shotStarted = performance.now();
    sampleCanvas.current ??= document.createElement("canvas");

    const loop = (now: number) => {
      frame = requestAnimationFrame(loop);
      if (!showManual && now - shotStarted > MANUAL_AFTER_MS) setShowManual(true);
      if (!landmarker || !video || capturing || now - lastRun < DETECT_INTERVAL_MS || video.readyState < 2) return;
      lastRun = now;
      const res = landmarker.detectForVideo(video, now);
      const lm = res.faceLandmarks[0];
      const measure: FrameMeasure = { faces: res.faceLandmarks.length, pose: null, faceHeightRatio: null, brightness: null, nose: null };
      if (lm) {
        const xs = lm.map((p) => p.x), ys = lm.map((p) => p.y);
        const box = { x: Math.min(...xs), y: Math.min(...ys), w: Math.max(...xs) - Math.min(...xs), h: Math.max(...ys) - Math.min(...ys) };
        measure.pose = res.facialTransformationMatrixes[0] ? poseFromMatrix(res.facialTransformationMatrixes[0].data) : null;
        measure.faceHeightRatio = faceHeightRatio(lm);
        measure.brightness = regionBrightness(video, box, sampleCanvas.current!);
        measure.nose = { x: lm[1].x, y: lm[1].y };
        nose.push(measure.nose);
        if (nose.length > 10) nose.shift();
      }
      const g = evaluate(measure, shot, requirements);
      const still = isStill(nose);
      if (g.ok && still) {
        holdSince ??= now;
        const progress = Math.min(1, (now - holdSince) / HOLD_MS);
        setHoldProgress(progress);
        setHint("Hold still…");
        if (progress >= 1) {
          capturing = true;
          void capture().then((blob) => (blob ? finishShot(blob) : undefined));
        }
      } else {
        holdSince = null;
        setHoldProgress(0);
        setHint(g.ok ? "Hold still…" : g.hint);
      }
      if (process.env.NODE_ENV !== "production" && measure.pose) {
        // Exposed for the end-to-end test that calibrates client vs server pose.
        (window as unknown as { __efPose?: unknown }).__efPose = { ...measure.pose, ratio: measure.faceHeightRatio, brightness: measure.brightness };
      }
    };
    frame = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(frame);
  }, [status, shotIndex, shot, requirements, capture, finishShot, showManual, paused]);

  if (!started) return <Requirements onStart={() => setStarted(true)} />;

  const submitting = shotIndex >= SHOTS.length;
  return (
    <Card className="mx-auto max-w-xl" >
      <div data-shot={submitting ? "done" : shot} className="flex items-center justify-between gap-3">
        <h2 className="font-display text-2xl">{submitting ? "Finding your photos…" : SHOT_INSTRUCTION[shot]}</h2>
        <ol className="flex gap-1.5" aria-label="Progress">
          {SHOTS.map((s) => (
            <li
              key={s}
              title={s}
              className={`size-2.5 rounded-full ${done.includes(s) ? "bg-leaf" : s === shot && !submitting ? "bg-accent" : "bg-line"}`}
            />
          ))}
        </ol>
      </div>

      {serverMessage && (
        <div className="mt-3">
          <Alert>{serverMessage}</Alert>
        </div>
      )}

      <div className="relative mt-4 aspect-[4/3] overflow-hidden rounded-xl bg-ink">
        <video ref={videoRef} playsInline muted className="h-full w-full -scale-x-100 object-cover" />
        {status === "live" && !submitting && !paused && (
          <>
            <svg aria-hidden viewBox="0 0 100 75" className="pointer-events-none absolute inset-0 h-full w-full">
              <defs>
                <mask id="oval-cutout">
                  <rect width="100" height="75" fill="white" />
                  <ellipse cx="50" cy="37.5" rx="17" ry="24" fill="black" />
                </mask>
              </defs>
              <rect width="100" height="75" fill="rgba(0,0,0,0.35)" mask="url(#oval-cutout)" />
              <ellipse cx="50" cy="37.5" rx="17" ry="24" fill="none" stroke="white" strokeOpacity="0.8" strokeWidth="0.6" />
              <ellipse
                cx="50"
                cy="37.5"
                rx="17"
                ry="24"
                fill="none"
                stroke="#2f7d4f"
                strokeWidth="1.2"
                pathLength={100}
                strokeDasharray={`${holdProgress * 100} 100`}
                transform="rotate(-90 50 37.5)"
              />
            </svg>
            <p role="status" aria-live="polite" className="absolute inset-x-0 bottom-3 mx-auto w-fit rounded-full bg-ink/75 px-4 py-1.5 text-sm text-white">
              {guidanceUnavailable ? SHOT_INSTRUCTION[shot] : hint}
            </p>
          </>
        )}
        {status === "loading" && <p className="absolute inset-0 flex items-center justify-center text-sm text-white/70">Starting camera…</p>}
        {submitting && (
          <p className="absolute inset-0 flex items-center justify-center bg-ink/60 text-sm text-white">{busy ? "Searching…" : "Checking your photos…"}</p>
        )}
        {paused && !submitting && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-ink/85 p-5 text-center text-white">
            <p className="font-medium">Let&apos;s fix this before trying again</p>
            <ul className="space-y-1 text-left text-sm text-white/85">
              {RETRY_TIPS.map((tip) => (
                <li key={tip}>• {tip}</li>
              ))}
            </ul>
            <Button
              variant="secondary"
              onClick={() => {
                setPaused(false); // the reason stays on screen until the next photo is taken
                void startCamera();
              }}
            >
              Try again
            </Button>
          </div>
        )}
      </div>

      {error && (
        <div className="mt-4 space-y-3">
          <Alert>{error}</Alert>
          <Button variant="secondary" onClick={() => void startCamera()}>
            Try again
          </Button>
        </div>
      )}
      {guidanceUnavailable && status === "live" && (
        <p className="mt-3 text-xs text-ink/70">Live guidance isn&apos;t available in this browser. Follow the instruction above and take each photo yourself.</p>
      )}
      {showManual && status === "live" && !submitting && !paused && (
        <Button
          variant={guidanceUnavailable ? "primary" : "ghost"}
          className="mt-3 w-full"
          onClick={() => void capture().then((blob) => (blob ? finishShot(blob) : undefined))}
        >
          Take this photo now
        </Button>
      )}
    </Card>
  );
}
