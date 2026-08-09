"""
Synthetic dataset generator for Prestige Travel Services (PTS) — Best Rate
Guarantee (BRG) claims. Implements the schema, derived features, and
rule-based label-generation logic described in Prompt.md (Sections 4-7).

Usage:
    python scripts/generate_synthetic_data.py [--n 9000] [--seed 42] [--out data/brg_claims.csv]
"""

import argparse
import json
import math
import random
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from faker import Faker

# --------------------------------------------------------------------------
# Config / lookup tables
# --------------------------------------------------------------------------

BOOKING_TYPES = ["Flight", "Hotel/Lodging", "Package", "Car", "Cruise"]
BOOKING_TYPE_WEIGHTS = [0.35, 0.30, 0.15, 0.12, 0.08]

CLAIM_CHANNELS = ["Web", "Mobile App", "Call Center", "Email", "Travel Agent"]
CLAIM_CHANNEL_WEIGHTS = [0.40, 0.25, 0.15, 0.12, 0.08]

CLAIM_STATUS_TERMINAL = ["Approved", "Rejected", "Closed"]

BOOKING_CHANNELS = ["PTS Web", "App", "Agent-Assisted"]
BOOKING_CHANNEL_WEIGHTS = [0.5, 0.3, 0.2]

CURRENCIES = ["USD"] * 92 + ["EUR", "GBP", "CAD", "AUD"] * 2  # ~92% USD

FLEXIBILITY = ["Refundable", "Non-Refundable", "Partially Flexible", "Change Fee Applies"]
FLEXIBILITY_WEIGHTS = [0.20, 0.35, 0.30, 0.15]

LOYALTY_TIERS = ["Standard", "Silver", "Gold", "Platinum"]
LOYALTY_TIER_WEIGHTS = [0.45, 0.30, 0.18, 0.07]
LOYALTY_TIER_ORDINAL = {"Standard": 0, "Silver": 1, "Gold": 2, "Platinum": 3}

ACCOUNT_STATUSES = ["Active"] * 90 + ["Suspended"] * 3 + ["VIP-Flagged"] * 7

PROOF_TYPES = ["Screenshot", "PDF Quote", "Confirmation Email", "None"]
PROOF_TYPE_WEIGHTS = [0.40, 0.30, 0.20, 0.10]

BETTER_RATE_VENDORS = [
    "Expedia", "Booking.com", "Vendor Direct", "Priceline", "Hotels.com",
    "Kayak", "Orbitz", "Travelocity", "Agoda", "Direct Airline Site",
]

REFUND_METHODS = ["Original Payment Method", "Travel Credit", "Loyalty Points", "Split"]
REFUND_METHOD_WEIGHTS = [0.45, 0.25, 0.15, 0.15]

AIRLINES = ["Delta", "United", "American", "Southwest", "JetBlue", "Alaska", "Lufthansa", "British Airways"]
FARE_CLASSES = ["Economy", "Premium", "Business", "First"]
FARE_CLASS_WEIGHTS = [0.65, 0.18, 0.13, 0.04]
FARE_TYPES = ["Basic", "Standard", "Flex"]
AIRPORTS = ["JFK", "LAX", "ORD", "ATL", "DFW", "SFO", "SEA", "MIA", "BOS", "LHR", "CDG", "FRA", "DXB", "SIN"]

ROOM_TYPES = ["Standard", "Deluxe", "Suite", "Executive", "Family Room"]
MEAL_PLANS = ["Room Only", "Breakfast Included", "Half Board", "Full Board", "All-Inclusive"]

RENTAL_COMPANIES = ["Hertz", "Avis", "Enterprise", "Budget", "National", "Sixt"]
VEHICLE_CLASSES = ["Economy", "Compact", "SUV", "Luxury", "Minivan", "Convertible"]

CRUISE_LINES = ["Royal Caribbean", "Carnival", "Norwegian", "Princess", "Celebrity", "MSC"]
CABIN_TYPES = ["Interior", "Ocean View", "Balcony", "Suite"]
PORTS = ["Nassau", "Cozumel", "St. Thomas", "Roatan", "Grand Cayman", "Barcelona", "Rome", "Santorini"]

