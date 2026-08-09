# Prestige Travel Services (PTS) — Best Rate Guarantee (BRG) Claims

## Synthetic Dataset & ML Classification Model — Generation Prompt

---

## 1\. Role & Objective

You are a data engineering and ML agent supporting an **AI / agentic-AI case study**. Your task has two parts:

1. **Generate a realistic, feature-rich synthetic dataset** representing historical Best Rate Guarantee (BRG) claims for Prestige Travel Services (PTS), a fictional travel booking company.  
2. **Train and evaluate a binary classification model** that predicts `IsApproved` (Approved / Not Approved) for a claim, using the dataset you generate.

The dataset must be internally consistent — i.e., the target label should be *derivable* from a mix of the other fields via realistic business logic plus injected noise, not assigned purely at random. This is what makes the dataset useful for a supervised ML case study.

---

## 2\. Business Background

- PTS offers a **Best Rate Guarantee**: if a customer finds a lower publicly available rate for the *same* itinerary from a competing vendor, PTS will refund the difference (in cash and/or loyalty points), provided the customer supplies proof and the competing rate has matching travel restrictions/flexibility terms.  
- Customers submit a claim (`CaseID` / `ClaimID`) with supporting evidence (screenshots, PDFs, URLs).  
- **Advisors** manually adjudicate each claim — reviewing terms, verifying the competing rate, and approving/rejecting with a documented reason.  
  - Advisor cost: **$50/hour**  
  - Typical handling time: **45–60 minutes per case** (use this to derive labor cost and to model SLA risk)  
- **SLA target: 24 hours** from submission to decision.  
- Claims can cover a **single booking or a multi-segment trip** (e.g., flight \+ hotel \+ car in one itinerary), and bookings can include multiple travelers/passengers (e.g., families).

---

## 3\. Deliverables

| \# | Deliverable | Format |
| :---- | :---- | :---- |
| 1 | Synthetic claims dataset | CSV (flat, ML-ready) **and** a nested JSON version preserving multi-segment/multi-passenger structure |
| 2 | Data dictionary | Table of every field, type, description, example, and whether it's raw or derived |
| 3 | Trained classification model \+ evaluation report | Notebook/script \+ metrics summary |
| 4 | (Optional) Agentic pipeline design | See Section 9 |

---

## 4\. Dataset Schema

### 4.1 Case / Claim — Core

| Field | Type | Notes |
| :---- | :---- | :---- |
| `CaseID` / `ClaimID` | string (PTS-CLM-000001) | Primary key |
| `ClaimSubmissionDate` | datetime |  |
| `ClaimSubmissionChannel` | categorical | Web, Mobile App, Call Center, Email, Travel Agent |
| `ClaimStatus` | categorical | Submitted, In Review, Escalated, Approved, Rejected, Closed |
| `AssignedAdvisorID` | string |  |
| `AdvisorTenureMonths` | int | Optional — more tenure → slightly faster/more consistent decisions |
| `IsApproved` | **Target** — Yes/No | See Section 6 for generation logic |
| `ApprovalOrRejectionReason` | categorical (code \+ text) | See reason taxonomy, Section 6 |
| `CustomerComments` | free text | Short synthetic text |
| `InternalAdvisorNotes` | free text | Optional — adjudication rationale |

### 4.2 Financials

| Field | Type | Notes |
| :---- | :---- | :---- |
| `ClaimAmount` | currency | Dollar gap claimed |
| `ClaimPoints` | int | Loyalty points portion claimed |
| `ApprovedAmount` | currency | ≤ ClaimAmount; 0 if rejected |
| `ApprovedPoints` | int |  |
| `RefundAmount` | currency | Actual disbursed amount |
| `RefundPoints` | int |  |
| `RefundMethod` | categorical | Original Payment Method, Travel Credit, Loyalty Points, Split |
| `BetterRateURL` | string/URL | Competitor listing |
| `BetterRateVendorName` | categorical | Expedia, Booking.com, Vendor Direct, etc. |
| `BetterRateAmount` | currency |  |
| `MinimumClaimThresholdMet` | bool | Derived — many BRG programs require ≥3–5% or ≥$5 gap |

### 4.3 Attachments & Proof

| Field | Type | Notes |
| :---- | :---- | :---- |
| `Attachment1`…`Attachment5` | string (filename \+ type: PDF/JPG/PNG/DOC) | Empty if unused |
| `AttachmentCount` | int (derived) | 0–5 |
| `ProofType` | categorical | Screenshot, PDF Quote, Confirmation Email, None |
| `ProofQualityFlag` | categorical (derived) | Verified, Ambiguous, Insufficient |
| `RestrictionsMatchFlag` | bool | Do cancellation/change/fare rules match the PTS booking? — **key driver field** |

### 4.4 SLA & Adjudication Economics

