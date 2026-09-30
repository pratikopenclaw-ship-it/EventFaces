// k6: 10x burst against one API process. 60 people search at the same instant (the
// process admits SEARCH_MAX_CONCURRENT=6); queued searches are polled like the browser
// does until done. Expected: ~6 served immediately, up to SEARCH_OVERFLOW_QUEUE_SIZE (20)
// queued and all completed, the rest "busy" (503), and no errors.
// Run with docker-compose.load.yml (see loadtest/eventfaces.js for setup notes):
//   docker compose -f docker-compose.yml -f docker-compose.e2e.yml -f docker-compose.load.yml --profile load \
//     run --rm k6 run /scripts/queue-burst.js
import http from "k6/http";
import exec from "k6/execution";
import { sleep, check } from "k6";
import { Counter, Trend } from "k6/metrics";

const API = "http://api:8000";
const VUS = 60;

export const served = new Counter("burst_served_200");
export const queued = new Counter("burst_queued_202");
export const busy = new Counter("burst_busy_503");
export const other = new Counter("burst_other_status");
export const queuedDone = new Counter("burst_queued_done");
export const queuedLost = new Counter("burst_queued_not_done");
export const syncLatency = new Trend("burst_sync_latency", true);
export const queueTime = new Trend("burst_queue_time_to_done", true);

export const options = {
  setupTimeout: "300s",
  scenarios: { burst: { executor: "per-vu-iterations", vus: VUS, iterations: 1, maxDuration: "15m" } },
  summaryTrendStats: ["min", "med", "p(95)", "p(99)", "max"],
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
  const event = http.post(`${API}/__e2e/event`, null, { timeout: "300s" }).json();
  const users = http.post(`${API}/__e2e/event/${event.id}/users?n=${VUS}`, null, { timeout: "300s" }).json();
  return { event, emails: users.emails, password: users.password };
}

export default function (data) {
  const n = exec.vu.idInTest - 1;
  const email = data.emails[n];
  const ip = `10.9.${n >> 8}.${(n % 250) + 1}`;
  const jar = new http.CookieJar();
  const csrf = http.get(`${API}/api/auth/csrf`, { jar }).json().csrf_token;
  const h = (extra = {}) => ({ "X-CSRF-Token": csrf, "X-Forwarded-For": ip, ...extra });
  check(http.post(`${API}/api/auth/login`, JSON.stringify({ email, password: data.password }), { jar, headers: h({ "Content-Type": "application/json" }) }), {
    "login 200": (r) => r.status === 200,
  });
  const shots = ["front", "left", "right"].map((s) => http.get(`${API}/__e2e/selfie/${s}.jpg`, { responseType: "binary" }).body);
  const token = http.post(`${API}/api/events/${data.event.id}/capture-token`, null, { jar, headers: h() }).json().token;

  // Everyone presses "search" together.
  exec.vu.metrics.tags.phase = "burst";
  sleep(Math.max(0, 2 - (Date.now() % 1000) / 1000));
  const started = Date.now();
  const r = http.post(`${API}/api/events/${data.event.id}/search?source=camera`, concat(shots), {
    jar,
    timeout: "120s",
    headers: h({
      "X-Capture-Token": token,
      "Content-Type": "application/x-selfie-set",
      "X-Selfie-Shots": "front,left,right",
      "X-Selfie-Lengths": shots.map((b) => b.byteLength).join(","),
    }),
  });
  if (r.status === 200) {
    served.add(1);
    syncLatency.add(r.timings.duration);
  } else if (r.status === 202) {
    queued.add(1);
    // Poll like the open page does (the browser uses 10 s; 2 s gives finer timings).
    for (let i = 0; i < 300; i++) {
      sleep(2);
      const s = http.get(`${API}/api/events/${data.event.id}/search-status`, { jar, headers: h() }).json();
      if (s.state === "done") {
        queuedDone.add(1);
        queueTime.add(Date.now() - started);
        return;
      }
      if (s.state !== "queued") break;
    }
    queuedLost.add(1);
  } else if (r.status === 503) {
    busy.add(1);
  } else {
    other.add(1);
  }
}

export function handleSummary(data) {
  return { "/scripts/results/queue-burst.json": JSON.stringify(data, null, 2), stdout: "" };
}
