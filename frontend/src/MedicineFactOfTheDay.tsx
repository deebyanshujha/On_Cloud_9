import { useMemo } from "react";

const FACTS: string[] = [
  "Taking medicines at the same time every day helps your body absorb them consistently.",
  "Never mix medicines without consulting your doctor or pharmacist first.",
  "Always finish your full course of antibiotics, even if you feel better midway.",
  "Store most medicines in a cool, dry place — not the bathroom, where humidity can degrade them.",
  "Generic medicines contain the same active ingredient as branded ones, at a lower cost.",
  "Drinking a full glass of water with tablets helps them dissolve and absorb properly.",
  "Expired medicines can lose effectiveness or become harmful — always check the date.",
  "Vaccines work by training your immune system to recognize and fight specific diseases.",
];

function getDayIndex(length: number): number {
  const today = new Date();
  const start = new Date(today.getFullYear(), 0, 0);
  const dayOfYear = Math.floor((today.getTime() - start.getTime()) / 86_400_000);
  return dayOfYear % length;
}

export default function MedicineFactOfTheDay() {
  const fact = useMemo(() => FACTS[getDayIndex(FACTS.length)], []);
  const today = useMemo(
    () => new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" }),
    []
  );

  return (
    <div
      style={{
        background: "linear-gradient(135deg, #fff7f5 0%, #fdf1ee 100%)",
        border: "1px solid #f0d9d3",
        borderRadius: "10px",
        padding: "24px 28px",
        marginBottom: "20px",
        display: "flex",
        alignItems: "flex-start",
        gap: "18px",
      }}
    >
      <span style={{ fontSize: "34px", lineHeight: 1 }}>💊</span>
      <div>
        <div
          style={{
            fontSize: "12px",
            fontWeight: 600,
            letterSpacing: "0.06em",
            color: "#b5493a",
            marginBottom: "8px",
          }}
        >
          {today}
        </div>
        <p
          style={{
            margin: 0,
            fontSize: "24px",
            fontWeight: 700,
            lineHeight: 1.4,
            color: "#2a2320",
            fontFamily: "Georgia, 'Times New Roman', serif",
          }}
        >
          {fact}
        </p>
      </div>
    </div>
  );
}
