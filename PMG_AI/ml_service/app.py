"""PMG ML endpoint - exposes the claim scorer (pmg_predict.py) as a REST API using Flask.

Production flow (this service is ONE of three; it is never called by the browser directly):

    Browser (React) --HTTPS--> Node backend (auth, validation, claim ID) --HTTP + API key--> THIS SERVICE
                                                                                              |
                                                       model loaded ONCE at start-up  <-------+
                                                       derive fields -> engineer features -> RandomForest
                                                       -> APPROVE / REFER TO ADVISOR / REJECT + P(approved)

Endpoints
    GET  /health        liveness + model-loaded check (no auth, used by orchestrators / the backend)
    GET  /v1/model      model metadata (auth required)
    POST /v1/predict    score ONE claim (auth required)

Run (dev):   python ml_service/app.py
Run (prod):  python ml_service/serve.py        (waitress WSGI server, works on Windows/Linux)
"""
import hmac
import logging
import os
import pathlib
import sys
import time

# pmg_predict.py lives one folder up; make it importable no matter where we are launched from.
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd                      # noqa: E402  (import after sys.path tweak on purpose)
from flask import Flask, jsonify, request  # noqa: E402

import pmg_predict as pmg                # noqa: E402  (feature pipeline + scorer, unchanged)

# --------------------------------------------------------------------------------------
# Configuration comes from environment variables (12-factor) - never hard-code secrets.
# --------------------------------------------------------------------------------------
API_KEY = os.environ.get("ML_API_KEY", "dev-ml-key-change-me")        # shared secret with the backend
MAX_BODY_BYTES = 64 * 1024                                            # a claim is ~2 KB; reject huge bodies

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s [ml] %(message)s")
log = logging.getLogger("pmg-ml")

# --------------------------------------------------------------------------------------
# Allowed values for categorical inputs. Anything else is rejected with HTTP 422 instead of
# silently becoming an all-zero one-hot row (which would give a misleading score).
# --------------------------------------------------------------------------------------
CATEGORIES = {
    "BookingType": ["Car", "Cruise", "Flight", "Hotel/Lodging", "Package"],
    "BookingChannel": ["Agent-Assisted", "App", "PTS Web"],
    "ClaimSubmissionChannel": ["Call Center", "Email", "Mobile App", "Travel Agent", "Web"],
    "ProofQualityFlag": ["Ambiguous", "Insufficient", "Verified"],
    "LoyaltyTier": ["Standard", "Silver", "Gold", "Platinum"],
    "AccountStatus": ["Active", "Suspended", "VIP-Flagged"],
    "FareOrRatePlanFlexibility": ["Change Fee Applies", "Non-Refundable", "Partially Flexible", "Refundable"],
    "BetterRateVendorName": ["Agoda", "Booking.com", "Direct Airline Site", "Expedia", "Hotels.com",
                             "Kayak", "Orbitz", "Priceline", "Travelocity", "Vendor Direct"],
}
OPTIONAL_CATEGORIES = {   # may be null/absent
    "ProofType": ["Confirmation Email", "PDF Quote", "Screenshot"],
    "BookingSpecialConsiderations": ["Companion fare", "Corporate rate", "Group booking", "Honeymoon package",
                                     "Military discount", "None", "Senior discount", "Travel agent override"],
}
NUMBERS = ["BookingAmount", "BetterRateAmount", "ClaimAmount", "ClaimPoints", "CustomerLifetimeValue",
           "PriorClaimsCount", "PriorApprovedClaimsCount", "AttachmentCount", "NumberOfPassengers",
           "AdvisorTenureMonths"]
BOOLEANS = ["RestrictionsMatchFlag", "BlackoutDateOrExcludedFare", "IsMultiSegmentBooking", "IsFamilyBooking"]
DATES = ["BookingDate", "TravelStartDate", "TravelEndDate", "ClaimSubmissionDate", "LoyaltyMemberSinceDate"]