SPECIAL_CONSIDERATIONS = [
    "", "", "", "Group booking", "Corporate rate", "Companion fare",
    "Honeymoon package", "Senior discount", "Military discount", "Travel agent override",
]

APPROVAL_REASONS = [
    "Verified matching rate with equivalent terms",
    "Documentation sufficient and rate independently confirmed",
    "Within all program eligibility guidelines",
]

REJECTION_REASONS = [
    "Restrictions/flexibility do not match",
    "Insufficient or unverifiable documentation",
    "Rate no longer available at time of verification",
    "Competing rate not from an eligible/comparable vendor",
    "Price difference below minimum threshold",
    "Claim submitted after travel completed",
    "Blackout date / excluded fare or rate plan",
]

ADVISOR_COST_PER_HOUR = 50.0
SLA_TARGET_HOURS = 24


def weighted_choice(rng, options, weights):
    return rng.choices(options, weights=weights, k=1)[0]


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


# --------------------------------------------------------------------------
# Customer pool
# --------------------------------------------------------------------------

def generate_customers(n_customers, fake, rng, np_rng):
    customers = []
    for i in range(n_customers):
        tier = weighted_choice(rng, LOYALTY_TIERS, LOYALTY_TIER_WEIGHTS)
        member_since = fake.date_between(start_date="-10y", end_date="-30d")
        clv = round(float(np_rng.lognormal(mean=7.2, sigma=0.9)), 2)  # ~$1,300 median, long tail
        customers.append({
            "CustomerID": f"PTS-CUST-{i+1:06d}",
            "FirstName": fake.first_name(),
            "LastName": fake.last_name(),
            "Phone": fake.numerify("###-###-####"),
            "Email": fake.free_email(),
            "AddressStreet": fake.street_address(),
            "AddressCity": fake.city(),
            "AddressState": fake.state_abbr(),
            "AddressZip": fake.zipcode(),
            "AddressCountry": "USA",
            "LoyaltyTier": tier,
            "LoyaltyMemberSinceDate": member_since,
            "CustomerLifetimeValue": clv,
            "AccountStatus": random.choice(ACCOUNT_STATUSES),
            "_claim_history": [],  # list of bools (approved?), built up as claims are generated
        })
    return customers


# --------------------------------------------------------------------------
# Per-claim booking detail generation
# --------------------------------------------------------------------------

def generate_booking_type_fields(booking_type, rng, fake, np_rng):
    fields = {
        "Airline": "", "FareClass": "", "Origin": "", "Destination": "",
        "NumberOfStops": "", "FareType": "",
        "PropertyName": "", "RoomType": "", "StarRating": "", "MealPlan": "",
        "CheckInDate": "", "CheckOutDate": "", "NumberOfRooms": "",
        "RentalCompany": "", "VehicleClass": "", "PickupLocation": "",
        "DropoffLocation": "", "RentalDurationDays": "",
        "CruiseLine": "", "ShipName": "", "CabinType": "", "PortsOfCall": "",
        "NightsDuration": "",
        "SegmentList": "",
    }

    if booking_type == "Flight":
        origin, dest = rng.sample(AIRPORTS, 2)
        fields.update({
            "Airline": random.choice(AIRLINES),
            "FareClass": weighted_choice(rng, FARE_CLASSES, FARE_CLASS_WEIGHTS),
            "Origin": origin,
            "Destination": dest,
            "NumberOfStops": int(np_rng.choice([0, 1, 2], p=[0.55, 0.35, 0.10])),
            "FareType": random.choice(FARE_TYPES),
        })
    elif booking_type == "Hotel/Lodging":
        fields.update({
            "PropertyName": f"{fake.city()} {random.choice(['Grand Hotel', 'Resort & Spa', 'Inn', 'Suites', 'Plaza Hotel'])}",
            "RoomType": random.choice(ROOM_TYPES),
            "StarRating": int(np_rng.choice([2, 3, 4, 5], p=[0.05, 0.30, 0.45, 0.20])),
            "MealPlan": random.choice(MEAL_PLANS),
            "NumberOfRooms": int(np_rng.choice([1, 2, 3], p=[0.75, 0.20, 0.05])),
        })
    elif booking_type == "Car":
        pickup, dropoff = rng.sample(AIRPORTS, 2) if rng.random() < 0.3 else (fake.city(), fake.city())
        fields.update({
            "RentalCompany": random.choice(RENTAL_COMPANIES),
            "VehicleClass": random.choice(VEHICLE_CLASSES),
            "PickupLocation": pickup,
            "DropoffLocation": dropoff,
            "RentalDurationDays": int(np_rng.integers(1, 15)),
        })
    elif booking_type == "Cruise":
        n_ports = int(np_rng.integers(1, 5))
        fields.update({
            "CruiseLine": random.choice(CRUISE_LINES),
            "ShipName": f"MS {fake.first_name()}",
            "CabinType": random.choice(CABIN_TYPES),
            "PortsOfCall": json.dumps(rng.sample(PORTS, min(n_ports, len(PORTS)))),
            "NightsDuration": int(np_rng.integers(3, 15)),
        })
    elif booking_type == "Package":
        n_segments = int(np_rng.choice([2, 3, 4], p=[0.5, 0.35, 0.15]))
        segment_types = rng.sample(["Flight", "Hotel/Lodging", "Car", "Cruise"], k=min(n_segments, 4))
        segments = []
        for si, stype in enumerate(segment_types):
            segments.append({
                "SegmentID": f"SEG-{si+1}",
                "SegmentType": stype,
                "SegmentAmount": round(float(np_rng.uniform(80, 1800)), 2),
                "SegmentDates": fake.date_between(start_date="-1y", end_date="+180d").isoformat(),
            })
        fields["SegmentList"] = json.dumps(segments)

    return fields


