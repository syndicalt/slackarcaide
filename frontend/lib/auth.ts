"use client";

// Agent identity persistence. Agents obtain API keys via the backend
// registration route; protected endpoints send `Authorization: Bearer <key>`.

const KEY_STORAGE = "arcade.apiKey";

export function getApiKey(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(KEY_STORAGE) || "";
  } catch {
    return "";
  }
}
