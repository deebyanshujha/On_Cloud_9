import { useEffect, useMemo, useRef, useState } from "react";

interface Props {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
  /** Static, pre-loaded suggestion list — filtered client-side. */
  options?: string[];
  /**
   * Remote suggestion source (e.g. searchMedications/searchConditions) —
   * debounced, cancels stale requests, never blocks typing. Preferred over
   * `options` when a clean backend entity search exists, since it returns
   * real terminology-service names instead of whatever raw text happens to
   * already be in the local dataset.
   */
  fetchOptions?: (query: string) => Promise<string[]>;
}

const DEBOUNCE_MS = 250;

// Free-text input with dynamic suggestions — not a locked dropdown. Any text
// the user types is accepted (case creation is free-text by design); the
// dropdown is a convenience layer, never a hard requirement to pick from it.
export default function AutocompleteInput({
  value,
  onChange,
  placeholder,
  autoFocus,
  options,
  fetchOptions,
}: Props) {
  const [focused, setFocused] = useState(false);
  const [remoteMatches, setRemoteMatches] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [unreachable, setUnreachable] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const requestId = useRef(0);

  const staticMatches = useMemo(() => {
    if (!options) return [];
    const q = value.trim().toLowerCase();
    if (!q) return [];
    return options.filter((o) => o.toLowerCase().includes(q)).slice(0, 8);
  }, [value, options]);

  useEffect(() => {
    if (!fetchOptions) return;
    const q = value.trim();
    if (!q) {
      setRemoteMatches([]);
      setLoading(false);
      setUnreachable(false);
      return;
    }
    setLoading(true);
    const id = ++requestId.current;
    const timer = setTimeout(() => {
      fetchOptions(q)
        .then((names) => {
          if (requestId.current !== id) return; // stale response, ignore
          setRemoteMatches(names.slice(0, 10));
          setUnreachable(false);
        })
        .catch(() => {
          if (requestId.current !== id) return;
          setRemoteMatches([]);
          setUnreachable(true);
        })
        .finally(() => {
          if (requestId.current === id) setLoading(false);
        });
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [value, fetchOptions]);

  const matches = fetchOptions ? remoteMatches : staticMatches;
  const showDropdown = focused && (matches.length > 0 || loading || unreachable);

  return (
    <div className="autocomplete">
      <input
        ref={inputRef}
        className="form-input mono"
        type="text"
        value={value}
        placeholder={placeholder}
        autoFocus={autoFocus}
        onChange={(e) => onChange(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => setTimeout(() => setFocused(false), 120)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            setFocused(false);
            inputRef.current?.blur();
          } else if (e.key === "Enter") {
            setFocused(false);
            inputRef.current?.blur();
          }
        }}
      />
      {showDropdown && (
        <ul className="autocomplete-list">
          {loading && matches.length === 0 && (
            <li className="autocomplete-status">searching…</li>
          )}
          {!loading && unreachable && (
            <li className="autocomplete-status">
              couldn't reach search — you can still type freely
            </li>
          )}
          {matches.map((m) => (
            <li key={m}>
              <button
                type="button"
                className="autocomplete-option"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  onChange(m);
                  setFocused(false);
                }}
              >
                {m}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
