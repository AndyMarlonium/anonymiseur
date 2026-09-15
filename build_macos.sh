#!/bin/bash
# Anonymiseur - Construction de l'application macOS (.app)
# avec Poppler et Tesseract embarqués (utilisateur final : rien à installer).
#
# ⚠️ Script non testé sur une vraie machine macOS (l'assistant qui l'a
# écrit travaille sur Linux et ne peut pas exécuter de build macOS).
# L'empaquetage des bibliothèques dynamiques (.dylib) sur macOS est
# notoirement plus délicat que les .dll Windows — attendez-vous
# probablement à un ou deux allers-retours de correction si ça ne
# fonctionne pas du premier coup. Voir README.md pour la marche à suivre
# en cas d'erreur.
#
# Prérequis (à installer une seule fois, via Homebrew) :
#   brew install poppler tesseract tesseract-lang dylibbundler
#
# Usage :
#   chmod +x build_macos.sh
#   ./build_macos.sh

set -e

echo "============================================"
echo " Anonymiseur - Construction de l'app macOS"
echo "============================================"
echo

# ----------------------------------------------------------------
# 1. Vérifier les prérequis
# ----------------------------------------------------------------

if ! command -v tesseract &> /dev/null; then
    echo "ERREUR : tesseract introuvable."
    echo "Installez-le avec : brew install tesseract tesseract-lang"
    exit 1
fi

if ! command -v pdftoppm &> /dev/null; then
    echo "ERREUR : pdftoppm introuvable."
    echo "Installez-le avec : brew install poppler"
    exit 1
fi

if ! command -v dylibbundler &> /dev/null; then
    echo "ERREUR : dylibbundler introuvable (nécessaire pour embarquer"
    echo "les bibliothèques dynamiques de Tesseract/Poppler)."
    echo "Installez-le avec : brew install dylibbundler"
    exit 1
fi

TESS_BIN=$(which tesseract)
PDFTOPPM_BIN=$(which pdftoppm)
PDFINFO_BIN=$(which pdfinfo)

echo "Tesseract trouvé : $TESS_BIN"
echo "pdftoppm trouvé  : $PDFTOPPM_BIN"
echo "pdfinfo trouvé   : $PDFINFO_BIN"
echo

# ----------------------------------------------------------------
# 2. Construire l'application avec PyInstaller (--windowed produit
#    automatiquement un vrai bundle .app sur macOS)
# ----------------------------------------------------------------

echo "============================================"
echo " Construction avec PyInstaller..."
echo "============================================"

rm -rf dist build

venv/bin/python -m PyInstaller --noconfirm --windowed --name Anonymiseur \
    --add-data "ocr_corpus.txt:." \
    app.py

APP="dist/Anonymiseur.app"
MACOS_DIR="$APP/Contents/MacOS"
VENDOR="$MACOS_DIR/vendor"

if [ ! -d "$MACOS_DIR" ]; then
    echo "ERREUR : $MACOS_DIR introuvable — la construction PyInstaller a dû échouer."
    exit 1
fi

# ----------------------------------------------------------------
# 3. Copier les binaires et fixer leurs dépendances dylib
# ----------------------------------------------------------------

echo
echo "============================================"
echo " Copie et fixation des bibliothèques..."
echo "============================================"

mkdir -p "$VENDOR/tesseract/tessdata"
mkdir -p "$VENDOR/poppler/bin"
mkdir -p "$VENDOR/libs"

cp "$TESS_BIN" "$VENDOR/tesseract/tesseract"
cp "$PDFTOPPM_BIN" "$VENDOR/poppler/bin/pdftoppm"
cp "$PDFINFO_BIN" "$VENDOR/poppler/bin/pdfinfo"

# Copier le dossier tessdata (données de langue) via Homebrew
TESS_PREFIX=$(brew --prefix tesseract 2>/dev/null || echo "")
if [ -n "$TESS_PREFIX" ] && [ -d "$TESS_PREFIX/share/tessdata" ]; then
    cp -R "$TESS_PREFIX/share/tessdata/." "$VENDOR/tesseract/tessdata/"
    echo "tessdata copié depuis $TESS_PREFIX/share/tessdata"
else
    echo "ATTENTION : dossier tessdata Homebrew introuvable automatiquement."
    echo "Copiez-le manuellement dans $VENDOR/tesseract/tessdata/"
fi

