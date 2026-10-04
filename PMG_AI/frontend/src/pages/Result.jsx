// Result.jsx - shows the ML prediction. The claimId displayed is the one generated when the form opened.
const COPY = { // plain-language wording for each model decision
  'APPROVE': { cls: 'ok', icon: '✓', title: 'Likely approved', text: 'Your claim looks strong. It has been recorded and will move to payout processing.' },
  'REFER TO ADVISOR': { cls: 'warn', icon: '!', title: 'Needs an advisor to review', text: 'Your claim is borderline. A price match advisor will review it and contact you.' },
  'REJECT': { cls: 'bad', icon: '✕', title: 'Unlikely to qualify', text: 'Based on the details provided this claim does not meet the guarantee terms.' },
};
const money = (n) => n.toLocaleString('en-US', { style: 'currency', currency: 'USD' });

export default function Result({ result: r, onNew, onHistory }) {
  const c = COPY[r.decision];
  const pct = Math.round(r.probabilityApproved * 100);
  const lo = (r.threshold - r.referBand) * 100; // start of the "advisor review" band
  const hi = (r.threshold + r.referBand) * 100; // end of the band
  return (
    <div className="card result">
      <div className="claimid inline"><small>Claim ID</small><b>{r.claimId}</b></div>
      <div className={`badge ${c.cls}`}>{c.icon}</div>
      <h1>{c.title}</h1>
      <p className="muted">{c.text}</p>

      {/* probability meter: coloured zones = reject / advisor / approve, marker = this claim */}
      <div className="meter" aria-label={`Approval likelihood ${pct}%`}>
        <div className="zones"><i style={{ width: `${lo}%` }} className="bad" /><i style={{ width: `${hi - lo}%` }} className="warn" /><i style={{ width: `${100 - hi}%` }} className="ok" /></div>
        <div className="marker" style={{ left: `${pct}%` }}><span>{pct}%</span></div>
      </div>
      <div className="legend"><span>Reject</span><span>Advisor review</span><span>Approve</span></div>

      <dl className="facts">
        <div><dt>Refund requested</dt><dd>{money(r.claimAmount)}</dd></div>
        <div><dt>Price gap</dt><dd>{r.signals.rateDifferencePercent}%</dd></div>
        <div><dt>Meets minimum gap (3%)</dt><dd>{r.signals.minimumThresholdMet ? 'Yes' : 'No'}</dd></div>
        <div><dt>Filed</dt><dd>{r.signals.claimSubmittedRelativeToTravel.toLowerCase()}</dd></div>
      </dl>
      <div className="actions"><button className="primary" onClick={onNew}>File another claim</button><button className="link" onClick={onHistory}>View my claims</button></div>
    </div>
  );
}