def generate_passengers(n_passengers, fake, rng, np_rng):
    passengers = []
    has_child = False
    for i in range(n_passengers):
        if i == 0:
            ptype = "Adult"
        else:
            ptype = weighted_choice(rng, ["Adult", "Child", "Infant"], [0.55, 0.30, 0.15])
        if ptype == "Adult":
            age = int(np_rng.integers(18, 75))
        elif ptype == "Child":
            age = int(np_rng.integers(2, 17))
            has_child = True
        else:
            age = int(np_rng.integers(0, 2))
            has_child = True
        passengers.append({
            "PassengerID": f"PAX-{i+1}",
            "Name": fake.name(),
            "Age": age,
            "PassengerType": ptype,
            "LoyaltyNumber": (f"LOY-{np_rng.integers(100000, 999999)}" if rng.random() < 0.4 else ""),
        })
    return passengers, has_child


def seasonality_flag(travel_start_date):
    month = travel_start_date.month
    if month in (6, 7, 8, 12):
        return "Peak"
    if month in (3, 4, 5, 9):
        return "Shoulder"
    return "Off-Peak"


# --------------------------------------------------------------------------
# Main generation loop
# --------------------------------------------------------------------------

def generate_dataset(n_claims, seed, out_path):
    random.seed(seed)
    np_rng = np.random.default_rng(seed)
    rng = random.Random(seed)
    fake = Faker()
    Faker.seed(seed)

    n_customers = max(200, int(n_claims / 2.1))
    customers = generate_customers(n_customers, fake, rng, np_rng)

    # Assign a number of claims to each customer (power-law-ish: most file 1)
    claims_per_customer = np_rng.choice([1, 2, 3, 4, 5], size=n_customers,
                                         p=[0.62, 0.22, 0.10, 0.04, 0.02])
    # Trim/pad so total == n_claims
    total = claims_per_customer.sum()
    idx = 0
    while total != n_claims:
        if total < n_claims:
            claims_per_customer[idx % n_customers] += 1
            total += 1
        else:
            if claims_per_customer[idx % n_customers] > 1:
                claims_per_customer[idx % n_customers] -= 1
                total -= 1
        idx += 1

    # Build (customer_idx, submission_date) pairs, sorted per customer ascending
    now = datetime(2026, 8, 9)
    window_start = now - timedelta(days=730)

    advisor_ids = [f"PTS-ADV-{i+1:04d}" for i in range(140)]
    advisor_tenure = {a: int(np_rng.integers(1, 145)) for a in advisor_ids}
    # rough running caseload counter per advisor per day (for AdvisorCaseloadAtSubmission)
    advisor_daily_load = {}

    rows = []
    case_counter = 0

    for cust_idx, n_c in enumerate(claims_per_customer):
        if n_c == 0:
            continue
        cust = customers[cust_idx]
        sub_dates = sorted(
            window_start + timedelta(seconds=int(np_rng.integers(0, int((now - window_start).total_seconds()))))
            for _ in range(n_c)
        )

        for sub_dt in sub_dates:
            case_counter += 1
            case_id = f"PTS-CLM-{case_counter:06d}"

            # ---- Prior claim stats (based on this customer's history so far) ----
            prior_claims_count = len(cust["_claim_history"])
            prior_approved_count = sum(cust["_claim_history"])
            prior_approval_rate = (prior_approved_count / prior_claims_count) if prior_claims_count > 0 else 0.5

            # ---- Booking ----
            booking_type = weighted_choice(rng, BOOKING_TYPES, BOOKING_TYPE_WEIGHTS)
            booking_amount = round(float(np_rng.lognormal(mean=6.2, sigma=0.65)), 2)  # median ~$490
            booking_amount = clamp(booking_amount, 60, 25000)
            booking_currency = random.choice(CURRENCIES)

            booking_date = sub_dt - timedelta(days=int(np_rng.integers(1, 120)))

            # Travel window relative to claim submission (drives ClaimSubmittedRelativeToTravel)
            rel_choice = weighted_choice(rng, ["Before Travel", "During Travel", "After Travel"], [0.68, 0.14, 0.18])
            if rel_choice == "Before Travel":
                travel_start = sub_dt + timedelta(days=int(np_rng.integers(1, 90)))
            elif rel_choice == "During Travel":
                travel_start = sub_dt - timedelta(days=int(np_rng.integers(0, 3)))
            else:
                travel_start = sub_dt - timedelta(days=int(np_rng.integers(4, 60)))

            trip_duration = int(np_rng.choice([1, 2, 3, 4, 5, 7, 10, 14], p=[0.10, 0.15, 0.18, 0.15, 0.14, 0.13, 0.09, 0.06]))
            travel_end = travel_start + timedelta(days=trip_duration)

            fare_flex = weighted_choice(rng, FLEXIBILITY, FLEXIBILITY_WEIGHTS)
            booking_channel = weighted_choice(rng, BOOKING_CHANNELS, BOOKING_CHANNEL_WEIGHTS)
            special_consideration = random.choice(SPECIAL_CONSIDERATIONS)

            type_fields = generate_booking_type_fields(booking_type, rng, fake, np_rng)

            # ---- Passengers ----
            n_pax = int(np_rng.choice([1, 2, 3, 4, 5, 6, 7, 8],
                                       p=[0.30, 0.32, 0.14, 0.14, 0.05, 0.03, 0.01, 0.01]))
            passengers, has_child = generate_passengers(n_pax, fake, rng, np_rng)
            is_family_booking = has_child

            # ---- Better rate / financials ----
            # Gap percentage: mixture — mostly plausible (3-40%), some tiny (<3%), some implausible (>60%)
            gap_bucket = weighted_choice(rng, ["tiny", "plausible", "high", "implausible"], [0.08, 0.62, 0.18, 0.12])
            if gap_bucket == "tiny":
                gap_pct = np_rng.uniform(0.0, 0.03)
            elif gap_bucket == "plausible":
                gap_pct = np_rng.uniform(0.03, 0.40)
            elif gap_bucket == "high":
                gap_pct = np_rng.uniform(0.40, 0.60)
            else:
                gap_pct = np_rng.uniform(0.60, 0.95)

            better_rate_amount = round(booking_amount * (1 - gap_pct), 2)
            rate_difference_amount = round(booking_amount - better_rate_amount, 2)
            rate_difference_percent = round(rate_difference_amount / booking_amount, 4) if booking_amount else 0.0

            # Customer's claimed amount is close to the true gap, with noise
            claim_amount = round(max(0.0, rate_difference_amount * float(np_rng.normal(1.0, 0.06))), 2)
            claim_points = int(np_rng.choice([0, 0, 0, 500, 1000, 2500, 5000], p=[0.55, 0.1, 0.05, 0.12, 0.10, 0.05, 0.03]))

            better_rate_vendor = random.choice(BETTER_RATE_VENDORS)

            min_threshold_met = bool(rate_difference_percent >= 0.03 and rate_difference_amount >= 5.0)

            # ---- Attachments / proof ----
            attachment_count = int(np_rng.choice([0, 1, 2, 3, 4, 5], p=[0.10, 0.30, 0.28, 0.18, 0.09, 0.05]))
            proof_type = weighted_choice(rng, PROOF_TYPES, PROOF_TYPE_WEIGHTS) if attachment_count > 0 else "None"
            attachment_types = ["PDF", "JPG", "PNG", "DOC"]
            attachments = ["" ] * 5
            for a in range(min(attachment_count, 5)):
                ext = random.choice(attachment_types)
                attachments[a] = f"{case_id}-att{a+1}.{ext.lower()}"

            if attachment_count == 0 or proof_type == "None":
                proof_quality = "Insufficient"
            elif proof_type in ("PDF Quote", "Confirmation Email") and attachment_count >= 2:
                proof_quality = weighted_choice(rng, ["Verified", "Ambiguous"], [0.85, 0.15])
            elif proof_type == "Screenshot":
                proof_quality = weighted_choice(rng, ["Verified", "Ambiguous", "Insufficient"], [0.45, 0.40, 0.15])
            else:
                proof_quality = weighted_choice(rng, ["Verified", "Ambiguous"], [0.6, 0.4])

            has_valid_url = bool(rng.random() < (0.85 if proof_type != "Screenshot" else 0.45))
            better_rate_url = (
                f"https://www.{better_rate_vendor.lower().replace('.', '').replace(' ', '')}.com/listing/{case_counter}"
                if has_valid_url else ""
            )

            restrictions_match = bool(rng.random() < (0.80 if fare_flex != "Non-Refundable" else 0.55))
            blackout_or_excluded = bool(rng.random() < (0.12 if seasonality_flag(travel_start) == "Peak" else 0.04))

            # ---- SLA / adjudication economics ----
            advisor_id = random.choice(advisor_ids)
            is_escalated = bool(rng.random() < 0.08)
            handle_minutes = float(np_rng.normal(52, 12))
            if is_escalated:
                handle_minutes = clamp(handle_minutes * 1.6, 60, 150)
            time_to_adjudicate = int(clamp(round(handle_minutes), 20, 150))

            day_key = (advisor_id, sub_dt.date())
            advisor_daily_load[day_key] = advisor_daily_load.get(day_key, 0) + 1
            advisor_caseload = advisor_daily_load[day_key]

            queue_wait_hours = float(np_rng.exponential(scale=3.5))
            if advisor_caseload > 8:
                queue_wait_hours += float(np_rng.exponential(scale=6.0))
            if is_escalated:
                queue_wait_hours += float(np_rng.exponential(scale=20.0))
            sla_hours_elapsed = round((time_to_adjudicate / 60.0) + queue_wait_hours, 2)
            decision_dt = sub_dt + timedelta(hours=sla_hours_elapsed)
            sla_breached = bool(sla_hours_elapsed > SLA_TARGET_HOURS)
            adjudication_labor_cost = round((time_to_adjudicate / 60.0) * ADVISOR_COST_PER_HOUR, 2)

            # ---- Derived features (Section 5) ----
            days_booking_to_claim = (sub_dt.date() - booking_date.date()).days
            days_claim_to_travel_start = (travel_start.date() - sub_dt.date()).days
            attachment_completeness_score = round(
                clamp((attachment_count / 5.0) * 0.6 +
                      {"Verified": 0.4, "Ambiguous": 0.2, "Insufficient": 0.0}[proof_quality], 0.0, 1.0), 3
            )
            season = seasonality_flag(travel_start)
            loyalty_ordinal = LOYALTY_TIER_ORDINAL[cust["LoyaltyTier"]]

            # ---- Legitimacy score -> P(approved) -> label ----
            score = 14.0  # base
            score += 20 if (attachment_count >= 1 and proof_quality == "Verified") else 0
            score += 25 if restrictions_match else -25
            if 0.03 <= rate_difference_percent <= 0.40:
                score += 20
            elif rate_difference_percent > 0.60:
                score -= 20
            score += 15 if rel_choice == "Before Travel" else (-15 if rel_choice == "After Travel" else -3)
            score += 10 if min_threshold_met else -15
            score += (prior_approval_rate - 0.5) * 20  # -10..+10
            score += 10 if has_valid_url else -5
            score -= 12 if proof_quality == "Insufficient" else 0
            score -= 10 if blackout_or_excluded else 0

            score = clamp(score, 0, 100)
            p_approved = 1 / (1 + math.exp(-(score - 50) / 10))
            approved_raw = bool(rng.random() < p_approved)

            # Noise: flip ~10% of labels
            flipped = bool(rng.random() < 0.10)
            is_approved = (not approved_raw) if flipped else approved_raw

            if is_approved:
                reason = random.choice(APPROVAL_REASONS)
            else:
                # Pick a reason weighted toward the actual negative driver(s)
                candidate_reasons = []
                if not restrictions_match:
                    candidate_reasons.append("Restrictions/flexibility do not match")
                if proof_quality == "Insufficient":
                    candidate_reasons.append("Insufficient or unverifiable documentation")
                if rate_difference_percent > 0.60:
                    candidate_reasons.append("Competing rate not from an eligible/comparable vendor")
                if not min_threshold_met:
                    candidate_reasons.append("Price difference below minimum threshold")
                if rel_choice == "After Travel":
                    candidate_reasons.append("Claim submitted after travel completed")
                if blackout_or_excluded:
                    candidate_reasons.append("Blackout date / excluded fare or rate plan")
                if not candidate_reasons:
                    candidate_reasons = REJECTION_REASONS
                reason = random.choice(candidate_reasons)

            claim_status = weighted_choice(
                rng,
                ["Approved", "Rejected", "Closed", "Escalated"] if not is_escalated else ["Escalated", "Approved", "Rejected"],
                [0.55, 0.35, 0.07, 0.03] if not is_escalated else [0.5, 0.3, 0.2],
            )
            # Ensure terminal status matches label when status is Approved/Rejected
            if claim_status in ("Approved", "Rejected"):
                claim_status = "Approved" if is_approved else "Rejected"

            if is_approved:
                approved_amount = round(claim_amount * float(np_rng.uniform(0.85, 1.0)), 2)
                approved_points = int(claim_points * np_rng.uniform(0.8, 1.0))
                refund_amount = approved_amount
                refund_points = approved_points
                refund_method = weighted_choice(rng, REFUND_METHODS, REFUND_METHOD_WEIGHTS)
            else:
                approved_amount = 0.0
                approved_points = 0
                refund_amount = 0.0
                refund_points = 0
                refund_method = ""

            # Missingness injection
            internal_notes = (
                f"Reviewed by {advisor_id}: {reason.lower()}." if rng.random() < 0.75 else ""
            )
            customer_comments = (
                f"Found a lower rate on {better_rate_vendor} for the same {booking_type.lower()} itinerary."
                if rng.random() < 0.9 else ""
            )

            row = {
                "CaseID": case_id,
                "ClaimSubmissionDate": sub_dt.isoformat(sep=" "),
                "ClaimSubmissionChannel": weighted_choice(rng, CLAIM_CHANNELS, CLAIM_CHANNEL_WEIGHTS),
                "ClaimStatus": claim_status,
                "ClaimDecisionDate": decision_dt.isoformat(sep=" "),
                "AssignedAdvisorID": advisor_id,
                "AdvisorTenureMonths": advisor_tenure[advisor_id],
                "IsApproved": "Yes" if is_approved else "No",
                "ApprovalOrRejectionReason": reason,
                "CustomerComments": customer_comments,
                "InternalAdvisorNotes": internal_notes,

                "ClaimAmount": claim_amount,
                "ClaimPoints": claim_points,
                "ApprovedAmount": approved_amount,
                "ApprovedPoints": approved_points,
                "RefundAmount": refund_amount,
                "RefundPoints": refund_points,
                "RefundMethod": refund_method,
                "BetterRateURL": better_rate_url,
                "BetterRateVendorName": better_rate_vendor,
                "BetterRateAmount": better_rate_amount,
                "MinimumClaimThresholdMet": min_threshold_met,

                "Attachment1": attachments[0], "Attachment2": attachments[1],
                "Attachment3": attachments[2], "Attachment4": attachments[3],
                "Attachment5": attachments[4],
                "AttachmentCount": attachment_count,
                "ProofType": proof_type,
                "ProofQualityFlag": proof_quality,
                "RestrictionsMatchFlag": restrictions_match,

                "SLATargetHours": SLA_TARGET_HOURS,
                "TimeToAdjudicateMinutes": time_to_adjudicate,
                "SLAHoursElapsed": sla_hours_elapsed,
                "SLABreached": sla_breached,
                "AdjudicationLaborCost": adjudication_labor_cost,

                "CustomerID": cust["CustomerID"],
                "FirstName": cust["FirstName"], "LastName": cust["LastName"],
                "Phone": cust["Phone"], "Email": cust["Email"],
                "AddressStreet": cust["AddressStreet"], "AddressCity": cust["AddressCity"],
                "AddressState": cust["AddressState"], "AddressZip": cust["AddressZip"],
                "AddressCountry": cust["AddressCountry"],
                "LoyaltyTier": cust["LoyaltyTier"],
                "LoyaltyMemberSinceDate": cust["LoyaltyMemberSinceDate"].isoformat(),
                "CustomerLifetimeValue": cust["CustomerLifetimeValue"],
                "PriorClaimsCount": prior_claims_count,
                "PriorApprovedClaimsCount": prior_approved_count,
                "PriorApprovalRate": round(prior_approval_rate, 4),
                "AccountStatus": cust["AccountStatus"],

                "BookingID": f"PTS-BKG-{case_counter:06d}",
                "IsMultiSegmentBooking": booking_type == "Package",
                "BookingType": booking_type,
                "BookingChannel": booking_channel,
                "BookingAmount": booking_amount,
                "BookingCurrency": booking_currency,
                "BookingDate": booking_date.date().isoformat(),
                "TravelStartDate": travel_start.date().isoformat(),
                "TravelEndDate": travel_end.date().isoformat(),
                "TripDurationDays": trip_duration,
                "FareOrRatePlanFlexibility": fare_flex,
                "BookingSpecialConsiderations": special_consideration,
                "ClaimSubmittedRelativeToTravel": rel_choice,
                "BlackoutDateOrExcludedFare": blackout_or_excluded,

                **type_fields,

                "NumberOfPassengers": n_pax,
                "PassengerDetails": json.dumps(passengers),
                "IsFamilyBooking": is_family_booking,

                "DaysBookingToClaim": days_booking_to_claim,
                "DaysClaimToTravelStart": days_claim_to_travel_start,
                "RateDifferenceAmount": rate_difference_amount,
                "RateDifferencePercent": rate_difference_percent,
                "AttachmentCompletenessScore": attachment_completeness_score,
                "HasValidBetterRateURL": has_valid_url,
                "AdvisorCaseloadAtSubmission": advisor_caseload,
                "SeasonalityFlag": season,
                "LoyaltyTierOrdinal": loyalty_ordinal,
                "LegitimacyScore": round(score, 2),
            }
            rows.append(row)

            cust["_claim_history"].append(is_approved)

    df = pd.DataFrame(rows)

    # Occasional extra missingness beyond what's built in above (BetterRateURL, InternalAdvisorNotes already handled)
    df = df.sort_values("ClaimSubmissionDate").reset_index(drop=True)

    df.to_csv(out_path, index=False)
    return df


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic PTS BRG claims dataset")
    parser.add_argument("--n", type=int, default=9000, help="Number of claim records")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--out", type=str, default="data/brg_claims.csv", help="Output CSV path")
    args = parser.parse_args()

    df = generate_dataset(args.n, args.seed, args.out)

    approved_pct = (df["IsApproved"] == "Yes").mean() * 100
    print(f"Generated {len(df):,} rows -> {args.out}")
    print(f"Approved: {approved_pct:.1f}% / Not Approved: {100 - approved_pct:.1f}%")
    print(df["BookingType"].value_counts(normalize=True).round(3).to_dict())


if __name__ == "__main__":
    main()
