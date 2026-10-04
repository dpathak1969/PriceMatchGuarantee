// options.js - the dropdown choices. They mirror the categories the ML model was trained on, so the
// UI can only ever send values the model understands. Served to the UI by GET /api/claims/options so
// the React app never hard-codes them (one source of truth).
const BOOKING_TYPES = ['Flight', 'Hotel/Lodging', 'Car', 'Cruise', 'Package'];
const BOOKING_CHANNELS = [
  { value: 'PTS Web', label: 'PTS website' },
  { value: 'App', label: 'PTS mobile app' },
  { value: 'Agent-Assisted', label: 'Through a travel advisor' },
];
const VENDORS = ['Expedia', 'Booking.com', 'Kayak', 'Priceline', 'Orbitz', 'Travelocity', 'Hotels.com',
  'Agoda', 'Direct Airline Site', 'Vendor Direct'];
const FLEXIBILITY = [
  { value: 'Refundable', label: 'Refundable' },
  { value: 'Partially Flexible', label: 'Partially flexible' },
  { value: 'Change Fee Applies', label: 'Changes allowed with a fee' },
  { value: 'Non-Refundable', label: 'Non-refundable' },
];
const SPECIAL = ['None', 'Companion fare', 'Corporate rate', 'Group booking', 'Honeymoon package',
  'Military discount', 'Senior discount', 'Travel agent override'];
const PROOF_TYPES = [
  { value: 'PDF Quote', label: 'PDF quote' },
  { value: 'Screenshot', label: 'Screenshot' },
  { value: 'Confirmation Email', label: 'Confirmation email' },
];
// The customer cannot know our internal "proof quality" rating, so we ask a plain-language question.
const PROOF_CLARITY = [
  { value: 'Verified', label: 'Clearly shows the same trip, dates and price' },
  { value: 'Ambiguous', label: 'Partly clear (some details are missing)' },
  { value: 'Insufficient', label: 'Not clear' },
];
// Advisor tenure bucket -> months (the model uses months). "Not sure" maps to the dataset average.
const ADVISOR_TENURE = [
  { value: 'unknown', label: 'Not sure / no advisor', months: 72 },
  { value: 'lt1', label: 'Less than 1 year', months: 6 },
  { value: '1to3', label: '1 - 3 years', months: 24 },
  { value: '3to6', label: '3 - 6 years', months: 54 },
  { value: 'gt6', label: 'More than 6 years', months: 96 },
];

module.exports = { BOOKING_TYPES, BOOKING_CHANNELS, VENDORS, FLEXIBILITY, SPECIAL, PROOF_TYPES, PROOF_CLARITY, ADVISOR_TENURE };
