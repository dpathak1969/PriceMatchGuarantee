// Login.jsx - sign-in screen. Sends credentials to POST /api/auth/login; on success the backend sets an
// httpOnly cookie (the browser JS never sees the token) and returns the user's display info.
import { useState } from 'react';
import { api } from '../api.js';

export default function Login({ onLogin }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false); // disables the button so a double click cannot send two requests

  const submit = async (e) => {
    e.preventDefault(); // stop the browser's default full-page form post
    setError('');
    setBusy(true);
    try {
      const { user } = await api.login(email.trim(), password);
      onLogin(user); // App switches to the claim form
    } catch (err) {
      setError(err.message); // e.g. "Incorrect email or password."
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <form className="card login" onSubmit={submit} noValidate>
        <div className="logo">✈</div>
        <h1>Price Match Guarantee</h1>
        <p className="muted">Found a better rate elsewhere? Sign in to file a claim.</p>

        <label htmlFor="email">Email</label>
        <input id="email" type="email" autoComplete="username" value={email} autoFocus
          onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />

        <label htmlFor="pw">Password</label>
        <input id="pw" type="password" autoComplete="current-password" value={password}
          onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />

        {error && <div className="alert" role="alert">{error}</div>}
        <button className="primary" disabled={busy || !email || !password}>{busy ? 'Signing in…' : 'Sign in'}</button>

        <div className="demo">
          <b>Demo accounts</b> (password <code>Passw0rd!</code>)
          {[['alice@example.com', 'Gold · clean history'], ['carol@example.com', 'Silver · mixed history'], ['bob@example.com', 'Standard · suspended account']].map(([m, d]) => (
            <button type="button" key={m} className="link" onClick={() => { setEmail(m); setPassword('Passw0rd!'); }}>{m} <span className="muted">— {d}</span></button>
          ))}
        </div>
      </form>
    </div>
  );
}
