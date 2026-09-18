import "./globals.css";
import { SiteFooter } from "@/components/footer";
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
    <html lang="en" data-theme="light" suppressHydrationWarning>
      <head>
        {/* Apply the stored theme before paint so there is no unreadable flash. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `try{document.documentElement.dataset.theme=localStorage.getItem('room-theme')||'light'}catch(e){}`,
          }}
        />
      </head>
      <body className="flex min-h-dvh flex-col bg-bg text-text">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-[var(--radius-sm)] focus:bg-surface focus:px-3 focus:py-2 focus:text-[14px] focus:shadow-[var(--shadow-lift)]"
        >
          Skip to content
        </a>
        <TopNav
          env={meta?.env ?? "unreachable"}
          network={meta?.network ?? "unknown"}
          simulated={meta?.simulated_chain ?? true}
        />
        <main id="main" className="site-main flex-1">
          {meta === null && (
            <div className="full-bleed mx-auto mt-6 max-w-[1200px] px-5 sm:px-8">
              <div className="rounded-[var(--radius-sm)] bg-danger-quiet px-5 py-4">
                <p className="text-[14px] font-semibold text-text">The ROOM API is not reachable</p>
                <p className="mt-1 text-[14px] text-muted">
                  Start it with <code className="font-mono">make api</code> (or{" "}
                  <code className="font-mono">uv run room-api</code>) and reload. Pages below show whatever data
                  is available.
                </p>
              </div>
            </div>
          )}
          {children}
        </main>
        <SiteFooter />
      </body>
    </html>
  );
}
