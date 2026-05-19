@echo off
echo ========================================
echo   Litigation Intelligence OS v1.0
echo   AI Co-Pilot for Indian Tax Litigation
echo ========================================
echo.

:: Change to the folder this batch file lives in
cd /d "%~dp0"

echo Installing dependencies...
python -m pip install streamlit anthropic python-dotenv PyMuPDF pdfplumber pandas plotly python-dateutil Pillow requests -q
echo.
echo Starting Litigation OS...
echo Open your browser at: http://localhost:8501
echo.
python -m streamlit run app.py --server.port 8501 --server.headless false
pause
