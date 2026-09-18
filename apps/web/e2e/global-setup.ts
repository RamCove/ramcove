/**
 * Reset the labelled demo dataset before the browser suite so runs are repeatable.
 * This only works in demo mode; the endpoint refuses in any other mode.
 */
const API = process.env.RAMCOVE_API_ORIGIN ?? "http://127.0.0.1:8787";

async function post(path: string, cookie: string | null, body?: unknown) {
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...(cookie ? { cookie } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  return res;
}

export default async function globalSetup() {
  const signIn = await post("/v1/auth/demo", null, { identity: "operator" });
  if (!signIn.ok) {
    throw new Error(`demo sign-in failed (${signIn.status}); is the API running in demo mode?`);
  }
  const cookie = (signIn.headers.get("set-cookie") ?? "").split(";")[0];
  const reset = await post("/v1/demo/reset", cookie);
  if (!reset.ok) {
    throw new Error(`demo reset failed: ${reset.status} ${await reset.text()}`);
  }
  // bring the simulated workers online so capacity exists during the run
  for (const id of ["w-op-1", "w-op-2"]) {
    process.env[`RAMCOVE_E2E_WORKER_${id}`] = "expected-online";
  }
  console.log("e2e: demo dataset reset");
}
