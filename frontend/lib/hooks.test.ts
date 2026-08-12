import { describe, expect, it } from "vitest";

import { isMessage, isObservation } from "./hooks";

describe("realtime guards", () => {
  it("rejects null render payloads", () => {
    expect(isObservation({ match_id: "m", render: null })).toBe(false);
  });

  it("accepts the minimum observation contract", () => {
    expect(isObservation({ match_id: "m", render: {} })).toBe(true);
  });

  it("rejects null messages", () => {
    expect(isMessage(null)).toBe(false);
  });
});
