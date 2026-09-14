# -*- coding: utf-8 -*-
"""
Import de fichiers PDF pour l'anonymiseur.

Deux cas de figure très différents derrière un même ".pdf" :

1. PDF "texte" : généré depuis un traitement de texte (Word -> PDF).
   Le texte est directement extractible, pas besoin d'OCR.
2. PDF "image" / scanné : chaque page est en réalité une photo/scan du
   document papier. Il n'y a pas de texte à extraire — il faut d'abord
   reconnaître les caractères dans l'image (OCR).

Ce module essaie d'abord l'extraction directe (rapide, fiable à 100%,
pas de dépendance lourde). Si le résultat est quasi vide, il bascule
automatiquement sur l'OCR.

Dépendance système requise pour l'OCR : le moteur Tesseract, avec le
pack de langue française (voir README.md — c'est l'étape qui complique
le plus la distribution "hors-ligne pour non-techniciens" de tout le
projet, à anticiper avant de figer une version distribuable).
"""

from __future__ import annotations
from pathlib import Path
import os
import re
import sys

import pdfplumber

from ocr_correction import load_corpus, correct_text, DEFAULT_CORPUS_PATH

# Seuil de caractères en-dessous duquel on considère qu'un PDF n'a pas
# de texte natif exploitable (page de garde vide, PDF entièrement scanné,
# texte "caché" dérisoire...) et qu'il faut basculer sur l'OCR.
MIN_CHARS_FOR_NATIVE_TEXT = 40


def _app_root() -> Path:
    """Dossier de référence pour chercher des binaires embarqués :
    - application empaquetée par PyInstaller (--onedir) : dossier contenant
      l'exécutable (sys.executable) ;
    - lancé depuis les sources (python app.py) : dossier du projet.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def _bundled_poppler_bin() -> Path | None:
    """Dossier bin de Poppler embarqué à côté de l'exécutable
    (vendor/poppler/bin/), s'il existe. None si absent — dans ce cas
    pdf2image se rabat sur le PATH système (comportement actuel,
    inchangé)."""
    candidate = _app_root() / "vendor" / "poppler" / "bin"
    return candidate if candidate.is_dir() else None


def _bundled_tesseract() -> tuple[Path, Path] | None:
    """(chemin de tesseract.exe/tesseract, dossier tessdata) embarqués à
    côté de l'exécutable (vendor/tesseract/), si présents. None si absent
    — dans ce cas pytesseract se rabat sur le PATH système / TESSDATA_PREFIX
    déjà configuré sur la machine (comportement actuel, inchangé)."""
    base = _app_root() / "vendor" / "tesseract"
    exe = base / ("tesseract.exe" if os.name == "nt" else "tesseract")
    tessdata = base / "tessdata"
    if exe.is_file() and tessdata.is_dir():
        return exe, tessdata
    return None


class OcrNotAvailable(RuntimeError):
    """Levée quand l'OCR serait nécessaire mais que Tesseract et/ou
    pdf2image/pytesseract ne sont pas installés sur la machine."""


def list_available_ocr_languages() -> list[str]:
    """Liste les modèles Tesseract installés (ex : ['eng', 'fra',
    'mlg_archives']). Utilisé pour proposer un choix de modèle dans
    l'interface. Vérifie d'abord un Tesseract embarqué à côté de
    l'exécutable, puis se rabat sur celui du système. Retourne une liste
    vide si Tesseract est introuvable, plutôt que de lever une exception
    (l'appelant peut alors se rabattre sur 'fra')."""
    import subprocess

    bundled = _bundled_tesseract()
    if bundled:
        exe_path, tessdata_path = bundled
        cmd = [str(exe_path), "--list-langs"]
        env = {**os.environ, "TESSDATA_PREFIX": str(tessdata_path)}
    else:
        cmd = ["tesseract", "--list-langs"]
        env = None

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, env=env)
        lines = result.stdout.strip().splitlines()
        # La 1ère ligne est "List of available languages (N):", pas un modèle
        langs = [l.strip() for l in lines[1:] if l.strip() and l.strip() != "osd"]
        return sorted(langs)
    except Exception:
        return []


