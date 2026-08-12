import { describe, expect, it } from "vitest";

import { hasRenderer } from "./index";

describe("game renderer registry", () => {
  it("renders both chess variants with the chess board", () => {
    expect(hasRenderer("chess")).toBe(true);
    expect(hasRenderer("chess960")).toBe(true);
  });

  it("rejects unregistered renderers", () => {
    expect(hasRenderer("unknown-game")).toBe(false);
  });
});
