"""Settings page — Gemini API key + Indian Kanoon. Saved to .env"""
import streamlit as st
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")


def _read_env() -> dict:
    values = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r") as f:
            for line in f:
                line = line.strip()
                if line and "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    values[k.strip()] = v.strip()
    return values


def _write_env(values: dict):
    with open(ENV_PATH, "w") as f:
        for k, v in values.items():
            f.write(f"{k}={v}\n")
    # Reload into config module immediately
    import config as cfg
    cfg.GEMINI_API_KEY        = values.get("GEMINI_API_KEY", "")
    cfg.GEMINI_MODEL          = values.get("GEMINI_MODEL", "gemini-2.5-flash")
    cfg.INDIAN_KANOON_API_KEY = values.get("INDIAN_KANOON_API_KEY", "")


def _mask(key: str) -> str:
    if not key or len(key) < 8:
        return "not set"
    return key[:8] + "•" * max(4, len(key) - 12) + key[-4:]


def render():
    st.header("⚙️ Settings")
    st.caption("Keys saved to local `.env` — never uploaded anywhere.")

    env = _read_env()

    gemini_ok = bool(env.get("GEMINI_API_KEY"))
    ik_ok     = bool(env.get("INDIAN_KANOON_API_KEY"))

    # ── STATUS BANNER ─────────────────────────────────────────────────────────
    if gemini_ok:
        st.success(
            f"✅ **Gemini 2.5 Flash active** — all AI features enabled.",
            icon="✨"
        )
    else:
        st.error(
            "❌ **Gemini API key not set** — AI features will not work until you add it below.",
            icon="🔴"
        )

    # Status metrics
    col1, col2 = st.columns(2)
    col1.metric("Gemini 2.5 Flash", "✅ Ready"     if gemini_ok else "❌ Not set")
    col2.metric("Indian Kanoon",    "✅ Connected" if ik_ok     else "❌ Not set")

    st.divider()

    # ════════════════════════════════════════════════════════════════════════════
    # SECTION 1 — GEMINI
    # ════════════════════════════════════════════════════════════════════════════
    st.subheader("1 · Google Gemini API Key")
    st.markdown(
        "Get your **free** key at "
        "**[aistudio.google.com/apikey](https://aistudio.google.com/apikey)** "
        "— no billing required for the free tier.  \n"
        "Gemini 2.5 Flash is a thinking model: fast, accurate, great for legal reasoning."
    )

    col_a, col_b = st.columns([3, 1])
    with col_a:
        gemini_key = st.text_input(
            "Gemini API Key",
            value=env.get("GEMINI_API_KEY", ""),
            type="password",
            placeholder="AIzaSy...",
        )
        gemini_model = st.selectbox(
            "Model",
            ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
            index=(
                ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"].index(
                    env.get("GEMINI_MODEL", "gemini-2.5-flash")
                )
                if env.get("GEMINI_MODEL", "gemini-2.5-flash") in
                   ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"]
                else 0
            ),
            help="gemini-2.5-flash — recommended (fast + thinking) | gemini-2.5-pro — deeper but slower",
        )
    with col_b:
        st.markdown("<br><br>", unsafe_allow_html=True)
        if st.button("🔍 Test Gemini", key="test_gemini", use_container_width=True):
            if not gemini_key:
                st.warning("Enter the key first.")
            else:
                with st.spinner("Testing..."):
                    import config as cfg
                    cfg.GEMINI_API_KEY = gemini_key
                    cfg.GEMINI_MODEL   = gemini_model
                    from ai.gemini_client import test_connection
                    ok, msg = test_connection()
                if ok:
                    st.success(f"✅ {msg}")
                else:
                    st.error(f"❌ {msg}")

    st.divider()

    # ════════════════════════════════════════════════════════════════════════════
    # SECTION 2 — INDIAN KANOON
    # ════════════════════════════════════════════════════════════════════════════
    st.subheader("2 · Indian Kanoon — Live Case Search")
    st.markdown(
        "Enables real-time ITAT/HC/SC judgment search in Phase 3 and Citation DB.  \n"
        "Your key is already configured."
    )

    col_a, col_b = st.columns([3, 1])
    with col_a:
        ik_key = st.text_input(
            "Indian Kanoon API Token",
            value=env.get("INDIAN_KANOON_API_KEY", ""),
            type="password",
            placeholder="40-character hex token",
        )
    with col_b:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Test IK", key="test_ik", use_container_width=True):
            if not ik_key:
                st.warning("Enter token first.")
            else:
                with st.spinner("Testing..."):
                    import requests
                    try:
                        r = requests.post(
                            "https://api.indiankanoon.org/search/",
                            headers={"Authorization": f"Token {ik_key}"},
                            data={"formInput": "section 269SS", "pagenum": 0},
                            timeout=10,
                        )
                        if r.status_code == 200:
                            docs = r.json().get("docs", [])
                            st.success(f"✅ Connected — {len(docs)} results found")
                        else:
                            st.error(f"❌ HTTP {r.status_code}")
                    except Exception as e:
                        st.error(f"❌ {e}")

    st.divider()

    # ════════════════════════════════════════════════════════════════════════════
    # SAVE
    # ════════════════════════════════════════════════════════════════════════════
    if st.button("💾  Save Settings", type="primary", use_container_width=True):
        env["GEMINI_API_KEY"]        = gemini_key.strip()
        env["GEMINI_MODEL"]          = gemini_model.strip()
        env["INDIAN_KANOON_API_KEY"] = ik_key.strip()
        _write_env(env)
        st.success("✅ Settings saved.")
        st.rerun()

    st.divider()

    # ── Config summary ────────────────────────────────────────────────────────
    st.subheader("Current Configuration")
    env_fresh = _read_env()
    rows = []
    for k, v in env_fresh.items():
        display_v = _mask(v) if any(x in k for x in ("KEY", "TOKEN", "SECRET")) else v
        rows.append(f"| `{k}` | `{display_v}` |")
    if rows:
        st.markdown("| Variable | Value |\n|---|---|\n" + "\n".join(rows))

    st.caption(f"📁 Config file: `{ENV_PATH}`")
    st.info(
        "🔒 **Privacy note:** Gemini receives your (PII-redacted) legal queries. "
        "All case data is stored locally in SQLite on your machine."
    )