| Field | Type | Notes |
| :---- | :---- | :---- |
| `SLATargetHours` | int | Fixed at 24 |
| `TimeToAdjudicateMinutes` | int | Sample \~N(52, 12), floor 20 / cap 150 for escalations |
| `SLAHoursElapsed` | float (derived) | SubmissionDate → DecisionDate |
| `SLABreached` | bool (derived) | `SLAHoursElapsed > 24` |
| `AdjudicationLaborCost` | currency (derived) | `(TimeToAdjudicateMinutes/60) * 50` |

### 4.5 Customer Profile

| Field | Type | Notes |
| :---- | :---- | :---- |
| `CustomerID` | string |  |
| `FirstName`, `LastName` | string | Use Faker — **no real PII** |
| `Phone`, `Email` | string | Synthetic only |
| `Address` (Street, City, State, Zip, Country) | string |  |
| `LoyaltyTier` | categorical | Standard, Silver, Gold, Platinum |
| `LoyaltyMemberSinceDate` | date |  |
| `CustomerLifetimeValue` | currency |  |
| `PriorClaimsCount` | int |  |
| `PriorApprovedClaimsCount` | int |  |
| `PriorApprovalRate` | float (derived) | Approved/Total prior — **useful predictive feature** |
| `AccountStatus` | categorical | Active, Suspended, VIP-Flagged |

### 4.6 Booking — Core Fields (all types)

| Field | Type | Notes |
| :---- | :---- | :---- |
| `BookingID` | string |  |
| `IsMultiSegmentBooking` | bool |  |
| `BookingType` | categorical | Flight, Hotel/Lodging, Car, Cruise, Package (multi-type) |
| `BookingChannel` | categorical | PTS Web, App, Agent-Assisted |
| `BookingAmount` | currency |  |
| `BookingCurrency` | categorical | USD default; add a few FX cases for realism |
| `BookingDate` | date |  |
| `TravelStartDate`, `TravelEndDate` | date |  |
| `TripDurationDays` | int (derived) |  |
| `FareOrRatePlanFlexibility` | categorical | Refundable, Non-Refundable, Partially Flexible, Change Fee Applies |
| `BookingSpecialConsiderations` | free text | e.g., "Group booking," "Corporate rate," "Companion fare" |
| `ClaimSubmittedRelativeToTravel` | categorical (derived) | Before Travel, During Travel, After Travel — **most BRG programs only allow "Before Travel"** |

### 4.7 Booking — Type-Specific Extensions

| BookingType | Additional Fields |
| :---- | :---- |
| **Flight** | `Airline`, `FareClass` (Economy/Premium/Business/First), `Origin`, `Destination`, `NumberOfStops`, `FareType` (Basic/Standard/Flex) |
| **Hotel/Lodging** | `PropertyName`, `RoomType`, `StarRating`, `MealPlan`, `CheckInDate`, `CheckOutDate`, `NumberOfRooms` |
| **Car** | `RentalCompany`, `VehicleClass`, `PickupLocation`, `DropoffLocation`, `RentalDurationDays` |
| **Cruise** | `CruiseLine`, `ShipName`, `CabinType`, `PortsOfCall` (list), `NightsDuration` |
| **Package (multi-segment)** | `SegmentList`: array of `{SegmentID, SegmentType, SegmentAmount, SegmentDates}` — one sub-record per component |

### 4.8 Passenger / Traveler Details

| Field | Type | Notes |
| :---- | :---- | :---- |
| `NumberOfPassengers` | int | 1–8, weighted toward 1–4 |
| `PassengerDetails` | nested array | `{PassengerID, Name, Age, PassengerType (Adult/Child/Infant), LoyaltyNumber (optional)}` |
| `IsFamilyBooking` | bool (derived) | ≥1 Child/Infant present |

---

## 5\. Derived / Engineered Features (for the ML step)

Compute these from raw fields — they should carry real predictive signal:

- `DaysBookingToClaim` \= ClaimSubmissionDate − BookingDate  
- `DaysClaimToTravelStart` \= TravelStartDate − ClaimSubmissionDate (negative if after travel started)  
- `RateDifferenceAmount` \= ClaimAmount − BetterRateAmount (sanity check vs. BookingAmount)  
- `RateDifferencePercent` \= RateDifferenceAmount / BookingAmount  
- `AttachmentCompletenessScore` (0–1) \= weighted function of AttachmentCount \+ ProofQualityFlag  
- `HasValidBetterRateURL` (bool)  
- `AdvisorCaseloadAtSubmission` (int) — optional, for SLA-breach modeling  
- `SeasonalityFlag` (Peak/Shoulder/Off-Peak, based on TravelStartDate)  
- `LoyaltyTierOrdinal` (0–3)

---

## 6\. Eligibility Rules & Label-Generation Logic

To make `IsApproved` learnable (not random), generate it with a **weighted rule-based legitimacy score**, then pass through a probability function plus noise:

