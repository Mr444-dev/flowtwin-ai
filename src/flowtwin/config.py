from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
REPORTS_DIR = PROJECT_ROOT / "reports" / "generated"
DB_PATH = PROCESSED_DIR / "flowtwin.sqlite3"
MODEL_PATH = ARTIFACTS_DIR / "remaining_time.joblib"
METRICS_PATH = REPORTS_DIR / "metrics.json"

DATASET_NAME = "BPI Challenge 2017.xes.gz"
DATASET_URL = (
    "https://data.4tu.nl/file/34c3f44b-3101-4ea9-8281-e38905c68b8d/"
    "f3aec4f7-d52c-4217-82f4-57d719a8298c"
)
DATASET_MD5 = "10b37a2f78e870d78406198403ff13d2"
DATASET_DOI = "10.4121/uuid:5f3067df-f10b-45da-b98b-86ae4c7a310b"

# A trace is counted as completed only when its final observed activity is one
# of these documented business outcomes. This is a transparent MVP heuristic.
TERMINAL_ACTIVITIES = {
    "A_Pending",
    "A_Denied",
    "A_Cancelled",
    "O_Accepted",
    "O_Refused",
    "O_Cancelled",
}

# Only these case fields are used. They are added to a feature vector only after
# they have appeared in the observed prefix, preventing future-attribute leakage.
NUMERIC_CASE_FIELDS = {
    "case:RequestedAmount": "requested_amount",
    "case:FirstWithdrawalAmount": "first_withdrawal_amount",
    "case:CreditScore": "credit_score",
    "case:MonthlyCost": "monthly_cost",
    "case:NumberOfTerms": "number_of_terms",
}
CATEGORICAL_CASE_FIELDS = {
    "case:LoanGoal": "loan_goal",
    "case:ApplicationType": "application_type",
}

# Observable prefix lengths avoid using the eventual trace length to choose a
# training snapshot. Cases contribute at most six forecasts.
SNAPSHOT_PREFIX_COUNTS = (1, 3, 5, 10, 20, 40)
