// Anonymiseur — version web de test. Toute la logique tourne dans le
// navigateur (OCR via Tesseract.js + modèle personnalisé, lecture PDF via
// pdf.js, lecture .docx via mammoth.js, anonymisation via anonymizer.js).
// Aucune donnée n'est envoyée à un serveur.
//
// Flux en une seule page, sans onglet : mode "Anonymiser" -> l'utilisateur
// copie le texte anonymisé (presse-papiers) et le colle dans une IA
// externe -> mode "Désanonymiser" -> l'utilisateur colle le résultat de
// l'IA et récupère les vraies données, grâce à la table de correspondance
// gardée en mémoire pour le document en cours (pas de bibliothèque
// persistante : tout se passe dans la même session).

(function () {
  "use strict";

  const LABEL_NAMES = {
    PERSONNE: "PERSONNE", ADRESSE: "ADRESSE", DATE: "DATE",
    MONTANT: "MONTANT", NUMERO: "NUMERO", AVOCAT: "AVOCAT/CABINET",
    SOCIETE: "SOCIETE", TELEPHONE: "TELEPHONE", VILLE: "VILLE",
    MATRICULE: "MATRICULE", PROPRIETE: "PROPRIETE",
  };
  const BUILTIN_LABELS = new Set(Object.keys(LABEL_NAMES));

  // Catégories personnalisées créées par l'utilisateur : chacune reçoit
  // une couleur prise dans cette palette (jamais deux fois la même tant
  // qu'il en reste), au lieu de devoir éditer le CSS pour chaque nouvelle
  // catégorie. Choisies pour rester lisibles avec du texte noir par-dessus
  // (mêmes tons pastel que les catégories prédéfinies).
  const CUSTOM_PALETTE = [
    "#ffd6e0", "#c8e6c9", "#b3e5fc", "#fff9c4", "#d1c4e9",
    "#ffccbc", "#b2dfdb", "#f0f4c3", "#e1bee7", "#c5e1a5",
    "#ffe0b2", "#b3e0ff",
  ];
  const customLabelColors = new Map(); // label -> couleur
  let customPaletteIndex = 0;

  function colorForLabel(label) {
    if (BUILTIN_LABELS.has(label)) return null; // utilise la variable CSS existante
    if (!customLabelColors.has(label)) {
      customLabelColors.set(label, CUSTOM_PALETTE[customPaletteIndex % CUSTOM_PALETTE.length]);
      customPaletteIndex++;
    }
    return customLabelColors.get(label);
  }

  function displayNameForLabel(label) {
    return LABEL_NAMES[label] || label;
  }

  let gazetteer = new AnonymizerLib.Gazetteer();
  let anonymizer = new AnonymizerLib.Anonymizer(gazetteer);
  let currentEntities = []; // [{...entity, checked: bool}]
  let ocrWorker = null;

  const $ = (id) => document.getElementById(id);
  const textArea = $("textArea");
  const entityList = $("entityList");
  const ocrProgress = $("ocrProgress");

  // ------------------------------------------------------------------
  // Mode de la page : "anonymize" (par défaut) ou "desanonymize" — une
  // seule page, pas d'onglets ; le libellé "Anonymiser"/"Désanonymiser"
  // s'affiche en grand pour indiquer clairement dans quel mode on se
  // trouve.
  // ------------------------------------------------------------------
  let mode = "anonymize";

  function setMode(newMode) {
    mode = newMode;
    const isAnonymize = mode === "anonymize";
    $("modeLabel").textContent = isAnonymize ? "Anonymiser" : "Désanonymiser";
    $("modeLabel").classList.toggle("mode-label-desanonymize", !isAnonymize);
    $("modeHint").textContent = isAnonymize
      ? "Importez un document : les informations personnelles (noms, dates, adresses…) sont repérées automatiquement."
      : "Collez ici le texte renvoyé par votre IA externe, puis cliquez sur « Désanonymiser » pour rétablir les vraies données.";
    $("anonymizeSteps").classList.toggle("hidden", !isAnonymize);
    $("desanonymizeSteps").classList.toggle("hidden", isAnonymize);
    $("entityCol").classList.toggle("hidden", !isAnonymize);
    $("textAreaHint").classList.toggle("hidden", !isAnonymize);
    $("textAreaLabel").textContent = isAnonymize ? "Aperçu du document" : "Texte reçu de l'IA";
    textArea.placeholder = isAnonymize
      ? "Le texte du document apparaîtra ici après import (ou collez/tapez-le directement)…"
      : "Collez ici (Ctrl+V) le texte renvoyé par l'IA…";
  }

  // ------------------------------------------------------------------
  // OCR — chargement paresseux du worker Tesseract.js (une seule fois),
  // avec le modèle personnalisé mlg_archives_v2 combiné à fra.
  // ------------------------------------------------------------------
  async function getWorker() {
    if (ocrWorker) return ocrWorker;
    ocrProgress.textContent = "Chargement du modèle OCR…";
    ocrWorker = await Tesseract.createWorker(["mlg_archives_v2", "fra"], 1, {
      langPath: "tessdata",
      gzip: false,
      // Sans ceci, tesseract.js va chercher son worker et son "coeur" WASM
      // sur un CDN par défaut — on les fait pointer vers les copies
      // locales (vendor/) pour un fonctionnement 100% hors-ligne.
      workerPath: "vendor/tesseract/worker.min.js",
      corePath: "vendor/tesseract/core",
      logger: (m) => {
        if (m.status === "recognizing text") {
          ocrProgress.textContent = `Reconnaissance en cours… ${Math.round(m.progress * 100)}%`;
        } else if (m.status) {
          ocrProgress.textContent = m.status;
        }
      },
    });
    ocrProgress.textContent = "";
    return ocrWorker;
  }

  async function ocrPdf(file) {
    const buf = await file.arrayBuffer();
    const pdf = await pdfjsLib.getDocument({ data: buf }).promise;
    const worker = await getWorker();
    let fullText = "";
    for (let i = 1; i <= pdf.numPages; i++) {
      ocrProgress.textContent = `Page ${i}/${pdf.numPages} — préparation de l'image…`;
      const page = await pdf.getPage(i);
      const viewport = page.getViewport({ scale: 2.5 });
      const canvas = document.createElement("canvas");
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      const ctx = canvas.getContext("2d");
      await page.render({ canvasContext: ctx, viewport }).promise;
      ocrProgress.textContent = `Page ${i}/${pdf.numPages} — OCR…`;
      const { data } = await worker.recognize(canvas);
      fullText += data.text + "\n\n";
    }
    ocrProgress.textContent = "";
    return fullText;
  }

  async function readDocx(file) {
    const buf = await file.arrayBuffer();
    const result = await mammoth.extractRawText({ arrayBuffer: buf });
    return result.value;
  }

  function readTxt(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsText(file, "utf-8");
    });
  }

  // ------------------------------------------------------------------
  // Étape 1 — Importer et détecter les entités
  // ------------------------------------------------------------------
  $("fileInput").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const ext = file.name.split(".").pop().toLowerCase();
    textArea.value = "";
    resetAll();
    try {
      let text;
      if (ext === "pdf") {
        ocrProgress.textContent = "Lecture du PDF…";
        text = await ocrPdf(file);
      } else if (ext === "docx") {
        text = await readDocx(file);
      } else {
        text = await readTxt(file);
      }
      textArea.value = text;
      $("btnDetect").disabled = false;
      // La détection des entités se lance automatiquement dès l'import —
      // pas besoin de cliquer sur un bouton séparé avant de pouvoir
      // anonymiser.
      runDetection();
    } catch (err) {
      console.error(err);
      alert("Erreur pendant l'import : " + err.message + "\n(voir la console du navigateur, F12, pour le détail complet)");
      ocrProgress.textContent = "";
    }
    e.target.value = ""; // permet de réimporter le même fichier ensuite
  });

  // Remet tout à zéro (nouveau document à anonymiser) : ré-affiche le mode
  // "Anonymiser", vide le texte et les entités, désactive tous les
  // boutons qui doivent l'être à ce stade.
  function resetAll() {
    anonymizer = new AnonymizerLib.Anonymizer(gazetteer);
    currentEntities = [];
    textArea.value = "";
    renderEntities();
    setMode("anonymize");
    $("btnDetect").disabled = true;
    $("btnAnonymize").disabled = true;
    $("btnDesanonymize").disabled = true;
    $("btnExport").disabled = true;
    $("btnExportDocx").disabled = true;
  }
  $("btnNewDocument").addEventListener("click", resetAll);

  // ------------------------------------------------------------------
  // Détection des entités — automatique dès qu'un document est importé ;
  // le bouton "Redétecter" permet de relancer manuellement après une
  // modification du texte (import ou texte collé/tapé directement).
  // ------------------------------------------------------------------
  function runDetection() {
    const text = textArea.value;
    if (!text.trim()) return;
    const entities = anonymizer.detect(text);
    currentEntities = entities.map((e) => ({ ...e, checked: true }));
    renderEntities();
    $("btnAnonymize").disabled = currentEntities.length === 0;
  }
  $("btnDetect").addEventListener("click", runDetection);

  const textBackdrop = $("textBackdrop");

  function renderHighlight() {
    const text = textArea.value;
    if (!currentEntities.length) {
      textBackdrop.innerHTML = "";
      return;
    }
    // currentEntities est déjà trié par position croissante et sans
    // chevauchement (résolu côté anonymizer.js) — on peut donc construire
    // le HTML en un seul passage de gauche à droite.
    const sorted = [...currentEntities].sort((a, b) => a.start - b.start);
    let html = "";
    let cursor = 0;
    for (const e of sorted) {
      html += escapeHtml(text.slice(cursor, e.start));
      if (e.checked) {
        html += `<mark class="${e.label}" style="${colorForLabel(e.label) ? `background:${colorForLabel(e.label)}` : ""}">${escapeHtml(text.slice(e.start, e.end))}</mark>`;
      } else {
        // Décochée : affichée en clair, sans surlignage, comme un aperçu
        // immédiat de ce qui resterait visible si on anonymisait maintenant.
        html += escapeHtml(text.slice(e.start, e.end));
      }
      cursor = e.end;
    }
    html += escapeHtml(text.slice(cursor));
    // Le textarea ajoute une ligne vide finale au rendu si le texte se
    // termine par \n — un espace insécable en plus évite que le calque de
    // fond soit légèrement plus court et désynchronise le défilement.
    textBackdrop.innerHTML = html + " ";
  }

  textArea.addEventListener("scroll", () => {
    textBackdrop.scrollTop = textArea.scrollTop;
    textBackdrop.scrollLeft = textArea.scrollLeft;
  });

  // Si l'utilisateur retouche le texte à la main, le surlignage ne
  // correspondrait plus aux bonnes positions (décalage) — on l'efface
  // plutôt que d'afficher des couleurs au mauvais endroit ; une nouvelle
  // détection le reconstruira correctement. On active/désactive aussi les
  // boutons pertinents selon le mode en cours et la présence de texte.
  textArea.addEventListener("input", () => {
    if (mode === "anonymize") {
      if (currentEntities.length) {
        currentEntities = [];
        renderEntities();
      }
      $("btnDetect").disabled = !textArea.value.trim();
      $("btnAnonymize").disabled = true;
    } else {
      $("btnDesanonymize").disabled = !textArea.value.trim();
    }
  });

  function renderEntities() {
    entityList.innerHTML = "";
    if (!currentEntities.length) {
      entityList.innerHTML = '<p class="muted">(aucune)</p>';
      renderHighlight();
      return;
    }
    // Regroupe les occurrences identiques (même texte + même catégorie) :
    // une seule case à cocher, qui s'applique à TOUTES les occurrences de
    // ce texte dans le document — pas seulement à la première trouvée.
    const groups = new Map(); // "label::texte" -> { label, text, indices: [...], checked }
    currentEntities.forEach((e, idx) => {
      const key = `${e.label}::${e.text}`;
      if (!groups.has(key)) {
        groups.set(key, { label: e.label, text: e.text, indices: [], checked: e.checked });
      }
      groups.get(key).indices.push(idx);
    });

    for (const group of groups.values()) {
      const row = document.createElement("div");
      row.className = "entity-row";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = group.checked;
      cb.addEventListener("change", () => {
        // Applique le même état coché/décoché à TOUTES les occurrences
        // de ce groupe (même texte + même catégorie) d'un coup.
        for (const idx of group.indices) currentEntities[idx].checked = cb.checked;
        // Décocher retire immédiatement le surlignage de CHAQUE
        // occurrence dans l'aperçu (elles ne seront pas anonymisées) —
        // recocher les remet toutes.
        renderHighlight();
      });
      const swatch = document.createElement("span");
      swatch.className = "swatch";
      swatch.style.background = colorForLabel(group.label) || `var(--entity-${group.label.toLowerCase()}, #ccc)`;
      const label = document.createElement("span");
      const countBadge = group.indices.length > 1
        ? ` <span class="occ-count">(${group.indices.length}×)</span>`
        : "";
      label.innerHTML = `<span class="lbl">[${escapeHtml(displayNameForLabel(group.label))}]</span> ${escapeHtml(group.text)}${countBadge}`;
      row.appendChild(cb);
      row.appendChild(swatch);
      row.appendChild(label);
      entityList.appendChild(row);
    }
    renderHighlight();
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // ------------------------------------------------------------------
  // Copie dans le presse-papiers, avec repli si l'API Clipboard moderne
  // n'est pas disponible (contexte non sécurisé, permission refusée…).
  // ------------------------------------------------------------------
  async function copyToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      try {
        await navigator.clipboard.writeText(text);
        return true;
      } catch (err) {
        console.error(err);
      }
    }
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return ok;
    } catch (err) {
      console.error(err);
      return false;
    }
  }

  // ------------------------------------------------------------------
  // Étape 2 — Anonymiser et copier : anonymise, copie le résultat dans le
  // presse-papiers, vide le champ (pour signaler que c'est bien copié) et
  // passe en mode "Désanonymiser". La table de correspondance reste en
  // mémoire (dans l'instance Anonymizer) pour l'étape 3.
  // ------------------------------------------------------------------
  $("btnAnonymize").addEventListener("click", async () => {
    const text = textArea.value;
    const checked = currentEntities.filter((e) => e.checked);
    const result = anonymizer.anonymize(text, checked);
    currentEntities = [];
    renderEntities();

    const copied = await copyToClipboard(result);

    textArea.value = "";
    setMode("desanonymize");
    $("btnDesanonymize").disabled = true;
    $("btnExport").disabled = true;
    $("btnExportDocx").disabled = true;

    if (copied) {
      alert(
        "Texte anonymisé copié !\n\nCollez-le dans votre IA externe, récupérez le résultat, " +
        "puis collez-le ici pour le désanonymiser."
      );
    } else {
      // Très rare (permissions du navigateur) : on remet le texte affiché
      // pour que rien ne soit perdu, plutôt que de vider le champ pour
      // rien.
      textArea.value = result;
      alert(
        "Impossible de copier automatiquement dans le presse-papiers — le texte anonymisé " +
        "est affiché ci-dessous : sélectionnez-le et copiez-le manuellement (Ctrl+C)."
      );
    }
  });

  // ------------------------------------------------------------------
  // Étape 3 — Désanonymiser : remet les vraies données à la place des
  // pseudonymes, dans le texte collé depuis l'IA externe.
  // ------------------------------------------------------------------
  $("btnDesanonymize").addEventListener("click", () => {
    const text = textArea.value;
    if (!text.trim()) return;
    const pairs = anonymizer.mappingAsPairs();
    if (!pairs.length) {
      alert("Aucune correspondance à restaurer pour l'instant — anonymisez d'abord un document dans cette session.");
      return;
    }
    const { text: restored, count } = AnonymizerLib.restoreOriginalNames(text, pairs);
    textArea.value = restored;
    $("btnExport").disabled = false;
    $("btnExportDocx").disabled = false;
    alert(
      `⚠️ Noms restaurés — ${count} correspondance(s) appliquée(s) sur ${pairs.length} possibles.\n\n` +
      "Le résultat affiché n'est plus anonymisé — à ne jamais diffuser tel quel."
    );
  });

  function downloadBlobAsFile(content, filename, mimeType) {
    const blob = content instanceof Blob ? content : new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // ------------------------------------------------------------------
  // Télécharger le document final (désanonymisé) : l'utilisateur choisit
  // l'emplacement et peut renommer le fichier directement dans la boîte
  // de dialogue d'enregistrement (File System Access API sur Chrome/
  // Edge) ; repli en téléchargement classique sur les navigateurs qui ne
  // la supportent pas (Firefox, Safari).
  // ------------------------------------------------------------------
  async function saveAsFile(content, suggestedName, mimeType, extension) {
    if (window.showSaveFilePicker) {
      try {
        const handle = await window.showSaveFilePicker({
          suggestedName,
          types: [{ description: "Fichier", accept: { [mimeType]: [extension] } }],
        });
        const writable = await handle.createWritable();
        await writable.write(content);
        await writable.close();
        return;
      } catch (err) {
        if (err && err.name === "AbortError") return; // l'utilisateur a annulé
        console.error(err);
        // Repli sur le téléchargement classique si l'API a échoué pour
        // une autre raison.
      }
    }
    downloadBlobAsFile(content, suggestedName, mimeType);
  }

  $("btnExport").addEventListener("click", async () => {
    await saveAsFile(textArea.value, "document-desanonymise.txt", "text/plain;charset=utf-8", ".txt");
  });

  $("btnExportDocx").addEventListener("click", async () => {
    try {
      const blob = await buildDocx(textArea.value);
      await saveAsFile(
        blob, "document-desanonymise.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"
      );
    } catch (err) {
      console.error(err);
      alert("Erreur pendant la création du .docx : " + err.message + " (voir la console, F12, pour le détail).");
    }
  });

  function escapeXml(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // Construit un .docx minimal mais valide (un paragraphe par ligne du
  // texte) — suffisant pour du texte brut, sans mise en forme à
  // conserver. Pas de bibliothèque dédiée à l'écriture de .docx dans ce
  // projet (mammoth.js, déjà présent, ne sait que LIRE des .docx) : on
  // construit directement le paquet OOXML minimal avec JSZip.
  async function buildDocx(text) {
    const paragraphs = text.split("\n").map((line) => {
      const escaped = escapeXml(line);
      return escaped ? `<w:p><w:r><w:t xml:space="preserve">${escaped}</w:t></w:r></w:p>` : "<w:p/>";
    }).join("");

    const documentXml =
      `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n` +
      `<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">` +
      `<w:body>${paragraphs}<w:sectPr/></w:body></w:document>`;

    const contentTypesXml =
      `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n` +
      `<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">` +
      `<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>` +
      `<Default Extension="xml" ContentType="application/xml"/>` +
      `<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>` +
      `</Types>`;

    const relsXml =
      `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n` +
      `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">` +
      `<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>` +
      `</Relationships>`;

    const zip = new JSZip();
    zip.file("[Content_Types].xml", contentTypesXml);
    zip.folder("_rels").file(".rels", relsXml);
    zip.folder("word").file("document.xml", documentXml);

    return zip.generateAsync({
      type: "blob",
      mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });
  }

  // ------------------------------------------------------------------
  // Ajouter un nom au gazetteer
  // ------------------------------------------------------------------
  $("btnAddGazetteer").addEventListener("click", () => {
    $("gazetteerInput").value = "";
    $("gazetteerCategory").value = "PERSONNE";
    $("gazetteerNewCategory").value = "";
    $("gazetteerNewCategory").style.display = "none";
    $("gazetteerModal").classList.remove("hidden");
    $("gazetteerInput").focus();
  });
  $("gazetteerCategory").addEventListener("change", () => {
    const isNew = $("gazetteerCategory").value === "__new__";
    $("gazetteerNewCategory").style.display = isNew ? "block" : "none";
    if (isNew) $("gazetteerNewCategory").focus();
  });
  $("gazetteerCancel").addEventListener("click", () => $("gazetteerModal").classList.add("hidden"));
  $("gazetteerOk").addEventListener("click", () => {
    const val = $("gazetteerInput").value.trim();
    let category = $("gazetteerCategory").value;
    if (category === "__new__") {
      const newName = $("gazetteerNewCategory").value.trim();
      if (!newName) {
        alert("Donnez un nom à la nouvelle catégorie (ou choisissez-en une existante).");
        return;
      }
      // Normalisé (majuscules, espaces -> underscores) : c'est ce nom
      // interne qui sert à la fois de classe CSS et de préfixe de
      // pseudonyme (ex : [TEMOIN_1]) — le nom tel que tapé reste affiché
      // tel quel dans la colonne des entités.
      category = newName.toUpperCase().normalize("NFD").replace(/[̀-ͯ]/g, "")
        .replace(/[^A-Z0-9]+/g, "_").replace(/^_+|_+$/g, "");
      if (!category) category = "PERSONNALISE";
      LABEL_NAMES[category] = newName;
    }
    $("gazetteerModal").classList.add("hidden");
    if (!val) return;
    gazetteer.add(val, category);
    // Sans ceci, le nom ajouté n'apparaissait nulle part tant qu'on ne
    // recliquait pas manuellement sur "Redétecter" — on relance donc la
    // détection immédiatement, comme pour les autres entités (uniquement
    // pertinent en mode "Anonymiser").
    if (mode === "anonymize" && textArea.value.trim()) {
      runDetection();
    } else {
      alert(`« ${val} » ajouté (catégorie : ${LABEL_NAMES[category] || category}). Il sera pris en compte dès qu'un document sera importé et détecté.`);
    }
  });
  $("gazetteerInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") $("gazetteerOk").click();
  });

  // ------------------------------------------------------------------
  // Initialisation : pdf.js worker + préchargement du modèle OCR dès
  // l'ouverture de la page (plutôt qu'au premier import), pour que le
  // premier PDF importé n'attende pas le téléchargement du modèle.
  // ------------------------------------------------------------------
  if (window.pdfjsLib) {
    pdfjsLib.GlobalWorkerOptions.workerSrc = "vendor/pdfjs/pdf.worker.min.js";
  }

  setMode("anonymize");

  async function preloadOcrModel() {
    try {
      await getWorker();
    } catch (err) {
      console.error("Échec du préchargement du modèle OCR :", err);
      ocrProgress.textContent = "⚠️ Modèle OCR non chargé — réessayez d'importer un PDF, ou voir la console (F12).";
    } finally {
      $("firstLoadBanner").classList.add("hidden");
    }
  }
  window.addEventListener("load", preloadOcrModel);
})();
