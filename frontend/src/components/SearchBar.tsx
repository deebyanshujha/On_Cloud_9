interface Props {
  value: string;
  onChange: (value: string) => void;
}

export default function SearchBar({ value, onChange }: Props) {
  return (
    <div className="search-wrap">
      <div className="search-field">
        <span className="search-icon">&#9906;</span>
        <input
          className="search-input mono"
          type="text"
          placeholder="search drug or disease..."
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      </div>
    </div>
  );
}
