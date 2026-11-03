
"""Persistent V5 bet builder using Supabase REST."""

import pandas as pd
import requests
import streamlit as st

TABLE = "v5_bets"


def config():
    try:
        url = str(st.secrets["SUPABASE_URL"]).rstrip("/")
        key = str(st.secrets["SUPABASE_SERVICE_ROLE_KEY"])

        if not url.startswith("https://") or not key:
            return None

        return url, key

    except (KeyError, FileNotFoundError):
        return None


def request(method, path="", payload=None, params=None):
    cfg = config()

    if not cfg:
        raise ValueError("Supabase secrets are not configured")

    url, key = cfg

    headers = {
        "apikey": key,
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

    response = requests.request(
        method,
        f"{url}/rest/v1/{TABLE}{path}",
        headers=headers,
        json=payload,
        params=params,
        timeout=20,
    )

    response.raise_for_status()
    return response.json() if response.content else []


def login():
    if not config():
        st.warning("Permanent tracking is not configured yet.")
        return False

    return True


def show(picks, day):
    st.subheader("Top 10 — odds & accumulator builder")

    st.caption(
        "Minimum recommended odds = 1.05 ÷ model Top 3 probability "
        "(5% theoretical expected ROI). Estimates depend on "
        "probability calibration."
    )

    if not login():
        df = picks[
            ["Horse", "Course", "Time", "Top 3 Probability"]
        ].copy()

        df["Top 3 %"] = (
            df.pop("Top 3 Probability") * 100
        ).round(1)

        df["Minimum recommended odds"] = (
            1.05 / (df["Top 3 %"] / 100)
        ).round(2)

        st.dataframe(
            df,
            hide_index=True,
            use_container_width=True,
        )
        return

    df = picks[
        ["Horse", "Course", "Time", "Top 3 Probability"]
    ].copy().reset_index(drop=True)

    df["Top 3 %"] = (
        df.pop("Top 3 Probability") * 100
    ).round(1)

    df["Minimum recommended odds"] = (
        1.05 / (df["Top 3 %"] / 100)
    ).round(2)

    df["Bet365 Top 3 odds"] = [None] * len(df)
    df["Add to bet"] = [False] * len(df)

    editor_key = "bet_editor_" + str(day)

    edited = st.data_editor(
        df,
        hide_index=True,
        use_container_width=True,
        key=editor_key,
        disabled=[
            "Horse",
            "Course",
            "Time",
            "Top 3 %",
            "Minimum recommended odds",
        ],
        column_config={
            "Bet365 Top 3 odds": st.column_config.NumberColumn(
                min_value=1.01,
                step=0.01,
                format="%.2f",
            ),
            "Add to bet": st.column_config.CheckboxColumn(),
            "Minimum recommended odds": st.column_config.NumberColumn(
                format="%.2f"
            ),
        },
    )

    chosen = edited[edited["Add to bet"] == True].copy()

    valid = True

    for _, row in chosen.iterrows():
        odds = row["Bet365 Top 3 odds"]

        if pd.isna(odds) or float(odds) <= 1:
            valid = False
            break

    combined = 1.0

    if valid:
        for odds in chosen["Bet365 Top 3 odds"]:
            combined *= float(odds)

    st.subheader("Your accumulator")

    if chosen.empty:
        st.info("Tick horses in the table to build a bet.")

    else:
        for _, row in chosen.iterrows():
            odds = row["Bet365 Top 3 odds"]

            price = (
                "Enter odds"
                if pd.isna(odds)
                else f"{float(odds):.2f}"
            )

            is_value = (
                not pd.isna(odds)
                and float(odds)
                >= float(row["Minimum recommended odds"])
            )

            status = (
                "Value ✓"
                if is_value
                else "Below target / no odds"
            )

            st.write(
                f"**{row['Horse']}** — {price} · {status}"
            )

        if valid:
            st.metric(
                "Combined decimal odds",
                f"{combined:.2f}",
            )
        else:
            st.warning(
                "Enter valid decimal odds for every "
                "selected horse before saving."
            )

    units = st.number_input(
        "Stake (units)",
        min_value=0.01,
        value=1.0,
        step=0.25,
        key="stake_units",
    )

    if st.button(
        "Save this bet permanently",
        disabled=chosen.empty or not valid,
        type="primary",
    ):
        legs = [
            {
                "horse": str(row["Horse"]),
                "course": str(row["Course"]),
                "time": str(row["Time"]),
                "probability": float(row["Top 3 %"]) / 100,
                "min_odds": float(
                    row["Minimum recommended odds"]
                ),
                "odds": float(row["Bet365 Top 3 odds"]),
            }
            for _, row in chosen.iterrows()
        ]

        payload = {
            "race_date": str(day),
            "legs": legs,
            "combined_odds": round(combined, 6),
            "stake_units": float(units),
            "result": "Pending",
        }

        try:
            request("POST", payload=payload)
            st.success("Bet saved to permanent history.")

        except Exception as exc:
            st.error(f"Could not save bet: {exc}")

    st.divider()
    st.subheader("Permanent bet history & units")

    try:
        rows = request(
            "GET",
            params={
                "select": "*",
                "order": "created_at.desc",
                "limit": "1000",
            },
        )

    except Exception as exc:
        st.error(f"Could not load history: {exc}")
        return

    won = sum(
        1 for row in rows if row["result"] == "Won"
    )

    lost = sum(
        1 for row in rows if row["result"] == "Lost"
    )

    pending = sum(
        1 for row in rows if row["result"] == "Pending"
    )

    pnl = sum(
        (
            (float(row["combined_odds"]) - 1)
            * float(row["stake_units"])
            if row["result"] == "Won"
            else -float(row["stake_units"])
            if row["result"] == "Lost"
            else 0
        )
        for row in rows
    )

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Net units", f"{pnl:+.2f}u")
    col2.metric("Won", won)
    col3.metric("Lost", lost)
    col4.metric("Pending", pending)

    for row in rows:
        horses = ", ".join(
            leg["horse"] for leg in row["legs"]
        )

        title = (
            f"{row['race_date']} · "
            f"{len(row['legs'])}-fold · "
            f"{float(row['combined_odds']):.2f} · "
            f"{row['result']}"
        )

        with st.expander(title):
            st.write(horses)

            stake = float(row["stake_units"])
            odds = float(row["combined_odds"])

            if row["result"] == "Won":
                result_pnl = f"{(odds - 1) * stake:+.2f}u"
            elif row["result"] == "Lost":
                result_pnl = f"{-stake:+.2f}u"
            else:
                result_pnl = "Pending / Void"

            st.caption(
                f"Stake: {stake:g}u · P/L: {result_pnl}"
            )

            statuses = [
                "Pending",
                "Won",
                "Lost",
                "Void",
            ]

            current_result = row["result"]

            new_result = st.selectbox(
                "Set result",
                statuses,
                index=(
                    statuses.index(current_result)
                    if current_result in statuses
                    else 0
                ),
                key="result_" + str(row["id"]),
            )

            if st.button(
                "Update result",
                key="save_result_" + str(row["id"]),
                disabled=new_result == current_result,
            ):
                try:
                    request(
                        "PATCH",
                        payload={"result": new_result},
                        params={
                            "id": "eq." + str(row["id"])
                        },
                    )
                    st.rerun()

                except Exception as exc:
                    st.error(f"Update failed: {exc}")

    if rows:
        export = pd.DataFrame(
            [
                {
                    "date": row["race_date"],
                    "horses": ", ".join(
                        leg["horse"] for leg in row["legs"]
                    ),
                    "odds": row["combined_odds"],
                    "stake_units": row["stake_units"],
                    "result": row["result"],
                }
                for row in rows
            ]
        )

        st.download_button(
            "Export bet history CSV",
            export.to_csv(index=False).encode(),
            "V5_bet_history.csv",
            "text/csv",
        )

    st.caption(
        "Void bets count as zero profit/loss. "
        "Pending bets do not affect units. "
        "Odds and stake are frozen when saved. "
        "No bets are placed automatically."
    )
