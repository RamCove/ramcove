"use client";

import { Button, CopyRef, ErrorText, ThemeToggle, useSession } from "@/components/client";
import { snapshotDate, usePreview } from "@/components/preview";
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

export function Wordmark({ className, size = 21 }: { className?: string; size?: number }) {
  return (
    <span className={clsx("inline-flex items-center gap-2.5", className)}>
      <Logomark size={Math.round(size * 1.3)} />
      <span
        className="font-display leading-none text-text"
        style={{ fontSize: size, fontWeight: 540, letterSpacing: "-0.02em" }}
      >
        Ram
        <span className="display-accent" style={{ marginLeft: "-0.03em" }}>
          Cove
        </span>
      </span>
    </span>
  );
}

/**
 * The RamCove mark. A crescent of land curves around a bay, and one memory cell sits sheltered in its
 * mouth: memory the GPU already has, turned into space for more work. Reads as a cove, as a C, and as a
 * block of RAM, and stays legible down to 16 px.
 */
export function Logomark({ size = 28, title = "RamCove" }: { size?: number; title?: string }) {
  const id = `cove-${size}`;
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" role="img" aria-label={title} className="shrink-0">
      <defs>
        <mask id={id}>
          <rect width="32" height="32" fill="#fff" />
          <circle cx="24.5" cy="16" r="8.5" fill="#000" />
        </mask>
      </defs>
      <circle cx="16" cy="16" r="13.5" fill="var(--ink)" mask={`url(#${id})`} />
      <rect x="18.6" y="12.6" width="6.8" height="6.8" rx="2" fill="var(--accent)" />
    </svg>
  );
}

