// Anonymiseur — version web de test. Toute la logique tourne dans le
// navigateur (OCR via Tesseract.js + modèle personnalisé, lecture PDF via
// pdf.js, lecture .docx via mammoth.js, anonymisation via anonymizer.js).
// Aucune donnée n'est envoyée à un serveur : la "bibliothèque" (onglet ②)
// est stockée dans localStorage, propre à ce navigateur.

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

  const LIBRARY_KEY = "anonymiseur_library_v1";

  let gazetteer = new AnonymizerLib.Gazetteer();
  let anonymizer = new AnonymizerLib.Anonymizer(gazetteer);
  let currentEntities = []; // [{...entity, checked: bool}]
  let ocrWorker = null;

  const $ = (id) => document.getElementById(id);
  const textArea = $("textArea");
  const entityList = $("entityList");
  const ocrProgress = $("ocrProgress");

  // ------------------------------------------------------------------
  // Onglets
  // ------------------------------------------------------------------
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      $(btn.dataset.tab).classList.add("active");
      if (btn.dataset.tab === "tab-restore") refreshLibraryTable();
    });
  });

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
  // Étape 1 — Importer
  // ------------------------------------------------------------------
  $("fileInput").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const ext = file.name.split(".").pop().toLowerCase();
    textArea.value = "";
    resetWorkflowAfterNewDocument();
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
      commitWorkingText();
    } catch (err) {
      console.error(err);
      alert("Erreur pendant l'import : " + err.message + "\n(voir la console du navigateur, F12, pour le détail complet)");
      ocrProgress.textContent = "";
    }
    e.target.value = ""; // permet de réimporter le même fichier ensuite
  });

  // ------------------------------------------------------------------
  // Coller / saisir directement
  // ------------------------------------------------------------------
  $("btnUsePasted").addEventListener("click", () => {
    if (!textArea.value.trim()) {
      alert("Le champ est vide — collez ou saisissez du texte avant d'enregistrer.");
      return;
    }
    resetWorkflowAfterNewDocument();
    commitWorkingText();
  });

  function resetWorkflowAfterNewDocument() {
    anonymizer = new AnonymizerLib.Anonymizer(gazetteer);
    currentEntities = [];
    renderEntities();
    setStepState({ detect: false, anonymize: false, exportBtn: false, save: false });
  }

  function commitWorkingText() {
    setStepState({ detect: true, anonymize: false, exportBtn: false, save: false });
  }

  function setStepState({ detect, anonymize, exportBtn, save }) {
    $("btnDetect").disabled = !detect;
    $("btnAnonymize").disabled = !anonymize;
    $("btnExport").disabled = !exportBtn;
    $("btnSaveLibrary").disabled = !save;
  }

  // ------------------------------------------------------------------
  // Étape 2 — Détecter les entités
  // ------------------------------------------------------------------
  function runDetection() {
    const text = textArea.value;
    if (!text.trim()) return;
    const entities = anonymizer.detect(text);
    currentEntities = entities.map((e) => ({ ...e, checked: true }));
    renderEntities();
    setStepState({ detect: true, anonymize: currentEntities.length > 0, exportBtn: false, save: false });
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
      html += `<mark class="${e.label}" style="${colorForLabel(e.label) ? `background:${colorForLabel(e.label)}` : ""}">${escapeHtml(text.slice(e.start, e.end))}</mark>`;
      cursor = e.end;
    }
    html += escapeHtml(text.slice(cursor));
    // Le textarea ajoute une ligne vide finale au rendu si le texte se
    // termine par \n — un espace insécable en plus évite que le calque de
    // fond soit légèrement plus court et désynchronise le défilement.
    textBackdrop.innerHTML = html + "\u00A0";
  }

  textArea.addEventListener("scroll", () => {
    textBackdrop.scrollTop = textArea.scrollTop;
    textBackdrop.scrollLeft = textArea.scrollLeft;
  });

  // Si l'utilisateur retouche le texte à la main après une détection, le
  // surlignage ne correspondrait plus aux bonnes positions (décalage) —
  // on l'efface plutôt que d'afficher des couleurs au mauvais endroit ;
  // une nouvelle détection le reconstruira correctement.
  textArea.addEventListener("input", () => {
    if (currentEntities.length) {
      currentEntities = [];
      renderEntities();
    }
  });

  function renderEntities() {
    entityList.innerHTML = "";
    if (!currentEntities.length) {
      entityList.innerHTML = '<p class="muted">(aucune)</p>';
      renderHighlight();
      return;
    }
    currentEntities.forEach((e, idx) => {
      const row = document.createElement("div");
      row.className = "entity-row";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = e.checked;
      cb.addEventListener("change", () => { currentEntities[idx].checked = cb.checked; });
      const swatch = document.createElement("span");
      swatch.className = "swatch";
      swatch.style.background = colorForLabel(e.label) || `var(--entity-${e.label.toLowerCase()}, #ccc)`;
      const label = document.createElement("span");
      label.innerHTML = `<span class="lbl">[${escapeHtml(displayNameForLabel(e.label))}]</span> ${escapeHtml(e.text)}`;
      row.appendChild(cb);
      row.appendChild(swatch);
      row.appendChild(label);
      entityList.appendChild(row);
    });
    renderHighlight();
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // ------------------------------------------------------------------
  // Étape 3 — Anonymiser
  // ------------------------------------------------------------------
  let lastAnonymizedText = "";
  let lastOriginalText = "";

  $("btnAnonymize").addEventListener("click", () => {
    const text = textArea.value;
    const checked = currentEntities.filter((e) => e.checked);
    lastOriginalText = text;
    const result = anonymizer.anonymize(text, checked);
    lastAnonymizedText = result;
    textArea.value = result;
    currentEntities = [];
    renderEntities();
    setStepState({ detect: true, anonymize: false, exportBtn: true, save: true });
  });

  // ------------------------------------------------------------------
  // Étape 4 — Télécharger
  // ------------------------------------------------------------------
  $("btnExport").addEventListener("click", () => {
    downloadTextFile(textArea.value, "document_anonymise.txt");
  });

  function downloadTextFile(content, filename) {
    const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
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
  // Étape 5 — Enregistrer dans la bibliothèque (localStorage)
  // ------------------------------------------------------------------
  $("btnSaveLibrary").addEventListener("click", () => {
    const name = prompt("Nom pour retrouver ce document dans la bibliothèque :", "Document " + new Date().toLocaleString("fr-FR"));
    if (!name) return;
    const lib = loadLibrary();
    lib.push({
      id: Date.now().toString(36),
      name,
      date: new Date().toISOString(),
      originalText: lastOriginalText,
      anonymizedText: lastAnonymizedText || textArea.value,
      mapping: anonymizer.mappingAsPairs(),
    });
    saveLibrary(lib);
    alert("Document enregistré dans la bibliothèque de ce navigateur.");
  });

  function loadLibrary() {
    try {
      return JSON.parse(localStorage.getItem(LIBRARY_KEY) || "[]");
    } catch (e) {
      return [];
    }
  }
  function saveLibrary(lib) {
    localStorage.setItem(LIBRARY_KEY, JSON.stringify(lib));
  }

  // ------------------------------------------------------------------
  // Onglet ② — Retrouver un document original
  // ------------------------------------------------------------------
  let selectedLibraryId = null;

  function refreshLibraryTable() {
    const lib = loadLibrary();
    const tbody = $("libraryTableBody");
    tbody.innerHTML = "";
    selectedLibraryId = null;
    $("btnLibRestore").disabled = true;
    $("btnLibRestoreExternal").disabled = true;
    if (!lib.length) {
      $("libraryStatus").textContent = "Aucun document enregistré pour l'instant.";
      return;
    }
    $("libraryStatus").textContent = `${lib.length} document(s).`;
    lib.slice().reverse().forEach((doc) => {
      const tr = document.createElement("tr");
      tr.dataset.id = doc.id;
      const dateDisplay = new Date(doc.date).toLocaleString("fr-FR");
      tr.innerHTML = `<td>${escapeHtml(doc.name)}</td><td>${dateDisplay}</td>`;
      tr.addEventListener("click", () => {
        document.querySelectorAll(".lib-table tbody tr").forEach((r) => r.classList.remove("selected"));
        tr.classList.add("selected");
        selectedLibraryId = doc.id;
        $("btnLibRestore").disabled = false;
        $("btnLibRestoreExternal").disabled = false;
      });
      tbody.appendChild(tr);
    });
  }

  $("btnLibRefresh").addEventListener("click", refreshLibraryTable);

  $("btnLibRestore").addEventListener("click", () => {
    const lib = loadLibrary();
    const doc = lib.find((d) => d.id === selectedLibraryId);
    if (!doc) return;
    if (!confirm(
      "Ceci va afficher le document avec les VRAIES données personnelles rétablies " +
      "à la place des pseudonymes.\n\nLe résultat n'est plus anonymisé — à ne jamais " +
      "diffuser tel quel.\n\nContinuer ?"
    )) return;
    textArea.value = doc.originalText;
    document.querySelector('[data-tab="tab-anonymize"]').click();
    resetWorkflowAfterNewDocument();
    commitWorkingText();
    setStepState({ detect: true, anonymize: false, exportBtn: true, save: false });
    alert("⚠️ Version restaurée affichée dans l'onglet ① — ne pas diffuser tel quel.");
  });

  $("btnLibRestoreExternal").addEventListener("click", () => {
    const lib = loadLibrary();
    const doc = lib.find((d) => d.id === selectedLibraryId);
    if (!doc) return;
    if (!doc.mapping || !doc.mapping.length) {
      alert("Aucune table de correspondance trouvée pour ce document.");
      return;
    }
    if (!confirm(
      "Choisissez un fichier .txt retravaillé ailleurs (résumé, extrait…) contenant " +
      `encore des pseudonymes du document « ${doc.name} » (ex : [PERSONNE_1]).\n\n` +
      "Chaque pseudonyme reconnu sera remplacé par la vraie donnée correspondante. " +
      "Le résultat ne sera plus anonymisé — à ne jamais diffuser tel quel.\n\nContinuer ?"
    )) return;
    $("restoreFileInput").click();
    $("restoreFileInput").onchange = async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const modifiedText = await readTxt(file);
      const { text: restored, count } = AnonymizerLib.restoreOriginalNames(modifiedText, doc.mapping);
      textArea.value = restored;
      document.querySelector('[data-tab="tab-anonymize"]').click();
      resetWorkflowAfterNewDocument();
      commitWorkingText();
      setStepState({ detect: true, anonymize: false, exportBtn: true, save: false });
      alert(`⚠️ Noms restaurés dans "${file.name}" — ${count} correspondance(s) appliquée(s) sur ${doc.mapping.length} possibles. Ne pas diffuser.`);
      e.target.value = "";
    };
  });

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
      category = newName.toUpperCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "")
        .replace(/[^A-Z0-9]+/g, "_").replace(/^_+|_+$/g, "");
      if (!category) category = "PERSONNALISE";
      LABEL_NAMES[category] = newName;
    }
    $("gazetteerModal").classList.add("hidden");
    if (!val) return;
    gazetteer.add(val, category);
    // Sans ceci, le nom ajouté n'apparaissait nulle part tant qu'on ne
    // recliquait pas manuellement sur "Détecter les entités" — on relance
    // donc la détection immédiatement, comme pour les autres entités.
    if (textArea.value.trim()) {
      runDetection();
    } else {
      alert(`« ${val} » ajouté (catégorie : ${LABEL_NAMES[category] || category}). Il sera pris en compte dès qu'un document sera chargé et que vous cliquerez sur « Détecter les entités ».`);
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
    pdfjsLib.GlobalWorkerOptions.workerSrc =
      "https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.worker.min.js";
  }

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
