"use client";

import { ThemeToggle } from "@/components/client";
import { REPO_URL, WHITEPAPER_PDF } from "@/lib/site";
import clsx from "clsx";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

// The site is public and read-only: miners submit with the ramcove-miner command line, and validators
// run the controller and workers, so there is nothing to sign in to here.
const NAV = [
  { href: "/", label: "Overview" },
  { href: "/dashboard", label: "Dashboard" },
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

export function TopNav() {
  const path = usePathname();
  const [open, setOpen] = useState(false);
  const isActive = (href: string) => path === href || (href !== "/" && path.startsWith(href));
  const icon =
    "inline-flex h-9 w-9 items-center justify-center rounded-full text-muted transition-colors hover:bg-surface-2 hover:text-text";
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-bg/85 backdrop-blur-md supports-[backdrop-filter]:bg-bg/70">
      <div className="mx-auto flex h-16 max-w-[1200px] items-center gap-6 px-5 sm:px-8">
        <Link href="/" className="shrink-0 rounded-[var(--radius-sm)]" aria-label="RamCove home">
          <Wordmark />
        </Link>
        <div className="ml-auto flex items-center">
          <nav aria-label="Main" className="hidden lg:block">
            <ul className="flex items-center gap-0.5">
              {NAV.map((item) => {
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
          <span aria-hidden className="mx-3 hidden h-5 w-px bg-line-strong lg:block" />
          <div className="flex items-center gap-0.5">
            <a href={WHITEPAPER_PDF} target="_blank" rel="noreferrer" aria-label="Whitepaper (PDF)" title="Whitepaper" className={icon}>
              <WhitepaperIcon />
            </a>
            <a href={REPO_URL} target="_blank" rel="noreferrer" aria-label="RamCove on GitHub" title="RamCove on GitHub" className={icon}>
              <GitHubIcon />
            </a>
            <ThemeToggle />
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
      </div>
      {open && (
        <nav aria-label="Main (compact)" className="border-t border-line bg-bg px-5 pb-5 pt-3 lg:hidden">
          <ul className="grid gap-0.5">
            {NAV.map((item) => (
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
  );
}

function WhitepaperIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
      <path d="M14 3v5h5M9 13h6M9 17h6M9 9h2" />
    </svg>
  );
}

function GitHubIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M12 .5a11.5 11.5 0 0 0-3.64 22.41c.58.1.79-.25.79-.56v-2c-3.2.7-3.88-1.37-3.88-1.37-.52-1.33-1.28-1.69-1.28-1.69-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.56-.29-5.25-1.28-5.25-5.7 0-1.26.45-2.29 1.19-3.1-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.77 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.84 1.19 3.1 0 4.43-2.7 5.4-5.27 5.69.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 12 .5Z" />
    </svg>
  );
}
