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
