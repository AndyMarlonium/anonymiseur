# -*- coding: utf-8 -*-
"""
Moteur d'anonymisation pour décisions de justice (Madagascar / francophone).

Approche volontairement "règles + liste" plutôt que NER statistique :
- plus prévisible et déterministe sur des documents très formatés
  (arrêts, dates, montants, formules consacrées) ;
- ne nécessite aucun modèle lourd à embarquer dans l'exécutable offline ;
- facile à faire évoluer par un juriste (pas besoin de ré-entraîner un modèle,
  on ajoute une règle ou un nom à une liste).

Le module expose :
    - ENTITY_PATTERNS : règles regex prêtes à l'emploi (dates, montants,
      numéros de décision, adresses, formules "M./Mme X")
    - Gazetteer : liste de noms propres à repérer (à charger/éditer par
      l'utilisateur : parties, avocats, sociétés récurrentes, etc.)
    - Anonymizer : orchestre la détection puis le remplacement cohérent
      (la même entité est toujours remplacée par le même pseudonyme
      dans tout le document).
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional

# Classes de caractères françaises correctes.
# ATTENTION : la classe [A-ZÀ-Ÿ] est un piège classique — l'intervalle
# Unicode "À-Ÿ" (U+00C0 à U+0178) déborde largement sur le bloc des
# minuscules accentuées (à, é, î, ô...) et les fait matcher par erreur
# dans ce qui est censé être une classe "majuscules uniquement".
# On énumère donc explicitement les majuscules et minuscules accentuées
# réellement utilisées en français.
UPPER = "A-ZÀÂÄÇÉÈÊËÎÏÔÖÙÛÜŸÆŒ"
LOWER = "a-zàâäçéèêëîïôöùûüÿæœ"
WORD = f"{UPPER}{LOWER}"

# Mots en MAJUSCULES à ne jamais confondre avec un nom propre malgache :
# toponymes courants, institutions, formules d'arrêt. Éditable/complétable
# selon le corpus (ex: ajouter d'autres villes ou régions au besoin).
EXCLUDE_ALLCAPS = {
    "ANTANANARIVO", "ANTSIRABE", "TOAMASINA", "MAHAJANGA", "TOLIARA",
    "FIANARANTSOA", "ANTSIRANANA", "ANOSY", "ANALAMANGA", "MADAGASCAR",
    "ARIARY", "GREFFE", "CONSEIL", "ETAT", "ÉTAT", "COUR", "SUPREME",
    "SUPRÊME", "BARREAU", "MALAGASY", "REPOBLIKA", "REPOBLIKAN",
    "CHAMBRE", "SERVICES", "PUBLICS", "PUBLIQUE", "AUDIENCE",
    # Sigles de formes juridiques, fréquents juste avant un mot en
    # Casse-Titre ("... SARL Membre,") et donc sources de faux positifs
    # avec le pattern de nom malgache complet.
    "SARL", "SAU", "SASU", "EURL",
    # Vocabulaire juridique/institutionnel à ne jamais anonymiser, même
    # tout en majuscules (souvent utilisé en tête de section ou en titre).
    "PRESIDENT", "PRÉSIDENT", "TRIBUNAL", "DROIT", "MINISTERE",
    "MINISTÈRE", "MINISTRE", "REPUBLIQUE", "RÉPUBLIQUE", "ARTICLE",
    "LOI", "DECRET", "DÉCRET", "ORDONNANCE", "CODE", "PENAL", "PÉNAL",
    "CIVIL", "COMMERCIAL", "ADMINISTRATIF", "FRANCAIS", "FRANÇAIS",
    "JUGEMENT", "ARRET", "ARRÊT", "DECISION", "DÉCISION", "REQUERANT",
    "REQUÉRANT", "REQUERANTE", "REQUÉRANTE", "DEFENDEUR", "DÉFENDEUR",
    "DEFENDERESSE", "DÉFENDERESSE", "PARTIE", "PARTIES", "AVOCAT",
    "FANJAKANA", "FITSARANA", "FILANKEVI", "FILANKEVIM",
}

# Équivalent Casse-Titre de la liste ci-dessus, plus les connecteurs de
# phrase français qui commencent très souvent une phrase avec une
# majuscule dans un arrêt ("Attendu que...", "Considérant que...") — pour
# la règle "deux mots à Majuscule qui se suivent au milieu d'une phrase"
# plus bas, volontairement plus prudente que les autres règles.
STOPWORDS_TITLECASE = {
    "Tribunal", "Président", "Présidente", "Droit", "Conseil", "État",
    "Chambre", "Cour", "Suprême", "Barreau", "Ministère", "Ministre",
    "République", "Cabinet", "Société", "Monsieur", "Madame",
    "Mademoiselle", "Maître", "Article", "Loi", "Décret", "Ordonnance",
    "Code", "Pénal", "Civil", "Commercial", "Administratif", "Français",
    "Française", "Malgache", "Greffe", "Audience", "Jugement", "Arrêt",
    "Décision", "Requête", "Requérant", "Requérante", "Défendeur",
    "Défenderesse", "Partie", "Parties", "Avocat", "Avocate",
    "Fanjakana", "Fitsarana", "Filankevi", "Filankevim", "Filankevy",
    "Repoblika", "Repoblikan",
    "Le", "La", "Les", "Un", "Une", "Des", "Ce", "Cette", "Ces", "Il",
    "Elle", "Ils", "Elles", "Mais", "Or", "Donc", "Ainsi", "Cependant",
    "Toutefois", "Néanmoins", "Par", "Pour", "Sur", "Dans", "Avec",
    "Sans", "Vu", "Attendu", "Considérant", "Sous", "Après", "Avant",
    # Institutions, établissements, titres de poste — français et
    # malgache — fréquemment en Casse-Titre et à ne jamais anonymiser
    # (liste à compléter au fil des faux positifs rencontrés : c'est le
    # principal risque de cette règle-ci, plus large que les autres).
    "Centre", "Hospitalier", "Hospitalière", "Universitaire",
    "Référence", "Régional", "Régionale", "Réalisateur", "Réalisatrice",
    "Adjoint", "Adjointe", "Sages", "Femmes", "Infirmiers", "Infirmières",
    "Syndicat", "Salle", "Conférence", "Directeur", "Directrice",
    "Secrétaire", "Général", "Générale", "Inspecteur", "Inspectrice",
    "Contrôleur", "Contrôleuse", "Receveur", "Employé", "Employée",
    "Médecin", "Chef", "Principal", "Principale", "Faritra", "Analamanga",
    "Sekretera", "Jeneraly", "Mpampakateny", "Mpirakidraharaha",
    "Mpanolotsaina", "Mpitory", "Filoha", "Tonia", "Rantsana",
    "Antananarivo", "Mahajanga", "Antsiranana", "Toamasina", "Toliara",
    "Fianarantsoa", "Antsirabe", "Etat", "Etudiants", "Raharaha",
    "Fokontany", "Kaominina", "Distrikta", "Firaisana",
    # Connecteurs de phrase et mots grammaticaux malgaches très courants,
    # fréquemment en tête de phrase dans ce type de document ("Hita ny...",
    # "Satria...", "Ny Filoha...") — même rôle que les connecteurs
    # français ci-dessus. "Andriamatoa"/"Ramatoa" sont les équivalents
    # malgaches de Monsieur/Madame, à exclure pour la même raison.
    "Ny", "Sy", "Fa", "Dia", "Ka", "Na", "Satria", "Raha", "Rehefa",
    "Reheza", "Nefa", "Ary", "Toa", "Heno", "Hita", "Araka", "Noho",
    "Mikasika", "Ireo", "Manamarika", "Tsindrian", "Andriamatoa",
    "Ramatoa", "Atoa", "Rtoa", "Amin", "Tamin", "Momba", "Mahakasika",
    # Formules de tampon/enregistrement en fin de document, sans rapport
    # avec une personne ("Reçu Gratis", vocabulaire de procédure).
    "Reçu", "Gratis", "Appel", "Sociale", "Orinasa", "Ministry",
}

# Villes et grandes agglomérations malgaches, pour la règle VILLE
# ci-dessous. Volontairement une LISTE plutôt qu'une règle générique
# ("un mot à Majuscule tout seul") : les noms de ville se comportent
# exactement comme n'importe quel autre mot à Majuscule/Casse-Titre en
# français ou en malgache, impossible à distinguer par la forme seule
# d'un nom de personne ou d'un terme juridique — d'où une liste fermée,
# à compléter au besoin plutôt qu'une regex ouverte.
CITY_NAMES = [
    "Antananarivo", "Antsirabe", "Toamasina", "Mahajanga", "Toliara",
    "Fianarantsoa", "Antsiranana", "Nosy Be", "Antalaha", "Sambava",
    "Manakara", "Morondava", "Ambatondrazaka", "Ambositra", "Farafangana",
    "Maroantsetra", "Mananjary", "Moramanga", "Ihosy", "Vohémar",
    "Vohemar", "Ambovombe", "Betroka", "Manjakandriana", "Ambalavao",
    "Miandrivazo", "Tsiroanomandidy", "Maevatanana", "Ambanja",
    "Marovoay", "Bealanana", "Mandritsara", "Ambatolampy", "Antsohihy",
    "Fenoarivo", "Mahanoro", "Vangaindrano", "Beroroha", "Ikongo",
]


def _city_pattern() -> str:
    """Construit une alternance regex reconnaissant chaque ville de
    CITY_NAMES sous ses deux graphies rencontrées dans le corpus : tout
    en majuscules ('ANTANANARIVO', comme dans les en-têtes tapés à la
    machine) ou en Casse-Titre normale ('Antananarivo'). Triées par
    longueur décroissante pour qu'un nom composé ('Nosy Be') ne soit pas
    coupé par un sous-mot plus court testé en premier."""
    names = sorted(set(CITY_NAMES), key=len, reverse=True)
    alternatives: List[str] = []
    for name in names:
        alternatives.append(re.escape(name.upper()))
        alternatives.append(re.escape(name))
    return r"\b(?P<val>" + "|".join(alternatives) + r")\b"


# ---------------------------------------------------------------------------
# 1. Détection par entité
# ---------------------------------------------------------------------------

@dataclass
class Entity:
    start: int
    end: int
    label: str          # ex: "PERSONNE", "SOCIETE", "ADRESSE", "DATE", "MONTANT", "NUMERO"
    text: str
    source: str = "regex"   # "regex" ou "gazetteer"


# Regex génériques (formules courantes des arrêts francophones).
# Chaque pattern doit contenir un groupe nommé (?P<val>...) qui est
# la portion réellement anonymisée (utile quand on veut garder par ex.
# "M." mais masquer le nom qui suit).
ENTITY_PATTERNS: List[Tuple[str, str]] = [
    # M. / Mme / Mlle + Nom en capitales ou Nom Prénom
    ("PERSONNE", rf"\b(?:M\.|Mme|Mlle)\s+(?P<val>[{UPPER}][{UPPER}'\-]+(?:\s+[{UPPER}][{LOWER}'\-]+)*)"),

    # Sociétés introduites par "société", "la société", "Société".
    # Le nom est capturé comme une suite de mots à Majuscule, avec
    # connecteurs français autorisés entre deux mots à Majuscule
    # ("des", "du", "de", "la", "le", "les", "d'", "l'"). Dès qu'un mot
    # en minuscule qui n'est pas un connecteur apparaît (un verbe, un
    # adjectif...), la capture s'arrête — ça évite d'avaler la suite de
    # la phrase quand aucune ponctuation ne suit immédiatement le nom.
    # [ \t] (et non \s) empêche aussi de traverser un saut de ligne /
    # changement de paragraphe.
    ("SOCIETE", rf"\b(?:[Ll]a[ \t]+)?[Ss]ociété[ \t]+(?P<val>[{UPPER}][{WORD}'’\-]*"
                rf"(?:[ \t]+(?:(?:de|du|des|la|le|les|d['’]|l['’])[ \t]+)?"
                rf"[{UPPER}][{WORD}'’\-]*)*)"),

    # Cabinets d'avocats. Même logique que SOCIETE : le nom est une suite
    # de mots à Majuscule reliés par des connecteurs autorisés (dont "et",
    # pour "Rambeloson et Rambeloson"), ce qui est plus robuste qu'un
    # lookahead sur la ponctuation suivante (souvent absente ou trop loin).
    ("AVOCAT", rf"\b(?:Cabinet[ \t]+d['’]Avocats?(?:[ \t]+Associés)?"
               rf"(?:[ \t]+au[ \t]+Barreau[ \t]+de[ \t]+\w+)?[ \t]*,?[ \t]*)"
               rf"(?P<val>[{UPPER}][{WORD}'’\-]*"
               rf"(?:[ \t]+(?:(?:et|de|du|des|la|le|les|d['’]|l['’])[ \t]+)?"
               rf"[{UPPER}][{WORD}'’\-]*)*)"),

    # Avocats désignés par "Maître X", "Conseil de X", ou un "Cabinet X"
    # qui n'est pas de la forme "Cabinet d'Avocats..." déjà couverte
    # ci-dessus (le lookahead négatif évite un double repérage du même nom
    # par les deux règles).
    ("AVOCAT", rf"\bMaître[ \t]+(?P<val>[{UPPER}][{WORD}'’\-]*"
               rf"(?:[ \t]+[{UPPER}][{WORD}'’\-]*){{0,3}})"),
    ("AVOCAT", rf"\b[Cc]onseil[ \t]+de[ \t]+(?P<val>[{UPPER}][{WORD}'’\-]*"
               rf"(?:[ \t]+[{UPPER}][{WORD}'’\-]*){{0,4}})"),
    ("AVOCAT", rf"\b[Cc]abinet[ \t]+(?!d['’]Avocats)(?P<val>[{UPPER}][{WORD}'’\-]*"
               rf"(?:[ \t]+[{UPPER}][{WORD}'’\-]*){{0,4}})"),

    # Nom du/de la requérant(e), qui suit presque toujours la formule
    # "le requérant" / "la requérante" dans ce type de document (parfois
    # avec "M."/"Mme" intercalé). Capture 1 à 4 mots à Majuscule/Casse-Titre.
    ("PERSONNE", rf"\b(?:[Ll]e[ \t]+requérant|[Ll]a[ \t]+requérante)[ \t,]*"
                 rf"(?:M\.|Mme|Mlle)?[ \t]*"
                 rf"(?P<val>[{UPPER}][{WORD}'’\-]*(?:[ \t]+[{UPPER}][{WORD}'’\-]*){{0,3}})"),

    # Dates de naissance, françaises ("né le 12 janvier 1980" /
    # "né(e) le 12/01/1980") et malgaches ("teraka tamin'ny ...").
    ("DATE", rf"\bn[ée]e?[ \t]+le[ \t]+(?P<val>\d{{1,2}}[ \t]+(?:janvier|février|mars|avril|mai|juin|juillet|"
             rf"août|septembre|octobre|novembre|décembre)[ \t]+\d{{4}}|\d{{1,2}}[/.\-]\d{{1,2}}[/.\-]\d{{2,4}})\b"),
    ("DATE", rf"\bteraka[ \t]+tamin['’]ny[ \t]+(?P<val>\d{{1,2}}[ \t]+(?:janoary|febroary|martsa|aprily|mey|jona|jolay|"
             rf"aogositra|septambra|oktobra|novambra|desambra)[ \t]+\d{{4}})\b"),

    # Adresses : "au <numéro> rue <nom> <ville>"
    ("ADRESSE", rf"\b(?:au|à)[ \t]+(?P<val>\d{{1,4}}[ \t]+(?:rue|avenue|lot|boulevard|BP)[ \t]+[{WORD}\d'’\- ]{{2,60}}?)(?=[,;.\n])"),

    # Adresses introduites par une formule explicite : "demeurant à/au",
    # "à l'adresse (suivante)", "sise à/au" (souvent pour désigner le
    # siège d'une société), et en malgache "mipetraka ao" ("réside à" —
    # volontairement PAS "ao" seul : ce mot isolé est bien trop courant en
    # malgache, ("dans", "là") pour servir de déclencheur sans générer
    # énormément de faux positifs partout dans le document).
    ("ADRESSE", rf"\bdemeurant[ \t]+(?:à|au)[ \t]+(?P<val>[{WORD}\d][{WORD}\d'’,\- ]{{2,80}}?)(?=[,;.\n])"),
    ("ADRESSE", rf"\bà[ \t]+l['’]adresse(?:[ \t]+suivante)?[ \t]*:?[ \t]*(?P<val>[{WORD}\d][{WORD}\d'’,\- ]{{2,80}}?)(?=[,;.\n])"),
    ("ADRESSE", rf"\bsise?[ \t]+(?:à|au)[ \t]+(?P<val>[{WORD}\d][{WORD}\d'’,\- ]{{2,80}}?)(?=[,;.\n])"),
    ("ADRESSE", rf"\bmipetraka[ \t]+ao[ \t]+(?P<val>[{WORD}\d][{WORD}\d'’,\- ]{{2,80}}?)(?=[,;.\n])"),


    # Numéro matricule de fonctionnaire ("IM n°12345", "IM 12345").
    # Placé AVANT NUMERO dans la liste : à chevauchement de longueur égale,
    # detect_entities garde le premier ajouté à position égale — ce pattern
    # plus spécifique doit donc précéder la règle générique "n°...".
    ("MATRICULE", r"\bIM[ \t]*n?°?[ \t]*(?P<val>\d{3,10})\b"),

    # Numéros de téléphone malgaches : 10 chiffres commençant par 0,
    # avec séparateurs optionnels (espace, point, tiret) entre les groupes
    # habituels ("034 12 345 67", "033-12-345-67", "0341234567"...).
    ("TELEPHONE", r"\b(?P<val>0[23]\d(?:[ .\-]?\d){7})\b"),

    # Numéros de décision / procédure : "n°715", "n°03/12-ADM"
    ("NUMERO", r"\bn°\s?(?P<val>[\w/\-]+)"),

    # Montants en Ariary
    ("MONTANT", r"(?P<val>\d[\d\s]{2,}\d)\s*Ariary"),

    # Dates en toutes lettres, français ("13 janvier 2014", "dix-huit
    # septembre deux mille vingt-cinq")
    ("DATE", r"(?P<val>\b\d{1,2}\s+(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+\d{4}\b)"),

    # Dates en malgache, toujours introduites par "tamin'ny"
    # ("tamin'ny 06 febroary 2025"). Le préfixe "tamin'ny" reste visible
    # dans le texte anonymisé, seule la date elle-même est masquée —
    # même logique que pour les dates françaises ci-dessus.
    ("DATE", r"\btamin['’]ny[ \t]+(?P<val>\d{1,2}[ \t]+(?:janoary|febroary|martsa|aprily|mey|jona|jolay|"
             r"aogositra|septambra|oktobra|novambra|desambra)[ \t]+\d{4})\b"),

    # Noms propres malgaches : patronyme tout en MAJUSCULES (souvent long)
    # suivi d'un ou plusieurs prénoms en Casse-Titre
    # ("ANDRIATSARAFARA Soanavalomanjaka"). Le prénom est ICI OBLIGATOIRE :
    # un mot seul tout en majuscules est bien trop ambigu en droit
    # francophone (citations de jurisprudence, sigles, titres de section
    # sont aussi en capitales) pour être détecté fiablement seul.
    # Les mentions ultérieures du seul patronyme ("RANDRIANARIVONY" sans
    # prénom) sont retrouvées via l'auto-enrichissement du gazetteer dans
    # Anonymizer.detect() ci-dessous, pas par une regex générique.
    # Le nombre de mots de Casse-Titre à la suite est plafonné à 2 (et non
    # illimité) : un patronyme suivi de plus de deux mots en Casse-Titre
    # est presque toujours un nom en ALLCAPS suivi d'une adresse ou d'un
    # nom de lieu accolé (ex: "PHARMATEK Ambohitrakely Antananarivo"),
    # pas un prénom composé.
    ("PERSONNE", rf"\b(?!(?:{'|'.join(sorted(EXCLUDE_ALLCAPS, key=len, reverse=True))})\b)"
                 rf"(?P<val>[{UPPER}]{{4,}}(?:[ \t]+[{UPPER}]{{4,}})*"
                 rf"(?:[ \t]+[{UPPER}][{LOWER}]+){{1,2}})\b"),

    # Adresses au format malgache courant : "Lot B II 10 Ambatobe ANTANANARIVO"
    # ou "sise au lot ...". "lot" est repéré indépendamment de la casse
    # (Lot / lot), le déclencheur ("sise au", "sis au", rien du tout...)
    # n'a pas besoin d'être capturé explicitement.
    ("ADRESSE", rf"\b[Ll]ot\b[ \t]+(?P<val>[{WORD}\d]+(?:[ \t]+[{WORD}\d]+){{0,6}})(?=[ \t]*[,;.\n]|$)"),

    # Propriétés désignées par leur nom entre guillemets, formule
    # "la propriété dite « NOM »". Deux règles séparées (guillemets
    # français « » et droits " ") plutôt qu'une alternance dans un même
    # groupe nommé, pour rester compatible avec la façon dont
    # detect_entities lit le groupe "val".
    ("PROPRIETE", r"\bpropriété[ \t]+dite[ \t]+«[ \t]*(?P<val>[^»]+?)[ \t]*»"),
    ("PROPRIETE", r'\bpropriété[ \t]+dite[ \t]+"(?P<val>[^"]+?)"'),

    # Noms de ville (voir CITY_NAMES ci-dessus). Placée en dernier :
    # une ville mentionnée à l'intérieur d'une adresse plus longue déjà
    # repérée par une autre règle ("demeurant à Lot ... Antananarivo")
    # reste rattachée à cette adresse plutôt que d'être découpée à part
    # (la résolution des chevauchements dans detect_entities garde
    # toujours la correspondance la plus longue) ; seules les mentions
    # de ville isolées, hors de toute adresse détectée, sont anonymisées
    # par cette règle-ci.
    ("VILLE", _city_pattern()),
]


class Gazetteer:
    """Liste de noms propres / sociétés à repérer même hors des formules
    regex ci-dessus (ex: mentions répétées sans "M." ou "société" devant).
    Éditable par l'utilisateur final via l'interface (un nom par ligne)."""

    def __init__(self, names: Optional[List[str]] = None):
        self.entries: Dict[str, str] = {}  # texte -> label
        if names:
            for n in names:
                self.add(n)

    def add(self, name: str, label: str = "PERSONNE"):
        name = name.strip()
        if name:
            self.entries[name] = label

    def remove(self, name: str):
        self.entries.pop(name.strip(), None)

    def find(self, text: str) -> List[Entity]:
        found = []
        for name, label in self.entries.items():
            for m in re.finditer(re.escape(name), text):
                found.append(Entity(m.start(), m.end(), label, name, source="gazetteer"))
        return found


def _find_titlecase_name_sequences(text: str) -> List[Entity]:
    """Repère les suites de 2 à 4 mots à Casse-Titre qui se suivent, même
    au milieu d'une phrase sans mot déclencheur ('M.', 'société'...) —
    c'est un signal plus faible et plus ambigu que les règles ci-dessus
    (une majuscule en tête de phrase après un point, ou un terme
    juridique capitalisé, y ressemblent). On filtre donc énergiquement
    via STOPWORDS_TITLECASE : dès qu'un seul des mots de la séquence en
    fait partie, on rejette tout le candidat plutôt que de risquer un
    faux positif sur un terme juridique."""
    found: List[Entity] = []
    token = rf"[{UPPER}][{LOWER}]+(?:[\-’'][{UPPER}][{LOWER}]+)*"
    pattern = rf"\b{token}(?:[ \t]+{token}){{1,3}}\b"
    for m in re.finditer(pattern, text):
        words = m.group(0).split()
        if any(w in STOPWORDS_TITLECASE for w in words):
            continue
        found.append(Entity(m.start(), m.end(), "PERSONNE", m.group(0)))
    return found


def detect_entities(text: str, gazetteer: Optional[Gazetteer] = None) -> List[Entity]:
    """Détecte toutes les entités (regex + gazetteer), triées par position,
    en résolvant les chevauchements (on garde la plus longue correspondance)."""
    found: List[Entity] = []

    for label, pattern in ENTITY_PATTERNS:
        for m in re.finditer(pattern, text):
            found.append(Entity(m.start("val"), m.end("val"), label, m.group("val")))

    found.extend(_find_titlecase_name_sequences(text))

    if gazetteer:
        found.extend(gazetteer.find(text))

    # Filtre de sécurité général (pas propre à une seule règle) : si un
    # des mots captés fait partie du vocabulaire juridique/institutionnel
    # connu (STOPWORDS_TITLECASE), on rejette l'entité entière plutôt que
    # de l'anonymiser à moitié. Concerne surtout les correspondances
    # ALLCAPS + plusieurs mots à Casse-Titre, qui peuvent parfois avaler
    # une adresse ou un nom de lieu accolé à un nom de société/personne
    # (ex: "PHARMATEK Ambohitrakely Antananarivo" — la ville ne doit pas
    # se retrouver anonymisée comme si elle faisait partie d'un nom).
    # Uniquement pour PERSONNE/AVOCAT/SOCIETE : une ADRESSE, elle, contient
    # légitimement un nom de ville en fin de chaîne — ne pas la rejeter.
    def _touches_stopword(entity: Entity) -> bool:
        if entity.source == "gazetteer":
            return False  # choix explicite de l'utilisateur, jamais filtré
        if entity.label not in ("PERSONNE", "AVOCAT", "SOCIETE"):
            return False
        return any(tok in STOPWORDS_TITLECASE for tok in entity.text.split())

    found = [e for e in found if not _touches_stopword(e)]

    # Tri puis suppression des chevauchements :
    # - à position égale, on garde la correspondance la plus longue ;
    # - à position et longueur égales, le gazetteer (choix explicite de
    #   l'utilisateur) l'emporte toujours sur une règle regex générique.
    found.sort(key=lambda e: (e.start, -(e.end - e.start), 0 if e.source == "gazetteer" else 1))
    resolved: List[Entity] = []
    last_end = -1
    for e in found:
        if e.start >= last_end:
            resolved.append(e)
            last_end = e.end
    return resolved


# ---------------------------------------------------------------------------
# 2. Remplacement cohérent par pseudonymes
# ---------------------------------------------------------------------------

PLACEHOLDER_PREFIXES = {
    "PERSONNE": "PERSONNE",
    "SOCIETE": "SOCIETE",
    "AVOCAT": "CABINET",
    "ADRESSE": "ADRESSE",
    "NUMERO": "NUMERO",
    "MONTANT": "MONTANT",
    "DATE": "DATE",
    "MATRICULE": "MATRICULE",
    "TELEPHONE": "TELEPHONE",
    "VILLE": "VILLE",
}


def _extract_leading_surname(full_name: str) -> Optional[str]:
    """Depuis 'RABARISOA Andrianaina', retourne 'RABARISOA' (les tokens de
    tête entièrement en majuscules). Retourne None si aucun token ALLCAPS
    en tête (ne devrait pas arriver pour un match du pattern PERSONNE)."""
    tokens = full_name.split(" ")
    surname_tokens: List[str] = []
    for t in tokens:
        if t.isupper():
            surname_tokens.append(t)
        else:
            break
    return " ".join(surname_tokens) if surname_tokens else None


class Anonymizer:
    """Applique le remplacement en garantissant que la même chaîne de
    caractères (ex: 'Le Relais des Volcans') reçoit toujours le même
    pseudonyme dans tout le document."""

    def __init__(self, gazetteer: Optional[Gazetteer] = None):
        self.gazetteer = gazetteer or Gazetteer()
        self._mapping: Dict[str, str] = {}   # texte original -> pseudonyme
        self._counters: Dict[str, int] = {}

    def _pseudonym_for(self, entity_text: str, label: str) -> str:
        key = entity_text.strip()
        if key in self._mapping:
            return self._mapping[key]
        prefix = PLACEHOLDER_PREFIXES.get(label, label)
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        pseudo = f"[{prefix}_{self._counters[prefix]}]"
        self._mapping[key] = pseudo
        return pseudo

    def detect(self, text: str) -> List[Entity]:
        entities = detect_entities(text, self.gazetteer)

        # Auto-enrichissement : quand un nom complet "SURNOM Prénom" est
        # repéré (forme fiable), on ajoute le seul SURNOM au gazetteer afin
        # de retrouver ses mentions isolées plus loin dans le document —
        # plutôt que de scanner tout le texte à l'aveugle pour n'importe
        # quel mot en majuscules, ce qui produirait trop de faux positifs
        # (citations de jurisprudence, sigles, titres de section...).
        added = False
        for e in entities:
            if e.label == "PERSONNE" and e.source == "regex" and " " in e.text:
                surname = _extract_leading_surname(e.text)
                if surname and len(surname) >= 4 and surname not in self.gazetteer.entries:
                    self.gazetteer.add(surname, "PERSONNE")
                    added = True

        if added:
            entities = detect_entities(text, self.gazetteer)
        return entities

    def anonymize(self, text: str, entities: Optional[List[Entity]] = None) -> str:
        """entities: passer une liste (éventuellement filtrée par
        l'utilisateur après relecture) pour ne remplacer que celles-ci.
        Si None, on redétecte automatiquement."""
        if entities is None:
            entities = self.detect(text)

        # Remplacement de la fin vers le début pour ne pas décaler les index
        out = text
        for e in sorted(entities, key=lambda e: e.start, reverse=True):
            pseudo = self._pseudonym_for(e.text, e.label)
            out = out[:e.start] + pseudo + out[e.end:]
        return out

    def mapping_table(self) -> List[Tuple[str, str]]:
        """Retourne (texte_original, pseudonyme) — utile pour un export
        de correspondance à conserver en interne (hors diffusion publique)."""
        return sorted(self._mapping.items(), key=lambda kv: kv[1])
