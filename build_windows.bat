@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

echo ============================================
echo  Anonymiseur - Construction de l'executable
echo  (avec Poppler et Tesseract embarques)
echo ============================================
echo.

REM ----------------------------------------------------------------
REM 1. Localiser Tesseract et Poppler DEJA installes sur cette machine
REM    (ceux que vous avez installes en suivant le README precedent).
REM    On ne les re-telecharge pas : on recopie simplement leurs
REM    fichiers pour les embarquer dans l'executable final.
REM ----------------------------------------------------------------

where tesseract >nul 2>nul
if errorlevel 1 (
    echo ERREUR : tesseract.exe introuvable dans le PATH.
    echo Installez Tesseract d'abord ^(voir README.md, section OCR^),
    echo verifiez qu'il est dans le PATH ^(pdftoppm -v doit fonctionner^),
    echo puis relancez ce script.
    pause
    exit /b 1
)
for /f "delims=" %%i in ('where tesseract') do set "TESS_EXE=%%i"
for %%F in ("%TESS_EXE%") do set "TESS_DIR=%%~dpF"
REM IMPORTANT : retirer le \ final. "%TESS_DIR%" avec un \ juste avant le
REM guillemet fermant casse silencieusement les commandes qui suivent
REM (piege classique de l'interpretation des arguments sous Windows).
if "%TESS_DIR:~-1%"=="\" set "TESS_DIR=%TESS_DIR:~0,-1%"

where pdftoppm >nul 2>nul
if errorlevel 1 (
    echo ERREUR : pdftoppm.exe introuvable dans le PATH.
    echo Installez Poppler d'abord ^(voir README.md, section OCR^),
    echo puis relancez ce script.
    pause
    exit /b 1
)
for /f "delims=" %%i in ('where pdftoppm') do set "POPPLER_EXE=%%i"
for %%F in ("%POPPLER_EXE%") do set "POPPLER_DIR=%%~dpF"
if "%POPPLER_DIR:~-1%"=="\" set "POPPLER_DIR=%POPPLER_DIR:~0,-1%"

echo Tesseract trouve : %TESS_DIR%
echo Poppler trouve   : %POPPLER_DIR%
echo.

REM ----------------------------------------------------------------
REM 2. Construire l'executable avec PyInstaller (dossier autonome,
REM    pas de console qui s'ouvre derriere la fenetre de l'appli).
REM ----------------------------------------------------------------

echo ============================================
echo  Construction avec PyInstaller...
echo ============================================

if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

venv\Scripts\python.exe -m PyInstaller --noconfirm --onedir --windowed --name Anonymiseur ^
    --icon "icon.ico" ^
    --add-data "ocr_corpus.txt;." ^
    app.py

if errorlevel 1 (
    echo.
    echo ERREUR pendant la construction PyInstaller. Voir le detail ci-dessus.
    pause
    exit /b 1
)

echo.
echo ============================================
echo  Copie des binaires Tesseract/Poppler...
echo ============================================

set "OUT=dist\Anonymiseur"

mkdir "%OUT%\vendor\tesseract\tessdata" 2>nul
mkdir "%OUT%\vendor\poppler\bin" 2>nul

REM robocopy : copie robuste, /E inclut les sous-dossiers (tessdata)
robocopy "%TESS_DIR%" "%OUT%\vendor\tesseract" *.exe *.dll /NFL /NDL /NJH /NJS
robocopy "%TESS_DIR%\tessdata" "%OUT%\vendor\tesseract\tessdata" /E /NFL /NDL /NJH /NJS
robocopy "%POPPLER_DIR%" "%OUT%\vendor\poppler\bin" *.exe *.dll /NFL /NDL /NJH /NJS

REM Copie tous les modeles personnalises trouves a cote de ce script (ex:
REM mlg_archives.traineddata, mlg_archives_v2.traineddata) plutot qu'un seul
REM nom fixe -- app.py choisit ensuite automatiquement le meilleur au demarrage.
for %%F in (*.traineddata) do (
    copy /y "%%F" "%OUT%\vendor\tesseract\tessdata\" >nul
    echo Modele personnalise %%F inclus.
)

echo.
echo ============================================
echo  Verification (pour ne pas livrer un dossier
echo  vendor incomplet sans le savoir)...
echo ============================================

set "OK=1"

if not exist "%OUT%\vendor\poppler\bin\pdftoppm.exe" (
    echo ERREUR : pdftoppm.exe absent de vendor\poppler\bin\
    set "OK=0"
)
if not exist "%OUT%\vendor\poppler\bin\pdfinfo.exe" (
    echo ERREUR : pdfinfo.exe absent de vendor\poppler\bin\
    set "OK=0"
)
if not exist "%OUT%\vendor\tesseract\tesseract.exe" (
    echo ERREUR : tesseract.exe absent de vendor\tesseract\
    set "OK=0"
)
if not exist "%OUT%\vendor\tesseract\tessdata\fra.traineddata" (
    echo ERREUR : fra.traineddata absent de vendor\tesseract\tessdata\
    set "OK=0"
)

for /f %%c in ('dir /b "%OUT%\vendor\poppler\bin\*.dll" 2^>nul ^| find /c /v ""') do set "POPPLER_DLL_COUNT=%%c"
for /f %%c in ('dir /b "%OUT%\vendor\tesseract\*.dll" 2^>nul ^| find /c /v ""') do set "TESS_DLL_COUNT=%%c"
echo DLL copiees pour Poppler   : %POPPLER_DLL_COUNT%
echo DLL copiees pour Tesseract : %TESS_DLL_COUNT%
if %POPPLER_DLL_COUNT% LSS 1 (
    echo ATTENTION : aucune DLL copiee pour Poppler. Sur certaines
    echo installations les DLL necessaires sont dans un autre dossier
    echo que pdftoppm.exe -- copiez-les manuellement dans
    echo %OUT%\vendor\poppler\bin\ si l'OCR echoue une fois installe.
)

if "%OK%"=="0" (
    echo.
    echo ============================================
    echo  ECHEC : des fichiers essentiels manquent dans
    echo  vendor\. Ne continuez PAS vers Inno Setup tant
    echo  que ceci n'est pas corrige -- l'OCR ne
    echo  fonctionnera pas dans l'application installee.
    echo ============================================
    pause
    exit /b 1
)

echo.
echo Verification OK : tous les fichiers essentiels sont presents.
echo.
echo ============================================
echo  TERMINE
echo ============================================
echo.
echo Executable autonome pret dans : dist\Anonymiseur\
echo Ce dossier contient tout ^(Python, Tesseract, Poppler^) --
echo il peut etre copie sur une autre machine SANS RIEN installer.
echo.
echo Prochaine etape optionnelle : utiliser Inno Setup avec
echo installer.iss pour creer un vrai programme d'installation
echo ^(voir README.md^).
echo.
pause
