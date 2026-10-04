// claims.js - claim business logic: dynamic claim IDs, translating the friendly form into the exact raw
// fields the ML model expects (see demo_claims.py), and a tiny append-only claim log.
// Swap the log for a real database in production; the function signatures can stay the same.
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const config = require('./config');
const { ADVISOR_TENURE } = require('./options');

// ---------------------------------------------------------------- claim ID issuing
// A claim ID is issued when the customer OPENS the form, then reused for the upload, the ML call and the
// result, so every system sees one identifier. IDs are single-use and bound to the user that requested them.
const issued = new Map(); // claimId -> { userId, expires, used }
const ID_TTL_MS = 60 * 60 * 1000; // an unused ID expires after 1 hour

function issueClaimId(userId) {
  const d = new Date().toISOString().slice(0, 10).replace(/-/g, ''); // YYYYMMDD
  const id = `CLM-${d}-${crypto.randomBytes(3).toString('hex').toUpperCase()}`; // 24 random bits -> e.g. CLM-20261004-9F3A1C
  issued.set(id, { userId, expires: Date.now() + ID_TTL_MS, used: false });
  for (const [k, v] of issued) if (v.expires < Date.now()) issued.delete(k); // opportunistic cleanup of old IDs
  return id;
}

// Returns true only if the ID was issued to this user, is fresh and has not been submitted yet.
function consumeClaimId(claimId, userId) {
  const rec = issued.get(claimId);
  if (!rec || rec.userId !== userId || rec.used || rec.expires < Date.now()) return false;
  rec.used = true; // mark used BEFORE scoring so a double-click cannot create two claims
  return true;
}
// If scoring fails we hand the ID back so the customer can simply press Submit again with the same ID.
const releaseClaimId = (claimId) => { const r = issued.get(claimId); if (r) r.used = false; };

// ---------------------------------------------------------------- form -> model payload
const pad = (n) => String(n).padStart(2, '0');
const nowStamp = () => { // local "YYYY-MM-DD HH:mm", the format demo_claims.py uses for ClaimSubmissionDate
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

// input: validated customer answers; profile: trusted account data; attachmentCount: files actually accepted.
function buildMlPayload(input, profile, attachmentCount) {
  const hasProof = Boolean(input.proofType);
  const claimAmount = Math.round((input.bookingAmount - input.betterRateAmount) * 100) / 100; // refund requested
  return {
    ClaimID: input.claimId, // same ID the customer saw; the ML service echoes it back
    BookingType: input.bookingType,
    BookingChannel: input.bookingChannel,
    ClaimSubmissionChannel: 'Web', // this portal IS the web channel, so we do not ask
    BookingAmount: input.bookingAmount,
    BetterRateAmount: input.betterRateAmount,
    ClaimAmount: claimAmount, // computed, not typed: removes a field that could contradict the two prices
    ClaimPoints: input.pointsRequested,
    BookingDate: input.bookingDate,
    TravelStartDate: input.travelStartDate,
    TravelEndDate: input.travelEndDate,
    ClaimSubmissionDate: nowStamp(), // server clock = tamper-proof "when filed"
    ...profile, // LoyaltyTier, AccountStatus, history ... from the server, not the browser
    ProofType: hasProof ? input.proofType : null,
    ProofQualityFlag: hasProof ? input.proofClarity : 'Insufficient', // no proof => always insufficient
    AttachmentCount: attachmentCount,
    RestrictionsMatchFlag: input.restrictionsMatch,
    BlackoutDateOrExcludedFare: input.blackoutOrExcluded,
    IsMultiSegmentBooking: input.multiSegment,
    BetterRateURL: input.betterRateUrl || null,
    BetterRateVendorName: input.vendorName,
    FareOrRatePlanFlexibility: input.flexibility,
    BookingSpecialConsiderations: input.specialConsiderations === 'None' ? null : input.specialConsiderations,
    NumberOfPassengers: input.passengers,
    IsFamilyBooking: input.familyBooking,
    AdvisorTenureMonths: ADVISOR_TENURE.find((a) => a.value === input.advisorTenure).months,
    CustomerComments: input.comments || null,
  };
}

// ---------------------------------------------------------------- claim log (JSON Lines file)
const logFile = path.join(config.dataDir, 'claims.jsonl');
fs.mkdirSync(config.dataDir, { recursive: true });
const history = fs.existsSync(logFile) // load previous claims into memory at start-up
  ? fs.readFileSync(logFile, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l)) : [];

function saveClaim(record) {
  history.push(record);
  fs.appendFileSync(logFile, JSON.stringify(record) + '\n'); // append-only: cheap and crash-safe enough for a demo
}
const claimsForUser = (userId) => history.filter((c) => c.userId === userId).reverse(); // newest first

module.exports = { issueClaimId, consumeClaimId, releaseClaimId, buildMlPayload, saveClaim, claimsForUser };
