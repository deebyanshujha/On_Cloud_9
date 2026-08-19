interface Props {
  prominent?: boolean;
}

// Non-negotiable per the brief: every screen that renders case-analysis
// output carries this, verbatim. `prominent` renders it as a banner (case
// results screen); otherwise it's the compact footer-style strip used
// globally.
export default function Disclaimer({ prominent }: Props) {
  const text =
    "This platform provides research intelligence and is not a medical diagnosis, prescription, or treatment recommendation.";

  if (prominent) {
    return (
      <div className="disclaimer-banner">
        <span className="disclaimer-icon">ⓘ</span>
        <span>{text}</span>
      </div>
    );
  }

  return <div className="disclaimer-strip">{text}</div>;
}