def read_pdf(
    path: str,
    ocr_lang: str = "fra",
    ocr_dpi: int = 300,
    ocr_psm: int | None = None,
    corpus_path: str | Path = DEFAULT_CORPUS_PATH,
) -> tuple[str, bool, int]:
    """Lit un PDF et retourne (texte, ocr_utilise, nb_corrections_ocr).

    - Tente d'abord l'extraction de texte natif (pdfplumber).
    - Si le texte obtenu est trop court, bascule sur l'OCR page par page,
      puis corrige le texte reconnu contre le corpus de vocabulaire
      (voir ocr_correction.py). nb_corrections_ocr vaut 0 si l'OCR n'a
      pas été utilisé (texte natif présumé déjà fiable, pas de correction
      appliquée).
    - ocr_psm : mode de segmentation de page Tesseract (--psm). Laissé à
      None (comportement par défaut = segmentation automatique) sauf cas
      particulier : un mode forcé peut dégrader fortement un document à
      mise en page complexe (colonnes, en-têtes multi-blocs), donc ne
      l'imposer que si vous savez que vos documents sont un bloc de
      texte uniforme (ex : une simple lettre scannée) — voir README.md.

    Lève OcrNotAvailable si l'OCR est nécessaire mais indisponible, avec
    un message explicite à afficher à l'utilisateur (plutôt qu'une
    ImportError/FileNotFoundError technique incompréhensible pour un
    non-technicien).
    """
    native_text = _extract_native_text(path)
    if len(native_text.strip()) >= MIN_CHARS_FOR_NATIVE_TEXT:
        return _normalize_pdf_text(native_text), False, 0

    ocr_text = _extract_via_ocr(path, lang=ocr_lang, dpi=ocr_dpi, psm=ocr_psm)
    ocr_text = _normalize_pdf_text(ocr_text)

    corpus = load_corpus(corpus_path)
    corrected_text, n_corrections = correct_text(ocr_text, corpus)
    return corrected_text, True, n_corrections


def _normalize_pdf_text(text: str) -> str:
    """Un PDF n'a pas de notion de paragraphe : chaque ligne y est coupée
    selon la largeur de page, sans rapport avec la ponctuation. Sans
    normalisation, un nom ou une date à cheval sur deux lignes de mise en
    page ("société Le Relais\ndes Volcans") ne serait pas détecté par les
    règles qui s'interdisent de franchir un saut de ligne (justement pour
    éviter de fusionner deux paragraphes distincts d'un .docx — voir
    anonymizer.py). On recolle donc les sauts de ligne "simples" (mise en
    page) en espace, en gardant les vraies coupures de paragraphe (ligne
    vide, "\\n\\n") intactes."""
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text


def _extract_native_text(path: str) -> str:
    with pdfplumber.open(path) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    return "\n".join(pages)