export function TopNav({ env, network, simulated }: { env: string; network: string; simulated: boolean }) {
  const path = usePathname();
  const preview = usePreview();
  const { session, loaded, reload } = useSession();
  const [open, setOpen] = useState(false);
  const roles = new Set(session?.roles ?? []);
  const visible = NAV.filter(
    (item) =>
      !("needs" in item) ||
      (item.needs === "session" ? Boolean(session) : roles.has(item.needs as string) || roles.has("operator")),
  );
  const isActive = (href: string) => path === href || (href !== "/" && path.startsWith(href));
  // The bar carries the public pages; personal and role workspaces live in the account menu, so the
  // header never overflows however many roles a session holds.
  const primary = visible.filter((item) => !("needs" in item));
  const workspace = visible.filter((item) => "needs" in item);
  return (
    <>
      <div className="bg-band text-on-band">
        <div className="mx-auto flex max-w-[1200px] items-center gap-3 px-5 py-2 sm:px-8">
          <span aria-hidden className="live-dot shrink-0 text-accent" />
          <p className="min-w-0 truncate font-mono text-[11px] uppercase tracking-[0.12em] opacity-85" title={`network ${network}`}>
            {preview.on ? (
              <>
                <span>Public preview</span>
                <span className="opacity-60"> · </span>
                <span>snapshot of the local simulation, {snapshotDate(preview.takenAt)}</span>
                <span className="hidden md:inline">
                  <span className="opacity-60"> · </span>read-only
                  <span className="opacity-60"> · </span>no real tokens move
                </span>
              </>
            ) : (
              <>
                <span>Local development build</span>
                <span className="opacity-60"> · env </span>
                <span>{env}</span>
              </>
            )}
            {simulated && !preview.on && (
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
          <Link href="/" className="shrink-0 rounded-[var(--radius-sm)]" aria-label="RamCove home">
            <Wordmark />
          </Link>
          <nav aria-label="Main" className="ml-auto hidden lg:block">
            <ul className="flex items-center gap-0.5">
              {primary.map((item) => {
                const active = isActive(item.href);
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      aria-current={active ? "page" : undefined}
                      className={clsx(
                        "relative whitespace-nowrap rounded-full px-3 py-1.5 text-[14px] transition-colors",
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
            {preview.on ? (
              <span
                className="inline-flex h-9 items-center gap-2 whitespace-nowrap rounded-full border border-line bg-surface px-3 text-[13px] text-muted sm:px-3.5"
                title="Sign-in and submissions are off in the public preview"
              >
                <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-sim" />
                <span className="hidden sm:inline">Read-only preview</span>
                <span className="sm:hidden">Preview</span>
              </span>
            ) : (
            <SessionButton
              session={session}
              loaded={loaded}
              reload={reload}
              workspace={workspace.map((w) => ({ href: w.href, label: w.label, active: isActive(w.href) }))}
            />
            )}
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
              {[...primary, ...workspace].map((item, i) => (
                <li key={item.href}>
                  {i === primary.length && workspace.length > 0 && (
                    <p className="eyebrow mb-1 mt-4 border-t border-line px-3 pt-4">Your workspace</p>
                  )}
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
  workspace,
}: {
  session: { hotkey: string; demo: boolean; roles: string[] } | null;
  loaded: boolean;
  reload: () => Promise<void>;
  workspace: { href: string; label: string; active: boolean }[];
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const router = useRouter();
  if (!loaded) return <span className="inline-block h-9 w-[84px] rounded-full bg-surface-2" aria-hidden />;
  if (session) {
    return (
      <AccountMenu
        session={session}
        workspace={workspace}
        onSignOut={async () => {
          await clientFetch("/v1/auth/logout", { method: "POST" });
          await reload();
          router.refresh();
        }}
      />
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

function AccountMenu({
  session,
  workspace,
  onSignOut,
}: {
  session: { hotkey: string; demo: boolean; roles: string[] };
  workspace: { href: string; label: string; active: boolean }[];
  onSignOut: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const short = `${session.hotkey.slice(0, 5)}…${session.hotkey.slice(-4)}`;
  const anyActive = workspace.some((w) => w.active);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={box} className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="true"
        aria-label={`Account ${short}`}
        onClick={() => setOpen((v) => !v)}
        title={session.hotkey}
        className={clsx(
          "inline-flex h-9 items-center gap-2 whitespace-nowrap rounded-full border bg-surface py-1 pl-1.5 pr-2.5 text-[13px] transition-colors hover:border-line-strong sm:pr-3",
          anyActive ? "border-accent/50" : "border-line",
        )}
      >
        <span aria-hidden className="h-6 w-6 rounded-full bg-accent-quiet ring-1 ring-accent/30" />
        <span className="num hidden font-mono text-text sm:inline">{short}</span>
        {session.roles[0] && (
          <span className="hidden text-muted xl:inline">· {session.roles[0]}</span>
        )}
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden className="text-faint">
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>
      {open && (
        <div
          className="absolute right-0 top-[calc(100%+8px)] z-40 w-64 overflow-hidden rounded-[var(--radius-sm)] border border-line bg-surface"
          style={{ boxShadow: "var(--shadow-lift)" }}
        >
          <div className="border-b border-line px-4 py-3">
            <p className="eyebrow">Signed in{session.demo ? " · demo" : ""}</p>
            <p className="num mt-1 truncate font-mono text-[12.5px] text-text">{session.hotkey}</p>
            {session.roles.length > 0 && (
              <p className="mt-1 text-[12.5px] text-muted">{session.roles.join(" · ")}</p>
            )}
          </div>
          {workspace.length > 0 && (
            <nav aria-label="Your workspace" className="py-1.5">
              {workspace.map((w) => (
                <Link
                  key={w.href}
                  href={w.href}
                  onClick={() => setOpen(false)}
                  aria-current={w.active ? "page" : undefined}
                  className={clsx(
                    "flex items-center justify-between px-4 py-2 text-[14px] transition-colors hover:bg-surface-2",
                    w.active ? "text-text" : "text-muted hover:text-text",
                  )}
                >
                  {w.label}
                  {w.active && <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-accent" />}
                </Link>
              ))}
            </nav>
          )}
          <div className="border-t border-line p-1.5">
            <button
              type="button"
              onClick={async () => {
                setOpen(false);
                await onSignOut();
              }}
              className="w-full rounded-[8px] px-3 py-2 text-left text-[14px] text-muted transition-colors hover:bg-surface-2 hover:text-text"
            >
              Sign out
            </button>
          </div>
        </div>
      )}
    </div>
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
          RamCove never asks for a seed phrase or a private key file. You sign a one-time message that says it
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
