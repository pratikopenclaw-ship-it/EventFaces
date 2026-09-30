import { describe, expect, it } from "vitest";

import { isMediapipeInfo } from "@/components/guided-capture";

describe("MediaPipe log filter (UX-008)", () => {
  it.each([
    "INFO: Created TensorFlow Lite XNNPACK delegate for CPU.",
    "W0929 14:14:20.116000 2196592 face_landmarker_graph.cc:180] Sets FaceBlendshapesGraph acceleration to xnnpack by default.",
    "I0929 14:14:20.137999 2196592 gl_context.cc:1119] OpenGL error checking is disabled",
  ])("downgrades known informational lines: %s", (line) => expect(isMediapipeInfo(line)).toBe(true));

  it.each(["TypeError: x is undefined", "Failed to load resource", "E0929 real error", new Error("boom"), undefined])(
    "keeps real errors: %s",
    (line) => expect(isMediapipeInfo(line)).toBe(false),
  );
});
