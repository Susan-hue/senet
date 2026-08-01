import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../../services/api";

interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export function useAsyncData<T>(
  fetcher: () => Promise<T>,
  deps: ReadonlyArray<unknown>,
): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const reload = useCallback(() => setTick((n) => n + 1), []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    fetcher()
      .then((result) => {
        if (active) setData(result);
      })
      .catch((err) => {
        if (!active) return;
        setError(err instanceof ApiError ? err.message : "Unable to load data.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  return { data, loading, error, reload };
}

interface AsyncActionState {
  pending: boolean;
  message: string | null;
  errors: Record<string, string[]> | null;
  /** Show a problem the form caught itself, without calling the API. */
  fail: (problem: string | Record<string, string[]>) => void;
  reset: () => void;
  run: (action: () => Promise<unknown>) => Promise<boolean>;
}

/**
 * Run a write (save, delete, ratify) and hold what the form needs to render it:
 * whether it is in flight, the message to show if it failed, and the per-field
 * errors the API returned. `run` reports success so a caller can branch, and
 * leaves `pending` set on success — the screen it belongs to is on its way out.
 */
export function useAsyncAction(fallbackMessage: string): AsyncActionState {
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string[]> | null>(null);

  const reset = useCallback(() => {
    setMessage(null);
    setErrors(null);
  }, []);

  const fail = useCallback((problem: string | Record<string, string[]>) => {
    setMessage(typeof problem === "string" ? problem : null);
    setErrors(typeof problem === "string" ? null : problem);
  }, []);

  const run = useCallback(
    async (action: () => Promise<unknown>) => {
      setPending(true);
      setMessage(null);
      setErrors(null);
      try {
        await action();
        return true;
      } catch (err) {
        if (err instanceof ApiError) {
          setMessage(err.message);
          setErrors(err.fieldErrors);
        } else {
          setMessage(fallbackMessage);
        }
        setPending(false);
        return false;
      }
    },
    [fallbackMessage],
  );

  return { pending, message, errors, fail, reset, run };
}

export function useDebounced<T>(value: T, delayMs = 350): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}
