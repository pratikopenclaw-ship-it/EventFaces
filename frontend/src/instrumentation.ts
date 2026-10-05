import type { Instrumentation } from "next";

// Server-side errors (rendering, route handlers, proxy) go to GlitchTip when SENTRY_DSN is
// set. Only the error type, a redacted message and stack, the route and the path are sent.
export const onRequestError: Instrumentation.onRequestError = async (err, request, context) => {
  const { sendReport } = await import("@/lib/error-report");
  const error = err instanceof Error ? err : new Error(String(err));
  const digest = typeof err === "object" && err !== null && "digest" in err ? String(err.digest) : undefined;
  await sendReport({
    component: "web-server",
    type: error.name,
    message: error.message,
    stack: error.stack,
    path: request.path,
    tags: {
      route: context.routePath.slice(0, 200),
      route_type: context.routeType,
      ...(digest ? { digest: digest.slice(0, 100) } : {}),
    },
  });
};
