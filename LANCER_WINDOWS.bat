@echo off
REM Anonymiseur — lancement local (Windows)
REM Double-cliquez simplement sur ce fichier.
REM
REM Pourquoi ce script est nécessaire : les navigateurs (Chrome, Firefox,
REM Edge...) bloquent par sécurité le chargement de fichiers voisins
REM (comme les modèles OCR de tessdata/) quand une page est ouverte en
REM double-cliquant directement sur index.html (protocole file://). C'est
REM une restriction du navigateur lui-même, pas de cette application —
REM elle touche tous les sites qui fonctionnent de cette façon. Ce script
REM démarre un tout petit serveur local (accessible uniquement depuis
REM CET ordinateur, invisible depuis l'extérieur/internet) puis ouvre
REM automatiquement le navigateur dessus, ce qui contourne cette
REM restriction proprement.

cd /d "%~dp0"

set PORT=8000

where python >nul 2>nul
if %errorlevel%==0 (
    echo Demarrage du serveur local sur le port %PORT%...
    start "" http://localhost:%PORT%/
    python -m http.server %PORT%
    goto :eof
)

where py >nul 2>nul
if %errorlevel%==0 (
    echo Demarrage du serveur local sur le port %PORT%...
    start "" http://localhost:%PORT%/
    py -m http.server %PORT%
    goto :eof
)

where node >nul 2>nul
if %errorlevel%==0 (
    echo Demarrage du serveur local sur le port %PORT% ^(via Node.js^)...
    start "" http://localhost:%PORT%/
    npx --yes serve -l %PORT% .
    goto :eof
)

echo.
echo ============================================================
echo  Python ou Node.js sont necessaires pour lancer l'appli en local.
echo  Aucun des deux n'a ete trouve sur cet ordinateur.
echo.
echo  Solution la plus simple : installez Python depuis
echo  https://www.python.org/downloads/ (cochez "Add python.exe to PATH"
echo  pendant l'installation), puis redoublez-cliquez sur ce fichier.
echo ============================================================
echo.
pause
