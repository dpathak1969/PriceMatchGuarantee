"""PriceMatch Guarantee (PMG) - real-time claim scoring.

Loads the saved model artifact (artifacts/pmg_predictor.joblib) and scores raw claim dicts.
Converted from Section 27 of PMG.ipynb.

Usage:
    python pmg_predict.py                    # score the 5 built-in demo claims
    python pmg_predict.py --claim my.json    # score one claim (JSON object) or a list of claims
"""
import argparse
import json
import pathlib
import time
import warnings

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.impute import SimpleImputer

warnings.filterwarnings("ignore")

ARTIFACT_PATH = pathlib.Path(__file__).resolve().parent / "artifacts" / "pmg_predictor.joblib"
REFER_BAND = 0.07          # +/- window around the threshold => refer to advisor

# --- lookup tables for the derived fields (reverse-engineered from the dataset) --------
# Season is a pure function of the travel-start month
SEASON_BY_MONTH = {1: "Off-Peak", 2: "Off-Peak", 3: "Shoulder", 4: "Shoulder", 5: "Shoulder",
                   6: "Peak", 7: "Peak", 8: "Peak", 9: "Shoulder", 10: "Off-Peak",
                   11: "Off-Peak", 12: "Peak"}
# AttachmentCompletenessScore == 0.12 * AttachmentCount + quality bonus (clipped to 0..1)
PROOF_QUALITY_BONUS  = {"Insufficient": 0.0, "Ambiguous": 0.20, "Verified": 0.40}
# LoyaltyTier -> ordinal rank
LOYALTY_TIER_ORDINAL = {"Standard": 0, "Silver": 1, "Gold": 2, "Platinum": 3}

# ------------------------------------------------------------------------------------------
# Feature pipeline (verbatim from the notebook: the joblib holds only the model)
# ------------------------------------------------------------------------------------------
def derive_intermediate_fields(raw: pd.DataFrame) -> pd.DataFrame:
    """Recompute every 'derived' business field from the raw booking/claim columns.

    Running the SAME logic on the historical CSV and on a brand-new claim removes any
    train/serve skew in the derived inputs.
    """
    d = raw.copy()                                              # never mutate the caller's frame

    # parse any date-like columns that are present (a single new claim may omit some)
    for c in ["ClaimSubmissionDate", "BookingDate", "TravelStartDate",
              "TravelEndDate", "LoyaltyMemberSinceDate"]:
        if c in d.columns:
            d[c] = pd.to_datetime(d[c], errors="coerce")        # unpardeable -> NaT

    # --- money gap between what PTS charged and the competing rate --------------------
    d["RateDifferenceAmount"]  = d["BookingAmount"] - d["BetterRateAmount"]      # absolute $ gap
    d["RateDifferencePercent"] = d["RateDifferenceAmount"] / d["BookingAmount"]  # gap as a fraction of our price

    # --- BRG program threshold: the gap must be at least ~3% of our price ------------
    d["MinimumClaimThresholdMet"] = d["RateDifferencePercent"] >= 0.03

    # --- a proof URL counts as 'valid' when one was actually supplied ---------------
    d["HasValidBetterRateURL"] = (
        d["BetterRateURL"].notna() & (d["BetterRateURL"].astype(str).str.len() > 0)
    )

    # --- attachments: count then completeness score ---------------------------------
    if "AttachmentCount" not in d.columns:                      # derive from Attachment1..5 if needed
        att_cols = [c for c in ["Attachment1", "Attachment2", "Attachment3",
                                "Attachment4", "Attachment5"] if c in d.columns]
        d["AttachmentCount"] = d[att_cols].notna().sum(axis=1) if att_cols else 0
    d["AttachmentCompletenessScore"] = np.clip(
        0.12 * d["AttachmentCount"]
        + d["ProofQualityFlag"].map(PROOF_QUALITY_BONUS).fillna(0.0),
        0, 1)

    # --- calendar deltas ------------------------------------------------------------
    d["DaysBookingToClaim"]     = (d["ClaimSubmissionDate"] - d["BookingDate"]).dt.days
    d["DaysClaimToTravelStart"] = (d["TravelStartDate"] - d["ClaimSubmissionDate"]).dt.days
    if "TripDurationDays" not in d.columns:
        d["TripDurationDays"] = (d["TravelEndDate"] - d["TravelStartDate"]).dt.days

    # --- when was the claim filed relative to the trip window ----------------------
    def _relative(row):
        if pd.isna(row["DaysClaimToTravelStart"]):
            return "Before Travel"                              # default when dates are missing
        if row["DaysClaimToTravelStart"] > 0:
            return "Before Travel"                              # filed before departure
        if pd.notna(row["TravelEndDate"]) and row["ClaimSubmissionDate"] <= row["TravelEndDate"]:
            return "During Travel"                              # filed mid-trip
        return "After Travel"                                   # filed once the trip finished
    d["ClaimSubmittedRelativeToTravel"] = d.apply(_relative, axis=1)

    # --- seasonality of the trip --------------------------------------------------
    d["SeasonalityFlag"] = d["TravelStartDate"].dt.month.map(SEASON_BY_MONTH)

    # --- loyalty tier as an ordinal ---------------------------------------------
    d["LoyaltyTierOrdinal"] = d["LoyaltyTier"].map(LOYALTY_TIER_ORDINAL).fillna(0).astype(int)

    # --- customer's historical approval rate -----------------------------------
    denom = d["PriorClaimsCount"].replace(0, np.nan)            # avoid divide-by-zero
    d["PriorApprovalRate"] = (d["PriorApprovedClaimsCount"] / denom).fillna(0.0)

    # --- sensible fallbacks for optional passenger fields --------------------
    if "NumberOfPassengers" not in d.columns:
        d["NumberOfPassengers"] = 1
    if "IsFamilyBooking" not in d.columns:
        d["IsFamilyBooking"] = False

    # --- normalise boolean dtype so .astype(int) is safe downstream --------
    for b in ["RestrictionsMatchFlag", "BlackoutDateOrExcludedFare",
              "IsMultiSegmentBooking", "IsFamilyBooking"]:
        if b in d.columns:
            d[b] = d[b].astype(bool)
    return d

