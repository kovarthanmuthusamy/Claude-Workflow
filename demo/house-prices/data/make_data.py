"""Create a synthetic apartment-listings CSV in data/ (fixed seed, so runs are repeatable)."""

from pathlib import Path

import numpy as np
import pandas as pd

if __name__ == "__main__":
    rng = np.random.default_rng(3)
    n = 240
    size = rng.normal(75, 25, n).clip(25, 180).round()          # square metres
    rooms = (size / 28 + rng.normal(0, 0.6, n)).clip(1, 6).round()
    distance = rng.gamma(2.0, 2.5, n).round(1)                   # km to the city centre
    age = rng.integers(0, 80, n)                                 # years since built
    # Price in thousands: mostly size and distance, plus noise. Rooms adds little once size is known.
    price = 40 + 3.1 * size + 4 * rooms - 9 * distance - 0.6 * age + rng.normal(0, 25, n)
    out = Path(__file__).parent / "listings.csv"
    pd.DataFrame({"size_m2": size, "rooms": rooms, "distance_km": distance,
                  "age_years": age, "price_k": price.round(1)}).to_csv(out, index=False)
    print(f"wrote {n} listings to {out}")
