import { connection } from "next/server";

import { appIdFrom, buildAasa } from "@/lib/aasa";

// Served as JSON with no redirect (Apple's CDN fetches it). Configured at runtime from
// APPLE_TEAM_ID and IOS_BUNDLE_ID; without them there is no app to link to.
export async function GET() {
  await connection();
  const appId = appIdFrom(process.env.APPLE_TEAM_ID, process.env.IOS_BUNDLE_ID);
  if (!appId) return new Response("Not found", { status: 404 });
  return Response.json(buildAasa(appId), { headers: { "Cache-Control": "public, max-age=3600" } });
}
