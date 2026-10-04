// api.js - the only place the UI talks to the backend. Every call uses relative /api URLs (same origin)
// and credentials: 'include' so the browser sends the httpOnly login cookie automatically.

// Wraps fetch: parses JSON, and throws an Error carrying .status and .fields on any non-2xx answer.
async function request(path, init = {}) {
  let res;
  try {
    res = await fetch(`/api${path}`, { credentials: 'include', ...init });
  } catch {
    throw Object.assign(new Error('Cannot reach the server. Check your connection and try again.'), { status: 0 });
  }
  const data = await res.json().catch(() => ({})); // an error page may not be JSON
  if (!res.ok) throw Object.assign(new Error(data.error || 'Something went wrong.'), { status: res.status, fields: data.fields });
  return data;
}

const json = (body) => ({ headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

export const api = {
  login: (email, password) => request('/auth/login', { method: 'POST', ...json({ email, password }) }),
  logout: () => request('/auth/logout', { method: 'POST' }),
  me: () => request('/auth/me'), // restores the session after a page refresh
  options: () => request('/claims/options'), // dropdown values
  newClaimId: () => request('/claims/draft', { method: 'POST' }), // dynamic claim id
  history: () => request('/claims'),
  // Claims go as multipart: the JSON in one field, the proof files as separate parts.
  submitClaim: (claim, files) => {
    const fd = new FormData();
    fd.append('claim', JSON.stringify(claim));
    files.forEach((f) => fd.append('proofFiles', f));
    return request('/claims', { method: 'POST', body: fd }); // browser sets the multipart boundary itself
  },
};
