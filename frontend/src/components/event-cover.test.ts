import { describe, expect, it } from "vitest";

import { coverTiles } from "@/components/event-cover";

describe("event cover pattern", () => {
  it("is the same for the same event, every render (server and browser agree)", () => {
    expect(coverTiles("event-a", 60)).toEqual(coverTiles("event-a", 60));
  });

  it("differs between events", () => {
    expect(coverTiles("event-a", 60)).not.toEqual(coverTiles("event-b", 60));
  });

  it("keeps tiles faint, so the pattern never competes with the title", () => {
    const tiles = coverTiles("any", 500);
    expect(Math.max(...tiles.map((t) => t.opacity))).toBeLessThanOrEqual(0.22);
    expect(Math.min(...tiles.map((t) => t.opacity))).toBeGreaterThanOrEqual(0.06);
    expect(tiles.some((t) => t.found)).toBe(true);
  });
});
