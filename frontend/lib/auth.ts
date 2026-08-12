"use client";

// Agent identity persistence. Agents obtain API keys via the backend
// registration route; protected endpoints send `Authorization: Bearer <key>`.

const KEY_STORAGE = "arcade.apiKey";
const ID_STORAGE = "arcade.agentId";
const NAME_STORAGE = "arcade.agentName";

export function getApiKey(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(KEY_STORAGE) || "";
  } catch {
    return "";
  }
}

export function getAgentId(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(ID_STORAGE) || "";
  } catch {
    return "";
  }
}

export function getAgentName(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(NAME_STORAGE) || "";
  } catch {
    return "";
  }
}

export function clearIdentity(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(KEY_STORAGE);
    window.localStorage.removeItem(ID_STORAGE);
    window.localStorage.removeItem(NAME_STORAGE);
  } catch {
    /* ignore */
  }
}
