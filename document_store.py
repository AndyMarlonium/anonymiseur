# -*- coding: utf-8 -*-
"""
Bibliothèque de documents traités : un sous-dossier par document importé,
pour pouvoir le retrouver et le rouvrir plus tard.

⚠️ IMPORTANT — donnée sensible stockée en clair :
Chaque dossier contient, entre autres, le texte AVANT anonymisation et la
table de correspondance pseudonyme -> texte original (fichier
`correspondance.json`). C'est littéralement la clé qui permet de retrouver
qui se cache derrière un pseudonyme comme [PERSONNE_3]. Ce module ne
chiffre rien : c'est un choix à faire consciemment par l'organisation qui
utilise l'application (qui a accès à la machine ? au dossier bibliothèque ?
faut-il le mettre sur un disque chiffré ?) — pas une décision que ce code
prend à votre place.

Structure d'un dossier de document :
    <bibliothèque>/<nom_document>/
        original.<ext>          — copie du fichier importé tel quel
        texte_extrait.txt        — texte brut obtenu à l'import (avant anonymisation)
        texte_anonymise.txt      — résultat final (texte)
        correspondance.json      — pseudonyme -> texte original (SENSIBLE)
        info.json                — métadonnées (date, modèle OCR, etc.)
"""

from __future__ import annotations
import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


DEFAULT_CONFIG_PATH = Path.home() / ".anonymiseur" / "config.json"


# ---------------------------------------------------------------------------
# Configuration : mémoriser le dossier bibliothèque choisi par l'utilisateur
# ---------------------------------------------------------------------------

def load_library_root(config_path: Path = DEFAULT_CONFIG_PATH) -> Path | None:
    """Retourne le dossier bibliothèque mémorisé, ou None si jamais configuré
    (ou si le dossier mémorisé n'existe plus, ex: clé USB débranchée)."""
    if not config_path.exists():
        return None
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        root = data.get("library_root")
        if root and Path(root).is_dir():
            return Path(root)
    except Exception:
        pass
    return None


def save_library_root(root: str | Path, config_path: Path = DEFAULT_CONFIG_PATH) -> None:
    """Mémorise le dossier bibliothèque choisi, pour ne pas avoir à le
    resélectionner à chaque lancement de l'application."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps({"library_root": str(root)}, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Création / sauvegarde d'un dossier de document
# ---------------------------------------------------------------------------

def _sanitize_folder_name(name: str) -> str:
    """Nettoie un nom de fichier pour en faire un nom de dossier valide sur
    Windows/Mac/Linux (retire les caractères interdits, limite la longueur)."""
    name = Path(name).stem  # sans l'extension
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = name.strip(" .")
    return name[:120] or "document"


def _unique_folder(library_root: Path, base_name: str) -> Path:
    """Évite d'écraser un dossier existant : ajoute (2), (3)... si besoin."""
    candidate = library_root / base_name
    if not candidate.exists():
        return candidate
    i = 2
    while (library_root / f"{base_name} ({i})").exists():
        i += 1
    return library_root / f"{base_name} ({i})"


@dataclass
class SavedDocument:
    folder: Path
    original_path: str | None = None
    extracted_text: str = ""
    anonymized_text: str = ""
    mapping: list[tuple[str, str]] = field(default_factory=list)
    ocr_used: bool = False
    ocr_lang: str | None = None
    n_corrections: int = 0
    saved_at: str = ""


def save_document(
    library_root: Path,
    original_path: str | None,
    extracted_text: str,
    anonymized_text: str,
    mapping: list[tuple[str, str]],
    ocr_used: bool = False,
    ocr_lang: str | None = None,
    n_corrections: int = 0,
) -> Path:
    """Crée (ou met à jour) le dossier de ce document dans la bibliothèque
    et y écrit tous les fichiers. Retourne le chemin du dossier créé."""
    library_root = Path(library_root)
    library_root.mkdir(parents=True, exist_ok=True)

    base_name = _sanitize_folder_name(Path(original_path).name if original_path else "document")
    folder = _unique_folder(library_root, base_name)
    folder.mkdir(parents=True, exist_ok=True)

    if original_path and Path(original_path).exists():
        ext = Path(original_path).suffix
        shutil.copy2(original_path, folder / f"original{ext}")

    (folder / "texte_extrait.txt").write_text(extracted_text, encoding="utf-8")
    (folder / "texte_anonymise.txt").write_text(anonymized_text, encoding="utf-8")

    # Sensible : voir avertissement en tête de fichier.
    (folder / "correspondance.json").write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    info = {
        "nom_original": Path(original_path).name if original_path else None,
        "date_enregistrement": datetime.now().isoformat(timespec="seconds"),
        "ocr_utilise": ocr_used,
        "modele_ocr": ocr_lang if ocr_used else None,
        "corrections_ocr": n_corrections if ocr_used else 0,
    }
    (folder / "info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")

    return folder


