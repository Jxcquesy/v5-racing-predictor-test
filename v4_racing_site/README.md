# V5 Racing Predictor — Streamlit

Only the trained V5 Top 3 model is used for new predictions. Historical coverage and safe results imports remain available.

## Deploy
Use `v4_racing_site/app.py` as the Streamlit entry point. Keep `v5_top3_model.joblib`, `v5_engine.py`, and `v5_feature_reference.py` in this folder. The requirements pin scikit-learn to 1.6.1.

## Use
Upload your master runner-results CSV in the sidebar. In the V5 tab, upload At The Races PDF form guides or a corrected runner CSV. Check runners, going, race types, distances and other fields before confirming. Press Generate V5 Top 10 and treble. Only races with six or more runners are eligible, with one horse per race.

Predictions and results tracking are manual, not an automatic live feed. Model percentages are estimates, not guarantees. Session uploads and results are not saved persistently.
