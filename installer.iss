; Script Inno Setup — génère un installeur Windows classique
; (Anonymiseur_Setup.exe) à partir du dossier dist\Anonymiseur\
; produit par build_windows.bat.
;
; Utilisation :
;   1. Lancer d'abord build_windows.bat (doit avoir produit dist\Anonymiseur\)
;   2. Installer Inno Setup : https://jrsoftware.org/isinfo.php
;   3. Ouvrir ce fichier avec Inno Setup Compiler, cliquer "Compile"
;   4. Le programme d'installation apparaît dans le dossier Output\
;
; Aucune connaissance technique nécessaire pour l'utilisateur final :
; il double-clique Anonymiseur_Setup.exe comme n'importe quel logiciel.

#define MyAppName "Anonymiseur de décisions de justice"
#define MyAppVersion "1.0"
#define MyAppExeName "Anonymiseur.exe"

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\Anonymiseur
DefaultGroupName=Anonymiseur
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=Anonymiseur_Setup
Compression=lzma2
SolidCompression=yes
; Pas besoin des droits administrateur pour une installation par utilisateur :
PrivilegesRequired=lowest
WizardStyle=modern

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; GroupDescription: "Raccourcis :"

[Files]
; Copie tout le contenu du dossier construit par PyInstaller (l'exécutable,
; les bibliothèques Python, et vendor\ avec Tesseract/Poppler embarqués).
Source: "dist\Anonymiseur\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Anonymiseur"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Désinstaller Anonymiseur"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Anonymiseur"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Lancer Anonymiseur"; Flags: nowait postinstall skipifsilent
