import { NextResponse } from "next/server";

/**
 * Expose the canonical agent guide at /llms.txt on the frontend too, so an
 * agent that lands on the marketing/site host can discover the API.
 * The backend (/llms.txt) is the source of truth; we proxy it server-side.
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "https://api.slackarcaide.com";

export async function GET() {
  try {
    const res = await fetch(`${API_BASE.replace(/\/+$/, "")}/llms.txt`, {
      headers: { Accept: "text/markdown, text/plain" },
      cache: "no-store",
    });
    if (!res.ok) {
      return new NextResponse("llms.txt unavailable", {
        status: 502,
        headers: { "Content-Type": "text/plain; charset=utf-8" },
      });
    }
    const body = await res.text();
    return new NextResponse(body, {
      status: 200,
      headers: {
        "Content-Type": "text/markdown; charset=utf-8",
        "Cache-Control": "public, max-age=300",
      },
    });
  } catch {
    return new NextResponse("llms.txt unavailable", {
      status: 502,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  }
}
