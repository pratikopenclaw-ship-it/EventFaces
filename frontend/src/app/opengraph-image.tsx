import { ImageResponse } from "next/og";

// The link preview (WhatsApp, iMessage, Slack…) for every page. Join links need a login, so
// crawlers land on /login and show this one: it never names an event.
// Colours are the light theme tokens (design/tokens.json); next/og can't read CSS variables.

export const alt = "EventFaces: find every photo of you from the event";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const ACCENT = "#0f766e";
const ON_ACCENT = "#ffffff";
const INK = "#10231f";
const MUTED = "#586b66";
const CANVAS = "#f3f7f6";

// The contact sheet: most tiles dim, a few outlined ("your" photos). Fixed layout.
const FOUND = new Set([3, 10, 16, 25, 31]);

export default function Image() {
  return new ImageResponse(
    (
      <div style={{ display: "flex", width: "100%", height: "100%", background: CANVAS }}>
        <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", width: 640, padding: "0 72px" }}>
          {/* One text run: next/og spaces adjacent spans apart, which would split the name. */}
          <div style={{ display: "flex", fontSize: 40, color: ACCENT }}>EventFaces</div>
          <div style={{ display: "flex", marginTop: 36, fontSize: 76, lineHeight: 1.05, color: INK, letterSpacing: -2 }}>
            Find every photo of you.
          </div>
          <div style={{ display: "flex", marginTop: 28, fontSize: 30, lineHeight: 1.35, color: MUTED }}>
            One selfie finds you among thousands of event photos. Your selfie is never stored.
          </div>
        </div>
        <div style={{ display: "flex", flex: 1, alignItems: "center", justifyContent: "center", background: ACCENT }}>
          <div style={{ display: "flex", flexWrap: "wrap", width: 420, gap: 12 }}>
            {Array.from({ length: 36 }, (_, i) => (
              <div
                key={i}
                style={{
                  display: "flex",
                  width: 60,
                  height: 45,
                  borderRadius: 5,
                  background: ON_ACCENT,
                  opacity: FOUND.has(i) ? 0.9 : 0.12 + ((i * 7) % 5) * 0.03,
                  border: FOUND.has(i) ? `4px solid ${ON_ACCENT}` : "none",
                }}
              />
            ))}
          </div>
        </div>
      </div>
    ),
    size,
  );
}
