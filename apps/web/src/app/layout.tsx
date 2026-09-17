import "./globals.css";
import { TopNav } from "@/components/shell";
import { apiGetOrNull } from "@/lib/api";
import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: { default: "ROOM — More AI. Same GPU.", template: "%s · ROOM" },
  description:
    "ROOM is a proposed Bittensor subnet that rewards verified software improvements which let a fixed GPU serve more useful AI requests.",
};

export const dynamic = "force-dynamic";

type Meta = { env: string; network: string; simulated_chain: boolean };

export default async function RootLayout({ children }: { children: ReactNode }) {
  const meta = await apiGetOrNull<Meta>("/v1/meta");
  return (
    <html lang="en" data-theme="dark" suppressHydrationWarning>
      <head>
        {/* Apply the stored theme before paint so there is no unreadable flash. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `try{document.documentElement.dataset.theme=localStorage.getItem('room-theme')||'dark'}catch(e){}`,
          }}
        />
      </head>
      <body className="min-h-dvh bg-bg text-text">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-[var(--radius-sm)] focus:bg-surface focus:px-3 focus:py-2 focus:text-[13px]"
        >
          Skip to content
        </a>
        <TopNav
          env={meta?.env ?? "unreachable"}
          network={meta?.network ?? "unknown"}
          simulated={meta?.simulated_chain ?? true}
        />
        <main id="main" className="mx-auto w-full max-w-[1180px] px-4 py-6">
          {meta === null && (
            <div className="mb-5 rounded-[var(--radius-sm)] border-l-2 border-danger bg-danger-quiet px-4 py-3">
              <p className="text-[13px] font-semibold text-text">The ROOM API is not reachable</p>
              <p className="mt-1 text-[13px] text-muted">
                Start it with <code className="font-mono">make api</code> (or{" "}
                <code className="font-mono">uv run room-api</code>) and reload. Pages below show whatever data
                is available.
              </p>
            </div>
          )}
          {children}
        </main>
        <footer className="mx-auto w-full max-w-[1180px] px-4 pb-10 pt-4 text-[12px] leading-relaxed text-faint">
          <p>
            ROOM is a proposal. Nothing here is measured on an H100, no real tokens move, and mainnet writes
            are disabled in this build.
          </p>
        </footer>
      </body>
    </html>
  );
}
