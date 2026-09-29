// Live selfie guidance: turns MediaPipe Face Landmarker output into the same checks the
// server applies (thresholds come from /api/selfie-requirements), plus a stillness check.
// All angles use the server's (InsightFace) convention:
//   yaw   > 0 = the person turned to THEIR left (nose toward the right of the raw frame)
//   pitch < 0 = looking down
//   roll: sign irrelevant for guidance (only |roll| is checked)

export type Shot = "front" | "left" | "right";

export interface SelfieRequirements {
  min_width: number;
  min_height: number;
  face_height_min: number;
  face_height_max: number;
  max_yaw: number;
  max_pitch: number;
  max_roll: number;
  front_max_yaw: number;
  side_min_yaw: number;
  min_brightness: number;
  max_brightness: number;
  capture_token_seconds: number;
  global_file_upload: boolean;
}

export interface Pose {
  yaw: number;
  pitch: number;
  roll: number;
}

export interface FrameMeasure {
  faces: number;
  pose: Pose | null;
  faceHeightRatio: number | null; // face height / frame height
  brightness: number | null; // mean luma of the face region, 0–255
  nose: { x: number; y: number } | null; // normalized, for stillness
}

export interface Guidance {
  ok: boolean;
  code: string | null;
  hint: string;
}

// Calibrated in the browser against InsightFace on identical frames (Phase 6 e2e):
//   yaw   server -20.6 / MediaPipe -18.8  → same sign
//   pitch server -21.9 / MediaPipe +20.4  → flip (frame: person looking down)
//   roll  server -19.9 / MediaPipe +21.8  → flip
const YAW_SIGN = 1;
const PITCH_SIGN = -1;
const ROLL_SIGN = -1;

const deg = (rad: number) => (rad * 180) / Math.PI;

/** Euler angles from MediaPipe's 4×4 facial transformation matrix (column-major). */
export function poseFromMatrix(data: number[]): Pose {
  const r00 = data[0], r10 = data[1], r20 = data[2];
  const r21 = data[6], r22 = data[10];
  return {
    pitch: PITCH_SIGN * deg(Math.atan2(r21, r22)),
    yaw: YAW_SIGN * deg(Math.atan2(-r20, Math.hypot(r21, r22))),
    roll: ROLL_SIGN * deg(Math.atan2(r10, r00)),
  };
}

/** Face height / frame height from the 468-point mesh (forehead #10 to chin #152), padded
 * slightly because the server's detector box is a bit taller than the mesh. */
export function faceHeightRatio(landmarks: { x: number; y: number }[]): number {
  let min = 1, max = 0;
  for (const p of landmarks) {
    if (p.y < min) min = p.y;
    if (p.y > max) max = p.y;
  }
  return (max - min) * 1.05;
}

export const SHOT_INSTRUCTION: Record<Shot, string> = {
  front: "Look straight at the camera",
  left: "Turn your head slightly to your left",
  right: "Turn your head slightly to your right",
};

export function evaluate(m: FrameMeasure, shot: Shot, req: SelfieRequirements): Guidance {
  const fail = (code: string, hint: string): Guidance => ({ ok: false, code, hint });
  if (m.faces === 0 || !m.pose || m.faceHeightRatio === null) return fail("no_face", "Center your face in the oval");
  if (m.faces > 1) return fail("multiple_faces", "Make sure only you are in the picture");
  if (m.brightness !== null && m.brightness < req.min_brightness) return fail("too_dark", "Find more light: face a window or lamp");
  if (m.brightness !== null && m.brightness > req.max_brightness) return fail("too_bright", "Too bright: move out of direct light");
  if (m.faceHeightRatio < req.face_height_min) return fail("face_too_small", "Move closer");
  if (m.faceHeightRatio > req.face_height_max) return fail("face_too_large", "Move back a little");
  const { yaw, pitch, roll } = m.pose;
  if (Math.abs(pitch) > req.max_pitch) return fail("pitch_out_of_range", pitch < 0 ? "Raise your chin a little" : "Lower your chin a little");
  if (Math.abs(roll) > req.max_roll) return fail("roll_out_of_range", "Keep your head straight, don't tilt it");
  if (Math.abs(yaw) > req.max_yaw) return fail("yaw_out_of_range", "Turn back toward the camera a little");
  if (shot === "front" && Math.abs(yaw) > req.front_max_yaw) return fail("not_facing_camera", "Look straight at the camera");
  if (shot === "left" && yaw < req.side_min_yaw) return fail("wrong_turn_left", "Turn your head slightly to your left");
  if (shot === "right" && -yaw < req.side_min_yaw) return fail("wrong_turn_right", "Turn your head slightly to your right");
  return { ok: true, code: null, hint: "Hold still…" };
}

/** True if the nose moved less than `tolerance` (normalized units) over the window. */
export function isStill(history: { x: number; y: number }[], tolerance = 0.012): boolean {
  if (history.length < 6) return false;
  const xs = history.map((p) => p.x), ys = history.map((p) => p.y);
  return Math.max(...xs) - Math.min(...xs) < tolerance && Math.max(...ys) - Math.min(...ys) < tolerance;
}

/** Mean luma of a region of the video, sampled on a tiny canvas (cheap enough per frame). */
export function regionBrightness(
  video: HTMLVideoElement,
  box: { x: number; y: number; w: number; h: number },
  canvas: HTMLCanvasElement,
): number | null {
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx || !video.videoWidth) return null;
  canvas.width = 32;
  canvas.height = 32;
  const vw = video.videoWidth, vh = video.videoHeight;
  ctx.drawImage(video, box.x * vw, box.y * vh, Math.max(1, box.w * vw), Math.max(1, box.h * vh), 0, 0, 32, 32);
  const { data } = ctx.getImageData(0, 0, 32, 32);
  let sum = 0;
  for (let i = 0; i < data.length; i += 4) sum += 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
  return sum / (data.length / 4);
}
