// apple-app-site-association: which web links open the iOS app (Universal Links).
// Only flows the app handles: joining (QR/link), invites, sign-in links and event pages
// (queued-search result emails). Admin and API paths never open the app.

const ID_PART = /^[A-Z0-9]{10}$/;
const BUNDLE = /^[A-Za-z0-9.-]{3,155}$/;

export function appIdFrom(teamId: string | undefined, bundleId: string | undefined): string | null {
  if (!teamId || !bundleId || !ID_PART.test(teamId) || !BUNDLE.test(bundleId)) return null;
  return `${teamId}.${bundleId}`;
}

export function buildAasa(appId: string) {
  return {
    applinks: {
      details: [
        {
          appIDs: [appId],
          // Evaluated in order: exclusions first.
          components: [
            { "/": "/admin/*", exclude: true, comment: "Organizer tools stay on the web" },
            { "/": "/api/*", exclude: true },
            { "/": "/join/*", comment: "Event join links and QR codes" },
            { "/": "/invite/*", comment: "Invite magic links" },
            { "/": "/m/signin", "?": { t: "?*" }, comment: "Sign-in links" },
            { "/": "/events/*", comment: "Event pages and search-result links" },
          ],
        },
      ],
    },
  };
}
