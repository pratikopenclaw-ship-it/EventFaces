// k6 load test: concurrent selfie searches (ramping to find the breaking point),
// downloads and guest uploads, plus a check that per-user rate limiting still bites.
// Runs inside the compose network against the e2e API: see docker-compose.load.yml.
import http from "k6/http";
import exec from "k6/execution";
import { check } from "k6";
import { Trend, Rate, Counter } from "k6/metrics";

const API = "http://api:8000";
const USERS = 240;

export const searchLatency = new Trend("search_latency", true);
export const downloadLatency = new Trend("download_latency", true);
export const uploadLatency = new Trend("upload_latency", true);
export const errors = new Rate("app_errors"); // non-2xx that aren't expected 429s
export const limited = new Counter("rate_limited_429");

export const options = {
  setupTimeout: "300s",
  scenarios: {
    search: {
      executor: "ramping-vus",
      exec: "search",
      startVUs: 1,
      stages: [
        { duration: "45s", target: 2 },
        { duration: "45s", target: 5 },
        { duration: "45s", target: 10 },
        { duration: "45s", target: 20 },
        { duration: "45s", target: 40 },
      ],
      gracefulRampDown: "30s",
    },
    download: { executor: "constant-vus", exec: "download", vus: 3, duration: "225s" },
    upload: { executor: "constant-vus", exec: "upload", vus: 2, duration: "225s" },
    limiter: { executor: "shared-iterations", exec: "limiter", vus: 1, iterations: 1, startTime: "240s" },
  },
  summaryTrendStats: ["min", "med", "avg", "p(90)", "p(95)", "p(99)", "max"],
};

function concat(parts) {
  const total = parts.reduce((n, p) => n + p.byteLength, 0);
  const out = new Uint8Array(total);
  let off = 0;
  for (const p of parts) {
    out.set(new Uint8Array(p), off);
    off += p.byteLength;
  }
  return out.buffer;
}

export function setup() {
  http.post(`${API}/__e2e/reset`);
  const event = http.post(`${API}/__e2e/event?guest_uploads=true&moderation=auto`, null, { timeout: "300s" }).json();
  const users = http.post(`${API}/__e2e/event/${event.id}/users?n=${USERS}`, null, { timeout: "300s" }).json();
  return { event, emails: users.emails, password: users.password };
}

// Binary fixtures are fetched once per VU: setup() data is JSON-serialized, which
// would silently turn ArrayBuffers into {}.
let fixtures = null;
function files() {
  if (!fixtures) {
    const shots = ["front", "left", "right"].map((s) => http.get(`${API}/__e2e/selfie/${s}.jpg`, { responseType: "binary" }).body);
    const photo = http.get(`${API}/__e2e/guest-photo.jpg`, { responseType: "binary" }).body;
    fixtures = { body: concat(shots), lengths: shots.map((b) => b.byteLength).join(","), photo };
  }
  return fixtures;
}

const sessions = {}; // per VU: email -> { jar, csrf, photos }

function session(data, email) {
  if (sessions[email]) return sessions[email];
  const n = data.emails.indexOf(email);
  const ip = `10.${(n >> 8) & 255}.${n & 255}.${1 + (n % 250)}`; // one client address per user
  const jar = new http.CookieJar();
  const csrf = http.get(`${API}/api/auth/csrf`, { jar }).json().csrf_token;
  const r = http.post(`${API}/api/auth/login`, JSON.stringify({ email, password: data.password }), {
    jar,
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf, "X-Forwarded-For": ip },
    tags: { name: "login" },
  });
  check(r, { "login 200": (x) => x.status === 200 });
  sessions[email] = { jar, csrf, ip, photos: [] };
  return sessions[email];
}

// Headers for an authenticated, CSRF-protected request from this user's address.
function h(s, extra = {}) {
  return { "X-CSRF-Token": s.csrf, "X-Forwarded-For": s.ip, ...extra };
}

function record(res, trend, expect429 = false) {
  if (res.status === 429) {
    limited.add(1);
    errors.add(!expect429);
    return;
  }
  errors.add(res.status >= 300);
  if (res.status < 300) trend.add(res.timings.duration);
}

