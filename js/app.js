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
      // La détection des entités se lance désormais automatiquement dès
      // l'import — l'utilisateur n'a plus besoin de cliquer sur un bouton
      // séparé "Détecter les entités" avant de pouvoir anonymiser.
      runDetection();
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
    // Enregistré directement dans la bibliothèque de ce navigateur (même
    // bibliothèque que l'onglet ② Désanonymiser), sans boîte de dialogue
    // "Enregistrer sous" ni téléchargement — un seul clic, sans interruption.
    const lib = loadLibrary();
    lib.push({
      id: Date.now().toString(36),
      name: "Texte collé " + new Date().toLocaleString("fr-FR"),
      date: new Date().toISOString(),
      originalText: textArea.value,
      anonymizedText: textArea.value,
      mapping: [],
    });
    saveLibrary(lib);
    // Idem que pour un import de fichier : détection automatique, pour
    // enchaîner directement sur "Anonymiser" sans étape supplémentaire.
    runDetection();
    alert("Le texte est bien enregistré, vous pouvez continuer directement à l'étape « Anonymiser ».");
  });

  function resetWorkflowAfterNewDocument() {
    anonymizer = new AnonymizerLib.Anonymizer(gazetteer);
    currentEntities = [];
    currentDocSaved = false;
    renderEntities();
    setStepState({ detect: false, anonymize: false, exportBtn: false });
  }

  function commitWorkingText() {
    setStepState({ detect: true, anonymize: false, exportBtn: false });
  }

  function setStepState({ detect, anonymize, exportBtn }) {
    // "detect" sert désormais uniquement au bouton secondaire "Redétecter"
    // (la détection initiale se déclenche automatiquement après import).
    $("btnDetect").disabled = !detect;
    $("btnAnonymize").disabled = !anonymize;
    $("btnExport").disabled = !exportBtn;
    $("btnExportDocx").disabled = !exportBtn;
  }

  // ------------------------------------------------------------------
  // Détection des entités — automatique dès qu'un document est chargé
  // (import ou texte collé) ; le bouton "Redétecter" permet de relancer
  // manuellement après une modification du texte.
  // ------------------------------------------------------------------
  function runDetection() {
    const text = textArea.value;
    if (!text.trim()) return;
    const entities = anonymizer.detect(text);
    currentEntities = entities.map((e) => ({ ...e, checked: true }));
    renderEntities();
    setStepState({ detect: true, anonymize: currentEntities.length > 0, exportBtn: false });
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
  // Étape 3 — Anonymiser
  // ------------------------------------------------------------------
  let lastAnonymizedText = "";
  let lastOriginalText = "";
  // Nom donné par l'utilisateur au moment d'"Enregistrer et télécharger" —
  // réutilisé comme suggestion pour le nom du fichier téléchargé, avec
  // "-anonymisé" ajouté à la fin.
  let lastSavedDocName = "";
  // Devient vrai dès qu'une entrée a été créée dans la bibliothèque pour le
  // texte anonymisé courant — évite de redemander le nom et de dupliquer
  // l'entrée si l'utilisateur clique successivement sur .docx PUIS .txt
  // (ou l'inverse) pour le même document.
  let currentDocSaved = false;

  $("btnAnonymize").addEventListener("click", () => {
    const text = textArea.value;
    const checked = currentEntities.filter((e) => e.checked);
    lastOriginalText = text;
    const result = anonymizer.anonymize(text, checked);
    lastAnonymizedText = result;
    textArea.value = result;
    currentEntities = [];
    currentDocSaved = false;
    renderEntities();
    // "Enregistrer et télécharger" (étape 3) se débloque directement — le
    // nom ne sera demandé qu'une fois, au premier clic sur l'un des deux
    // boutons (.docx ou .txt).
    setStepState({ detect: true, anonymize: false, exportBtn: true });
  });

  // ------------------------------------------------------------------
  // Étape 3 — Enregistrer (bibliothèque locale) ET télécharger, en une
  // seule action : le nom n'est demandé qu'une fois, quel que soit le
  // bouton (.docx / .txt) cliqué en premier.
  // ------------------------------------------------------------------
  async function ensureSavedToLibrary() {
    if (currentDocSaved) return true;
    const name = prompt(
      "Nom du document, pour le retrouver facilement dans l'onglet ② Désanonymiser :",
      "Document " + new Date().toLocaleString("fr-FR")
    );
    if (!name) return false;
    lastSavedDocName = name;
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
    currentDocSaved = true;
    return true;
  }

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

  function downloadTextFile(content, filename) {
    downloadBlobAsFile(content, filename, "text/plain;charset=utf-8");
  }

  // ------------------------------------------------------------------
  // Étape 5 — Télécharger : l'utilisateur choisit l'emplacement, avec un
  // nom suggéré basé sur celui donné à l'étape 4 ("<nom>-anonymisé.txt" ou
  // ".docx"). Repose sur la File System Access API (Chrome/Edge) pour un
  // vrai choix d'emplacement ; sur les navigateurs qui ne la supportent
  // pas (Firefox, Safari), on retombe sur un téléchargement classique
  // avec le même nom suggéré, dans le dossier de téléchargement par défaut.
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
    if (!(await ensureSavedToLibrary())) return;
    const base = (lastSavedDocName || "document").trim();
    await saveAsFile(textArea.value, `${base}-anonymisé.txt`, "text/plain;charset=utf-8", ".txt");
  });

  $("btnExportDocx").addEventListener("click", async () => {
    if (!(await ensureSavedToLibrary())) return;
    const base = (lastSavedDocName || "document").trim();
    try {
      const blob = await buildDocx(textArea.value);
      await saveAsFile(
        blob, `${base}-anonymisé.docx`,
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
  // Armé par le OK de la boîte "Désanonymiser un fichier traité par IA" :
  // le PROCHAIN clic sur une ligne de la liste ci-dessous ouvre alors
  // directement le sélecteur de fichier pour ce document, sans étape
  // intermédiaire.
  let awaitingRestoreFileSelection = false;

  function refreshLibraryTable() {
    const lib = loadLibrary();
    const tbody = $("libraryTableBody");
    tbody.innerHTML = "";
    selectedLibraryId = null;
    $("btnLibRestore").disabled = true;
    // btnLibRestoreExternal reste volontairement toujours actif : il
    // affiche d'abord une explication (boîte de dialogue), puis attend
    // le prochain clic sur une ligne de cette liste pour ouvrir le
    // sélecteur de fichier — voir awaitingRestoreFileSelection plus bas.
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
        if (awaitingRestoreFileSelection) {
          awaitingRestoreFileSelection = false;
          openExternalRestorePicker(doc);
        }
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
    lastOriginalText = doc.originalText;
    lastAnonymizedText = doc.originalText;
    lastSavedDocName = doc.name + " (restauré)";
    // Un document restauré (vraies données) ne doit pas être réenregistré
    // dans la bibliothèque des documents anonymisés — seul le
    // téléchargement direct est proposé ici.
    currentDocSaved = true;
    setStepState({ detect: true, anonymize: false, exportBtn: true });
    alert("⚠️ Version restaurée affichée dans l'onglet ① — ne pas diffuser tel quel.");
  });

  $("btnLibRestoreExternal").addEventListener("click", () => {
    // Affiche une explication dans une boîte de dialogue "maison" (pas
    // une fenêtre système bloquante, pour ne pas risquer de perdre le
    // geste utilisateur nécessaire à l'ouverture du sélecteur de fichier
    // plus tard). Un seul bouton OK : ça arme l'attente d'un choix dans
    // la liste ci-dessous (étape 1) — voir awaitingRestoreFileSelection.
    $("restoreExternalModal").classList.remove("hidden");
  });

  $("restoreExternalOk").addEventListener("click", () => {
    $("restoreExternalModal").classList.add("hidden");
    awaitingRestoreFileSelection = true;
  });

  // Une fois armée par le OK ci-dessus, le PROCHAIN clic sur une ligne de
  // la liste (étape 1, géré dans refreshLibraryTable) ouvre directement
  // le sélecteur de fichier pour ce document — voir openExternalRestorePicker.
  async function openExternalRestorePicker(doc) {
    if (!doc.mapping || !doc.mapping.length) {
      alert("Aucune table de correspondance trouvée pour ce document.");
      return;
    }
    $("restoreFileInput").click();
    $("restoreFileInput").onchange = async (e) => {
      const file = e.target.files[0];
      if (!file) return;

      let modifiedText;
      try {
        modifiedText = file.name.toLowerCase().endsWith(".docx")
          ? await readDocx(file)
          : await readTxt(file);
      } catch (err) {
        console.error(err);
        alert("Erreur de lecture du fichier : " + err.message);
        e.target.value = "";
        return;
      }
      const { text: restored, count } = AnonymizerLib.restoreOriginalNames(modifiedText, doc.mapping);
      textArea.value = restored;
      document.querySelector('[data-tab="tab-anonymize"]').click();
      resetWorkflowAfterNewDocument();
      commitWorkingText();
      lastOriginalText = restored;
      lastAnonymizedText = restored;
      lastSavedDocName = doc.name + " (restauré)";
      // Idem : pas de réenregistrement dans la bibliothèque pour un
      // document avec les vraies données restaurées.
      currentDocSaved = true;
      setStepState({ detect: true, anonymize: false, exportBtn: true });
      alert(
        `⚠️ Noms restaurés dans "${file.name}" — ${count} correspondance(s) appliquée(s) sur ` +
        `${doc.mapping.length} possibles.\n\nLe résultat affiché n'est plus anonymisé — à ne jamais diffuser tel quel.`
      );
      e.target.value = "";
    };
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
    pdfjsLib.GlobalWorkerOptions.workerSrc = "vendor/pdfjs/pdf.worker.min.js";
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