**Increases approval likelihood:**

- `AttachmentCount ≥ 1` and `ProofQualityFlag = Verified`  
- `RestrictionsMatchFlag = True`  
- `RateDifferencePercent` between \~3% and \~40% (plausible range)  
- `ClaimSubmittedRelativeToTravel = Before Travel`  
- `MinimumClaimThresholdMet = True`  
- High `PriorApprovalRate` for the customer  
- `HasValidBetterRateURL = True`

**Decreases approval likelihood:**

- No attachments / `ProofQualityFlag = Insufficient`  
- `RestrictionsMatchFlag = False` (different cancellation/fare terms — common real-world rejection reason)  
- `RateDifferencePercent > ~60%` (flagged as implausible/likely fraud or mismatched product)  
- Claim submitted `After Travel` or during blackout dates  
- `MinimumClaimThresholdMet = False`

**Implementation suggestion:** assign point weights to each factor → sum to a 0–100 `LegitimacyScore` → map through a sigmoid to get `P(Approved)` → sample `IsApproved` → **flip \~8–12% of labels randomly** to simulate real-world adjudicator subjectivity and edge cases (this noise level is what makes the case study realistic and prevents a trivial 100%-accuracy model).

**Rejection reason taxonomy** (sample from when `IsApproved = No`):

- Restrictions/flexibility do not match  
- Insufficient or unverifiable documentation  
- Rate no longer available at time of verification  
- Competing rate not from an eligible/comparable vendor  
- Price difference below minimum threshold  
- Claim submitted after travel completed  
- Blackout date / excluded fare or rate plan

**Approval reason taxonomy** (sample when `IsApproved = Yes`):

- Verified matching rate with equivalent terms  
- Documentation sufficient and rate independently confirmed  
- Within all program eligibility guidelines

---

## 7\. Data Volume, Format & Realism Parameters

- **Volume:** default 8,000–10,000 claim records (parameterize; note count in metadata)  
- **Class balance:** target \~55–65% Approved / 35–45% Not Approved (adjust via the scoring threshold, don't hard-code)  
- **BookingType distribution:** roughly Flight 35%, Hotel 30%, Package/Multi-segment 15%, Car 12%, Cruise 8% (adjustable)  
- **PII:** all customer data must be synthetic (e.g., via Faker) — no real names, emails, phone numbers, or addresses  
- **Missingness:** inject realistic nulls (e.g., some claims missing `InternalAdvisorNotes`, occasional missing `BetterRateURL` when proof was a screenshot only)  
- **Output:** flat CSV for the ML pipeline; nested JSON preserving `PassengerDetails` and `SegmentList` for the full record

---

## 8\. ML Modeling Requirements

- **Target:** `IsApproved` (binary classification)  
- **Split:** 70/15/15 train/validation/test, stratified on target  
- **Candidate models:** Logistic Regression (baseline/interpretable), Random Forest, XGBoost/LightGBM  
- **Evaluation metrics:** Accuracy, Precision, Recall, F1, ROC-AUC, confusion matrix — report Precision/Recall separately since false approvals (cost) and false rejections (customer trust) have different business costs  
- **Explainability:** SHAP or feature importance ranking — deliverable should identify which fields drive approval decisions (useful for advisor training and for the agentic-AI narrative)  
- **Business-value framing:** tie model output back to labor cost — e.g., "correctly flags X% of clear-cut approvals/rejections, potentially saving Y advisor-hours at $50/hr"

---

## 9\. Optional — Agentic Workflow Decomposition

Since this feeds an agentic-AI case study, the pipeline can be framed as discrete agent roles:

1. **Data Generation Agent** — builds the synthetic dataset per Sections 4–7  
2. **Feature Engineering Agent** — computes Section 5 derived features  
3. **Adjudication-Assist Agent** — trains/serves the classifier from Section 8 and produces a recommendation \+ rationale per case (mirroring what a human advisor does)  
4. **Explainability/QA Agent** — checks label consistency against the rules in Section 6 and flags anomalies  
5. **Orchestrator** — routes a new claim through 1→4 and hands a decision packet to a human advisor for final sign-off (human-in-the-loop, given the financial/customer-trust stakes)

---

## 10\. Acceptance Checklist

- [ ] All fields in Sections 4.1–4.8 present, correctly typed  
- [ ] Multi-segment bookings and multi-passenger records supported (not just flat single-item rows)  
- [ ] `IsApproved` demonstrably correlated with the rule factors in Section 6 (not random) but includes realistic noise  
- [ ] SLA and advisor-cost fields internally consistent (`AdjudicationLaborCost` matches `TimeToAdjudicateMinutes`)  
- [ ] No real PII anywhere in the dataset  
- [ ] Data dictionary delivered alongside the dataset  
- [ ] Trained model \+ metrics \+ top feature drivers delivered

