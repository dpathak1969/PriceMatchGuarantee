// App.jsx - top-level shell. Decides which screen to show:
//   not signed in -> Login | signed in -> header + (New claim form | Result | My claims)
import { useEffect, useState } from 'react';
import { api } from './api.js';
import Login from './pages/Login.jsx';
import ClaimForm from './pages/ClaimForm.jsx';
import Result from './pages/Result.jsx';
import History from './pages/History.jsx';

export default function App() {
  const [user, setUser] = useState(null); // signed-in customer, or null
  const [booting, setBooting] = useState(true); // true while we check for an existing session cookie
  const [view, setView] = useState('form'); // 'form' | 'result' | 'history'
  const [result, setResult] = useState(null); // the last prediction returned by the backend
  const [formKey, setFormKey] = useState(0); // bumping this remounts the form => fresh claim id + empty fields

  // On first load, ask the backend whether the cookie is still valid so a refresh does not log the user out.
  useEffect(() => {
    api.me().then((r) => setUser(r.user)).catch(() => setUser(null)).finally(() => setBooting(false));
  }, []);

  if (booting) return <div className="center muted">Loading…</div>;
  if (!user) return <Login onLogin={setUser} />;

  const logout = async () => { await api.logout().catch(() => {}); setUser(null); setView('form'); setResult(null); };
  const startNew = () => { setResult(null); setFormKey((k) => k + 1); setView('form'); };

  return (
    <>
      <header className="topbar">
        <div className="brand">✈ Price Match Guarantee</div>
        <nav>
          <button className={`tab ${view !== 'history' ? 'on' : ''}`} onClick={startNew}>New claim</button>
          <button className={`tab ${view === 'history' ? 'on' : ''}`} onClick={() => setView('history')}>My claims</button>
        </nav>
        <div className="who">
          <span>{user.name} · <b>{user.loyaltyTier}</b></span>
          <button className="link" onClick={logout}>Sign out</button>
        </div>
      </header>
      <main className="container">
        {view === 'form' && (
          <ClaimForm key={formKey} onDone={(r) => { setResult(r); setView('result'); }}
            onSessionExpired={() => setUser(null)} />
        )}
        {view === 'result' && <Result result={result} onNew={startNew} onHistory={() => setView('history')} />}
        {view === 'history' && <History />}
      </main>
    </>
  );
}
