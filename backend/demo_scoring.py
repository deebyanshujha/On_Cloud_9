"""Manual, human-readable demo of the scoring engine using the hardcoded
known-cases fixture. Run with: python demo_scoring.py
"""
from datetime import date

from app.core.fixtures import load_known_cases
from app.core.scoring import run_comparison


def main() -> None:
    documents, approved = load_known_cases()
    signals = run_comparison(documents, approved, today=date.today())

    print(f"Loaded {len(documents)} documents, {len(approved)} approved indications.\n")
    print(f"Found {len(signals)} repurposing signal(s):\n")

    for s in signals:
        print(f"  {s.drug} -> {s.disease}  (score: {s.score})")
        print(f"    approved for: {', '.join(s.approved_for) or 'nothing on file'}")
        print(f"    reasons: {'; '.join(s.reasons)}")
        print(f"    supporting docs: {len(s.supporting_documents)}")
        print()


if __name__ == "__main__":
    main()
