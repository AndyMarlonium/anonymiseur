# -*- coding: utf-8 -*-
"""
Anonymiseur de décisions de justice — interface Tkinter.

Flux d'utilisation :
    1. Importer un fichier .docx ou .txt
    2. L'application détecte automatiquement les entités (dates, montants,
       numéros de décision, noms précédés de M./Mme, sociétés, cabinets,
       adresses) et les surligne dans l'aperçu
    3. L'utilisateur peut décocher une entité détectée à tort, ou ajouter
       manuellement un nom oublié (liste de gazetteer)
    4. "Anonymiser" applique le remplacement par des pseudonymes cohérents
       ([PERSONNE_1], [SOCIETE_1], ...)
    5. "Exporter" sauvegarde le résultat en .docx (en conservant la mise en
       forme du document original si possible) ou .txt

Lancer :  python app.py
Empaqueter en exécutable autonome :  voir README.md (PyInstaller)
"""

from __future__ import annotations
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

from anonymizer import Anonymizer, Gazetteer, Entity
from docx_io import read_text, write_text
from pdf_io import read_pdf, OcrNotAvailable, list_available_ocr_languages
import document_store
from document_store import restore_original_names


def _app_root() -> Path:
    """Dossier de l'exécutable une fois empaqueté (PyInstaller), ou du
    projet en développement — pour retrouver icon.ico à côté."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


LABEL_COLORS = {
    "PERSONNE": "#ffd166",
    "SOCIETE": "#06d6a0",
    "AVOCAT": "#118ab2",
    "ADRESSE": "#ef476f",
    "NUMERO": "#8338ec",
    "MONTANT": "#fb5607",
    "DATE": "#adb5bd",
    "MATRICULE": "#ff006e",
    "TELEPHONE": "#3a86ff",
    "PROPRIETE": "#606c38",
}

# Palette utilisée pour attribuer automatiquement une couleur aux types
# d'entité personnalisés créés par l'utilisateur (cycle si épuisée).
CUSTOM_LABEL_PALETTE = [
    "#f4a261", "#2a9d8f", "#e76f51", "#9b5de5", "#00bbf9",
    "#ffb703", "#fb8500", "#4cc9f0", "#7209b7", "#80ed99",
]


class AnonymiserApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Anonymiseur de décisions de justice")
        # Fenêtre volontairement plus large que le strict nécessaire sous
        # Linux : les thèmes Aqua (Mac) et natif Windows rendent boutons et
        # polices sensiblement plus larges que sous Linux/X11, ce qui a
        # déjà fait sortir le bouton de l'étape 5 hors de la fenêtre sur
        # Mac avec une géométrie plus étroite. minsize empêche aussi de
        # redescendre en dessous par un redimensionnement manuel.
        self.geometry("1250x750")
        self.minsize(1100, 650)
        self._load_app_icon()

        self.original_text: str = ""
        self.original_path: str | None = None
        self.entities: list[Entity] = []
        self.entity_vars: dict[int, tk.BooleanVar] = {}  # index -> inclus ?
        self.gazetteer = Gazetteer()
        self.anonymizer = Anonymizer(self.gazetteer)

        # Métadonnées du dernier import, utilisées lors de l'enregistrement
        # dans la bibliothèque (voir on_save_to_library).
        self.last_ocr_used: bool = False
        self.last_ocr_lang: str | None = None
        self.last_n_corrections: int = 0

        self.library_root: Path | None = document_store.load_library_root()

        self._build_ui()

    # ------------------------------------------------------------------
    # Construction de l'interface
    # ------------------------------------------------------------------
    def _make_step(self, parent, num, label, caption, command, width=18):
        """Construit un bouton d'étape numérotée : petite carte avec un
        numéro d'étape, le bouton lui-même, et une légende d'une ligne
        expliquant ce qu'il fait. Retourne le Button (pour pouvoir le
        griser/dégriser selon la progression de l'utilisateur)."""
        card = ttk.Frame(parent, relief="groove", borderwidth=1, padding=(8, 6))
        card.pack(side="left", padx=4, pady=2, fill="y")
        ttk.Label(card, text=f"Étape {num}", font=("TkDefaultFont", 8, "bold"), foreground="#555").pack(anchor="w")
        btn = ttk.Button(card, text=label, command=command, width=width)
        btn.pack(anchor="w", pady=(3, 3), fill="x")
        ttk.Label(card, text=caption, font=("TkDefaultFont", 8), foreground="#777",
                  wraplength=140, justify="left").pack(anchor="w")
        return btn

    def _build_ui(self):
        # Sélecteur de modèle OCR : en dehors des onglets (utile avant même
        # d'importer, sur l'onglet Anonymiser) — une seule ligne en haut de
        # la fenêtre, toujours visible quel que soit l'onglet actif.
        ocr_bar = ttk.Frame(self)
        ocr_bar.pack(side="top", fill="x", padx=8, pady=(6, 0))

        ttk.Label(ocr_bar, text="Modèle OCR :").pack(side="left")
        available_langs = list_available_ocr_languages()
        ocr_choices = ["fra"] + [l for l in available_langs if l != "fra"]
        for lang in available_langs:
            if lang not in ("fra", "eng") and "fra" in available_langs:
                combo_choice = f"{lang}+fra"
                if combo_choice not in ocr_choices:
                    ocr_choices.append(combo_choice)

        # Choix verrouillé sur le meilleur modèle disponible plutôt que
        # laissé à l'utilisateur (source de confusion, et un choix erroné
        # ici dégrade silencieusement la qualité de l'OCR) : on préfère
        # toujours la dernière combinaison mlg_archives_v2+fra, avec un
        # repli sur les versions antérieures ou fra seul si elle n'est pas
        # présente dans ce dossier tessdata.
        preferred_order = [
            "mlg_archives_v2+fra", "mlg_archives+fra",
            "mlg_archives_v2", "mlg_archives", "fra",
        ]
        best_choice = next((c for c in preferred_order if c in ocr_choices), None)
        if best_choice is None:
            best_choice = ocr_choices[0] if ocr_choices else "fra"
        self.ocr_lang_var = tk.StringVar(value=best_choice)
        ocr_combo = ttk.Combobox(
            ocr_bar, textvariable=self.ocr_lang_var, state="disabled",
            values=ocr_choices, width=20,
        )
        ocr_combo.pack(side="left", padx=4)
        if not available_langs:
            ttk.Label(ocr_bar, text="(Tesseract introuvable — OCR indisponible)", foreground="#999").pack(side="left", padx=4)
        else:
            ttk.Label(ocr_bar, text="(modèle fixé automatiquement — le plus fiable détecté)", foreground="#666").pack(side="left", padx=4)

        # Les deux parcours de l'application sont volontairement séparés en
        # deux onglets, pour ne jamais les mélanger visuellement : anonymiser
        # un document neuf d'un côté, retrouver les données d'origine d'un
        # document déjà traité de l'autre.
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=6)

        anonymize_tab = ttk.Frame(self.notebook)
        restore_tab = ttk.Frame(self.notebook)
        self.notebook.add(anonymize_tab, text="① Anonymiser un document")
        self.notebook.add(restore_tab, text="② Retrouver un document original")

        self._build_anonymize_tab(anonymize_tab)
        self._build_restore_tab(restore_tab)

        self.status = tk.StringVar(value="Aucun document chargé.")
        status_bar = ttk.Frame(self)
        status_bar.pack(side="bottom", fill="x", padx=8, pady=4)
        ttk.Label(status_bar, textvariable=self.status, anchor="w").pack(side="left", fill="x", expand=True)
        # Mention discrète, coin bas-droit — petite taille, couleur neutre,
        # pour ne pas distraire de l'usage réel de l'application.
        ttk.Label(status_bar, text="Andy Marlonium", foreground="#aaaaaa", font=("TkDefaultFont", 8)).pack(side="right")

    def _build_anonymize_tab(self, parent):
        # Rangée d'étapes numérotées : l'ordre normal d'utilisation, de
        # gauche à droite. Les étapes 2 à 5 sont grisées tant que l'étape
        # précédente n'a pas été faite, pour guider l'œil sans avoir à lire.
        # Toute la rangée est placée dans un canevas défilable horizontalement
        # (barre de défilement en dessous) : filet de sécurité si les 5
        # cartes d'étape dépassent la largeur de la fenêtre — ce qui s'est
        # produit sur Mac, où le thème Aqua rend boutons et polices plus
        # larges que sous Linux, poussant l'étape 5 hors champ sans cela.
        steps_outer = ttk.Frame(parent)
        steps_outer.pack(side="top", fill="x", pady=(6, 2))
        steps_canvas = tk.Canvas(steps_outer, highlightthickness=0)
        steps_hscroll = ttk.Scrollbar(steps_outer, orient="horizontal", command=steps_canvas.xview)
        steps_bar = ttk.Frame(steps_canvas)

        def _sync_steps_canvas(_e=None):
            steps_canvas.configure(
                scrollregion=steps_canvas.bbox("all"),
                height=steps_bar.winfo_reqheight(),
            )
        steps_bar.bind("<Configure>", _sync_steps_canvas)
        steps_canvas.create_window((0, 0), window=steps_bar, anchor="nw")
        steps_canvas.configure(xscrollcommand=steps_hscroll.set)
        steps_canvas.pack(side="top", fill="x")
        steps_hscroll.pack(side="top", fill="x")

        self.btn_import = self._make_step(
            steps_bar, 1, "Importer…",
            "Charger un PDF, Word ou texte à traiter.",
            self.on_import,
        )
        self.btn_detect = self._make_step(
            steps_bar, 2, "Détecter les entités",
            "Repérer automatiquement noms, dates, montants, adresses…",
            self.on_detect,
        )
        self.btn_anonymize = self._make_step(
            steps_bar, 3, "Anonymiser",
            "Remplacer les entités cochées par des pseudonymes.",
            self.on_anonymize,
        )
        self.btn_export = self._make_step(
            steps_bar, 4, "Exporter…",
            "Enregistrer le résultat anonymisé dans un fichier.",
            self.on_export,
        )
        ttk.Separator(steps_bar, orient="vertical").pack(side="left", fill="y", padx=6, pady=8)
        self.btn_save_library = self._make_step(
            steps_bar, 5, "Enregistrer",
            "Optionnel : garder une trace dans la bibliothèque pour "
            "pouvoir retrouver les données d'origine plus tard (onglet ②).",
            self.on_save_to_library, width=18,
        )
        for b in (self.btn_detect, self.btn_anonymize, self.btn_export, self.btn_save_library):
            b.configure(state="disabled")

        # Action secondaire, optionnelle : volontairement plus discrète que
        # les étapes numérotées (ce n'est pas une étape obligatoire du flux).
        secondary_bar = ttk.Frame(parent)
        secondary_bar.pack(side="top", fill="x", padx=4, pady=(2, 6))
        ttk.Button(secondary_bar, text="+ Ajouter un nom à repérer (optionnel)",
                   command=self.on_add_gazetteer).pack(side="left")
        self.library_status_var = tk.StringVar()
        ttk.Label(secondary_bar, textvariable=self.library_status_var, foreground="#666").pack(side="left", padx=12)
        self._update_library_status_label()

        main = ttk.Frame(parent)
        main.pack(fill="both", expand=True, padx=4, pady=4)

        # Zone de texte (aperçu / édition)
        text_frame = ttk.Frame(main)
        text_frame.pack(side="left", fill="both", expand=True)

        # Emplacement dédié pour la bannière d'avertissement, toujours en
        # haut de la zone de texte : affichée uniquement quand le texte
        # visible est une version RESTAURÉE (noms d'origine rétablis) —
        # pour ne jamais la confondre avec une version anonymisée prête à
        # partager. Cachée par défaut (voir _set_restored_banner).
        self.restored_banner = tk.Label(
            text_frame,
            text="⚠️ VERSION RESTAURÉE — noms et données d'origine rétablis, NE PAS diffuser tel quel",
            bg="#d62828", fg="white", font=("TkDefaultFont", 10, "bold"), pady=4,
        )
        self.viewing_restored = False
        # Pas de .pack() ici : affichée à la demande par _set_restored_banner,
        # toujours en premier dans text_frame donc toujours en haut quand visible.

        preview_header = ttk.Frame(text_frame)
        preview_header.pack(fill="x", pady=(0, 2))
        self.preview_header = preview_header
        self.doc_label = ttk.Label(preview_header, text="Aperçu du document")
        self.doc_label.pack(side="left", anchor="w")
        # Bouton isolé, volontairement à l'écart de la rangée d'étapes
        # numérotées : chemin alternatif à "① Importer…" pour qui préfère
        # coller/taper du texte directement (depuis un e-mail, un autre
        # logiciel...) plutôt que de partir d'un fichier.
        ttk.Button(
            preview_header, text="Enregistrer le texte collé ci-dessous",
            command=self.on_use_pasted_text,
        ).pack(side="right", padx=(8, 0))

        ttk.Label(
            text_frame,
            text="Vous pouvez aussi coller ou taper du texte directement ci-dessous (Ctrl+V), "
                 "puis cliquer sur \"Enregistrer le texte collé\" pour l'utiliser comme document de travail.",
            foreground="#666", font=("TkDefaultFont", 8), wraplength=520, justify="left",
        ).pack(anchor="w", pady=(0, 4))

        # Barre de défilement explicite plutôt que de compter sur les
        # raccourcis clavier/molette par défaut de Tk : sur Mac, le geste
        # de défilement au trackpad ne déclenche pas toujours cette
        # liaison par défaut selon la version/le thème, ce qui rendait le
        # document bloqué sur sa partie supérieure sans moyen d'accéder
        # au reste. Une vraie barre, cliquable/glissable, fonctionne dans
        # tous les cas quel que soit le geste ou le système.
        text_scroll_frame = ttk.Frame(text_frame)
        text_scroll_frame.pack(fill="both", expand=True)
        self.text_widget = tk.Text(text_scroll_frame, wrap="word", undo=True)
        text_scrollbar = ttk.Scrollbar(text_scroll_frame, orient="vertical", command=self.text_widget.yview)
        self.text_widget.configure(yscrollcommand=text_scrollbar.set)
        self.text_widget.pack(side="left", fill="both", expand=True)
        text_scrollbar.pack(side="right", fill="y")
        for label, color in LABEL_COLORS.items():
            self.text_widget.tag_configure(label, background=color)

        # Panneau latéral : entités détectées
        side = ttk.Frame(main, width=280)
        side.pack(side="right", fill="y", padx=(8, 0))
        side.pack_propagate(False)

        ttk.Label(side, text="Entités détectées").pack(anchor="w")
        self.entity_list_frame = ttk.Frame(side)
        self.entity_list_frame.pack(fill="both", expand=True)

    def _build_restore_tab(self, parent):
        intro = ttk.Frame(parent, padding=(4, 10, 4, 4))
        intro.pack(side="top", fill="x")
        ttk.Label(
            intro,
            text="Retrouver les vraies données (noms, adresses…) d'un document déjà anonymisé et enregistré dans la bibliothèque.",
            font=("TkDefaultFont", 9, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            intro,
            text="⚠️ Le résultat n'est plus anonymisé — à ne jamais diffuser tel quel.",
            foreground="#d62828",
        ).pack(anchor="w", pady=(2, 0))

        header = ttk.Frame(parent)
        header.pack(fill="x", padx=4, pady=(8, 4))
        self.restore_lib_path_var = tk.StringVar()
        ttk.Label(header, textvariable=self.restore_lib_path_var, foreground="#666").pack(side="left")
        ttk.Button(header, text="Changer de dossier…",
                   command=lambda: (self._choose_library_root(), self._refresh_library_tree())).pack(side="right")

        step1 = ttk.Frame(parent, padding=(4, 2))
        step1.pack(fill="x", padx=4)
        ttk.Label(step1, text="Étape 1 — Sélectionnez un document dans la liste :",
                  font=("TkDefaultFont", 8, "bold"), foreground="#555").pack(anchor="w")

        list_frame = ttk.Frame(parent)
        list_frame.pack(fill="both", expand=True, padx=4, pady=(2, 4))

        columns = ("nom", "date", "ocr")
        self.library_tree = ttk.Treeview(list_frame, columns=columns, show="headings")
        self.library_tree.heading("nom", text="Document")
        self.library_tree.heading("date", text="Enregistré le")
        self.library_tree.heading("ocr", text="OCR")
        self.library_tree.column("nom", width=320)
        self.library_tree.column("date", width=160)
        self.library_tree.column("ocr", width=60, anchor="center")
        self.library_tree.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.library_tree.yview)
        self.library_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")

        self._library_folders_by_item: dict[str, Path] = {}
        self.library_tree_status_var = tk.StringVar()
        ttk.Label(parent, textvariable=self.library_tree_status_var, foreground="#666").pack(anchor="w", padx=4, pady=(0, 4))

        step2 = ttk.Frame(parent, padding=(4, 2))
        step2.pack(fill="x", padx=4)
        ttk.Label(step2, text="Étape 2 — Choisissez une action pour ce document :",
                  font=("TkDefaultFont", 8, "bold"), foreground="#555").pack(anchor="w")

        actions_bar = ttk.Frame(parent)
        actions_bar.pack(fill="x", padx=4, pady=(2, 10))
        self.btn_lib_restore = self._make_step(
            actions_bar, "2a", "Désanonymiser sans modifications",
            "Réafficher le document avec les vraies données.",
            self._on_library_restore_selected, width=34,
        )
        self.btn_lib_restore_external = self._make_step(
            actions_bar, "2b", "Désanonymiser fichier traité par IA",
            "Appliquer les vraies données à un fichier retravaillé ailleurs.",
            self._on_library_restore_external, width=36,
        )
        ttk.Separator(actions_bar, orient="vertical").pack(side="left", fill="y", padx=6, pady=8)
        self._make_step(
            actions_bar, "↻", "Actualiser",
            "Rafraîchir la liste (nouveaux documents enregistrés).",
            self._refresh_library_tree, width=14,
        )
        for b in (self.btn_lib_restore, self.btn_lib_restore_external):
            b.configure(state="disabled")

        self.library_tree.bind("<<TreeviewSelect>>", self._on_library_selection_changed)

        self._refresh_library_tree()

    def _load_app_icon(self):
        """Charge icon.ico (à côté de l'exécutable ou du script) comme
        icône de la fenêtre. Silencieux si absent ou si la plateforme ne
        supporte pas .ico (ex: certaines configurations Linux) — l'icône
        n'est qu'un détail cosmétique, son absence ne doit jamais empêcher
        l'application de démarrer."""
        icon_path = _app_root() / "icon.ico"
        if icon_path.exists():
            try:
                self.iconbitmap(str(icon_path))
            except Exception:
                pass

    def _set_restored_banner(self, visible: bool):
        """Affiche/cache la bannière rouge d'avertissement selon que le
        texte actuellement affiché est une version restaurée (noms
        d'origine) ou non."""
        self.viewing_restored = visible
        if visible:
            self.restored_banner.pack(fill="x", before=self.preview_header)
        else:
            self.restored_banner.pack_forget()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def on_import(self):
        path = filedialog.askopenfilename(
            title="Importer un document",
            filetypes=[
                ("Documents pris en charge", "*.docx *.txt *.pdf"),
                ("Documents Word ou texte", "*.docx *.txt"),
                ("PDF (texte ou scanné)", "*.pdf"),
                ("Tous les fichiers", "*.*"),
            ],
        )
        if not path:
            return

        suffix = Path(path).suffix.lower()
        ocr_used = False
        n_corrections = 0
        try:
            if suffix == ".pdf":
                self.status.set("Lecture du PDF… (l'OCR d'un PDF scanné peut prendre quelques secondes par page)")
                self.update_idletasks()
                self.original_text, ocr_used, n_corrections = read_pdf(path, ocr_lang=self.ocr_lang_var.get())
            else:
                self.original_text = read_text(path)
        except OcrNotAvailable as exc:
            messagebox.showerror("OCR indisponible", str(exc))
            return
        except Exception as exc:
            messagebox.showerror("Erreur d'import", str(exc))
            return

        self.original_path = path
        self.text_widget.delete("1.0", "end")
        self.text_widget.insert("1.0", self.original_text)
        self.entities = []
        self._refresh_entity_panel()
        self._set_restored_banner(False)

        # Nouveau document : on repart de l'étape 2, les étapes suivantes
        # (déjà anonymisé/exporté) ne s'appliquent plus à ce texte-ci.
        self.btn_detect.configure(state="normal")
        self.btn_anonymize.configure(state="disabled")
        self.btn_export.configure(state="disabled")
        self.btn_save_library.configure(state="disabled")

        # Mémorisé pour l'enregistrement dans la bibliothèque (voir
        # on_save_to_library) — pas seulement pour l'affichage immédiat.
        self.last_ocr_used = ocr_used
        self.last_ocr_lang = self.ocr_lang_var.get() if ocr_used else None
        self.last_n_corrections = n_corrections

        if suffix == ".pdf" and ocr_used:
            self.status.set(
                f"Document chargé : {Path(path).name} (OCR modèle '{self.ocr_lang_var.get()}', "
                f"{n_corrections} correction(s) automatique(s) appliquée(s) — "
                "relisez attentivement, l'OCR peut introduire des erreurs de reconnaissance)"
            )
        else:
            self.status.set(f"Document chargé : {Path(path).name}")

    def on_use_pasted_text(self):
        """Étape alternative à 'Importer…' : prend en compte le texte
        déjà tapé/collé directement dans la zone d'aperçu (Ctrl+V depuis
        n'importe quelle source externe) comme document de travail, sans
        passer par un fichier. Une fois validé ici, la suite du parcours
        (détection, anonymisation, export/bibliothèque) fonctionne
        exactement comme pour un document importé."""
        pasted_text = self.text_widget.get("1.0", "end-1c")
        if not pasted_text.strip():
            messagebox.showinfo(
                "Info",
                "Collez ou tapez d'abord du texte dans la zone d'aperçu, "
                "puis cliquez sur ce bouton pour l'enregistrer comme document de travail.",
            )
            return

        self.original_text = pasted_text
        self.original_path = None  # aucun fichier associé : ni OCR, ni format d'origine
        self.entities = []
        self._refresh_entity_panel()
        self._set_restored_banner(False)

        # Même remise à zéro des étapes que pour un import classique (voir
        # on_import) : nouveau texte de travail, la suite doit repartir de
        # la détection.
        self.btn_detect.configure(state="normal")
        self.btn_anonymize.configure(state="disabled")
        self.btn_export.configure(state="disabled")
        self.btn_save_library.configure(state="disabled")

        self.last_ocr_used = False
        self.last_ocr_lang = None
        self.last_n_corrections = 0

        self.status.set(
            f"Texte collé enregistré comme document de travail ({len(pasted_text)} caractères) — "
            "passez à l'étape 2, Détecter les entités."
        )

    def on_detect(self):
        if not self.original_text:
            messagebox.showinfo("Info", "Importez d'abord un document.")
            return
        current_text = self.text_widget.get("1.0", "end-1c")
        self.entities = self.anonymizer.detect(current_text)
        self._highlight_entities(current_text)
        self._refresh_entity_panel()
        self.status.set(f"{len(self.entities)} entité(s) détectée(s).")
        self.btn_anonymize.configure(state="normal")

    def on_anonymize(self):
        if not self.entities:
            self.on_detect()
            if not self.entities:
                messagebox.showinfo("Info", "Aucune entité détectée à anonymiser.")
                return

        current_text = self.text_widget.get("1.0", "end-1c")
        # Ne garder que les entités cochées par l'utilisateur
        selected = [e for i, e in enumerate(self.entities) if self.entity_vars.get(i, tk.BooleanVar(value=True)).get()]

        anonymized = self.anonymizer.anonymize(current_text, selected)

        self.text_widget.delete("1.0", "end")
        self.text_widget.insert("1.0", anonymized)
        self.entities = []
        self._refresh_entity_panel()
        self.status.set("Document anonymisé. Vérifiez le résultat avant export.")
        self.btn_export.configure(state="normal")
        self.btn_save_library.configure(state="normal")

    def on_export(self):
        current_text = self.text_widget.get("1.0", "end-1c")
        if not current_text.strip():
            messagebox.showinfo("Info", "Rien à exporter.")
            return

        default_ext = ".docx" if (self.original_path and self.original_path.lower().endswith(".docx")) else ".txt"
        path = filedialog.asksaveasfilename(
            title="Exporter le document anonymisé",
            defaultextension=default_ext,
            filetypes=[("Document Word", "*.docx"), ("Texte", "*.txt")],
        )
        if not path:
            return

        try:
            original_docx = self.original_path if (self.original_path or "").lower().endswith(".docx") else None
            write_text(path, current_text, original_docx_path=original_docx)
        except Exception as exc:
            messagebox.showerror("Erreur d'export", str(exc))
            return

        messagebox.showinfo("Export réussi", f"Document exporté : {path}")

    def on_save_to_library(self):
        current_text = self.text_widget.get("1.0", "end-1c")
        if not current_text.strip():
            messagebox.showinfo("Info", "Rien à enregistrer — importez d'abord un document.")
            return

        if self.library_root is None:
            if not self._choose_library_root():
                return  # l'utilisateur a annulé

        try:
            folder = document_store.save_document(
                self.library_root,
                original_path=self.original_path,
                extracted_text=self.original_text,
                anonymized_text=current_text,
                mapping=self.anonymizer.mapping_table(),
                ocr_used=self.last_ocr_used,
                ocr_lang=self.last_ocr_lang,
                n_corrections=self.last_n_corrections,
            )
        except Exception as exc:
            messagebox.showerror("Erreur d'enregistrement", str(exc))
            return

        messagebox.showinfo("Enregistré", f"Document enregistré dans la bibliothèque :\n{folder}")
        self.status.set(f"Enregistré dans la bibliothèque : {folder.name}")
        if hasattr(self, "library_tree"):
            self._refresh_library_tree()

    def _choose_library_root(self) -> bool:
        """Demande à l'utilisateur de choisir le dossier bibliothèque (une
        seule fois normalement — mémorisé ensuite). Retourne True si un
        dossier a bien été choisi."""
        messagebox.showinfo(
            "Dossier bibliothèque",
            "Choisissez le dossier où seront enregistrés vos documents traités "
            "(un sous-dossier sera créé automatiquement pour chaque document).\n\n"
            "⚠️ Ce dossier contiendra, pour chaque document, le texte AVANT "
            "anonymisation ainsi que la table de correspondance permettant de "
            "retrouver qui se cache derrière chaque pseudonyme. Choisissez un "
            "emplacement sécurisé.",
        )
        chosen = filedialog.askdirectory(title="Choisir le dossier bibliothèque")
        if not chosen:
            return False
        self.library_root = Path(chosen)
        document_store.save_library_root(self.library_root)
        self._update_library_status_label()
        return True

    def _update_library_status_label(self):
        if self.library_root:
            text = f"Bibliothèque : {self.library_root}"
        else:
            text = "Bibliothèque : non configurée (choisie au premier enregistrement)"
        self.library_status_var.set(text)
        # Le même dossier est affiché sur l'onglet ② (peut ne pas encore
        # exister si _build_restore_tab n'a pas fini de s'exécuter).
        if hasattr(self, "restore_lib_path_var"):
            self.restore_lib_path_var.set(f"Dossier : {self.library_root}" if self.library_root else "Dossier : non configuré")

    # ------------------------------------------------------------------
    # Onglet ② — Retrouver un document original (liste intégrée, plus de
    # fenêtre séparée : tout se passe sur l'onglet, pour rester lisible).
    # ------------------------------------------------------------------
    def _refresh_library_tree(self):
        self._update_library_status_label()
        self.library_tree.delete(*self.library_tree.get_children())
        self._library_folders_by_item.clear()
        if self.library_root is None:
            self.library_tree_status_var.set("Aucune bibliothèque configurée pour l'instant (voir onglet ①, étape 5).")
            return
        docs = document_store.list_documents(self.library_root)
        if not docs:
            self.library_tree_status_var.set("Aucun document enregistré pour l'instant.")
            return
        for doc in docs:
            date_display = doc["date"].replace("T", " ")[:16]
            item = self.library_tree.insert(
                "", "end",
                values=(doc["nom_original"], date_display, "Oui" if doc["ocr_utilise"] else "Non"),
            )
            self._library_folders_by_item[item] = doc["folder"]
        self.library_tree_status_var.set(f"{len(docs)} document(s).")

    def _on_library_selection_changed(self, _event=None):
        state = "normal" if self.library_tree.selection() else "disabled"
        for b in (self.btn_lib_restore, self.btn_lib_restore_external):
            b.configure(state=state)

    def _selected_library_folder(self) -> Path | None:
        sel = self.library_tree.selection()
        if not sel:
            return None
        return self._library_folders_by_item.get(sel[0])

    def _on_library_restore_selected(self):
        folder = self._selected_library_folder()
        if not folder:
            messagebox.showinfo("Info", "Sélectionnez d'abord un document dans la liste.")
            return
        confirmed = messagebox.askyesno(
            "Désanonymiser sans modifications",
            "Ceci va afficher le document avec les VRAIS noms, adresses et "
            "autres données personnelles rétablis à la place des pseudonymes.\n\n"
            "Le résultat n'est plus anonymisé — à ne jamais diffuser tel quel.\n\n"
            "Continuer ?",
        )
        if confirmed:
            self._load_from_library(folder, restored=True)
            self.notebook.select(0)

    def _on_library_restore_external(self):
        folder = self._selected_library_folder()
        if not folder:
            messagebox.showinfo("Info", "Sélectionnez d'abord un document dans la liste.")
            return

        try:
            saved = document_store.load_document(folder)
        except Exception as exc:
            messagebox.showerror("Erreur", str(exc))
            return
        if not saved.mapping:
            messagebox.showinfo("Info", "Aucune table de correspondance trouvée pour ce document.")
            return

        confirmed = messagebox.askyesno(
            "Désanonymiser fichier traité par IA",
            "Choisissez un fichier retravaillé ailleurs (résumé, extrait...) "
            f"contenant encore des pseudonymes du document « {folder.name} » "
            "(ex : [PERSONNE_1]).\n\n"
            "Chaque pseudonyme reconnu sera remplacé par la vraie donnée "
            "correspondante. Le résultat ne sera plus anonymisé — à ne jamais "
            "diffuser tel quel.\n\n"
            "Continuer ?",
        )
        if not confirmed:
            return

        file_path = filedialog.askopenfilename(
            title="Choisir le fichier modifié à restaurer",
            filetypes=[("Documents Word ou texte", "*.docx *.txt"), ("Tous les fichiers", "*.*")],
        )
        if not file_path:
            return

        try:
            modified_text = read_text(file_path)
        except Exception as exc:
            messagebox.showerror("Erreur de lecture", str(exc))
            return

        restored_text, n_found = restore_original_names(modified_text, saved.mapping)

        self.text_widget.delete("1.0", "end")
        self.text_widget.insert("1.0", restored_text)
        self.entities = []
        self._refresh_entity_panel()
        self._set_restored_banner(True)
        self.original_path = file_path
        self.btn_export.configure(state="normal")
        self.btn_save_library.configure(state="normal")

        n_possible = len(saved.mapping)
        self.status.set(
            f"⚠️ Noms restaurés dans '{Path(file_path).name}' — "
            f"{n_found} correspondance(s) appliquée(s) (sur {n_possible} possibles "
            f"dans le document d'origine) — ne pas diffuser"
        )
        self.notebook.select(0)

    def _load_from_library(self, folder: Path, restored: bool = False):
        try:
            saved = document_store.load_document(folder)
        except Exception as exc:
            messagebox.showerror("Erreur", str(exc))
            return

        self.original_path = saved.original_path
        self.original_text = saved.extracted_text
        self.last_ocr_used = saved.ocr_used
        self.last_ocr_lang = saved.ocr_lang
        self.last_n_corrections = saved.n_corrections

        if restored:
            base_text = saved.anonymized_text.strip() or saved.extracted_text
            display_text, _n_found = restore_original_names(base_text, saved.mapping)
        else:
            # On affiche le texte anonymisé s'il existe (le document a déjà
            # été traité), sinon le texte extrait brut.
            display_text = saved.anonymized_text.strip() or saved.extracted_text

        self.text_widget.delete("1.0", "end")
        self.text_widget.insert("1.0", display_text)
        self.entities = []
        self._refresh_entity_panel()
        self._set_restored_banner(restored)

        # Le texte affiché est déjà anonymisé (ou restauré) : la détection
        # reste disponible pour un nouveau passage, et export/enregistrement
        # ont un sens immédiatement (contrairement à un import tout frais).
        self.btn_detect.configure(state="normal")
        self.btn_anonymize.configure(state="disabled")
        self.btn_export.configure(state="normal")
        self.btn_save_library.configure(state="normal")

        # Recharge aussi la table de correspondance dans le gazetteer, pour
        # que les mêmes pseudonymes soient réutilisés si vous continuez à
        # travailler sur ce document (ex: nouvelle passe d'anonymisation).
        for original, _pseudo in saved.mapping:
            if original not in self.gazetteer.entries:
                self.gazetteer.add(original)

        if restored:
            self.status.set(f"⚠️ Version RESTAURÉE (noms d'origine) : {folder.name} — ne pas diffuser")
        else:
            self.status.set(f"Document rouvert depuis la bibliothèque : {folder.name}")

    def on_add_gazetteer(self):
        top = tk.Toplevel(self)
        top.title("Ajouter un nom à repérer")
        top.geometry("560x180")

        ttk.Label(top, text="Nom ou texte exact à repérer :").pack(anchor="w", padx=8, pady=(10, 0))
        # Largeur augmentée (40 -> 90) : un nom composé, une adresse
        # complète ou une raison sociale longue doivent rester lisibles
        # en entier pendant la saisie plutôt que défiler dans un champ
        # trop étroit. Aucune limite de longueur n'est appliquée par
        # ailleurs : ttk.Entry n'en impose pas, "width" ne fixe que la
        # largeur d'affichage, pas le nombre de caractères saisissables.
        entry = ttk.Entry(top, width=90)
        entry.pack(padx=8, pady=6, fill="x")
        entry.focus()

        ttk.Label(top, text="Type d'entité (choisir ou saisir un nouveau type) :").pack(anchor="w", padx=8)
        label_var = tk.StringVar(value="SOCIETE")
        label_choice = ttk.Combobox(
            top, textvariable=label_var, state="normal",  # "normal" = éditable, pas seulement une liste fermée
            values=list(LABEL_COLORS.keys()),
        )
        label_choice.pack(padx=8, pady=(0, 6))

        def confirm():
            value = entry.get().strip()
            label = label_var.get().strip().upper().replace(" ", "_")
            if value and label:
                self._ensure_label_registered(label)
                self.gazetteer.add(value, label)
                self.status.set(f"'{value}' ajouté ({label}).")
            top.destroy()

        ttk.Button(top, text="Ajouter", command=confirm).pack(pady=4)
        top.bind("<Return>", lambda _e: confirm())

    def _ensure_label_registered(self, label: str) -> None:
        """Si l'utilisateur saisit un type d'entité qui n'existe pas encore
        (ex: 'NUMERO_CIN'), on lui attribue une couleur de la palette et on
        configure le tag de surlignage correspondant, à la volée."""
        if label in LABEL_COLORS:
            return
        used = set(LABEL_COLORS.values())
        color = next((c for c in CUSTOM_LABEL_PALETTE if c not in used), CUSTOM_LABEL_PALETTE[0])
        LABEL_COLORS[label] = color
        self.text_widget.tag_configure(label, background=color)

    # ------------------------------------------------------------------
    # Aide à l'affichage
    # ------------------------------------------------------------------
    def _highlight_entities(self, text: str):
        for label in LABEL_COLORS:
            self.text_widget.tag_remove(label, "1.0", "end")
        for e in self.entities:
            start_index = self._char_index_to_tk(text, e.start)
            end_index = self._char_index_to_tk(text, e.end)
            self.text_widget.tag_add(e.label, start_index, end_index)

    @staticmethod
    def _char_index_to_tk(text: str, char_offset: int) -> str:
        """Convertit un offset de caractère (str Python) en index Tkinter
        'ligne.colonne', car Tk indexe le texte par ligne."""
        line = text.count("\n", 0, char_offset) + 1
        last_nl = text.rfind("\n", 0, char_offset)
        col = char_offset if last_nl == -1 else char_offset - last_nl - 1
        return f"{line}.{col}"

    def _refresh_entity_panel(self):
        for child in self.entity_list_frame.winfo_children():
            child.destroy()
        self.entity_vars = {}

        if not self.entities:
            ttk.Label(self.entity_list_frame, text="(aucune)").pack(anchor="w", pady=4)
            return

        canvas = tk.Canvas(self.entity_list_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.entity_list_frame, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Molette/trackpad en plus de la barre glissable : la barre seule
        # est peu pratique au trackpad (Mac notamment). <MouseWheel> couvre
        # Windows et Mac (delta déjà à la bonne échelle sur Mac contrairement
        # à Windows, d'où le double comportement ci-dessous) ; <Button-4>/
        # <Button-5> couvrent X11/Linux, qui n'envoie pas <MouseWheel>.
        def _on_mousewheel(event):
            if event.num == 4:
                canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                canvas.yview_scroll(1, "units")
            else:
                step = -1 if event.delta > 0 else 1
                if abs(event.delta) >= 100:  # Windows : multiples de 120
                    step = -1 * (event.delta // 120)
                canvas.yview_scroll(int(step), "units")

        def _bind_wheel(_e=None):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)
            canvas.bind_all("<Button-4>", _on_mousewheel)
            canvas.bind_all("<Button-5>", _on_mousewheel)

        def _unbind_wheel(_e=None):
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")

        canvas.bind("<Enter>", _bind_wheel)
        canvas.bind("<Leave>", _unbind_wheel)

        for i, e in enumerate(self.entities):
            var = tk.BooleanVar(value=True)
            self.entity_vars[i] = var
            row = ttk.Frame(inner)
            row.pack(fill="x", pady=1)
            ttk.Checkbutton(row, variable=var).pack(side="left")
            swatch = tk.Label(row, text="  ", background=LABEL_COLORS.get(e.label, "#ccc"))
            swatch.pack(side="left", padx=(0, 4))
            label_text = f"[{e.label}] {e.text[:30]}"
            ttk.Label(row, text=label_text).pack(side="left")


if __name__ == "__main__":
    app = AnonymiserApp()
    app.mainloop()
