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
import os
import pathlib
import sys
import time

# pmg_predict.py lives one folder up; make it importable no matter where we are launched from.
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))                      # for pmg_predict
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))   # for pmg_logging (works under gunicorn too)

import pandas as pd                      # noqa: E402  (import after sys.path tweak on purpose)
from flask import Flask, jsonify, request  # noqa: E402
from werkzeug.exceptions import HTTPException  # noqa: E402

import pmg_predict as pmg                # noqa: E402  (feature pipeline + scorer, unchanged)
from pmg_logging import log             # noqa: E402  (levels: debug/info/summary/error, see pmg_logging.py)

# --------------------------------------------------------------------------------------
# Configuration comes from environment variables (12-factor) - never hard-code secrets.
# --------------------------------------------------------------------------------------
API_KEY = os.environ.get("ML_API_KEY", "dev-ml-key-change-me")        # shared secret with the backend
MAX_BODY_BYTES = 64 * 1024                                            # a claim is ~2 KB; reject huge bodies

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
    log.summary(f"model '{bundle['model_name']}' loaded in {(time.perf_counter() - t0) * 1000:.0f} ms "
                f"({len(bundle['feature_columns'])} features, threshold {bundle['threshold']:.4f}, log level: {log.level_name})")

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
        trace = request.headers.get("X-Trace-Id", "")[:40] or None   # claim id forwarded by the backend
        if not authorised():                                        # 1. authenticate the caller (backend only)
            log.error("REJECTED: missing/invalid X-API-Key", trace=trace)
            return jsonify(error="unauthorised"), 401
        claim = request.get_json(silent=True)                       # 2. parse JSON (None if malformed)
        if claim is None:
            log.error("REJECTED: body is not valid JSON", trace=trace)
            return jsonify(error="body must be valid JSON"), 400
        trace = trace or (claim.get("ClaimID") if isinstance(claim, dict) else None)
        log.info("==== ML REQUEST RECEIVED  (backend -> ML model) ====",
                 {"method": "POST", "path": "/v1/predict", "headers": {"X-API-Key": request.headers.get("X-API-Key", ""),
                  "X-Trace-Id": trace, "Content-Type": request.headers.get("Content-Type")}, "body": claim}, trace=trace)
        errs = validate_claim(claim)                                # 3. defence-in-depth validation
        if errs:
            log.error("validation FAILED -> 422", errs, trace=trace)
            return jsonify(error="validation failed", details=errs), 422
        log.info("validation passed", trace=trace)
        raw_row = pd.DataFrame([{k: v for k, v in claim.items() if k not in ("ClaimID", "_scenario")}])
        if log.enabled("debug"):                                    # show exactly what the model sees (only built when debugging)
            feats = pmg.build_X(raw_row, bundle["feature_columns"])
            nonzero = {c: (round(float(v), 4) if v == v else None) for c, v in feats.iloc[0].items() if v != 0}
            log.debug(f"model input: {len(feats.columns)} features, {len(nonzero)} non-zero (zeros omitted)", nonzero, trace=trace)
        t = time.perf_counter()
        result = pmg.score_claim(claim, bundle)                     # 4. derive -> engineer -> predict_proba -> decision
        latency = round((time.perf_counter() - t) * 1000, 1)
        # 5. human-friendly business signals so the UI can explain the decision
        d = pmg.derive_intermediate_fields(raw_row).iloc[0]
        signals = {"rateDifferenceAmount": round(float(d["RateDifferenceAmount"]), 2),
                   "rateDifferencePercent": round(float(d["RateDifferencePercent"]) * 100, 2),
                   "minimumThresholdMet": bool(d["MinimumClaimThresholdMet"]),
                   "claimSubmittedRelativeToTravel": d["ClaimSubmittedRelativeToTravel"]}
        response = dict(claimId=claim.get("ClaimID"),               # echo the SAME claim id back
                        decision=result["decision"], probabilityApproved=result["P(approved)"],
                        threshold=round(bundle["threshold"], 4), referBand=pmg.REFER_BAND,
                        signals=signals, modelName=bundle["model_name"], latencyMs=latency)
        log.info(f"model {bundle['model_name']} predicted P(approved)={result['P(approved)']} -> {result['decision']} in {latency}ms", trace=trace)
        log.debug(f"decision rule: APPROVE if P >= {bundle['threshold'] + pmg.REFER_BAND:.4f}, "
                  f"REFER if |P - {bundle['threshold']:.4f}| <= {pmg.REFER_BAND}, else REJECT", trace=trace)
        log.info(f"==== ML RESPONSE SENT  (ML model -> backend) ==== HTTP 200 -> {result['decision']} (P={result['P(approved)']})",
                 {"status": 200, "body": response}, trace=trace)
        log.summary(f"SCORED claim={claim.get('ClaimID')} -> {result['decision']} (P={result['P(approved)']}) model={latency}ms", trace=trace)
        return jsonify(response)

    @app.errorhandler(413)
    def too_large(_):
        return jsonify(error="request body too large"), 413

    @app.errorhandler(Exception)
    def unexpected(e):                                          # never leak stack traces to callers
        if isinstance(e, HTTPException):                        # 404/405/... keep their own status code
            return jsonify(error=e.description), e.code
        log.error(f"unhandled error: {e!r}")
        return jsonify(error="internal error"), 500

    return app


if __name__ == "__main__":                                      # dev server only; use serve.py in production
    create_app().run(host="127.0.0.1", port=int(os.environ.get("ML_PORT", "5001")))
