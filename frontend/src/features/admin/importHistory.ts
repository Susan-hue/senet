import type { ImportKind } from "../../types";

export interface ImportHistoryEntry {
  id: string;
  filename: string;
  kind: ImportKind;
  ext: string;
  created: number;
  skipped: number;
  status: "complete" | "partial" | "processing" | "failed";
  at: number;
}

const KEY = "senet.importHistory";
const MAX = 8;

export function loadImportHistory(): ImportHistoryEntry[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as ImportHistoryEntry[]) : [];
  } catch {
    return [];
  }
}

export function recordImport(entry: ImportHistoryEntry): ImportHistoryEntry[] {
  const next = [entry, ...loadImportHistory().filter((e) => e.id !== entry.id)].slice(0, MAX);
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* ignore quota errors */
  }
  return next;
}

export function relativeTime(at: number): string {
  const diff = Date.now() - at;
  const mins = Math.round(diff / 60000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days}d ago`;
  return new Date(at).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
