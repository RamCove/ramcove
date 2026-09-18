"use client";

import { createContext, useContext, type ReactNode } from "react";

export type PreviewState = { on: boolean; takenAt: string | null };

const PreviewContext = createContext<PreviewState>({ on: false, takenAt: null });

/** Tells client components whether they are running in the read-only public preview. */
export function PreviewProvider({ value, children }: { value: PreviewState; children: ReactNode }) {
  return <PreviewContext.Provider value={value}>{children}</PreviewContext.Provider>;
}

export function usePreview(): PreviewState {
  return useContext(PreviewContext);
}

export function snapshotDate(takenAt: string | null): string {
  if (!takenAt) return "an unknown date";
  return new Date(takenAt).toISOString().slice(0, 10);
}
