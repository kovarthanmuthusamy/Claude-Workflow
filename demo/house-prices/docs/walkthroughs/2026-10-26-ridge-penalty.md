# Ridge penalty, with the strength chosen on held-back apartments

## In one paragraph

The price model is a weighted sum of four apartment properties (size, rooms, distance to
the centre, age) plus a base price. Before this change, the weights were chosen purely to
minimise the squared prediction errors on the 180 training apartments. Now the fit also pays
a cost of *penalty × (sum of squared weights)*, which pulls the weights towards zero, so no
property can take an extreme weight just to explain a few odd apartments. How strong that
penalty should be is not guessed: 13 candidate strengths are tried, each is scored on
training apartments that were held back from that particular fit, and the best one wins.
The 60 test apartments are never used in that choice, so their error stays an honest
estimate.

## Step by step

### 1. Fit with a penalty on large weights

The fit now minimises *(sum of squared errors) + penalty × (sum of squared weights)*. To keep
the base price out of the penalty, the properties and prices are first shifted so their
averages are zero; then the base price is simply whatever makes the average prediction equal
the average price. With penalty 0 this is exactly the old least-squares fit.

- `Xc = X - x_mean`: shift every property so its average over these apartments is 0.
- `np.linalg.solve(Xc.T @ Xc + penalty * np.eye(...), Xc.T @ (y - y_mean))`: this is the
  standard ridge solution. It is the usual least-squares equation, except that `penalty` is
  added to each diagonal entry of the "properties × properties" matrix. That extra amount
  shrinks the weights and keeps the answer stable when two properties nearly duplicate
  each other.
- `y_mean - x_mean @ w`: the base price is set so that, on average, predictions match the
  average price.

<details><summary>Code: fit_linear</summary>

<!-- code: src/train.py:fit_linear -->
```python
def fit_linear(X: np.ndarray, y: np.ndarray, penalty: float = 0.0) -> tuple[np.ndarray, float]:
    # Centre first so the base price is left out of the penalty.
    x_mean, y_mean = X.mean(axis=0), y.mean()
    Xc = X - x_mean
    w = np.linalg.solve(Xc.T @ Xc + penalty * np.eye(X.shape[1]), Xc.T @ (y - y_mean))
    return w, float(y_mean - x_mean @ w)
```
<!-- /code -->

</details>

### 2. Choose the penalty strength on apartments the fit didn't see

The 180 training apartments are shuffled (fixed seed, so the result is repeatable) and cut
into 5 groups of 36. For each group in turn, the other 4 groups (144 apartments) are
rescaled using their own mean and spread and fitted at every candidate strength. Each fit
is then scored by its typical error (RMSE) on the held-back group. Averaging over the 5
groups gives one held-out error per strength, and the lowest one is chosen.

- `PENALTIES = [0] + 12 values from 0.01 to 1000, evenly spaced on a log scale`: 0 is
  included, so "no penalty" can win.
- `make_features(train_df.iloc[folds[k]], scaling)`: the held-back group is rescaled with
  the *fitting* groups' mean and spread, never its own, so no information leaks from it.
- `PENALTIES[np.argmin(cv_rmse)]`: keep the strength with the smallest average held-out
  error.

<details><summary>Code: choose_penalty</summary>

<!-- code: src/train.py:choose_penalty -->
```python
def choose_penalty(train_df: pd.DataFrame, n_folds: int = 5, seed: int = 0) -> tuple[float, np.ndarray]:
    folds = np.array_split(np.random.default_rng(seed).permutation(len(train_df)), n_folds)
    cv_rmse = np.zeros(len(PENALTIES))
    for k in range(n_folds):
        fit_rows = np.concatenate([f for j, f in enumerate(folds) if j != k])
        X_fit, y_fit, scaling = make_features(train_df.iloc[fit_rows])
        X_val, y_val, _ = make_features(train_df.iloc[folds[k]], scaling)
        for i, lam in enumerate(PENALTIES):
            w, b = fit_linear(X_fit, y_fit, lam)
            cv_rmse[i] += np.sqrt(np.mean((X_val @ w + b - y_val) ** 2)) / n_folds
    return float(PENALTIES[np.argmin(cv_rmse)]), cv_rmse
```
<!-- /code -->

</details>

### 3. Refit on all 180 and save

With the chosen strength, the model is fitted once more on all 180 training apartments. The
weights, base price, rescaling and chosen penalty are saved, and evaluation on the 60 test
apartments runs exactly as before.

## Worked example

Twenty made-up apartments, built so that the penalty clearly matters. *Rooms* is almost a
copy of *size* (correlation 0.95), the true price rule ignores rooms entirely, and there
is a lot of noise relative to only 20 apartments.

