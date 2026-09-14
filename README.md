# Anonymiseur de décisions de justice

Application de bureau, 100 % hors-ligne, pour anonymiser des documents
juridiques (.docx / .txt / .pdf) avant relecture ou publication.

## Structure du projet

```
anonymiseur/
├── app.py             # Interface Tkinter (point d'entrée)
├── anonymizer.py       # Moteur de détection + remplacement (règles regex + liste de noms)
├── docx_io.py          # Import/export .docx et .txt
├── pdf_io.py            # Import .pdf (texte natif ou OCR pour les scans)
├── ocr_correction.py    # Correction post-OCR par corpus (difflib, sans nouvelle dépendance)
├── ocr_corpus.txt       # Corpus de vocabulaire pour la correction post-OCR (à enrichir)
├── requirements.txt
├── requirements-dev.txt # + PyInstaller, pour fabriquer l'exécutable (voir plus bas)
└── README.md
```

## Fonctionnement

1. **Importer** un fichier `.docx`, `.txt` ou `.pdf`.
2. **Détecter les entités** : le moteur repère automatiquement, par règles
   regex, les formules courantes d'un arrêt francophone/malgache :
   - noms précédés de « M. / Mme / Mlle »
   - noms malgaches complets, patronyme en MAJUSCULES + prénom
     (« ANDRIATSARAFARA Soanavalomanjaka »)
   - sociétés (« la société X »)
   - cabinets d'avocats
   - adresses au format « au 49 rue ... », au format malgache
     « Lot B II 10 Ambatobe ANTANANARIVO » / « sise au lot ... »
   - propriétés désignées entre guillemets (« la propriété dite « VILLA X » »)
   - numéros de décision/procédure (« n°715 »)
   - numéros matricules de fonctionnaires (« IM n°12345 »)
   - numéros de téléphone malgaches (10 chiffres, ex : « 034 12 345 67 »)
   - montants en Ariary
   - dates en toutes lettres, en français et en malgache
     (« 13 janvier 2014 » / « tamin'ny 06 febroary 2025 »)
3. Chaque entité détectée est **surlignée** dans l'aperçu et listée dans le
   panneau latéral, avec une case à cocher pour l'inclure ou non dans
   l'anonymisation (utile pour retirer un faux positif).
4. **« + Ajouter un nom à repérer »** permet de compléter avec des noms
   propres qui ne suivent aucune des formules ci-dessus. Le champ « Type
   d'entité » propose les catégories existantes mais reste éditable :
   on peut y saisir un nouveau type (ex : `NUMERO_CIN`), qui reçoit
   automatiquement une couleur de surlignage et se comporte ensuite comme
   n'importe quel autre type (préfixe de pseudonyme = le nom du type).
5. **Anonymiser** remplace chaque entité retenue par un pseudonyme
   cohérent : la même chaîne de caractères reçoit toujours le même
   pseudonyme dans tout le document (`[SOCIETE_1]`, `[PERSONNE_2]`, etc.).
6. **Exporter** sauvegarde en `.docx` (en réutilisant la structure de
   paragraphes du document d'origine quand c'est possible) ou en `.txt`.
7. **Enregistrer dans la bibliothèque** : conserve le document (original,
   texte extrait, texte anonymisé, table de correspondance) dans un
   dossier dédié, pour le retrouver plus tard via **Bibliothèque…**. Voir
   `document_store.py` et l'avertissement ci-dessous.

### Bibliothèque de documents traités

Chaque document enregistré obtient son propre sous-dossier dans le
dossier bibliothèque (choisi une fois, mémorisé ensuite dans
`~/.anonymiseur/config.json`) :

```
<bibliothèque>/<nom du document>/
    original.pdf              — copie du fichier importé
    texte_extrait.txt          — texte brut (avant anonymisation)
    texte_anonymise.txt        — résultat final
    correspondance.json        — pseudonyme <-> texte original
    info.json                  — date, modèle OCR utilisé, etc.
```

**⚠️ Donnée sensible stockée en clair.** `texte_extrait.txt` et surtout
`correspondance.json` contiennent — ou permettent de reconstituer — les
informations que l'anonymisation est censée protéger. Ce n'est pas une
négligence technique à corriger : c'est un choix qui vous revient
(emplacement du dossier bibliothèque, qui y a accès, faut-il un disque
chiffré...). L'application vous prévient à la première configuration du
dossier, mais ne chiffre rien elle-même.

### Import PDF (texte natif ou scanné)

Un `.pdf` peut être importé comme un `.docx`/`.txt`. Deux cas, gérés
automatiquement :
- **PDF texte** (généré depuis Word, par exemple) : le texte est extrait
  directement, aucun délai notable.
- **PDF scanné** (photo/scan d'un document papier, pas de texte
  sélectionnable) : bascule automatique sur l'OCR (reconnaissance de
  caractères), page par page. Compter quelques secondes par page. Le
  texte reconnu est affiché avec un avertissement dans la barre de statut
  — **relisez-le attentivement avant d'anonymiser**, l'OCR peut mal lire
  certains caractères (accents, chiffres proches visuellement...).

