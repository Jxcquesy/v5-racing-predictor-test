"""V5 Supabase REST storage. Credentials are read ONLY from Streamlit Secrets.

NOTE: This test build has no user authentication. Restrict app access before
using with real data. A service-role key bypasses Supabase row-level security.
"""
import requests
import streamlit as st

TABLE = "v5_bets"


def config():
    """Return (url, key), or None if either configured secret is missing."""
    try:
        url = str(st.secrets.get("SUPABASE_URL", "")).strip().rstrip("/")
        key = str(st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
    except (FileNotFoundError, OSError):
        return None
    if not url.startswith("https://") or not key:
        return None
    return url, key


def login():
    """Check connectivity settings only; NOT an authentication mechanism."""
    try:
        has_url = bool(str(st.secrets.get("SUPABASE_URL", "")).strip())
        has_key = bool(str(st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", "")).strip())
    except (FileNotFoundError, OSError):
        has_url = has_key = False
    if not has_url or not has_key:
        missing = []
        if not has_url: missing.append("SUPABASE_URL")
        if not has_key: missing.append("SUPABASE_SERVICE_ROLE_KEY")
        st.error("Streamlit Secrets missing: " + ", ".join(missing) + ". Configure these in the TEST app's Settings → Secrets.")
        return False
    if not config():
        st.error("Supabase URL must begin with https:// and both secrets must contain actual values, not placeholders.")
        return False
    return True


def request(method, path="", payload=None, params=None):
    cfg = config()
    if not cfg:
        raise ValueError("Supabase Secrets are missing or invalid. Check the TEST app's Settings → Secrets.")
    url, key = cfg
    if method not in {"GET", "POST", "PATCH"}:
        raise ValueError("Unsupported Supabase method")
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
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        # Avoid echoing sensitive request headers or response body.
        raise RuntimeError(f"Supabase returned HTTP {response.status_code} when accessing {TABLE}.") from exc
    return response.json() if response.content else []