<!-- run: python docs/walkthroughs/ridge-penalty_example.py -->
```text
First 5 of 20 apartments:
 size_m2  rooms  distance_km  age_years  price_k
    81.0    3.0         11.5       38.0    103.0
   116.0    5.0          4.9       51.0    229.0
    52.0    2.0          7.8       36.0     90.0
   116.0    5.0         14.7       16.0    142.0
    65.0    3.0         14.5       50.0     21.0
correlation of size and rooms: 0.952

Weights (size, rooms, distance, age) and base price as the penalty grows:
  penalty   0:  weights [ 36.2   7.7 -48.2 -15.5]  size of weights   62.7  base 124.75
  penalty   1:  weights [ 29.6  12.9 -46.5 -14.6]  size of weights   58.5  base 124.75
  penalty  10:  weights [ 20.3  13.1 -31.4  -9.2]  size of weights   40.7  base 124.75
  penalty 100:  weights [ 6.2  4.7 -7.1 -2. ]  size of weights   10.8  base 124.75

Held-out error per penalty (5 groups of 4 apartments, each held back once):
  penalty     0.000  held-out RMSE   20.1
  penalty     0.010  held-out RMSE   20.1
  penalty     0.028  held-out RMSE   20.0
  penalty     0.081  held-out RMSE   19.8
  penalty     0.231  held-out RMSE   19.3
  penalty     0.658  held-out RMSE   18.5
  penalty     1.874  held-out RMSE   18.4  <- lowest
  penalty     5.337  held-out RMSE   23.9
  penalty    15.199  held-out RMSE   36.2
  penalty    43.288  held-out RMSE   48.7
  penalty   123.285  held-out RMSE   56.9
  penalty   351.119  held-out RMSE   60.9
  penalty  1000.000  held-out RMSE   62.6
chosen penalty: 1.874
```
<!-- /run -->

<details><summary>Code: the example script</summary>

<!-- code: docs/walkthroughs/ridge-penalty_example.py -->
```python
"""Worked example: ridge penalty on 20 made-up apartments, where size and rooms nearly duplicate each other."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.prepare import make_features
from src.train import PENALTIES, choose_penalty, fit_linear

rng = np.random.default_rng(1)
n = 20
size = rng.uniform(40, 120, n).round()
apartments = pd.DataFrame({
    "size_m2": size,
    "rooms": (size / 25).round(),            # rooms follow size almost exactly
    "distance_km": rng.uniform(1, 15, n).round(1),
    "age_years": rng.uniform(0, 60, n).round(),
})
# True rule: price depends on size, distance and age only (rooms adds nothing), plus noise.
apartments["price_k"] = (60 + 2 * size - 8 * apartments["distance_km"]
                         - 0.5 * apartments["age_years"] + rng.normal(0, 25, n)).round()

print("First 5 of 20 apartments:")
print(apartments.head().to_string(index=False))
print("correlation of size and rooms:", round(np.corrcoef(apartments["size_m2"], apartments["rooms"])[0, 1], 3))

X, y, _ = make_features(apartments)
print("\nWeights (size, rooms, distance, age) and base price as the penalty grows:")
for lam in [0, 1, 10, 100]:
    w, b = fit_linear(X, y, lam)
    print(f"  penalty {lam:>3}:  weights {np.round(w, 1)}  size of weights {np.linalg.norm(w):6.1f}  base {b:.2f}")

penalty, cv_rmse = choose_penalty(apartments)
print("\nHeld-out error per penalty (5 groups of 4 apartments, each held back once):")
for lam, err in zip(PENALTIES, cv_rmse):
    mark = "  <- lowest" if lam == penalty else ""
    print(f"  penalty {lam:9.3f}  held-out RMSE {err:6.1f}{mark}")
print("chosen penalty:", round(penalty, 3))
```
<!-- /code -->

</details>

**Reading the numbers.**

- **The weights shrink as the penalty grows.** Their combined size falls from 62.7 (no
  penalty) to 58.5, 40.7, then 10.8 at penalty 100. The base price stays at 124.75, the
  average price, because it is never penalised.
- **Size and rooms share the credit.** At penalty 0, size takes 36.2 and rooms 7.7. At
  penalty 1, size drops to 29.6 and rooms rises to 12.9. Because the two carry nearly the
  same information, the penalty prefers two moderate weights to one large one: that gives a
  smaller sum of squares for almost the same fit.
- **Held-out error has a clear best strength.** It falls from 20.1 (no penalty) to 18.4
  at penalty 1.87, then rises steeply: 23.9 at 5.3, and 62.6 at 1000. Too little penalty
  lets the weights chase noise; too much flattens every apartment towards the average price.
  The procedure picks the bottom, 1.87.

