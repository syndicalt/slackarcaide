import { afterEach, describe, expect, it, vi } from "vitest";

import { describeAction, flattenActions } from "./actions";
import { getApiKey } from "./auth";
import { errMsg, isUnauthorized, toActionError } from "./errors";

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("action presentation", () => {
  it("describes primitives, noops, and nested values", () => {
    expect(describeAction({})).toBe("noop");
    expect(describeAction({ from: "e2", nested: { x: 1 } })).toBe(
      'from=e2 nested={"x":1}',
    );
    expect(describeAction("up")).toBe("up");
  });

  it("flattens per-seat actions without duplicates", () => {
    expect(flattenActions()).toEqual([]);
    expect(flattenActions([])).toEqual([]);
    expect(
      flattenActions([
        [{ action: "up" }, { action: "up" }],
        { action: "down" },
      ]),
    ).toEqual([{ action: "up" }, { action: "down" }]);
  });
});

describe("error and credential handling", () => {
  it("uses structured API errors and recognizes only 401", () => {
    const error = Object.assign(new Error("fallback"), {
      status: 401,
      api: { code: "invalid_api_key", message: "Invalid key" },
    });
    expect(errMsg(error)).toBe("invalid_api_key — Invalid key");
    expect(isUnauthorized(error)).toBe(true);
    expect(toActionError(error)).toEqual({
      unauthorized: true,
      message: "invalid_api_key — Invalid key",
    });
    expect(
      isUnauthorized(Object.assign(new Error("no"), { status: 403 })),
    ).toBe(false);
    expect(errMsg("plain")).toBe("plain");
  });

  it("reads the stored key and fails closed when storage throws", () => {
    localStorage.setItem("arcade.apiKey", "arc_key");
    expect(getApiKey()).toBe("arc_key");
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked");
    });
    expect(getApiKey()).toBe("");
  });
});
