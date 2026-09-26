#!/bin/bash
# Anonymiseur — lancement local (Mac / Linux)
# Double-cliquez simplement sur ce fichier (sur Mac : clic droit -> Ouvrir,
# la premiere fois, a cause de la protection Gatekeeper habituelle).
#
# Pourquoi ce script est necessaire : les navigateurs (Safari, Chrome,
# Firefox...) bloquent par securite le chargement de fichiers voisins
# (comme les modeles OCR de tessdata/) quand une page est ouverte en
# double-cliquant directement sur index.html (protocole file://). C'est
# une restriction du navigateur lui-meme, pas de cette application. Ce
# script demarre un tout petit serveur local (accessible uniquement
# depuis CET ordinateur, invisible depuis l'exterieur/internet) puis
# ouvre automatiquement le navigateur dessus.

cd "$(dirname "$0")"

PORT=8000
URL="http://localhost:$PORT/"

open_browser() {
  if command -v open >/dev/null 2>&1; then
    open "$URL"          # macOS
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL"      # Linux
  fi
}

if command -v python3 >/dev/null 2>&1; then
  echo "Démarrage du serveur local sur le port $PORT..."
  ( sleep 1; open_browser ) &
  python3 -m http.server "$PORT"
  exit 0
fi

if command -v python >/dev/null 2>&1; then
  echo "Démarrage du serveur local sur le port $PORT..."
  ( sleep 1; open_browser ) &
  python -m http.server "$PORT"
  exit 0
fi

if command -v node >/dev/null 2>&1; then
  echo "Démarrage du serveur local sur le port $PORT (via Node.js)..."
  ( sleep 1; open_browser ) &
  npx --yes serve -l "$PORT" .
  exit 0
fi

echo
echo "============================================================"
echo " Python ou Node.js sont nécessaires pour lancer l'appli en local."
echo " Aucun des deux n'a été trouvé sur cet ordinateur."
echo
echo " Mac : Python est parfois déjà présent (tapez 'python3 --version'"
echo " dans le Terminal pour vérifier), sinon installez-le via"
echo " https://www.python.org/downloads/ ou 'brew install python3'."
echo "============================================================"
echo
read -p "Appuyez sur Entrée pour fermer..."
