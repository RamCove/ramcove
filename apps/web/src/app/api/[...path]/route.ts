/** Same-origin proxy to the RamCove API, so the session cookie stays first-party and CORS is not needed. */

import { API_ORIGIN } from "@/lib/api";
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

async function forward(req: NextRequest, path: string[]) {
  const url = new URL(`${API_ORIGIN}/${path.join("/")}`);
  req.nextUrl.searchParams.forEach((v, k) => url.searchParams.append(k, v));
  const headers = new Headers();
  for (const name of ["content-type", "cookie", "idempotency-key", "accept"]) {
    const value = req.headers.get(name);
    if (value) headers.set(name, value);
  }
  // The API also checks the origin; forward the app's own origin, never an attacker-supplied one.
  headers.set("origin", process.env.ROOM_PUBLIC_ORIGIN ?? "http://localhost:3787");
  const init: RequestInit = { method: req.method, headers, redirect: "manual" };
  if (req.method !== "GET" && req.method !== "HEAD") init.body = await req.arrayBuffer();
  const res = await fetch(url, init);
  const out = new Headers();
  for (const [k, v] of res.headers.entries()) {
    if (["content-type", "set-cookie", "cache-control"].includes(k)) out.append(k, v);
  }
  return new Response(res.body, { status: res.status, headers: out });
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(req, (await ctx.params).path);
}

export async function POST(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(req, (await ctx.params).path);
}
