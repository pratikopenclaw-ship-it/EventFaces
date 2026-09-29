// Self-host MediaPipe's runtime and model under /public/mediapipe so visitors' browsers
// never contact Google (GDPR: no IP addresses sent to a third party). Runs on install
// and in the production Docker build. The model is downloaded once at build time and
// checked against a pinned SHA-256.
import { createHash } from "node:crypto";
import { cpSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(root, "public", "mediapipe");
const wasmSrc = join(root, "node_modules", "@mediapipe", "tasks-vision", "wasm");

const MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task";
const MODEL_SHA256 = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff";
const modelPath = join(out, "face_landmarker.task");

const sha256 = (buf) => createHash("sha256").update(buf).digest("hex");

mkdirSync(out, { recursive: true });
if (existsSync(wasmSrc)) cpSync(wasmSrc, join(out, "wasm"), { recursive: true });

if (existsSync(modelPath) && sha256(readFileSync(modelPath)) === MODEL_SHA256) {
  console.log("mediapipe: model present");
} else {
  const res = await fetch(MODEL_URL);
  if (!res.ok) throw new Error(`mediapipe: model download failed (${res.status})`);
  const buf = Buffer.from(await res.arrayBuffer());
  if (sha256(buf) !== MODEL_SHA256) throw new Error("mediapipe: model checksum mismatch");
  writeFileSync(modelPath, buf);
  console.log(`mediapipe: model downloaded (${buf.length} bytes)`);
}
