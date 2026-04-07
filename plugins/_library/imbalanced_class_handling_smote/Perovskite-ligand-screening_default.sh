# ── SNIPPET: imbalanced_class_handling_smote/Perovskite-ligand-screening_default ─
# Scheduler:   any
# Tool:        sklearn
# Tested:      ML/ML_all_model.py
# Invariants:
#   - Oversample minority class with SMOTE(sampling_strategy='minority') before splitting.
# Notes: This is the exact ordering used in the workflow.
# ────────────────────────────────────────────────────────────

from imblearn.over_sampling import SMOTE
from sklearn.model_selection import train_test_split

oversample = SMOTE(sampling_strategy='minority')
X_over, y_over = oversample.fit_resample(data, label)
X_train, X_test, y_train, y_test = train_test_split(X_over, y_over, test_size=0.2,random_state=0)
