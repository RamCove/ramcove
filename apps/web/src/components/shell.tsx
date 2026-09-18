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
    <span className={clsx("inline-flex items-center gap-2.5", className)}>
      <Logomark />
      <span className="text-[15px] font-semibold tracking-[0.2em] text-text">ROOM</span>
    </span>
  );
}

/** A fixed frame with work packed into it, and one block of new room in the corner. */
export function Logomark({ size = 26 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 26 26" role="img" aria-label="ROOM" className="shrink-0">
      <rect x="1" y="1" width="24" height="24" rx="7" fill="var(--ink)" />
      <rect x="6" y="6" width="6" height="6" rx="1.6" fill="var(--on-ink)" />
      <rect x="14" y="6" width="6" height="6" rx="1.6" fill="var(--on-ink)" opacity="0.55" />
      <rect x="6" y="14" width="6" height="6" rx="1.6" fill="var(--on-ink)" opacity="0.55" />
      <rect x="14" y="14" width="6" height="6" rx="1.6" fill="var(--accent)" />
    </svg>
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
  const isActive = (href: string) => path === href || (href !== "/" && path.startsWith(href));
  return (
    <>
      <div className="bg-band text-on-band">
        <div className="mx-auto flex max-w-[1200px] items-center gap-3 px-5 py-2 sm:px-8">
          <span aria-hidden className="live-dot shrink-0 text-accent" />
          <p className="min-w-0 truncate font-mono text-[11px] uppercase tracking-[0.12em] opacity-85" title={`network ${network}`}>
            <span>Local development build</span>
            <span className="opacity-60"> · env </span>
            <span>{env}</span>
            {simulated && (
              <span className="hidden md:inline">
                <span className="opacity-60"> · </span>simulated chain, beacon, payments and workers
                <span className="opacity-60"> · </span>no real tokens move
              </span>
            )}
          </p>
          <Link
            href="/status"
            className="ml-auto hidden shrink-0 font-mono text-[11px] uppercase tracking-[0.12em] opacity-70 transition-opacity hover:opacity-100 sm:inline"
          >
            What is real →
          </Link>
        </div>
      </div>
      <header className="sticky top-0 z-30 border-b border-line bg-bg/85 backdrop-blur-md supports-[backdrop-filter]:bg-bg/70">
        <div className="mx-auto flex h-16 max-w-[1200px] items-center gap-6 px-5 sm:px-8">
          <Link href="/" className="shrink-0 rounded-[var(--radius-sm)]" aria-label="ROOM home">
            <Wordmark />
          </Link>
          <nav aria-label="Main" className="ml-auto hidden lg:block">
            <ul className="flex items-center gap-0.5">
              {visible.map((item) => {
                const active = isActive(item.href);
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      aria-current={active ? "page" : undefined}
                      className={clsx(
                        "relative rounded-full px-3 py-1.5 text-[14px] transition-colors",
                        active ? "text-text" : "text-muted hover:text-text",
                      )}
                    >
                      {item.label}
                      {active && (
                        <span aria-hidden className="absolute inset-x-3 -bottom-[17px] h-[2px] rounded-full bg-accent" />
                      )}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>
          <div className="ml-auto flex items-center gap-1.5 lg:ml-2">
            <ThemeToggle />
            <SessionButton session={session} loaded={loaded} reload={reload} />
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              aria-expanded={open}
              className="inline-flex h-9 w-9 items-center justify-center rounded-full text-text hover:bg-surface-2 lg:hidden"
            >
              <span className="sr-only">Menu</span>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden>
                {open ? <path d="M6 6l12 12M18 6L6 18" /> : <path d="M4 8h16M4 16h16" />}
              </svg>
            </button>
          </div>
        </div>
        {open && (
          <nav aria-label="Main (compact)" className="border-t border-line bg-bg px-5 pb-5 pt-3 lg:hidden">
            <ul className="grid gap-0.5">
              {visible.map((item) => (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={() => setOpen(false)}
                    aria-current={isActive(item.href) ? "page" : undefined}
                    className={clsx(
                      "flex items-center justify-between rounded-[var(--radius-sm)] px-3 py-3 text-[16px]",
                      isActive(item.href) ? "bg-surface-2 text-text" : "text-muted hover:bg-surface-2 hover:text-text",
                    )}
                  >
                    {item.label}
                    <span aria-hidden className="text-faint">→</span>
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        )}
      </header>
    </>
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
  if (!loaded) return <span className="inline-block h-8 w-[72px] rounded-[var(--radius-sm)] bg-surface-2" aria-hidden />;
  if (session) {
    return (
      <div className="flex items-center gap-2">
        <span
          className="hidden items-center gap-2 rounded-full border border-line bg-surface py-1 pl-1.5 pr-3 text-[12.5px] text-muted sm:inline-flex"
          title={session.hotkey}
        >
          <span aria-hidden className="h-5 w-5 rounded-full bg-accent-quiet ring-1 ring-accent/30" />
          <span className="num font-mono">
            {session.hotkey.slice(0, 5)}…{session.hotkey.slice(-4)}
          </span>
          {session.roles.length > 0 && <span className="text-faint">· {session.roles.join(", ")}</span>}
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
      className="m-auto w-[min(34rem,94vw)] rounded-[var(--radius-card)] border border-line bg-surface p-0 text-text shadow-[var(--shadow-lift)]"
    >
      <div className="px-6 pb-2 pt-6">
        <p className="eyebrow">Sign in</p>
        <h2 id="signin-title" className="font-display mt-2 text-[28px] leading-tight">
          Sign in with your hotkey
        </h2>
        <p className="mt-2 text-[14px] leading-relaxed text-muted">
          ROOM never asks for a seed phrase or a private key file. You sign a one-time message that says it
          only signs you in and authorizes no payment.
        </p>

        {identities.length > 0 && (
          <div className="mt-5 rounded-[var(--radius-sm)] bg-sim-quiet px-4 py-4">
            <p className="font-mono text-[11px] font-medium uppercase tracking-[0.12em] text-sim">
              Demo identities · local build only
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
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

        <div className="mt-5">
          <label htmlFor="hotkey" className="eyebrow">
            Hotkey address (ss58)
          </label>
          <div className="mt-2 flex gap-2">
            <input
              id="hotkey"
              value={hotkey}
              onChange={(e) => setHotkey(e.target.value.trim())}
              placeholder="5F…"
              className="num h-10 min-w-0 flex-1 rounded-[var(--radius-sm)] border border-line-strong bg-bg px-3 font-mono text-[13px] text-text placeholder:text-faint focus:border-accent"
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
            <pre className="mt-2 max-h-40 overflow-auto rounded-[var(--radius-sm)] border border-line bg-bg p-3 font-mono text-[12px] leading-relaxed text-muted">
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
                className="num h-10 min-w-0 flex-1 rounded-[var(--radius-sm)] border border-line-strong bg-bg px-3 font-mono text-[13px] text-text placeholder:text-faint focus:border-accent"
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
      <div className="flex justify-end px-6 pb-5 pt-3">
        <Button variant="quiet" onClick={() => dialogRef.current?.close()}>
          Close
        </Button>
      </div>
    </dialog>
  );
}