**Limite importante — pas de modèle OCR malgache.** Tesseract (le moteur
d'OCR utilisé) ne propose pas de modèle entraîné pour le malgache. L'OCR
est donc fait avec le modèle **français** (`fra`), ce qui reste
globalement correct pour vos documents (rédigés en français, y compris
les patronymes malgaches qui s'OCRisent la plupart du temps correctement
même avec un modèle français) mais peut introduire plus d'erreurs sur
des tournures purement malgaches (formules "tamin'ny...", etc.).

### Réduire les fautes d'OCR

Trois leviers, complémentaires :

1. **Prétraitement d'image** (`pdf_io.py`, `_preprocess_for_ocr`) :
   niveaux de gris + contraste renforcé avant de lancer Tesseract, plus
   des réglages adaptés au type de document (`--oem 1 --psm 6` : moteur
   neuronal seul, bloc de texte uniforme). Automatique, rien à configurer.
2. **Modèle Tesseract "best"** au lieu du modèle "fast" installé par
   défaut : plus précis, un peu plus lent. Téléchargez
   [`fra.traineddata` (best)](https://github.com/tesseract-ocr/tessdata_best/blob/main/fra.traineddata)
   et remplacez le fichier du même nom dans le dossier `tessdata` de
   Tesseract (voir emplacement plus bas).
3. **Correction par corpus** (`ocr_correction.py` + `ocr_corpus.txt`) :
   après l'OCR, chaque mot du texte est comparé à un petit dictionnaire
   de vocabulaire courant (français juridique + mots-outils et mois
   malgaches). Un mot très proche d'une entrée du corpus (accent
   manqué, confusion visuelle "rn"/"m", "0"/"o"...) est corrigé
   automatiquement ; un mot trop différent est laissé tel quel plutôt
   que risquer une correction hasardeuse. **Les noms propres ne sont
   jamais touchés** : le corpus ne doit contenir que du vocabulaire
   courant, jamais de patronymes — sinon un nom rare mais correct
   pourrait être "corrigé" à tort vers un mot proche du dictionnaire.

   Aucune nouvelle dépendance : la correction utilise `difflib`, déjà
   inclus dans Python.

   **`ocr_corpus.txt` est fait pour être enrichi** au fil des documents
   traités : un mot par ligne, lignes commençant par `#` ignorées. À
   chaque nouveau document, notez les mots de vocabulaire (jamais les
   noms propres) que l'OCR peine à reconnaître et ajoutez-les. Plus le
   corpus grandit, plus la correction devient fiable sur votre corpus
   réel de documents.

### Cas particulier : noms malgaches mentionnés une seule fois en majuscules

Un mot isolé tout en MAJUSCULES est **volontairement non détecté
automatiquement** (trop ambigu : sigles, titres de section, citations de
jurisprudence en capitales sont fréquents en droit francophone). Le moteur
détecte de façon fiable la forme complète « SURNOM Prénom », puis ajoute
automatiquement le seul SURNOM à la liste de repérage pour retrouver ses
mentions isolées plus loin dans le même document (`Anonymizer.detect()`,
fonction `_extract_leading_surname`).

**Conséquence pratique** : si une personne n'est *jamais* mentionnée avec
son prénom dans le document (uniquement par son patronyme en majuscules),
elle ne sera pas détectée automatiquement — il faut l'ajouter manuellement
via « + Ajouter un nom à repérer ».

La liste `EXCLUDE_ALLCAPS` (dans `anonymizer.py`) exclut les toponymes et
sigles institutionnels connus (villes malgaches courantes, « CONSEIL »,
« ÉTAT », « BARREAU », sigles de formes juridiques « SARL »...) pour
réduire encore les faux positifs. À compléter selon votre corpus si de
nouveaux faux positifs apparaissent.

## Limites connues (à corriger avant mise en production)

- **Approche par règles** : très fiable sur les formulations attendues,
  mais peut générer des faux positifs sur des tournures inhabituelles.
  **La relecture manuelle via les cases à cocher avant export est
  indispensable** — ne jamais publier sans vérification humaine.
- **OCR** : la reconnaissance de caractères n'est jamais fiable à 100 %,
  particulièrement sur un scan de mauvaise qualité. Toujours relire le
  texte importé depuis un PDF scanné avant d'anonymiser.
- **Mise en forme .docx** : lors de l'export, chaque paragraphe est
  réécrit en un seul run de texte. Le style du paragraphe est conservé,
  mais une mise en forme très fine au sein d'un paragraphe (un mot en gras
  au milieu d'une phrase) peut être simplifiée.
- **Export depuis un PDF** : contrairement à un .docx d'origine, il n'y a
  pas de structure de paragraphes à réutiliser — l'export se fait par
  défaut en `.txt`, ou en `.docx` nouvellement créé (mise en forme simple).
- **Noms malgaches non conventionnels** : les règles actuelles reposent
  sur des formules françaises/malgaches standards. Pour des noms propres
  qui n'apparaissent jamais après une formule reconnue, il faut les
  ajouter manuellement via le gazetteer, ou étoffer les regex avec
  d'autres formules propres à votre corpus de documents.
- **Correspondance interne** : `Anonymizer.mapping_table()` renvoie la
  table (texte original → pseudonyme). Elle n'est pas exposée dans
  l'interface pour l'instant — à ajouter (ex: export séparé, réservé à un
  usage interne) si vous devez pouvoir « lever » l'anonymisation plus tard.

## Installation pour développement

```bash
python3 -m venv venv
source venv/bin/activate        # Windows : venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

`requirements.txt` contient uniquement ce qui est nécessaire pour **faire
tourner** l'application. PyInstaller (utile seulement pour **fabriquer**
l'exécutable, voir plus bas) est dans un fichier séparé,
`requirements-dev.txt`, justement pour éviter les conflits de dépendances
entre PyInstaller et les bibliothèques d'OCR lors d'un simple `pip
install -r requirements.txt`.

**Dépendances système en plus de `pip install` (obligatoires pour le PDF/OCR) :**

| Fonction | Dépendance système | Windows | macOS | Linux (Debian/Ubuntu) |
|---|---|---|---|---|
| Conversion PDF → image | **Poppler** | [binaires Poppler pour Windows](https://github.com/oschwartz10612/poppler-windows/releases/) (ajouter le dossier `bin` au PATH) | `brew install poppler` | `apt install poppler-utils` |
| OCR | **Tesseract** + pack français | [installeur Windows Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) (cocher "French" à l'installation) | `brew install tesseract tesseract-lang` | `apt install tesseract-ocr tesseract-ocr-fra` |

Sans ces deux logiciels, l'import de PDF **texte** fonctionne quand même
(pdfplumber n'en a pas besoin) ; seul l'OCR des PDF **scannés** échouera,
avec un message clair invitant à consulter cette section.

## Empaqueter en exécutable autonome (pour utilisateurs non-techniciens)

**Cette section décrit une procédure concrète, déjà implémentée et testée**
(voir `build_windows.bat` et `installer.iss`) — la stratégie « clé en
main » : Poppler et Tesseract sont embarqués directement à côté de
l'exécutable, l'utilisateur final n'installe strictement rien.

### Comment ça marche

`pdf_io.py` détecte automatiquement, au démarrage, un dossier `vendor/`
à côté de l'exécutable :
```
Anonymiseur/               (dossier produit par PyInstaller)
├── Anonymiseur.exe
├── vendor/
│   ├── tesseract/
│   │   ├── tesseract.exe
│   │   ├── *.dll
│   │   └── tessdata/
│   │       ├── fra.traineddata
│   │       └── mlg_archives.traineddata   (si vous l'avez entraîné)
│   └── poppler/
│       └── bin/
│           ├── pdftoppm.exe
│           └── *.dll
```
S'il existe, l'application utilise **exclusivement** ces binaires — testé
en pratique en rendant `tesseract`/`pdftoppm` du système introuvables et
en confirmant que l'OCR fonctionne quand même. S'il n'existe pas
(développement, ou si vous préférez la stratégie « installation séparée »
plus simple décrite plus bas), l'application se rabat sur le PATH système,
exactement comme avant — aucune régression.

### Construire l'exécutable (Windows)

**Préalable** : ce script réutilise le Tesseract et le Poppler que vous
avez déjà installés séparément (voir section OCR plus haut) — il les
recopie pour les embarquer, il ne les télécharge pas à nouveau. Assurez-
vous donc que `pdftoppm -v` et `tesseract --version` fonctionnent déjà
dans votre invite de commande avant de lancer ce script.

```bat
venv\Scripts\python.exe -m pip install -r requirements-dev.txt
build_windows.bat
```

Ce script (à la racine du projet) :
1. Repère votre installation Tesseract/Poppler existante (via le PATH).
2. Construit l'exécutable avec PyInstaller (`--onedir`, sans console).
3. Copie automatiquement les binaires Tesseract/Poppler dans
   `dist\Anonymiseur\vendor\`.
4. Inclut aussi `mlg_archives.traineddata` s'il est présent à côté du
   script, sans rien à configurer de plus.

Résultat : `dist\Anonymiseur\` est un dossier **complet et autonome** —
copiable tel quel sur n'importe quelle machine Windows, sans rien
installer (ni Python, ni Tesseract, ni Poppler).

### Créer un vrai installeur (recommandé pour la distribution)

Un dossier à copier-coller reste peu naturel pour un non-technicien.
[Inno Setup](https://jrsoftware.org/isinfo.php) (gratuit) transforme ça
en un installeur classique :

1. Lancer `build_windows.bat` d'abord (doit produire `dist\Anonymiseur\`).
2. Installer Inno Setup.
3. Ouvrir `installer.iss` (déjà fourni, à la racine du projet) avec
   Inno Setup Compiler, cliquer "Compile".
4. `Output\Anonymiseur_Setup.exe` est généré : c'est le fichier à
   distribuer. L'utilisateur le double-clique, suit un assistant
   d'installation classique (en français), et se retrouve avec un
   raccourci sur le Bureau — sans jamais voir de terminal ni installer
   quoi que ce soit d'autre.

### Alternative plus simple (sans embarquer les binaires)

Si embarquer Tesseract/Poppler est disproportionné pour votre situation
(peu d'utilisateurs, tous à l'aise pour suivre une notice d'installation),
vous pouvez aussi construire un exécutable plus léger et laisser chaque
utilisateur installer Tesseract/Poppler séparément (notice à leur
fournir — voir section OCR plus haut) :

```bat
venv\Scripts\python.exe -m PyInstaller --onedir --windowed --name Anonymiseur app.py
```

Sans le dossier `vendor/`, l'application se rabat automatiquement sur
une installation système de Tesseract/Poppler (voir "Comment ça marche"
ci-dessus).

### Points d'attention

- **Taille** : `dist\Anonymiseur\` avec binaires embarqués pèse environ
  150-200 Mo (Tesseract + pack de langue + Poppler). Sans eux, plutôt
  30-50 Mo. À garder en tête pour la distribution (clé USB, email...).
- **Testez sur une machine "propre"** : idéalement une machine Windows
  sans Python/Tesseract/Poppler déjà installés, pour vérifier qu'aucune
  dépendance cachée n'a été oubliée.
- **Mettre à jour le modèle OCR personnalisé** : si vous ré-entraînez
  `mlg_archives.traineddata` plus tard, il suffit de relancer
  `build_windows.bat` (le nouveau fichier sera repris automatiquement
  s'il est à côté du script), puis de recompiler l'installeur.
- Le cœur de l'application (import .docx/.txt, détection, anonymisation,
  export) ne dépend d'aucune connexion internet ni d'aucun logiciel
  externe, embarqué ou non.

## Empaqueter en application macOS (.app + .dmg)

**⚠️ Non testé sur une vraie machine macOS** (contrairement au reste du
projet — l'assistant qui a écrit ces scripts travaille sur Linux et ne
peut pas exécuter de build macOS lui-même). Le principe est identique à
Windows, mais l'empaquetage des bibliothèques dynamiques (`.dylib`) est
notoirement plus délicat sur macOS — attendez-vous probablement à un ou
deux allers-retours de correction si `build_macos.sh` échoue du premier
coup, comme ça a été le cas pour `build_windows.bat`.

### Prérequis (une seule fois, via [Homebrew](https://brew.sh))

```bash
brew install poppler tesseract tesseract-lang dylibbundler
```

`dylibbundler` est l'outil qui copie et corrige automatiquement les
bibliothèques dynamiques dont dépendent Tesseract/Poppler, pour qu'elles
soient embarquées dans l'application plutôt que de dépendre de Homebrew
installé sur la machine de l'utilisateur final.

### Construire l'application

```bash
pip install -r requirements-dev.txt   # dans le venv, comme pour Windows
chmod +x build_macos.sh build_dmg.sh
./build_macos.sh
```

Ce script repère votre Tesseract/Poppler installés via Homebrew, construit
l'application avec PyInstaller (qui produit automatiquement un vrai bundle
`.app` sur macOS), puis copie et corrige les bibliothèques nécessaires
avec `dylibbundler`. Résultat : `dist/Anonymiseur.app`, autonome.

**Testez-le avant d'aller plus loin** : double-cliquez dessus, importez un
PDF scanné, vérifiez que l'OCR fonctionne. Si Tesseract/Poppler échouent,
le message d'erreur de l'application indique désormais où elle a cherché
les binaires embarqués (utile pour diagnostiquer avec moi si besoin).

### Créer le .dmg à distribuer

```bash
./build_dmg.sh
```

Produit `dist/Anonymiseur_Installateur.dmg` — l'utilisateur l'ouvre,
glisse l'application dans son dossier Applications (interaction standard
sur Mac), puis la lance depuis le Launchpad.

### ⚠️ Avertissement Gatekeeper (à prévoir)

L'application n'étant pas signée avec un compte développeur Apple
(payant, 99 $/an — disproportionné pour un usage interne), macOS
affichera un avertissement de sécurité au premier lancement chez vos
utilisateurs : *"Anonymiseur ne peut pas être ouvert car il provient d'un
développeur non identifié"*. Ce n'est pas un bug, c'est le comportement
normal de macOS pour toute application non signée. Marche à suivre à
transmettre à vos utilisateurs (à faire une seule fois, au premier
lancement) :

1. **Clic droit** (ou Ctrl+clic) sur l'application dans Applications,
   choisir **"Ouvrir"** — PAS un double-clic normal.
2. Une boîte de dialogue apparaît, toujours avec l'avertissement, mais
   cette fois avec un bouton **"Ouvrir quand même"**. Cliquer dessus.
3. Aux lancements suivants, l'application s'ouvre normalement au
   double-clic — cette étape n'est nécessaire qu'une seule fois.

Alternative si ça ne suffit pas (versions récentes de macOS) : Réglages
Système → Confidentialité et sécurité → faire défiler jusqu'au message
concernant Anonymiseur → "Ouvrir quand même".

### Construire sans machine Mac (GitHub Actions, gratuit)

Aucun Mac sous la main, ou utilisateurs non-techniciens qui ne doivent
toucher à aucun terminal ? Un fichier de configuration est fourni
(`.github/workflows/build-macos.yml`) pour construire l'application
automatiquement sur une vraie machine Mac fournie gratuitement par
GitHub — tout se passe dans le navigateur :

1. Mettre ce dossier `anonymiseur` (avec `.github/` inclus — dossier
   caché, bien vérifier qu'il est bien envoyé) dans un dépôt GitHub.
   Public ou privé, peu importe ; un compte GitHub gratuit suffit.
2. Onglet **Actions** du dépôt → **Build macOS app** (menu de gauche) →
   bouton **Run workflow** → **Run workflow** à nouveau pour confirmer.
3. Attendre : la page se met à jour toute seule, généralement 10 à
   15 minutes pour un run complet.
4. Une fois le run marqué d'un ✓ vert, cliquer dessus, puis tout en bas
   de la page : **Artifacts** → télécharger **Anonymiseur-macOS**. C'est
   un zip contenant le dossier `dist/` complet, avec `Anonymiseur.app`
   et `Anonymiseur_Installateur.dmg` dedans — exactement le résultat
   d'un `./build_macos.sh && ./build_dmg.sh` lancé sur un vrai Mac.

Limite gratuite : les dépôts publics ont un usage gratuit illimité des
machines Mac de GitHub Actions ; les dépôts privés ont un quota mensuel
gratuit (les minutes macOS comptent 10 fois plus que les minutes Linux
dans ce quota — un run de 15 minutes en consomme donc l'équivalent de
150). Largement suffisant pour reconstruire l'app de temps en temps ;
insuffisant pour un usage massif/quotidien sur un dépôt privé.

### Alternative plus simple (sans embarquer les binaires)

Si `dylibbundler` pose problème, ou si vos utilisateurs Mac sont à l'aise
pour taper une commande Homebrew une fois, la version non-embarquée est
bien plus simple à construire :

```bash
venv/bin/python -m PyInstaller --windowed --name Anonymiseur app.py
```

Chaque utilisateur installe alors Tesseract/Poppler séparément :
```bash
brew install poppler tesseract tesseract-lang
```
Sans dossier `vendor/`, l'application se rabat automatiquement sur ces
binaires installés via Homebrew (même mécanisme que pour Windows, voir
"Comment ça marche" plus haut).


