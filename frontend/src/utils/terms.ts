import type { Semester, Session } from "../types";

/**
 * The semester a session is currently in, falling back to its first one. Screens
 * that open on "now" land the user in the term they are actually teaching or
 * studying in rather than an empty picker.
 */
export function currentSemesterOf(session: Session | null, semesters: Semester[]): Semester | null {
  if (!session) return null;
  const now = Date.now();
  const inSession = semesters.filter((s) => s.session === session.id);
  return (
    inSession.find(
      (s) => new Date(s.start_date).getTime() <= now && now <= new Date(s.end_date).getTime(),
    ) ??
    inSession[0] ??
    null
  );
}
