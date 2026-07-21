import { NextResponse } from "next/server";

// Server-side proxy so the UI can toggle Fabric enrichment on the retention
// backend without CORS or exposing the backend URL to the browser.
// POST body: { state: "on" | "off", uid?: string }
// When turning enrichment ON, we also clear the given user's cached churn score
// so the next exit-risk triggers a fresh, live Fabric scoring call.
const BACKEND = process.env.RETENTION_BACKEND_URL;

// Optional shared key for the backend's protected endpoints. Stays server-side
// (this is a route handler), never shipped to the browser.
const ADMIN_KEY = process.env.ADMIN_API_KEY;
const adminHeaders = ADMIN_KEY ? { "X-Admin-Key": ADMIN_KEY } : {};

// Report the backend's current enrichment state so the UI toggle can reflect
// reality on mount (persists across page navigation and reloads this way).
export async function GET() {
  if (!BACKEND) {
    return NextResponse.json(
      { error: "RETENTION_BACKEND_URL is not set" },
      { status: 500 }
    );
  }
  try {
    const res = await fetch(`${BACKEND}/enrichment`, { method: "GET" });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.ok ? 200 : 502 });
  } catch (error) {
    return NextResponse.json(
      { error: `Failed to reach retention backend: ${String(error)}` },
      { status: 502 }
    );
  }
}

export async function POST(request) {
  if (!BACKEND) {
    return NextResponse.json(
      { error: "RETENTION_BACKEND_URL is not set" },
      { status: 500 }
    );
  }

  let body;
  try {
    body = await request.json();
  } catch {
    body = {};
  }
  const { state, uid } = body;

  if (state !== "on" && state !== "off") {
    return NextResponse.json(
      { error: "state must be 'on' or 'off'" },
      { status: 400 }
    );
  }

  try {
    const enrichRes = await fetch(`${BACKEND}/enrichment/${state}`, {
      method: "POST",
      headers: adminHeaders,
    });
    const enrich = await enrichRes.json().catch(() => ({}));

    let cleared = null;
    if (state === "on" && uid) {
      const clrRes = await fetch(`${BACKEND}/churn-score/${uid}`, {
        method: "DELETE",
        headers: adminHeaders,
      });
      cleared = await clrRes.json().catch(() => ({}));
    }

    return NextResponse.json(
      { ...enrich, cleared },
      { status: enrichRes.ok ? 200 : 502 }
    );
  } catch (error) {
    return NextResponse.json(
      { error: `Failed to reach retention backend: ${String(error)}` },
      { status: 502 }
    );
  }
}