**On the real data** (180 apartments, 4 properties), the same curve is flat at 24.03 from 0
up to 0.66 and only rises after that. With that many apartments per weight, the plain fit
is already stable, so the chosen penalty of 0.66 barely moves the weights. Test error
went from 24.3 to 24.4.

## What changed

- **src/train.py**: the fit takes a penalty strength. A new step picks that strength by
  5-group held-out scoring. The training run prints the held-out error for every candidate
  and saves the chosen penalty with the model.
- **architecture.yaml**: new `choose_penalty` step and its arrows; `fit_linear` updated.
- **docs/walkthroughs/**: this walkthrough and its example script.

<details><summary>Exact changes</summary>

<!-- diff: src/train.py -->
```diff
diff --git a/src/train.py b/src/train.py
index e701ddd..5e3c99a 100644
--- a/src/train.py
+++ b/src/train.py
@@ -1,20 +1,42 @@
 from pathlib import Path
 
 import numpy as np
+import pandas as pd
 
 from src.prepare import load_listings, make_features, split_listings
 
+PENALTIES = np.concatenate([[0.0], np.logspace(-2, 3, 12)])
 
-def fit_linear(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float]:
-    A = np.hstack([X, np.ones((len(X), 1))])
-    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
-    return coef[:-1], float(coef[-1])
+
+def fit_linear(X: np.ndarray, y: np.ndarray, penalty: float = 0.0) -> tuple[np.ndarray, float]:
+    # Centre first so the base price is left out of the penalty.
+    x_mean, y_mean = X.mean(axis=0), y.mean()
+    Xc = X - x_mean
+    w = np.linalg.solve(Xc.T @ Xc + penalty * np.eye(X.shape[1]), Xc.T @ (y - y_mean))
+    return w, float(y_mean - x_mean @ w)
+
+
+def choose_penalty(train_df: pd.DataFrame, n_folds: int = 5, seed: int = 0) -> tuple[float, np.ndarray]:
+    folds = np.array_split(np.random.default_rng(seed).permutation(len(train_df)), n_folds)
+    cv_rmse = np.zeros(len(PENALTIES))
+    for k in range(n_folds):
+        fit_rows = np.concatenate([f for j, f in enumerate(folds) if j != k])
+        X_fit, y_fit, scaling = make_features(train_df.iloc[fit_rows])
+        X_val, y_val, _ = make_features(train_df.iloc[folds[k]], scaling)
+        for i, lam in enumerate(PENALTIES):
+            w, b = fit_linear(X_fit, y_fit, lam)
+            cv_rmse[i] += np.sqrt(np.mean((X_val @ w + b - y_val) ** 2)) / n_folds
+    return float(PENALTIES[np.argmin(cv_rmse)]), cv_rmse
 
 
 if __name__ == "__main__":
     train_df, _ = split_listings(load_listings(Path("data/listings.csv")))
+    penalty, cv_rmse = choose_penalty(train_df)
+    for lam, err in zip(PENALTIES, cv_rmse):
+        print(f"penalty {lam:9.3f}  held-out RMSE {err:6.2f}")
     X, y, scaling = make_features(train_df)
-    w, b = fit_linear(X, y)
+    w, b = fit_linear(X, y, penalty)
     Path("models").mkdir(exist_ok=True)
-    np.savez("models/model.npz", w=w, b=b, mean=scaling[0], std=scaling[1])
+    np.savez("models/model.npz", w=w, b=b, mean=scaling[0], std=scaling[1], penalty=penalty)
+    print("chosen penalty:", round(penalty, 3))
     print("weights per feature:", np.round(w, 2), "intercept:", round(b, 1))
```
<!-- /diff -->

</details>

## Check your understanding

1. On the real data, the procedure chose 0.66 rather than 0, even though both scored 24.03.
   Why can it pick a nonzero penalty when the scores look equal?

   <details><summary>Answer</summary>

   The scores are rounded to two decimals in the printout. Underneath, 0.66 was very
   slightly lower, so it was the smallest. A difference that small is noise, and in
   practice 0 and 0.66 are equally good. You can see this in the result: the weights
   barely moved and test error was essentially unchanged.

   </details>

2. What would go wrong if the penalty were chosen by scoring each candidate on the 60 test
   apartments instead?

   <details><summary>Answer</summary>

   The test apartments would then have helped choose the model, so their error would be
   optimistically biased. It would no longer be an honest estimate of how the model does on
   genuinely new apartments.

   </details>

3. If the penalty were enormous (say a million), what would the model predict for every
   apartment?

   <details><summary>Answer</summary>

   Every weight would be pushed to almost zero, so every apartment would get roughly the
   same prediction: the base price, which is the average training price. The base price is
   not penalised, so it survives. In the example, penalty 100 already shrank the weights to
   a combined size of 10.8 while the base stayed at 124.75.

   </details>