def validate_claim(c: dict) -> list:
    """Return a list of human-readable problems; an empty list means the claim is scoreable."""
    errs = []
    if not isinstance(c, dict):
        return ["body must be a JSON object"]
    for f, allowed in CATEGORIES.items():                       # required categoricals
        if c.get(f) not in allowed:
            errs.append(f"{f} must be one of {allowed}")
    for f, allowed in OPTIONAL_CATEGORIES.items():              # optional categoricals
        if c.get(f) is not None and c.get(f) not in allowed:
            errs.append(f"{f} must be null or one of {allowed}")
    for f in NUMBERS:                                           # numeric, finite, non-negative
        v = c.get(f)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v < 0:
            errs.append(f"{f} must be a non-negative number")
    for f in BOOLEANS:                                          # real JSON booleans only
        if not isinstance(c.get(f), bool):
            errs.append(f"{f} must be true or false")
    for f in DATES:                                             # parseable dates
        if pd.isna(pd.to_datetime(c.get(f), errors="coerce")):
            errs.append(f"{f} must be a valid date")
    if not errs:                                                # cross-field business sanity checks
        if c["BookingAmount"] <= 0:
            errs.append("BookingAmount must be greater than 0")
        if c["PriorApprovedClaimsCount"] > c["PriorClaimsCount"]:
            errs.append("PriorApprovedClaimsCount cannot exceed PriorClaimsCount")
        if pd.to_datetime(c["TravelEndDate"]) < pd.to_datetime(c["TravelStartDate"]):
            errs.append("TravelEndDate cannot be before TravelStartDate")
    return errs


def create_app() -> Flask:
    """Application factory: builds the Flask app and loads the model exactly once."""
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_BODY_BYTES           # Flask answers 413 above this size

    t0 = time.perf_counter()
    bundle = pmg.load_artifact()                                # heavy: unpickle the RandomForest (once!)
    log.info("model '%s' loaded in %.0f ms (%d features, threshold %.4f)", bundle["model_name"],
             (time.perf_counter() - t0) * 1000, len(bundle["feature_columns"]), bundle["threshold"])

    def authorised() -> bool:
        """Constant-time compare of the X-API-Key header (prevents timing attacks)."""
        return hmac.compare_digest(request.headers.get("X-API-Key", ""), API_KEY)

    @app.get("/health")
    def health():
        return jsonify(status="ok", model=bundle["model_name"])

    @app.get("/v1/model")
    def model_info():
        if not authorised():
            return jsonify(error="unauthorised"), 401
        return jsonify(model=bundle["model_name"], threshold=round(bundle["threshold"], 4),
                       referBand=pmg.REFER_BAND, featureCount=len(bundle["feature_columns"]))

    @app.post("/v1/predict")
    def predict():
        if not authorised():                                    # 1. authenticate the caller (backend only)
            return jsonify(error="unauthorised"), 401
        claim = request.get_json(silent=True)                   # 2. parse JSON (None if malformed)
        if claim is None:
            return jsonify(error="body must be valid JSON"), 400
        errs = validate_claim(claim)                            # 3. defence-in-depth validation
        if errs:
            return jsonify(error="validation failed", details=errs), 422
        t = time.perf_counter()
        result = pmg.score_claim(claim, bundle)                 # 4. derive -> engineer -> predict_proba -> decision
        latency = round((time.perf_counter() - t) * 1000, 1)
        # 5. human-friendly business signals so the UI can explain the decision
        d = pmg.derive_intermediate_fields(pd.DataFrame([{k: v for k, v in claim.items() if k != "ClaimID"}])).iloc[0]
        signals = {"rateDifferenceAmount": round(float(d["RateDifferenceAmount"]), 2),
                   "rateDifferencePercent": round(float(d["RateDifferencePercent"]) * 100, 2),
                   "minimumThresholdMet": bool(d["MinimumClaimThresholdMet"]),
                   "claimSubmittedRelativeToTravel": d["ClaimSubmittedRelativeToTravel"]}
        log.info("scored claim=%s decision=%s p=%.4f latency=%.1fms", claim.get("ClaimID"),
                 result["decision"], result["P(approved)"], latency)
        return jsonify(claimId=claim.get("ClaimID"),            # echo the SAME claim id back
                       decision=result["decision"], probabilityApproved=result["P(approved)"],
                       threshold=round(bundle["threshold"], 4), referBand=pmg.REFER_BAND,
                       signals=signals, modelName=bundle["model_name"], latencyMs=latency)

    @app.errorhandler(413)
    def too_large(_):
        return jsonify(error="request body too large"), 413

    @app.errorhandler(Exception)
    def unexpected(e):                                          # never leak stack traces to callers
        log.exception("unhandled error")
        return jsonify(error="internal error"), 500

    return app


if __name__ == "__main__":                                      # dev server only; use serve.py in production
    create_app().run(host="127.0.0.1", port=int(os.environ.get("ML_PORT", "5001")))