def engineer_features(d: pd.DataFrame):
    """Section-16 feature engineering. Returns (numeric_frame, one_hot_frame)."""
    fe = pd.DataFrame(index=d.index)                            # engineered NUMERIC features go here

    # ---------- proof / documentation strength ----------
    fe["proof_verified"]          = (d["ProofQualityFlag"] == "Verified").astype(int)          # gold-standard proof
    fe["proof_insufficient"]      = (d["ProofQualityFlag"] == "Insufficient").astype(int)      # unusable proof
    fe["proof_quality_ord"]       = d["ProofQualityFlag"].map({"Insufficient": 0, "Ambiguous": 1, "Verified": 2})
    fe["has_attachments"]         = (d["AttachmentCount"] >= 1).astype(int)                    # any file at all
    fe["multi_attachments"]       = (d["AttachmentCount"] >= 2).astype(int)                    # more than one file
    fe["strong_proof"]            = ((d["AttachmentCount"] >= 1) & (d["ProofQualityFlag"] == "Verified")).astype(int)
    fe["proof_type_missing"]      = d["ProofType"].isna().astype(int)                          # no proof type recorded
    fe["attachment_count"]        = d["AttachmentCount"]
    fe["attachment_completeness"] = d["AttachmentCompletenessScore"]
    fe["attachment_density"]      = d["AttachmentCompletenessScore"] * d["AttachmentCount"]    # interaction term

    # ---------- restrictions / program eligibility ----------
    fe["restrictions_match"]      = d["RestrictionsMatchFlag"].astype(int)                     # terms line up (key driver)
    fe["threshold_met"]           = d["MinimumClaimThresholdMet"].astype(int)                  # gap clears the minimum
    fe["has_valid_url"]           = d["HasValidBetterRateURL"].astype(int)                     # proof link supplied
    fe["blackout_or_excluded"]    = d["BlackoutDateOrExcludedFare"].astype(int)               # excluded fare/date

    # ---------- rate-difference plausibility band (Sec 6: 3-40% plausible, >60% implausible) ----------
    rdp = d["RateDifferencePercent"]
    fe["rate_diff_pct"]           = rdp
    fe["rate_diff_amount"]        = d["RateDifferenceAmount"]
    fe["rate_diff_in_band"]       = rdp.between(0.03, 0.40).astype(int)                        # the "believable" range
    fe["rate_diff_below_min"]     = (rdp < 0.03).astype(int)                                   # too small to qualify
    fe["rate_diff_implausible"]   = (rdp > 0.60).astype(int)                                   # suspiciously large

    # ---------- submission timing ----------
    fe["submitted_before_travel"] = (d["ClaimSubmittedRelativeToTravel"] == "Before Travel").astype(int)
    fe["submitted_during_travel"] = (d["ClaimSubmittedRelativeToTravel"] == "During Travel").astype(int)
    fe["submitted_after_travel"]  = (d["ClaimSubmittedRelativeToTravel"] == "After Travel").astype(int)

    # ---------- customer prior track record ----------
    fe["prior_approval_rate"]     = d["PriorApprovalRate"]
    fe["prior_claims_count"]      = d["PriorClaimsCount"]
    fe["prior_approved_count"]    = d["PriorApprovedClaimsCount"]
    fe["prior_rejected_count"]    = (d["PriorClaimsCount"] - d["PriorApprovedClaimsCount"]).clip(lower=0)
    fe["is_first_time_claimant"]  = (d["PriorClaimsCount"] == 0).astype(int)

    # ---------- composite eligibility scores (mirror the Section-6 legitimacy logic) ----------
    POS = ["strong_proof", "restrictions_match", "rate_diff_in_band",
           "submitted_before_travel", "threshold_met", "has_valid_url"]
    NEG = ["proof_insufficient", "rate_diff_implausible", "rate_diff_below_min",
           "submitted_after_travel", "blackout_or_excluded"]
    fe["eligibility_positive_score"] = fe[POS].sum(axis=1)                                     # 0..6 good signals
    fe["eligibility_redflag_count"]  = fe[NEG].sum(axis=1)                                     # 0..5 red flags
    fe["eligibility_net_score"]      = fe["eligibility_positive_score"] - fe["eligibility_redflag_count"]
    fe["eligibility_net_score_plus"] = fe["eligibility_net_score"] + (d["PriorApprovalRate"].fillna(0.5) - 0.5) * 2

    # ---------- temporal ----------
    sub = d["ClaimSubmissionDate"]
    fe["submission_month"]           = sub.dt.month
    fe["submission_quarter"]         = sub.dt.quarter
    fe["submission_dayofweek"]       = sub.dt.dayofweek
    fe["submission_is_weekend"]      = (sub.dt.dayofweek >= 5).astype(int)
    fe["submission_hour"]            = sub.dt.hour.fillna(12)                                  # noon fallback if time missing
    fe["booking_lead_days"]          = (d["TravelStartDate"] - d["BookingDate"]).dt.days
    fe["loyalty_tenure_days"]        = (d["ClaimSubmissionDate"] - d["LoyaltyMemberSinceDate"]).dt.days
    fe["days_booking_to_claim"]      = d["DaysBookingToClaim"]
    fe["days_claim_to_travel"]       = d["DaysClaimToTravelStart"]
    fe["claim_after_travel_started"] = (d["DaysClaimToTravelStart"] < 0).astype(int)
    fe["trip_duration_days"]         = d["TripDurationDays"]

    # ---------- monetary / ratio ----------
    fe["claim_amount"]           = d["ClaimAmount"]
    fe["claim_amount_log"]       = np.log1p(d["ClaimAmount"].clip(lower=0))                    # tame the heavy tail
    fe["booking_amount"]         = d["BookingAmount"]
    fe["booking_amount_log"]     = np.log1p(d["BookingAmount"].clip(lower=0))
    fe["claim_to_booking_ratio"] = d["ClaimAmount"] / d["BookingAmount"]                       # claim size vs booking size
    fe["better_rate_to_booking"] = d["BetterRateAmount"] / d["BookingAmount"]
    fe["has_points_claim"]       = (d["ClaimPoints"] > 0).astype(int)
    fe["claim_points"]           = d["ClaimPoints"]
    fe["clv"]                    = d["CustomerLifetimeValue"]
    fe["clv_log"]                = np.log1p(d["CustomerLifetimeValue"].clip(lower=0))

    # ---------- customer / booking context ----------
    fe["loyalty_tier_ordinal"]   = d["LoyaltyTierOrdinal"]
    fe["account_suspended"]      = (d["AccountStatus"] == "Suspended").astype(int)
    fe["account_vip"]            = (d["AccountStatus"] == "VIP-Flagged").astype(int)
    fe["is_family_booking"]      = d["IsFamilyBooking"].astype(int)
    fe["is_multisegment"]        = d["IsMultiSegmentBooking"].astype(int)
    fe["number_of_passengers"]   = d["NumberOfPassengers"]
    fe["advisor_tenure_months"]  = d.get("AdvisorTenureMonths", pd.Series(0, index=d.index))

    # ---------- text signal from the customer's own comment ----------
    cc = d["CustomerComments"].fillna("") if "CustomerComments" in d.columns else pd.Series("", index=d.index)
    fe["has_customer_comment"]   = (cc.str.len() > 0).astype(int)
    fe["comment_char_len"]       = cc.str.len()
    fe["comment_word_count"]     = cc.str.split().str.len().fillna(0).astype(int)
    fe["comment_has_url"]        = cc.str.contains(r"http|www\.|\.com", case=False, regex=True).astype(int)
    fe["comment_mentions_price"] = cc.str.contains(r"price|cheaper|rate|cost|\$", case=False, regex=True).astype(int)

    # ---------- categoricals -> one-hot ----------
    CATS = {
        "BookingType": d["BookingType"], "BookingChannel": d["BookingChannel"],
        "ClaimSubmissionChannel": d["ClaimSubmissionChannel"],
        "ClaimSubmittedRelativeToTravel": d["ClaimSubmittedRelativeToTravel"],
        "ProofType": d["ProofType"].fillna("No Proof"), "ProofQualityFlag": d["ProofQualityFlag"],
        "LoyaltyTier": d["LoyaltyTier"], "AccountStatus": d["AccountStatus"],
        "SeasonalityFlag": d["SeasonalityFlag"], "FareOrRatePlanFlexibility": d["FareOrRatePlanFlexibility"],
        "BetterRateVendorName": d["BetterRateVendorName"],
        "BookingSpecialConsiderations": d["BookingSpecialConsiderations"].fillna("None"),
    }
    cat_df = pd.get_dummies(pd.DataFrame(CATS), prefix_sep="=", dtype=int)
    return fe, cat_df