// Searches: users 0..199, rotated so per-user limits aren't the bottleneck.
export function search(data) {
  const email = data.emails[(exec.vu.idInTest * 7 + exec.vu.iterationInScenario) % 200];
  const s = session(data, email);
  const tok = http.post(`${API}/api/events/${data.event.id}/capture-token`, null, {
    jar: s.jar, headers: h(s), tags: { name: "capture-token" },
  });
  if (tok.status !== 200) return record(tok, searchLatency);
  const res = http.post(`${API}/api/events/${data.event.id}/search?source=camera`, files().body, {
    jar: s.jar,
    timeout: "120s",
    tags: { name: "search", vus: String(exec.instance.vusActive) },
    headers: h(s, {
      "X-Capture-Token": tok.json().token,
      "Content-Type": "application/x-selfie-set",
      "X-Selfie-Shots": "front,left,right",
      "X-Selfie-Lengths": files().lengths,
    }),
  });
  record(res, searchLatency);
  check(res, { "search found photos": (r) => r.status !== 200 || r.json().matches.length > 0 });
}

// Downloads: users 200..219 search once, then repeatedly download their matches as a ZIP.
export function download(data) {
  const email = data.emails[200 + ((exec.vu.idInTest + exec.vu.iterationInScenario) % 20)];
  const s = session(data, email);
  if (!s.photos.length) {
    const tok = http.post(`${API}/api/events/${data.event.id}/capture-token`, null, { jar: s.jar, headers: h(s) });
    const r = http.post(`${API}/api/events/${data.event.id}/search?source=camera`, files().body, {
      jar: s.jar, timeout: "120s",
      headers: h(s, { "X-Capture-Token": tok.json().token, "Content-Type": "application/x-selfie-set", "X-Selfie-Shots": "front,left,right", "X-Selfie-Lengths": files().lengths }),
    });
    if (r.status === 200) s.photos = r.json().matches.map((m) => m.id);
    return;
  }
  const t = http.post(`${API}/api/events/${data.event.id}/downloads`, JSON.stringify({ photo_ids: s.photos }), {
    jar: s.jar, headers: h(s, { "Content-Type": "application/json" }), tags: { name: "download-ticket" },
  });
  if (t.status !== 200) return record(t, downloadLatency);
  const res = http.get(`${API}${t.json().url}`, { jar: s.jar, responseType: "none", tags: { name: "download-zip" } });
  record(res, downloadLatency);
}

// Guest uploads: users 220..239: start → presigned PUT to storage → complete.
export function upload(data) {
  const email = data.emails[220 + ((exec.vu.idInTest + exec.vu.iterationInScenario) % 20)];
  const s = session(data, email);
  const started = Date.now();
  const st = http.post(`${API}/api/events/${data.event.id}/uploads`,
    JSON.stringify({ filename: "load.jpg", content_type: "image/jpeg", size: files().photo.byteLength }), {
      jar: s.jar, headers: h(s, { "Content-Type": "application/json" }), tags: { name: "upload-start" },
    });
  if (st.status !== 201) return record(st, uploadLatency);
  const put = http.put(st.json().upload_url, files().photo, { headers: { "Content-Type": "image/jpeg" }, tags: { name: "upload-put" } });
  if (put.status !== 200) return record(put, uploadLatency);
  const done = http.post(`${API}/api/events/${data.event.id}/uploads/${st.json().photo_id}/complete`, null, {
    jar: s.jar, headers: h(s), timeout: "120s", tags: { name: "upload-complete" },
  });
  if (done.status < 300) uploadLatency.add(Date.now() - started);
  else record(done, uploadLatency);
}

// The hard-coded per-user capture-token limit (30/10 min) must still return 429 under load.
export function limiter(data) {
  const s = session(data, data.emails[0]);
  const codes = [];
  for (let i = 0; i < 40; i++) {
    codes.push(http.post(`${API}/api/events/${data.event.id}/capture-token`, null, { jar: s.jar, headers: h(s), tags: { name: "limiter" } }).status);
  }
  const got429 = codes.includes(429);
  check(null, { "rate limiter still returns 429 under load": () => got429 });
  if (got429) limited.add(1);
}

export function handleSummary(data) {
  return { "/scripts/results/summary.json": JSON.stringify(data, null, 2), stdout: "" };
}
