# ── SNIPPET: gridsearch_with_leave_one_out/Perovskite-ligand-screening_default ─
# Scheduler:   any
# Tool:        sklearn
# Tested:      ML/ML_all_model.py
# Invariants:
#   - Use LeaveOneOut() for cv on small datasets.
#   - Return best_estimator_ after reporting.
# Notes: The tuned parameter grids are model-specific and embedded in the function.
# ────────────────────────────────────────────────────────────

from sklearn.model_selection import GridSearchCV, LeaveOneOut
from sklearn.tree import DecisionTreeClassifier

cv = LeaveOneOut()
tuned_parameters = [{'max_depth':list(range(1,20))}]
clf = GridSearchCV(DecisionTreeClassifier(),tuned_parameters,scoring='accuracy',return_train_score=True,cv=cv,n_jobs=64)
clf.fit(X_train,y_train)
best = clf.best_estimator_