def build_X(raw: pd.DataFrame, feature_columns=None) -> pd.DataFrame:
    """raw dataframe -> model-ready feature matrix.

    `feature_columns` is passed at inference time so a single new claim is reindexed
    to exactly the columns the model was trained on (unseen categories -> all-zero).
    """
    d = derive_intermediate_fields(raw)                         # step 1: derived business fields
    fe, cat = engineer_features(d)                              # step 2: engineered + one-hot features
    X = pd.concat([fe, cat], axis=1).replace([np.inf, -np.inf], np.nan)   # step 3: assemble, kill infinities
    if feature_columns is not None:
        X = X.reindex(columns=feature_columns, fill_value=0)    # step 4: lock schema for serving
    return X


# ------------------------------------------------------------------------------------------
# Artifact loading + scoring
# ------------------------------------------------------------------------------------------
def load_artifact(path=ARTIFACT_PATH) -> dict:
    """Load the joblib bundle: model, feature_columns, threshold, model_name."""
    bundle = joblib.load(path)
    # Pickles from scikit-learn <1.8 lack SimpleImputer._fill_dtype, which 1.8+ needs at predict time.
    for _, step in getattr(bundle["model"], "steps", []):
        if isinstance(step, SimpleImputer) and not hasattr(step, "_fill_dtype"):
            step._fill_dtype = step.statistics_.dtype
    return bundle