# dylibbundler : copie les .dylib dont dépendent ces binaires et corrige
# leurs chemins pour qu'ils se trouvent les uns les autres à côté d'eux,
# sans dépendre de Homebrew installé sur la machine de l'utilisateur final.
#
# -s indique explicitement où chercher les bibliothèques : sur les Mac
# Apple Silicon (M1/M2/...), Homebrew installe dans /opt/homebrew au lieu
# de /usr/local (Intel), et dylibbundler ne fouille pas forcément cet
# emplacement par défaut selon les versions — d'où des dépendances comme
# libpoppler introuvables (message "can't get path for '@rpath/...'" et
# invite interactive à saisir un chemin, qui bloque indéfiniment un build
# automatisé sans terminal pour répondre). On couvre les deux emplacements
# possibles (Intel et Apple Silicon) plutôt que de deviner lequel est actif.
# < /dev/null : filet de sécurité — si malgré tout une bibliothèque reste
# introuvable, dylibbundler échoue immédiatement (EOF sur son invite) au
# lieu de rester bloqué à attendre une réponse qui ne viendra jamais.
BREW_PREFIX="$(brew --prefix)"
dylibbundler -od -b \
    -x "$VENDOR/tesseract/tesseract" \
    -x "$VENDOR/poppler/bin/pdftoppm" \
    -x "$VENDOR/poppler/bin/pdfinfo" \
    -d "$VENDOR/libs" \
    -p "@executable_path/../libs/" \
    -s "$BREW_PREFIX/lib" \
    -s "/opt/homebrew/lib" \
    -s "/usr/local/lib" \
    -s "$(brew --prefix poppler 2>/dev/null)/lib" \
    -s "$(brew --prefix tesseract 2>/dev/null)/lib" \
    -s "$(brew --prefix leptonica 2>/dev/null)/lib" \
    < /dev/null

# Modèle(s) OCR personnalisé(s), présents à côté de ce script. Copie tous
# les .traineddata trouvés à la racine du projet (ex: mlg_archives.traineddata,
# mlg_archives_v2.traineddata) plutôt qu'un seul nom fixe — app.py choisit
# ensuite automatiquement le meilleur modèle détecté au démarrage.
shopt -s nullglob
custom_models=(*.traineddata)
shopt -u nullglob
if [ ${#custom_models[@]} -gt 0 ]; then
    for model in "${custom_models[@]}"; do
        cp "$model" "$VENDOR/tesseract/tessdata/"
        echo "Modèle personnalisé $model inclus."
    done
else
    echo "Aucun modèle personnalisé (*.traineddata) trouvé à côté de ce script — seul fra sera disponible."
fi

# ----------------------------------------------------------------
# 4. Vérification (pour ne pas livrer une app incomplète sans le savoir)
# ----------------------------------------------------------------

echo
echo "============================================"
echo " Vérification..."
echo "============================================"

OK=1
[ -f "$VENDOR/poppler/bin/pdftoppm" ] || { echo "ERREUR : pdftoppm manquant"; OK=0; }
[ -f "$VENDOR/poppler/bin/pdfinfo" ] || { echo "ERREUR : pdfinfo manquant"; OK=0; }
[ -f "$VENDOR/tesseract/tesseract" ] || { echo "ERREUR : tesseract manquant"; OK=0; }
[ -f "$VENDOR/tesseract/tessdata/fra.traineddata" ] || { echo "ERREUR : fra.traineddata manquant"; OK=0; }

DYLIB_COUNT=$(find "$VENDOR/libs" -name "*.dylib" 2>/dev/null | wc -l | tr -d ' ')
echo "Bibliothèques .dylib embarquées : $DYLIB_COUNT"
if [ "$DYLIB_COUNT" -lt 1 ]; then
    echo "ATTENTION : aucune .dylib embarquée — dylibbundler a peut-être échoué silencieusement."
fi

if [ "$OK" = "0" ]; then
    echo
    echo "ÉCHEC : des fichiers essentiels manquent. Ne continuez pas vers"
    echo "la création du .dmg tant que ceci n'est pas corrigé."
    exit 1
fi

echo
echo "Vérification OK."
echo
echo "============================================"
echo " TERMINÉ"
echo "============================================"
echo
echo "Application prête : dist/Anonymiseur.app"
echo
echo "IMPORTANT — à tester avant de distribuer : lancez d'abord"
echo "dist/Anonymiseur.app en double-cliquant, importez un PDF scanné,"
echo "et vérifiez que l'OCR fonctionne. Si ça échoue, voir README.md"
echo "pour le diagnostic (le message d'erreur affiché par l'application"
echo "indique désormais où elle a cherché les binaires embarqués)."
echo
echo "Étape suivante optionnelle : ./build_dmg.sh pour créer un .dmg"
echo "à distribuer (glisser-déposer dans Applications)."
echo
