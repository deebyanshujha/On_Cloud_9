import { useMemo, useRef, useState } from "react";

interface Props {
  value: string;
  onChange: (value: string) => void;
  options: string[];
  placeholder?: string;
  autoFocus?: boolean;
}

// Free-text input with dynamic, data-derived suggestions — not a locked
// dropdown. Any text the user types is accepted (case creation is free-text
// per the backend brief); suggestions are just a convenience layer over
// whatever diseases/drugs already exist in the ingested data.
export default function AutocompleteInput({ value, onChange, options, placeholder, autoFocus }: Props) {
  const [focused, setFocused] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const matches = useMemo(() => {
    const q = value.trim().toLowerCase();
    if (!q) return [];
    return options.filter((o) => o.toLowerCase().includes(q)).slice(0, 8);
  }, [value, options]);

  const showSuggestions = focused && matches.length > 0;

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
      {showSuggestions && (
        <ul className="autocomplete-list">
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