def _extract_via_ocr(path: str, lang: str, dpi: int, psm: int | None = None) -> str:
    try:
        from pdf2image import convert_from_path
        import pytesseract
    except ImportError as exc:
        raise OcrNotAvailable(
            "Ce PDF semble être un scan (pas de texte natif détecté), "
            "mais les bibliothèques d'OCR (pdf2image, pytesseract) ne "
            "sont pas installées. Voir README.md, section OCR."
        ) from exc

    # Utilise Poppler embarqué à côté de l'exécutable s'il est présent
    # (vendor/poppler/bin/), sinon celui du système (comportement actuel,
    # inchangé — voir README.md pour l'installer séparément).
    poppler_bin = _bundled_poppler_bin()
    try:
        if poppler_bin:
            images = convert_from_path(path, dpi=dpi, poppler_path=str(poppler_bin))
        else:
            images = convert_from_path(path, dpi=dpi)
    except Exception as exc:
        if poppler_bin:
            detail = (
                f"Dossier Poppler embarqué détecté et utilisé : {poppler_bin}\n"
                f"Vérifiez qu'il contient bien pdftoppm.exe, pdfinfo.exe, ET leurs "
                f"fichiers .dll associés (voir build_windows.bat)."
            )
        else:
            detail = (
                f"Aucun dossier Poppler embarqué détecté (cherché dans : "
                f"{_app_root() / 'vendor' / 'poppler' / 'bin'}).\n"
                f"Poppler système (PATH) est-il installé et accessible ?"
            )
        raise OcrNotAvailable(
            "Impossible de convertir le PDF en images pour l'OCR. "
            "Poppler (poppler-utils / poppler pour Windows) est-il "
            "installé et accessible dans le PATH ? Voir README.md.\n\n"
            f"{detail}\n\n"
            f"Détail technique : {type(exc).__name__}: {exc}"
        ) from exc

    # Prétraitement + OCR page par page, avec un filet de sécurité :
    # certains scans (notamment des photos au téléphone avec un fond
    # visible — papier froissé, ombres, surface derrière la page) font
    # totalement échouer l'analyse de mise en page de Tesseract en mode
    # automatique (il ne détecte AUCUNE zone de texte, résultat vide),
    # alors que l'image est parfaitement lisible pour un humain. Un
    # contraste renforcé seul ne suffit pas toujours dans ce cas ; une
    # binarisation nette (noir/blanc pur) résout le problème. On tente
    # donc le contraste renforcé d'abord (meilleur pour les scans propres
    # avec dégradés fins), et on retente en binarisation uniquement si le
    # résultat est anormalement vide pour cette page.
    #
    # --oem 1 : moteur neuronal (LSTM) seul, le plus précis des moteurs
    # disponibles dans Tesseract 4/5.
    # PAS de --psm forcé par défaut : le mode automatique de Tesseract
    # détecte lui-même la structure en colonnes/blocs, essentiel sur ce
    # type de document (en-têtes de jugement avec plusieurs blocs de
    # texte côte à côte). Forcer --psm 6 ("un seul bloc de texte
    # uniforme") faisait fusionner ces blocs en une lecture linéaire,
    # mélangeant les colonnes entre elles — largement pire que l'absence
    # de réglage. Ne passez ocr_psm que pour un document que vous savez
    # être un bloc de texte uniforme.
    tess_config = "--oem 1" + (f" --psm {psm}" if psm is not None else "")

    pages_text = []
    for img in images:
        prep = _preprocess_for_ocr(img)
        text = _run_tesseract(prep, lang, tess_config)
        if len(text.strip()) < MIN_CHARS_PER_PAGE_BEFORE_FALLBACK:
            prep_bw = _preprocess_for_ocr(img, binarize=True)
            text_bw = _run_tesseract(prep_bw, lang, tess_config)
            if len(text_bw.strip()) > len(text.strip()):
                text = text_bw
        pages_text.append(text)

    return "\n\n".join(pages_text)


def _run_tesseract(image, lang: str, tess_config: str) -> str:
    import pytesseract

    bundled = _bundled_tesseract()
    if bundled:
        exe_path, tessdata_path = bundled
        pytesseract.pytesseract.tesseract_cmd = str(exe_path)
        # TESSDATA_PREFIX doit être positionné pour ce process avant l'appel
        # (pytesseract/tesseract le lit depuis l'environnement).
        os.environ["TESSDATA_PREFIX"] = str(tessdata_path)

    try:
        return pytesseract.image_to_string(image, lang=lang, config=tess_config)
    except Exception as exc:
        raise OcrNotAvailable(
            "Impossible de lancer l'OCR (Tesseract). Vérifiez que "
            "Tesseract est installé avec le pack de langue "
            f"'{lang}'. Voir README.md, section OCR.\n\n"
            f"Détail technique : {type(exc).__name__}: {exc}"
        ) from exc


# En-dessous de ce nombre de caractères pour une page, on considère que
# le premier passage a probablement échoué (page vide détectée à tort)
# et on retente avec une binarisation plus agressive.
MIN_CHARS_PER_PAGE_BEFORE_FALLBACK = 30


def _preprocess_for_ocr(image, binarize: bool = False):
    """Niveaux de gris + accentuation du contraste avant OCR. Réduit
    nettement le taux d'erreur sur un scan de qualité moyenne (fond
    légèrement grisé, contraste faible), sans dépendance supplémentaire
    (Pillow est déjà requis par pdf2image).

    binarize=True : bascule sur un noir/blanc pur (seuil fixe) plutôt
    qu'un simple étirement de contraste — plus radical, utile en filet
    de sécurité quand l'image a un fond visible autour de la page
    (photo au téléphone plutôt que scan à plat) qui perturbe l'analyse
    de mise en page de Tesseract."""
    from PIL import ImageOps

    gray = image.convert("L")
    if binarize:
        return gray.point(lambda x: 0 if x < 140 else 255, mode="1").convert("L")
    return ImageOps.autocontrast(gray, cutoff=1)