def score_claim(claim: dict, bundle: dict, refer_band: float = REFER_BAND) -> dict:
    """Score one raw claim dict -> {decision, P(approved)}."""
    raw_row = pd.DataFrame([{k: v for k, v in claim.items() if k not in ("ClaimID", "_scenario")}])
    feats = build_X(raw_row, bundle["feature_columns"])          # derive + engineer + align schema
    proba = float(bundle["model"].predict_proba(feats)[0, 1])    # P(approved)
    threshold = bundle["threshold"]
    if abs(proba - threshold) <= refer_band:
        decision = "REFER TO ADVISOR"
    elif proba >= threshold:
        decision = "APPROVE"
    else:
        decision = "REJECT"
    return {"decision": decision, "P(approved)": round(proba, 4)}


def score_claims(claims: list, bundle: dict) -> pd.DataFrame:
    rows = []
    for i, c in enumerate(claims, 1):
        t = time.perf_counter()
        r = score_claim(c, bundle)
        r["latency_ms"] = round((time.perf_counter() - t) * 1000, 1)
        r["ClaimID"] = c.get("ClaimID", f"claim {i}")
        rows.append(r)
    return pd.DataFrame(rows)[["ClaimID", "decision", "P(approved)", "latency_ms"]]


def main():
    ap = argparse.ArgumentParser(description="Score PMG claims with the saved model artifact.")
    ap.add_argument("--claim", help="JSON file with one claim object or a list of claims")
    args = ap.parse_args()

    t0 = time.perf_counter()
    bundle = load_artifact()
    print(f"Loaded {ARTIFACT_PATH.name} in {(time.perf_counter() - t0) * 1000:.0f} ms | "
          f"model={bundle['model_name']} | features={len(bundle['feature_columns'])} | "
          f"threshold={bundle['threshold']:.3f} | scikit-learn {sklearn.__version__}")

    if args.claim:
        data = json.load(open(args.claim, encoding="utf-8"))
        claims = data if isinstance(data, list) else [data]
    else:
        from demo_claims import DEMO_CLAIMS
        claims = DEMO_CLAIMS

    results = score_claims(claims, bundle)
    print(f"\nScored {len(results)} claim(s) (threshold {bundle['threshold']:.3f}, "
          f"refer band +/- {REFER_BAND}):\n")
    with pd.option_context("display.max_colwidth", 80, "display.width", 200):
        print(results.to_string(index=False))


if __name__ == "__main__":
    main()
