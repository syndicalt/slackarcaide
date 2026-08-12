"use client";

import { getApiKey } from "@/lib/auth";
import Chat from "@/components/Chat";

const CHANNEL = "global";

export default function LoungePage() {
  return (
    <section>
      <h1>Lounge</h1>
      <p className="muted">
        Global message board — challenge others, talk meta, trash-talk.
      </p>
      <Chat
        channel={CHANNEL}
        title="Global lounge"
        apiKeyOverride={getApiKey()}
      />
    </section>
  );
}
