// Same-origin tunnel for browser error reports. Unlike an SDK tunnel it never forwards a
// client-built envelope (that would let anyone post anything to any DSN): it accepts a
// few string fields, redacts them and builds the event itself for the configured DSN.
import { allowReport, parseBrowserReport, sendReport } from "@/lib/error-report";

const MAX_BODY = 16_384;

// Other sites' pages can't use the tunnel. Browsers send Sec-Fetch-Site to trustworthy
// origins (HTTPS, localhost); elsewhere their POSTs always carry Origin, compared with Host.
function fromOurPage(headers: Headers): boolean {
  const site = headers.get("sec-fetch-site");
  if (site !== null) return site === "same-origin";
  const origin = headers.get("origin");
  const host = headers.get("host");
  if (!origin || !host) return false;
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

export async function POST(request: Request): Promise<Response> {
  if (!fromOurPage(request.headers)) return new Response(null, { status: 403 });
  const length = Number(request.headers.get("content-length") ?? "0");
  if (length > MAX_BODY) return new Response(null, { status: 413 });
  const text = await request.text();
  if (text.length > MAX_BODY) return new Response(null, { status: 413 });
  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    return new Response(null, { status: 400 });
  }
  const report = parseBrowserReport(body);
  if (!report) return new Response(null, { status: 400 });
  if (!allowReport()) return new Response(null, { status: 429, headers: { "Retry-After": "60" } });
  await sendReport(report);
  return new Response(null, { status: 204, headers: { "Cache-Control": "no-store" } });
}
