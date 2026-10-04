// History.jsx - the signed-in customer's previous claims (GET /api/claims returns only their own).
import { useEffect, useState } from 'react';
import { api } from '../api.js';

const CLS = { 'APPROVE': 'ok', 'REFER TO ADVISOR': 'warn', 'REJECT': 'bad' };

export default function History() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => { api.history().then((r) => setRows(r.claims)).catch((e) => setError(e.message)); }, []);

  if (error) return <div className="alert">{error}</div>;
  if (!rows) return <div className="center muted">Loading…</div>;
  return (
    <div className="card">
      <h2>My claims</h2>
      {rows.length === 0 ? <p className="muted">You have not filed any claims yet.</p> : (
        <table>
          <thead><tr><th>Claim ID</th><th>Filed</th><th>Type</th><th>Competitor</th><th>Refund</th><th>Outcome</th></tr></thead>
          <tbody>{rows.map((c) => (
            <tr key={c.claimId}>
              <td><code>{c.claimId}</code></td><td>{new Date(c.submittedAt).toLocaleString()}</td><td>{c.bookingType}</td><td>{c.vendorName}</td>
              <td>{c.claimAmount.toLocaleString('en-US', { style: 'currency', currency: 'USD' })}</td>
              <td><span className={`pill ${CLS[c.decision]}`}>{c.decision} · {Math.round(c.probabilityApproved * 100)}%</span></td>
            </tr>))}
          </tbody>
        </table>
      )}
    </div>
  );
}
