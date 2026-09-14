#!/bin/bash
# Crée un fichier .dmg à partir de dist/Anonymiseur.app — l'équivalent
# macOS de l'installeur Windows (installer.iss + Inno Setup).
#
# L'utilisateur final ouvre le .dmg, glisse Anonymiseur dans le dossier
# Applications (interaction standard sur Mac, comme pour n'importe quel
# logiciel téléchargé), puis le lance depuis Launchpad ou le Finder.
#
# N'utilise que des outils déjà inclus dans macOS (hdiutil) — rien à
# installer en plus pour cette étape.
#
# Usage :
#   chmod +x build_dmg.sh
#   ./build_dmg.sh

set -e

APP="dist/Anonymiseur.app"
DMG_NAME="Anonymiseur_Installateur.dmg"
VOLUME_NAME="Installer Anonymiseur"

if [ ! -d "$APP" ]; then
    echo "ERREUR : $APP introuvable. Lancez d'abord ./build_macos.sh"
    exit 1
fi

echo "============================================"
echo " Création du .dmg..."
echo "============================================"

rm -rf dist/dmg_staging
mkdir -p dist/dmg_staging

cp -R "$APP" dist/dmg_staging/
# Raccourci vers le dossier Applications : glisser l'app dessus l'installe.
ln -s /Applications dist/dmg_staging/Applications

rm -f "dist/$DMG_NAME"
hdiutil create -volname "$VOLUME_NAME" \
    -srcfolder dist/dmg_staging \
    -ov -format UDZO \
    "dist/$DMG_NAME"

rm -rf dist/dmg_staging

echo
echo "============================================"
echo " TERMINÉ"
echo "============================================"
echo
echo "Fichier prêt à distribuer : dist/$DMG_NAME"
echo
echo "⚠️ Note Gatekeeper : l'application n'étant pas signée avec un"
echo "compte développeur Apple (payant, 99\$/an), macOS affichera un"
echo "avertissement de sécurité au premier lancement chez vos"
echo "utilisateurs. Voir README.md, section \"Avertissement Gatekeeper\","
echo "pour la marche à suivre à leur transmettre."
echo