def list_documents(library_root: Path) -> list[dict]:
    """Liste les documents déjà enregistrés dans la bibliothèque, du plus
    récent au plus ancien. Chaque entrée : {folder, nom_original, date, ...}."""
    library_root = Path(library_root)
    if not library_root.is_dir():
        return []

    entries = []
    for sub in library_root.iterdir():
        if not sub.is_dir():
            continue
        info_path = sub / "info.json"
        info = {}
        if info_path.exists():
            try:
                info = json.loads(info_path.read_text(encoding="utf-8"))
            except Exception:
                info = {}
        entries.append({
            "folder": sub,
            "nom_original": info.get("nom_original", sub.name),
            "date": info.get("date_enregistrement", ""),
            "ocr_utilise": info.get("ocr_utilise", False),
        })

    entries.sort(key=lambda e: e["date"], reverse=True)
    return entries


def load_document(folder: Path) -> SavedDocument:
    """Recharge un document précédemment enregistré (texte extrait et
    anonymisé, table de correspondance). N'inclut pas le fichier original
    lui-même : à récupérer séparément si besoin (folder / 'original.*')."""
    folder = Path(folder)

    def _read(name: str) -> str:
        p = folder / name
        return p.read_text(encoding="utf-8") if p.exists() else ""

    mapping = []
    mapping_path = folder / "correspondance.json"
    if mapping_path.exists():
        try:
            mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
        except Exception:
            mapping = []

    info = {}
    info_path = folder / "info.json"
    if info_path.exists():
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except Exception:
            info = {}

    original_candidates = list(folder.glob("original.*"))

    return SavedDocument(
        folder=folder,
        original_path=str(original_candidates[0]) if original_candidates else None,
        extracted_text=_read("texte_extrait.txt"),
        anonymized_text=_read("texte_anonymise.txt"),
        mapping=[tuple(m) for m in mapping],
        ocr_used=info.get("ocr_utilise", False),
        ocr_lang=info.get("modele_ocr"),
        n_corrections=info.get("corrections_ocr", 0),
        saved_at=info.get("date_enregistrement", ""),
    )


def restore_original_names(anonymized_text: str, mapping: list[tuple[str, str]]) -> tuple[str, int]:
    """Opération inverse de l'anonymisation : remplace chaque pseudonyme
    ([PERSONNE_1], [SOCIETE_2]...) par le texte original correspondant,
    à partir de la table de correspondance sauvegardée avec le document.

    Fonctionne aussi bien sur le texte anonymisé d'origine que sur une
    version RETRAVAILLÉE ailleurs (résumé, extrait...) : tant que les
    pseudonymes n'ont pas été modifiés par cet autre traitement, ils sont
    reconnus et remplacés. Un pseudonyme absent du texte (ex : coupé par
    un résumé) est simplement ignoré, sans erreur.

    Chaque pseudonyme est un jeton unique et sans ambiguïté (ex :
    "[PERSONNE_1]"), donc un simple remplacement direct suffit — pas
    besoin d'une logique plus complexe que pour l'anonymisation elle-même
    (qui devait, elle, repérer les entités dans un texte libre).

    Retourne (texte_restauré, nombre_de_pseudonymes_effectivement_trouvés)
    — ce compte permet de signaler à l'utilisateur si le fichier fourni
    (ex: un résumé très raccourci) ne contenait qu'une partie des
    pseudonymes attendus.

    ⚠️ Le résultat contient à nouveau les données personnelles d'origine.
    Ce n'est pas une opération "de récupération d'urgence" anodine : elle
    doit rester réservée à un usage interne légitime (retrouver le
    document de travail original), jamais à la diffusion."""
    restored = anonymized_text
    found = 0
    for original, pseudonym in mapping:
        count = restored.count(pseudonym)
        if count:
            found += count
            restored = restored.replace(pseudonym, original)
    return restored, found
