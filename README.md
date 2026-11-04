# V5 Racing Predictor — clean test deployment

Main Streamlit entrypoint: **app.py** (repository root). Python: **3.12**.

## Upload

Upload the **contents** of this ZIP to the **root** of your GitHub test repository. Do not upload the enclosing folder itself. Keep the model `v5_top3_model.joblib` at root. Set Streamlit main file to `app.py` and Python to 3.12.

## Secrets

In the **test** app's Streamlit Cloud Settings → Secrets, set:

```toml
SUPABASE_URL = "https://YOUR_PROJECT.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "YOUR_ACTUAL_KEY"
```

Never add real secrets to GitHub or screenshots. The app reads them at runtime. No `TRACKER_PASSWORD` is required by this build.

## What works / does not

- V5 Top 3 inference and the supplied trained model are preserved.
- Racecard PDF and corrected CSV inputs, chronological AI picks, betslip, and history use the root `app.py`.
- Supabase history reads/writes the **existing** `v5_bets` table. The ZIP does not modify your database; clicking Save or Update in the deployed app **does** modify that table.
- The historical Master CSV is still a **session upload**. Automated fetching, persistent Master storage, model retraining, per-leg non-runner repricing, and settled return adjustments are **not implemented**.
- **Security warning:** this build does not authenticate users. If the test app is public, anyone who opens it can access or modify betting history using the app's server-side credentials. Protect the app before using it with real data; ideally use user authentication with row-level security rather than an unrestricted service-role key.

If the app reports missing Secrets, check the **test app**, not the original. If it reports HTTP 401/403, check credentials and access; do not paste keys into chat.
