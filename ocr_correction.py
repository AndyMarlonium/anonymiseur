# -*- coding: utf-8 -*-
"""
Correction des fautes d'OCR par comparaison à un petit corpus de
vocabulaire courant (français + malgache), après l'extraction OCR d'un
PDF scanné.

Principe volontairement simple et prévisible (dans le même esprit que
le moteur d'anonymisation par règles) :

    1. Chaque mot du texte OCRisé est comparé au corpus.
    2. S'il y est déjà tel quel, on ne touche à rien.
    3. S'il en est très proche (1-2 caractères de différence, typiquement
       une confusion visuelle "rn"/"m", "0"/"o", accent manqué...), on le
       remplace par l'entrée du corpus la plus proche.
    4. Sinon (mot trop différent de tout le corpus, ou absent), on le
       laisse tel quel plutôt que de risquer une correction hasardeuse.

Aucune nouvelle dépendance : `difflib` fait partie de la bibliothèque
standard de Python, ce qui compte pour un outil distribué hors-ligne.

Important — ce module ne doit PAS être appliqué aux noms propres
(patronymes, sociétés, adresses...), qui varient à l'infini et seraient
injustement "corrigés" vers un mot du dictionnaire qui leur ressemble.
Dans app.py, la correction est donc appliquée AVANT la détection
d'entités, uniquement sur le texte issu de l'OCR (jamais sur du texte
.docx/.txt saisi directement, présumé déjà correct), et le corpus ne
doit contenir que du vocabulaire courant / des formules récurrentes —
pas de noms de personnes.
"""

from __future__ import annotations
import difflib
import re
import unicodedata
from pathlib import Path

DEFAULT_CORPUS_PATH = Path(__file__).parent / "ocr_corpus.txt"

# En-dessous de cette longueur, on ne corrige pas : les mots courts
# (2-3 lettres) ont trop de "voisins" proches dans n'importe quel
# corpus, le risque de fausse correction dépasse le bénéfice.
MIN_WORD_LENGTH = 4

# Seuil de similarité (0 à 1) à partir duquel on considère qu'un mot du
# corpus est "assez proche" pour corriger. 0.8 tolère grossièrement
# 1 caractère différent sur 5, 2 sur 10.
SIMILARITY_THRESHOLD = 0.8

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def load_corpus(path: str | Path = DEFAULT_CORPUS_PATH) -> set[str]:
    """Charge le corpus depuis un fichier texte (un mot par ligne, les
    lignes vides et celles commençant par # sont ignorées). Fichier
    éditable directement par l'utilisateur pour l'enrichir au fil des
    documents traités."""
    p = Path(path)
    if not p.exists():
        return set()
    words = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            words.add(line)
    return words


def _strip_accents(word: str) -> str:
    """'société' -> 'societe'. Utilisé pour un premier passage de
    correction à haute confiance : un accent mal reconnu (ou absent) par
    l'OCR est la faute la plus fréquente sur du texte français, et
    contrairement à une comparaison floue générale, comparer les formes
    sans accents ne laisse quasiment aucune ambiguïté."""
    return "".join(c for c in unicodedata.normalize("NFKD", word) if not unicodedata.combining(c))


def correct_text(text: str, corpus: set[str]) -> tuple[str, int]:
    """Corrige le texte mot à mot contre le corpus. Retourne
    (texte_corrigé, nombre_de_corrections) — le compte est affiché à
    l'utilisateur pour qu'il sache qu'une relecture est d'autant plus
    utile qu'il y a eu de corrections automatiques.

    Deux passes, de la plus fiable à la plus approximative :
    1. Accents ignorés : si le mot sans accent correspond exactement à
       une entrée du corpus sans accent, on corrige (quasi certain).
    2. Similarité floue (difflib) : sinon, si un mot du corpus est très
       proche (SIMILARITY_THRESHOLD), on corrige aussi — couvre les
       autres confusions typiques de l'OCR (rn/m, 0/o, lettre manquante...).
    """
    if not corpus:
        return text, 0

    corpus_lower = {w.lower() for w in corpus}
    unaccented_map: dict[str, str] = {}
    for w in corpus_lower:
        unaccented_map.setdefault(_strip_accents(w), w)

    corrections = 0

    def _replace(match: re.Match) -> str:
        nonlocal corrections
        word = match.group(0)
        if len(word) < MIN_WORD_LENGTH:
            return word
        lower = word.lower()
        if lower in corpus_lower:
            return word  # déjà correct, rien à faire

        # Passe 1 : accents ignorés (haute confiance)
        target = unaccented_map.get(_strip_accents(lower))
        if target and target != lower:
            corrections += 1
            return _match_case(word, target)

        # Passe 2 : similarité floue générale (autres confusions OCR)
        close = difflib.get_close_matches(lower, corpus_lower, n=1, cutoff=SIMILARITY_THRESHOLD)
        if not close:
            return word  # trop différent de tout le corpus : on ne touche pas

        corrections += 1
        return _match_case(word, close[0])

    corrected = _WORD_RE.sub(_replace, text)
    return corrected, corrections


def _match_case(original: str, replacement: str) -> str:
    """Réapplique la casse du mot d'origine sur le mot de remplacement
    ('Societe' -> 'Société', 'SOCIETE' -> 'SOCIÉTÉ', 'société' -> 'société')."""
    if original.isupper():
        return replacement.upper()
    if original[0].isupper():
        return replacement[0].upper() + replacement[1:]
    return replacement
