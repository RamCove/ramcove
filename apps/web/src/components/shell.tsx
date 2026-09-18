"use client";

import { Button, CopyRef, ErrorText, ThemeToggle, useSession } from "@/components/client";
import { ApiFailure, clientFetch } from "@/lib/api";
import clsx from "clsx";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

const NAV = [
  { href: "/", label: "Overview" },
  { href: "/competition", label: "Competition" },
  { href: "/queue", label: "Queue" },
  { href: "/submit", label: "Submit" },
  { href: "/submissions", label: "My work", needs: "session" },
  { href: "/validator", label: "Validator", needs: "validator" },
  { href: "/review", label: "Review", needs: "reviewer" },
  { href: "/operator", label: "Operator", needs: "operator" },
  { href: "/docs", label: "Docs" },
  { href: "/status", label: "Status" },
] as const;

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={clsx("inline-flex items-center gap-2", className)}>
      <svg width="22" height="22" viewBox="0 0 22 22" role="img" aria-label="ROOM">
        <rect x="1.5" y="1.5" width="19" height="19" rx="5" fill="none" stroke="var(--accent)" strokeWidth="1.6" />
        <rect x="6" y="6" width="6" height="6" rx="1.5" fill="var(--accent)" />
        <rect x="13" y="13" width="3" height="3" rx="1" fill="var(--accent-strong)" opacity="0.8" />
      </svg>
      <span className="text-[15px] font-semibold tracking-[0.14em] text-text">ROOM</span>
    </span>
  );
}

