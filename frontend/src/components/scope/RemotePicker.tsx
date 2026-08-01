import { useEffect, useRef, useState } from "react";
import styles from "./scope.module.css";

export interface PickerOption {
  value: string;
  label: string;
  hint?: string;
}

export interface PickerResult {
  options: PickerOption[];
  count: number;
}

export function RemotePicker({
  value,
  valueLabel,
  placeholder,
  disabled = false,
  disabledHint,
  scopeKey,
  fetchOptions,
  onPick,
  emptyText,
  searchPlaceholder = "Type to search…",
  ariaLabel,
}: {
  value: string;
  valueLabel: string;
  placeholder: string;
  disabled?: boolean;
  disabledHint?: string;
  scopeKey: string;
  fetchOptions: (search: string) => Promise<PickerResult>;
  onPick: (option: PickerOption | null) => void;
  emptyText: string;
  searchPlaceholder?: string;
  ariaLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<PickerResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const root = useRef<HTMLDivElement | null>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);
  const fetchOptionsRef = useRef(fetchOptions);

  useEffect(() => {
    fetchOptionsRef.current = fetchOptions;
  });

  useEffect(() => {
    if (open) searchRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoading(true);
    setError(null);
    const timer = setTimeout(() => {
      fetchOptionsRef
        .current(query.trim())
        .then((r) => {
          if (active) setResult(r);
        })
        .catch(() => {
          if (active) setError("Could not load options.");
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    }, 300);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [open, query, scopeKey]);

  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  const options = result?.options ?? [];
  const hidden = result ? Math.max(result.count - options.length, 0) : 0;

  return (
    <div className={styles.picker} ref={root}>
      <div className={styles.pickerControl} data-disabled={disabled || undefined}>
        <button
          type="button"
          className={styles.pickerTrigger}
          disabled={disabled}
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-label={ariaLabel}
          onClick={() => setOpen((o) => !o)}
        >
          <span className={[styles.pickerValue, value ? "" : styles.pickerPlaceholder].join(" ")}>
            {value ? valueLabel : disabled ? (disabledHint ?? placeholder) : placeholder}
          </span>
        </button>
        {value ? (
          <button
            type="button"
            className={styles.pickerClear}
            aria-label="Clear selection"
            onClick={() => onPick(null)}
          >
            <svg
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            >
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        ) : (
          <svg
            className={styles.pickerCaret}
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="m6 9 6 6 6-6" />
          </svg>
        )}
      </div>

      {open ? (
        <div className={styles.pop}>
          <input
            ref={searchRef}
            className={styles.popSearch}
            type="search"
            value={query}
            placeholder={searchPlaceholder}
            aria-label={searchPlaceholder}
            onChange={(e) => setQuery(e.target.value)}
          />
          {loading ? (
            <p className={styles.popNote}>Searching…</p>
          ) : error ? (
            <p className={styles.popNote}>{error}</p>
          ) : options.length === 0 ? (
            <p className={styles.popNote}>{query ? "No matches for that search." : emptyText}</p>
          ) : (
            <ul className={styles.popList} role="listbox">
              {options.map((o) => (
                <li key={o.value}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={o.value === value}
                    className={[styles.popItem, o.value === value ? styles.popItemActive : ""].join(
                      " ",
                    )}
                    onClick={() => {
                      onPick(o);
                      setOpen(false);
                    }}
                  >
                    <span className={styles.popItemMain}>{o.label}</span>
                    {o.hint ? <span className={styles.popItemHint}>{o.hint}</span> : null}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {hidden > 0 ? (
            <div className={styles.popFoot}>
              {hidden.toLocaleString()} more — keep typing to narrow.
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
