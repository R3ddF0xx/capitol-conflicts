@echo off
echo ============================================
echo  Capitol Conflicts — Data Pipeline
echo ============================================
echo.

echo [1/4] Fetching Congress members...
python fetch_members.py
echo.

echo [2/4] Fetching Senate stock disclosures...
python fetch_disclosures.py --chamber senate
echo.

echo [3/4] Fetching votes (current congress only)...
python fetch_votes.py --congress 119
echo.
echo To fetch full history back to 2009 run:
echo   python fetch_votes.py --start 111 --end 119
echo.

echo [4/4] Computing conflicts...
python compute_conflicts.py
echo.

echo ============================================
echo  Pipeline complete.
echo ============================================
pause