export function TopNav({ env, network, simulated }: { env: string; network: string; simulated: boolean }) {
  const path = usePathname();
  const { session, loaded, reload } = useSession();
  const [open, setOpen] = useState(false);
  const roles = new Set(session?.roles ?? []);
  const visible = NAV.filter(
    (item) =>
      !("needs" in item) ||
      (item.needs === "session" ? Boolean(session) : roles.has(item.needs as string) || roles.has("operator")),
  );
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-bg/95 backdrop-blur">
      <div className="mx-auto flex max-w-[1180px] items-center gap-4 px-4 py-3">
        <Link href="/" className="shrink-0" aria-label="ROOM home">
          <Wordmark />
        </Link>
        <span className="hidden text-[12px] text-faint sm:inline">More AI. Same GPU.</span>
        <nav aria-label="Main" className="ml-auto hidden lg:block">
          <ul className="flex items-center gap-1">
            {visible.map((item) => {
              const active = path === item.href || (item.href !== "/" && path.startsWith(item.href));
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={clsx(
                      "rounded-[var(--radius-sm)] px-2.5 py-1.5 text-[13px] transition-colors",
                      active ? "bg-surface-2 text-text" : "text-muted hover:bg-surface-2 hover:text-text",
                    )}
                  >
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
        <div className="ml-auto flex items-center gap-2 lg:ml-0">
          <ThemeToggle />
          <SessionButton session={session} loaded={loaded} reload={reload} />
          <span className="lg:hidden">
            <Button variant="quiet" size="sm" onClick={() => setOpen((v) => !v)}>
              Menu
              <span className="sr-only">Toggle navigation</span>
            </Button>
          </span>
        </div>
      </div>
      {open && (
        <nav aria-label="Main (compact)" className="border-t border-line px-4 py-2 lg:hidden">
          <ul className="grid grid-cols-2 gap-1">
            {visible.map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  onClick={() => setOpen(false)}
                  className="block rounded-[var(--radius-sm)] px-2.5 py-2 text-[13px] text-muted hover:bg-surface-2 hover:text-text"
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      )}
      <div className="border-t border-line bg-sim-quiet px-4 py-1.5 text-center text-[12px] text-sim">
        Local development build · env <strong className="font-semibold">{env}</strong> · network{" "}
        <strong className="font-semibold">{network}</strong>
        {simulated && " · chain, beacon, payments and workers are simulated; no real tokens move"}
      </div>
    </header>
  );
}

function SessionButton({
  session,
  loaded,
  reload,
}: {
  session: { hotkey: string; demo: boolean; roles: string[] } | null;
  loaded: boolean;
  reload: () => Promise<void>;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const router = useRouter();
  if (!loaded) return <span className="text-[12px] text-faint">…</span>;
  if (session) {
    return (
      <div className="flex items-center gap-2">
        <span className="hidden text-[12px] text-muted sm:inline" title={session.hotkey}>
          {session.hotkey.slice(0, 6)}…{session.hotkey.slice(-4)}
          {session.roles.length > 0 && ` · ${session.roles.join(", ")}`}
        </span>
        <Button
          size="sm"
          variant="quiet"
          onClick={async () => {
            await clientFetch("/v1/auth/logout", { method: "POST" });
            await reload();
            router.refresh();
          }}
        >
          Sign out
        </Button>
      </div>
    );
  }
  return (
    <>
      <Button size="sm" variant="primary" onClick={() => ref.current?.showModal()}>
        Sign in
      </Button>
      <SignInDialog
        dialogRef={ref}
        onDone={async () => {
          await reload();
          router.refresh();
        }}
      />
    </>
  );
}

export function SignInDialog({
  dialogRef,
  onDone,
}: {
  dialogRef: React.RefObject<HTMLDialogElement | null>;
  onDone: () => Promise<void>;
}) {
  const [identities, setIdentities] = useState<{ key: string; name: string; roles: string[] }[]>([]);
  const [hotkey, setHotkey] = useState("");
  const [challenge, setChallenge] = useState<{ nonce: string; message: string } | null>(null);
  const [signature, setSignature] = useState("");
  const [error, setError] = useState<ApiFailure | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    clientFetch<{ identities: typeof identities }>("/v1/demo/identities")
      .then((r) => setIdentities(r.identities))
      .catch(() => setIdentities([]));
  }, []);

  async function run<T>(fn: () => Promise<T>) {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e as ApiFailure);
      return null;
    } finally {
      setBusy(false);
    }
  }

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="signin-title"
      className="w-[min(36rem,94vw)] rounded-[var(--radius-card)] border border-line bg-surface p-0 text-text backdrop:bg-black/60"
    >
      <div className="px-5 py-4">
        <h2 id="signin-title" className="text-[15px] font-semibold">
          Sign in with your hotkey
        </h2>
        <p className="mt-1 text-[13px] leading-relaxed text-muted">
          ROOM never asks for a seed phrase or a private key file. You sign a one-time message that says it
          only signs you in and authorizes no payment.
        </p>

        {identities.length > 0 && (
          <div className="mt-4 rounded-[var(--radius-sm)] border border-sim bg-sim-quiet px-3 py-3">
            <p className="text-[12px] font-semibold text-sim">Demo identities (local build only)</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {identities.map((i) => (
                <Button
                  key={i.key}
                  size="sm"
                  busy={busy}
                  onClick={async () => {
                    const ok = await run(() =>
                      clientFetch("/v1/auth/demo", { method: "POST", body: JSON.stringify({ identity: i.key }) }),
                    );
                    if (ok) {
                      dialogRef.current?.close();
                      await onDone();
                    }
                  }}
                >
                  {i.name}
                </Button>
              ))}
            </div>
          </div>
        )}

        <div className="mt-4">
          <label htmlFor="hotkey" className="text-[12px] font-medium text-muted">
            Hotkey address (ss58)
          </label>
          <div className="mt-1 flex gap-2">
            <input
              id="hotkey"
              value={hotkey}
              onChange={(e) => setHotkey(e.target.value.trim())}
              placeholder="5F…"
              className="num min-w-0 flex-1 rounded-[var(--radius-sm)] border border-line bg-surface-2 px-3 py-2 font-mono text-[12px] text-text placeholder:text-faint"
            />
            <Button
              busy={busy}
              disabled={hotkey.length < 46}
              onClick={async () => {
                const r = await run(() =>
                  clientFetch<{ nonce: string; message: string }>("/v1/auth/challenge", {
                    method: "POST",
                    body: JSON.stringify({ hotkey }),
                  }),
                );
                if (r) setChallenge(r);
              }}
            >
              Get message
            </Button>
          </div>
        </div>

        {challenge && (
          <div className="mt-3">
            <p className="text-[12px] font-medium text-muted">
              Sign this message with your hotkey, then paste the signature.
            </p>
            <pre className="mt-1 max-h-40 overflow-auto rounded-[var(--radius-sm)] border border-line bg-surface-2 p-3 font-mono text-[11px] leading-relaxed text-muted">
              {challenge.message}
            </pre>
            <div className="mt-1 flex justify-end">
              <CopyRef value={challenge.message} label="Copy message" />
            </div>
            <div className="mt-2 flex gap-2">
              <input
                aria-label="Signature"
                value={signature}
                onChange={(e) => setSignature(e.target.value.trim())}
                placeholder="0x…"
                className="num min-w-0 flex-1 rounded-[var(--radius-sm)] border border-line bg-surface-2 px-3 py-2 font-mono text-[12px] text-text placeholder:text-faint"
              />
              <Button
                variant="primary"
                busy={busy}
                disabled={signature.length < 10}
                onClick={async () => {
                  const ok = await run(() =>
                    clientFetch("/v1/auth/verify", {
                      method: "POST",
                      body: JSON.stringify({ nonce: challenge.nonce, signature }),
                    }),
                  );
                  if (ok) {
                    dialogRef.current?.close();
                    await onDone();
                  }
                }}
              >
                Sign in
              </Button>
            </div>
          </div>
        )}
        <ErrorText error={error} />
      </div>
      <div className="flex justify-end border-t border-line px-5 py-3">
        <Button variant="quiet" onClick={() => dialogRef.current?.close()}>
          Close
        </Button>
      </div>
    </dialog>
  );
}
