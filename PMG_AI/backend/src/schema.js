// schema.js - server-side validation of everything the customer typed (zod). The UI validates too, but
// the browser is untrusted: this is the validation that actually protects the system.
const { z } = require('zod');
const o = require('./options');

const vals = (arr) => arr.map((x) => (typeof x === 'string' ? x : x.value)); // option list -> allowed values
const blankToUndef = (s) => (s === '' ? undefined : s); // empty form fields arrive as '' -> treat as "not provided"
const isoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'Use a valid date')
  .refine((s) => !Number.isNaN(Date.parse(s)), 'Use a valid date');
const money = z.coerce.number({ invalid_type_error: 'Enter an amount' }).positive('Must be greater than 0')
  .max(250000, 'Amount is too large');

const claimInput = z.object({
  bookingType: z.enum(vals(o.BOOKING_TYPES)),
  bookingChannel: z.enum(vals(o.BOOKING_CHANNELS)),
  bookingAmount: money,
  betterRateAmount: money,
  bookingDate: isoDate,
  travelStartDate: isoDate,
  travelEndDate: isoDate,
  vendorName: z.enum(vals(o.VENDORS)),
  betterRateUrl: z.preprocess(blankToUndef, z.string().trim().url('Enter a full link starting with https://')
    .regex(/^https?:\/\//i, 'Link must start with http(s)://').max(500).optional()),
  flexibility: z.enum(vals(o.FLEXIBILITY)),
  specialConsiderations: z.enum(vals(o.SPECIAL)).default('None'),
  proofType: z.preprocess(blankToUndef, z.enum(vals(o.PROOF_TYPES)).optional()),
  proofClarity: z.preprocess(blankToUndef, z.enum(vals(o.PROOF_CLARITY)).optional()),
  restrictionsMatch: z.boolean(),
  blackoutOrExcluded: z.boolean(),
  multiSegment: z.boolean(),
  familyBooking: z.boolean(),
  passengers: z.coerce.number().int().min(1).max(20),
  advisorTenure: z.enum(vals(o.ADVISOR_TENURE)).default('unknown'),
  pointsRequested: z.coerce.number().int().min(0).max(1000000).default(0),
  comments: z.string().trim().max(500, 'Keep comments under 500 characters').optional().default(''),
  claimId: z.string().regex(/^CLM-\d{8}-[0-9A-F]{6}$/, 'Invalid claim id'),
}).strict() // unknown keys are rejected, not silently ignored
  .superRefine((v, ctx) => { // cross-field rules that single-field checks cannot express
    const add = (path, message) => ctx.addIssue({ code: 'custom', path: [path], message });
    const today = new Date().toISOString().slice(0, 10);
    if (v.betterRateAmount >= v.bookingAmount) add('betterRateAmount', 'The competitor price must be lower than what you paid');
    if (v.bookingDate > today) add('bookingDate', 'Booking date cannot be in the future');
    if (v.travelStartDate < v.bookingDate) add('travelStartDate', 'Travel cannot start before the booking date');
    if (v.travelEndDate < v.travelStartDate) add('travelEndDate', 'Travel end cannot be before travel start');
  });

module.exports = { claimInput };
