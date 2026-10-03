# PMG_AI – PriceMatch Guarantee real-time claim scorer

Standalone version of **Section 27 (Production Pipeline)** of `PMG.ipynb`. It loads the saved model
(`artifacts/pmg_predictor.joblib`) and scores raw price-match claims without needing the notebook.

For each claim it returns a decision and `P(approved)`:

| Decision | Rule |
| :- | :- |
| `APPROVE` | probability ≥ threshold + 0.07 |
| `REFER TO ADVISOR` | probability within ±0.07 of the threshold |
| `REJECT` | probability ≤ threshold − 0.07 |

The threshold (0.506) is stored inside the artifact. The model is a Random Forest.

## Files

| File | Purpose |
| :- | :- |
| `pmg_predict.py` | Feature pipeline, artifact loader, scoring functions and CLI |
| `demo_claims.py` | The five synthetic claims from Sections 26/27 |
| `artifacts/pmg_predictor.joblib` | Saved model, 119 feature columns, threshold, model name |
| `requirements.txt` | Pinned dependencies |

## Setup (Windows PowerShell)

```powershell
cd PMG_AI
python -m venv VENV_PMG
.\VENV_PMG\Scripts\Activate.ps1
pip install -r requirements.txt
```

macOS/Linux: `source VENV_PMG/bin/activate`.

## Run

```powershell
python pmg_predict.py                      # scores the 5 built-in demo claims
python pmg_predict.py --claim my_claim.json  # one claim (JSON object) or a list of claims
```

Expected output for the demo claims:

| Claim | Decision | P(approved) |
| :- | :- | :- |
| 1 · Textbook valid claim | APPROVE | 0.8864 |
| 2 · Junk claim | REJECT | 0.2054 |
| 3 · Terms mismatch + blackout + implausible gap | REJECT | 0.1677 |
| 4 · Borderline but solid | APPROVE | 0.8467 |
| 5 · Pristine claim, gap ~2% | APPROVE | 0.7610 |

## Use from Python

```python
from pmg_predict import load_artifact, score_claim
from demo_claims import DEMO_CLAIMS

bundle = load_artifact()
print(score_claim(DEMO_CLAIMS[0], bundle))   # {'decision': 'APPROVE', 'P(approved)': 0.8864}
```

A claim is a flat dict of raw intake fields (see `demo_claims.py` for every field name; required
fields are listed in Section 25.3 of the notebook).

## Notes

- The artifact was pickled with **scikit-learn 1.7.2**, which is pinned in `requirements.txt`. Loading it
  on 1.8+ works (a small compatibility shim in `load_artifact` handles it) but prints version warnings.
  Unpickling runs code, so only load artifacts you trust.
- The feature-engineering code in `pmg_predict.py` is a copy of the notebook's (Sections 17–25).
  If you change features in the notebook, re-copy it and re-save the joblib.
- `VENV_PMG/` is local and should not be committed.
