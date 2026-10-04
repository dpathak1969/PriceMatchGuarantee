// users.js - demo user directory. In production replace this module with your identity provider /
// customer database; the rest of the app only depends on findByEmail()/findById() and the shape returned.
// The `profile` is TRUSTED account data (loyalty tier, history...) that the model needs. It comes from
// the server, never from the browser, so a customer cannot edit their own loyalty tier or history.
const bcrypt = require('bcryptjs');

const DEMO_PASSWORD = 'Passw0rd!'; // demo only - documented in Instructions.md
const raw = [
  { id: 'u1', email: 'alice@example.com', name: 'Alice Johnson',
    profile: { LoyaltyMemberSinceDate: '2019-06-01', LoyaltyTier: 'Gold', AccountStatus: 'Active',
      CustomerLifetimeValue: 4200, PriorClaimsCount: 5, PriorApprovedClaimsCount: 5 } },
  { id: 'u2', email: 'bob@example.com', name: 'Bob Martinez',
    profile: { LoyaltyMemberSinceDate: '2024-06-15', LoyaltyTier: 'Standard', AccountStatus: 'Suspended',
      CustomerLifetimeValue: 280, PriorClaimsCount: 3, PriorApprovedClaimsCount: 0 } },
  { id: 'u3', email: 'carol@example.com', name: 'Carol Nguyen',
    profile: { LoyaltyMemberSinceDate: '2021-11-11', LoyaltyTier: 'Silver', AccountStatus: 'Active',
      CustomerLifetimeValue: 2100, PriorClaimsCount: 2, PriorApprovedClaimsCount: 1 } },
];
// Hash once at start-up. Only hashes are kept in memory, never the clear-text password.
const users = raw.map((u) => ({ ...u, passwordHash: bcrypt.hashSync(DEMO_PASSWORD, 10) }));
// A throw-away hash so login takes the same time whether or not the email exists (no user enumeration).
const DUMMY_HASH = bcrypt.hashSync('not-a-real-password', 10);

const findByEmail = (email) => users.find((u) => u.email === String(email).trim().toLowerCase());
const findById = (id) => users.find((u) => u.id === id);

module.exports = { findByEmail, findById, DUMMY_HASH };
