@echo off
echo ========================================
echo   Litigation Intelligence OS v2.0
echo   AI Co-Pilot for Indian Tax Litigation
echo ========================================
echo.

:: Change to the folder this batch file lives in
cd /d "%~dp0"

:: ── Start Ollama daemon ───────────────────────────────────────────────────────
echo [1/6] Starting Ollama...
start "" ollama serve

:: Give Ollama a moment to come up
timeout /t 4 /nobreak >nul

:: ── Pull primary model: mistral:7b ───────────────────────────────────────────
echo [2/6] Checking mistral:7b (primary model — better legal reasoning)...
ollama pull mistral:7b

:: ── Pull fallback model: phi3:mini ───────────────────────────────────────────
echo Checking phi3:mini (fallback model — fast, low RAM)...
ollama pull phi3:mini

echo.

:: ── Install Python dependencies ───────────────────────────────────────────────
echo [3/6] Installing Python dependencies...
python -m pip install streamlit anthropic python-dotenv PyMuPDF pdfplumber ^
    pandas plotly python-dateutil Pillow requests -q

echo.

:: ── Install spaCy + English NER model (for PII name detection) ───────────────
echo [4/6] Setting up spaCy NER (for PII name detection)...
python -m pip install spacy -q
python -m spacy download en_core_web_sm --quiet 2>nul || echo   (spaCy model already installed or skipped)

echo.

:: ── Install Playwright + Chromium (for Taxscan full-content scraping) ─────────
echo [5/6] Setting up Playwright browser (for Taxscan full content)...
python -m pip install playwright -q
python -m playwright install chromium --with-deps 2>nul || echo   (Playwright install skipped — optional)

echo.

:: ── Launch the app ────────────────────────────────────────────────────────────
echo [6/6] Starting Litigation OS...
echo.
echo  Open your browser at: http://localhost:8501
echo  Press Ctrl+C in this window to stop the app
echo.
echo ========================================
echo   AI Engine: mistral:7b (local Ollama)
echo   Fallback:  Claude API (if key set)
echo   Privacy:   PII redacted before any AI call
echo ========================================
echo.
python -m streamlit run app.py --server.port 8501 --server.headless false
pause
