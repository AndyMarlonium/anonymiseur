// -*- coding: utf-8 -*-
// Moteur d'anonymisation pour décisions de justice (Madagascar / francophone).
// Portage JavaScript fidèle de anonymizer.py (version bureau), pour une
// démonstration/test entièrement dans le navigateur, sans serveur.
//
// Approche volontairement "règles + liste" plutôt que NER statistique :
// voir anonymizer.py pour la justification complète. Toute correction
// faite ici doit normalement être reportée dans anonymizer.py (et
// inversement) pour que les deux versions restent alignées.

(function (global) {
  "use strict";

  // Classes de caractères françaises correctes (voir anonymizer.py pour
  // la mise en garde sur le piège classique [A-ZÀ-Ÿ]).
  const UPPER = "A-ZÀÂÄÇÉÈÊËÎÏÔÖÙÛÜŸÆŒ";
  const LOWER = "a-zàâäçéèêëîïôöùûüÿæœ";
  const WORD = UPPER + LOWER;

  function escapeRegex(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  // Mots en MAJUSCULES à ne jamais confondre avec un nom propre malgache.
  const EXCLUDE_ALLCAPS = new Set([
    "ANTANANARIVO", "ANTSIRABE", "TOAMASINA", "MAHAJANGA", "TOLIARA",
    "FIANARANTSOA", "ANTSIRANANA", "ANOSY", "ANALAMANGA", "MADAGASCAR",
    "ARIARY", "GREFFE", "CONSEIL", "ETAT", "ÉTAT", "COUR", "SUPREME",
    "SUPRÊME", "BARREAU", "MALAGASY", "REPOBLIKA", "REPOBLIKAN",
    "CHAMBRE", "SERVICES", "PUBLICS", "PUBLIQUE", "AUDIENCE",
    "SARL", "SAU", "SASU", "EURL",
    "PRESIDENT", "PRÉSIDENT", "TRIBUNAL", "DROIT", "MINISTERE",
    "MINISTÈRE", "MINISTRE", "REPUBLIQUE", "RÉPUBLIQUE", "ARTICLE",
    "LOI", "DECRET", "DÉCRET", "ORDONNANCE", "CODE", "PENAL", "PÉNAL",
    "CIVIL", "COMMERCIAL", "ADMINISTRATIF", "FRANCAIS", "FRANÇAIS",
    "JUGEMENT", "ARRET", "ARRÊT", "DECISION", "DÉCISION", "REQUERANT",
    "REQUÉRANT", "REQUERANTE", "REQUÉRANTE", "DEFENDEUR", "DÉFENDEUR",
    "DEFENDERESSE", "DÉFENDERESSE", "PARTIE", "PARTIES", "AVOCAT",
    "FANJAKANA", "FITSARANA", "FILANKEVI", "FILANKEVIM",
  ]);

  // Équivalent Casse-Titre, plus connecteurs de phrase (voir anonymizer.py).
  const STOPWORDS_TITLECASE = new Set([
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
    "Ny", "Sy", "Fa", "Dia", "Ka", "Na", "Satria", "Raha", "Rehefa",
    "Reheza", "Nefa", "Ary", "Toa", "Heno", "Hita", "Araka", "Noho",
    "Mikasika", "Ireo", "Manamarika", "Tsindrian", "Andriamatoa",
    "Ramatoa", "Atoa", "Rtoa", "Amin", "Tamin", "Momba", "Mahakasika",
    "Reçu", "Gratis", "Appel", "Sociale", "Orinasa", "Ministry",
  ]);

  // Villes et grandes agglomérations malgaches, pour la règle VILLE.
  const CITY_NAMES = [
    "Antananarivo", "Antsirabe", "Toamasina", "Mahajanga", "Toliara",
    "Fianarantsoa", "Antsiranana", "Nosy Be", "Antalaha", "Sambava",
    "Manakara", "Morondava", "Ambatondrazaka", "Ambositra", "Farafangana",
    "Maroantsetra", "Mananjary", "Moramanga", "Ihosy", "Vohémar",
    "Vohemar", "Ambovombe", "Betroka", "Manjakandriana", "Ambalavao",
    "Miandrivazo", "Tsiroanomandidy", "Maevatanana", "Ambanja",
    "Marovoay", "Bealanana", "Mandritsara", "Ambatolampy", "Antsohihy",
    "Fenoarivo", "Mahanoro", "Vangaindrano", "Beroroha", "Ikongo",
  ];

  function cityPattern() {
    const names = Array.from(new Set(CITY_NAMES)).sort((a, b) => b.length - a.length);
    const alternatives = [];
    for (const name of names) {
      alternatives.push(escapeRegex(name.toUpperCase()));
      alternatives.push(escapeRegex(name));
    }
    return String.raw`\b(?<val>${alternatives.join("|")})\b`;
  }

  // Alternance des mots à exclure, pour le lookahead négatif du pattern
  // ALLCAPS malgache ci-dessous (mêmes mots que EXCLUDE_ALLCAPS, sans
  // caractère spécial regex à échapper : ce sont des mots simples).
  function excludeAllcapsAlternation() {
    return Array.from(EXCLUDE_ALLCAPS).sort((a, b) => b.length - a.length).join("|");
  }

  // ---------------------------------------------------------------------
  // Règles regex (chaque motif contient un groupe nommé (?<val>...) : la
  // portion réellement anonymisée). Traduction terme à terme de
  // anonymizer.py — voir ce fichier pour les commentaires détaillés sur
  // chaque règle.
  // ---------------------------------------------------------------------
  const ENTITY_PATTERNS = [
    ["PERSONNE", String.raw`\b(?:M\.|Mme|Mlle)\s+(?<val>[${UPPER}][${UPPER}'\-]+(?:\s+[${UPPER}][${LOWER}'\-]+)*)`],

    ["SOCIETE", String.raw`\b(?:[Ll]a[ \t]+)?[Ss]ociété[ \t]+(?<val>[${UPPER}][${WORD}'’\-]*(?:[ \t]+(?:(?:de|du|des|la|le|les|d['’]|l['’])[ \t]+)?[${UPPER}][${WORD}'’\-]*)*)`],

    ["AVOCAT", String.raw`\b(?:Cabinet[ \t]+d['’]Avocats?(?:[ \t]+Associés)?(?:[ \t]+au[ \t]+Barreau[ \t]+de[ \t]+\w+)?[ \t]*,?[ \t]*)(?<val>[${UPPER}][${WORD}'’\-]*(?:[ \t]+(?:(?:et|de|du|des|la|le|les|d['’]|l['’])[ \t]+)?[${UPPER}][${WORD}'’\-]*)*)`],

    ["AVOCAT", String.raw`\bMaître[ \t]+(?<val>[${UPPER}][${WORD}'’\-]*(?:[ \t]+[${UPPER}][${WORD}'’\-]*){0,3})`],
    ["AVOCAT", String.raw`\b[Cc]onseil[ \t]+de[ \t]+(?<val>[${UPPER}][${WORD}'’\-]*(?:[ \t]+[${UPPER}][${WORD}'’\-]*){0,4})`],
    ["AVOCAT", String.raw`\b[Cc]abinet[ \t]+(?!d['’]Avocats)(?<val>[${UPPER}][${WORD}'’\-]*(?:[ \t]+[${UPPER}][${WORD}'’\-]*){0,4})`],

    ["PERSONNE", String.raw`\b(?:[Ll]e[ \t]+requérant|[Ll]a[ \t]+requérante)[ \t,]*(?:M\.|Mme|Mlle)?[ \t]*(?<val>[${UPPER}][${WORD}'’\-]*(?:[ \t]+[${UPPER}][${WORD}'’\-]*){0,3})`],

    ["DATE", String.raw`\bn[ée]e?[ \t]+le[ \t]+(?<val>\d{1,2}[ \t]+(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)[ \t]+\d{4}|\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})\b`],
    ["DATE", String.raw`\bteraka[ \t]+tamin['’]ny[ \t]+(?<val>\d{1,2}[ \t]+(?:janoary|febroary|martsa|aprily|mey|jona|jolay|aogositra|septambra|oktobra|novambra|desambra)[ \t]+\d{4})\b`],

    ["ADRESSE", String.raw`\b(?:au|à)[ \t]+(?<val>\d{1,4}[ \t]+(?:rue|avenue|lot|boulevard|BP)[ \t]+[${WORD}\d'’\- ]{2,60}?)(?=[,;.\n])`],
    ["ADRESSE", String.raw`\bdemeurant[ \t]+(?:à|au)[ \t]+(?<val>[${WORD}\d][${WORD}\d'’,\- ]{2,80}?)(?=[,;.\n])`],
    ["ADRESSE", String.raw`\bà[ \t]+l['’]adresse(?:[ \t]+suivante)?[ \t]*:?[ \t]*(?<val>[${WORD}\d][${WORD}\d'’,\- ]{2,80}?)(?=[,;.\n])`],
    ["ADRESSE", String.raw`\bsise?[ \t]+(?:à|au)[ \t]+(?<val>[${WORD}\d][${WORD}\d'’,\- ]{2,80}?)(?=[,;.\n])`],
    ["ADRESSE", String.raw`\bmipetraka[ \t]+ao[ \t]+(?<val>[${WORD}\d][${WORD}\d'’,\- ]{2,80}?)(?=[,;.\n])`],

    ["MATRICULE", String.raw`\bIM[ \t]*n?°?[ \t]*(?<val>\d{3,10})\b`],

    ["TELEPHONE", String.raw`\b(?<val>0[23]\d(?:[ .\-]?\d){7})\b`],

    ["NUMERO", String.raw`\bn°\s?(?<val>[\w/\-]+)`],

    ["MONTANT", String.raw`(?<val>\d[\d\s]{2,}\d)\s*Ariary`],

    ["DATE", String.raw`(?<val>\b\d{1,2}\s+(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+\d{4}\b)`],

    ["DATE", String.raw`\btamin['’]ny[ \t]+(?<val>\d{1,2}[ \t]+(?:janoary|febroary|martsa|aprily|mey|jona|jolay|aogositra|septambra|oktobra|novambra|desambra)[ \t]+\d{4})\b`],

    // PERSONNE ALLCAPS malgache : le lookahead négatif est reconstruit
    // dynamiquement plus bas (voir buildEntityPatterns), comme en Python.
    ["PERSONNE", "__ALLCAPS_PLACEHOLDER__"],

    ["ADRESSE", String.raw`\b[Ll]ot\b[ \t]+(?<val>[${WORD}\d]+(?:[ \t]+[${WORD}\d]+){0,6})(?=[ \t]*[,;.\n]|$)`],

    ["PROPRIETE", String.raw`\bpropriété[ \t]+dite[ \t]+«[ \t]*(?<val>[^»]+?)[ \t]*»`],
    ["PROPRIETE", String.raw`\bpropriété[ \t]+dite[ \t]+"(?<val>[^"]+?)"`],

    // VILLE : reconstruite dynamiquement plus bas (voir buildEntityPatterns).
    ["VILLE", "__CITY_PLACEHOLDER__"],
  ];

  function buildEntityPatterns() {
    return ENTITY_PATTERNS.map(([label, pattern]) => {
      if (pattern === "__ALLCAPS_PLACEHOLDER__") {
        pattern = String.raw`\b(?!(?:${excludeAllcapsAlternation()})\b)(?<val>[${UPPER}]{4,}(?:[ \t]+[${UPPER}]{4,})*(?:[ \t]+[${UPPER}][${LOWER}]+){1,2})\b`;
      } else if (pattern === "__CITY_PLACEHOLDER__") {
        pattern = cityPattern();
      }
      return [label, new RegExp(pattern, "gd")];
    });
  }

  // ---------------------------------------------------------------------
  // Gazetteer : liste de noms propres à repérer même hors des formules
  // regex (ex : mentions répétées sans "M." ou "société" devant).
  // ---------------------------------------------------------------------
  class Gazetteer {
    constructor(names) {
      this.entries = new Map(); // texte -> label
      if (names) names.forEach((n) => this.add(n));
    }
    add(name, label = "PERSONNE") {
      name = name.trim();
      if (name) this.entries.set(name, label);
    }
    remove(name) {
      this.entries.delete(name.trim());
    }
    find(text) {
      const found = [];
      for (const [name, label] of this.entries) {
        const re = new RegExp(escapeRegex(name), "g");
        let m;
        while ((m = re.exec(text)) !== null) {
          found.push({ start: m.index, end: m.index + name.length, label, text: name, source: "gazetteer" });
          if (m.index === re.lastIndex) re.lastIndex++;
        }
      }
      return found;
    }
  }

  function isAllUpper(token) {
    return token === token.toUpperCase() && token !== token.toLowerCase();
  }

  function findTitlecaseNameSequences(text) {
    const found = [];
    const token = String.raw`[${UPPER}][${LOWER}]+(?:[\-’'][${UPPER}][${LOWER}]+)*`;
    const pattern = new RegExp(String.raw`\b${token}(?:[ \t]+${token}){1,3}\b`, "g");
    let m;
    while ((m = pattern.exec(text)) !== null) {
      const words = m[0].split(/\s+/);
      if (!words.some((w) => STOPWORDS_TITLECASE.has(w))) {
        found.push({ start: m.index, end: m.index + m[0].length, label: "PERSONNE", text: m[0], source: "regex" });
      }
      if (m.index === pattern.lastIndex) pattern.lastIndex++;
    }
    return found;
  }

  function detectEntities(text, gazetteer, patterns) {
    let regexFound = [];

    for (const [label, re] of patterns) {
      re.lastIndex = 0;
      let m;
      while ((m = re.exec(text)) !== null) {
        const [start, end] = m.indices.groups.val;
        regexFound.push({ start, end, label, text: m.groups.val, source: "regex" });
        if (m.index === re.lastIndex) re.lastIndex++;
      }
    }
    regexFound = regexFound.concat(findTitlecaseNameSequences(text));

    function touchesStopword(e) {
      if (!["PERSONNE", "AVOCAT", "SOCIETE"].includes(e.label)) return false;
      return e.text.split(/\s+/).some((tok) => STOPWORDS_TITLECASE.has(tok));
    }
    regexFound = regexFound.filter((e) => !touchesStopword(e));

    const gazetteerFound = gazetteer ? gazetteer.find(text) : [];

    // Priorité absolue aux entrées du gazetteer (choix explicite de
    // l'utilisateur, catégorie comprise) : toute correspondance automatique
    // qui chevauche ne serait-ce que partiellement une entrée du gazetteer
    // est écartée — même si elle est plus longue. Sans ça, une règle
    // automatique plus large (ex : la séquence "deux mots à Casse-Titre qui
    // se suivent") pouvait avaler un mot ajouté manuellement et lui imposer
    // sa propre catégorie (typiquement PERSONNE) à la place de celle
    // choisie par l'utilisateur.
    function overlaps(a, b) {
      return a.start < b.end && b.start < a.end;
    }
    regexFound = regexFound.filter((e) => !gazetteerFound.some((g) => overlaps(e, g)));

    let found = regexFound.concat(gazetteerFound);

    found.sort((a, b) => {
      if (a.start !== b.start) return a.start - b.start;
      const lenDiff = (b.end - b.start) - (a.end - a.start);
      if (lenDiff !== 0) return lenDiff;
      const ag = a.source === "gazetteer" ? 0 : 1;
      const bg = b.source === "gazetteer" ? 0 : 1;
      return ag - bg;
    });

    const resolved = [];
    let lastEnd = -1;
    for (const e of found) {
      if (e.start >= lastEnd) {
        resolved.push(e);
        lastEnd = e.end;
      }
    }
    return resolved;
  }

  const PLACEHOLDER_PREFIXES = {
    PERSONNE: "PERSONNE", SOCIETE: "SOCIETE", AVOCAT: "CABINET",
    ADRESSE: "ADRESSE", NUMERO: "NUMERO", MONTANT: "MONTANT",
    DATE: "DATE", MATRICULE: "MATRICULE", TELEPHONE: "TELEPHONE",
    VILLE: "VILLE", PROPRIETE: "PROPRIETE",
  };

  function extractLeadingSurname(fullName) {
    const tokens = fullName.split(" ");
    const surnameTokens = [];
    for (const t of tokens) {
      if (isAllUpper(t)) surnameTokens.push(t);
      else break;
    }
    return surnameTokens.length ? surnameTokens.join(" ") : null;
  }

  class Anonymizer {
    constructor(gazetteer) {
      this.gazetteer = gazetteer || new Gazetteer();
      this.patterns = buildEntityPatterns();
      this._mapping = new Map(); // texte original -> pseudonyme
      this._counters = {};
    }

    _pseudonymFor(entityText, label) {
      const key = entityText.trim();
      if (this._mapping.has(key)) return this._mapping.get(key);
      const prefix = PLACEHOLDER_PREFIXES[label] || label;
      this._counters[prefix] = (this._counters[prefix] || 0) + 1;
      const pseudo = `[${prefix}_${this._counters[prefix]}]`;
      this._mapping.set(key, pseudo);
      return pseudo;
    }

    detect(text) {
      let entities = detectEntities(text, this.gazetteer, this.patterns);

      let added = false;
      for (const e of entities) {
        if (e.label === "PERSONNE" && e.source === "regex" && e.text.includes(" ")) {
          const surname = extractLeadingSurname(e.text);
          if (surname && surname.length >= 4 && !this.gazetteer.entries.has(surname)) {
            this.gazetteer.add(surname, "PERSONNE");
            added = true;
          }
        }
      }
      if (added) entities = detectEntities(text, this.gazetteer, this.patterns);
      return entities;
    }

    anonymize(text, entities) {
      if (!entities) entities = this.detect(text);
      let out = text;
      const sorted = [...entities].sort((a, b) => b.start - a.start);
      for (const e of sorted) {
        const pseudo = this._pseudonymFor(e.text, e.label);
        out = out.slice(0, e.start) + pseudo + out.slice(e.end);
      }
      return out;
    }

    mappingTable() {
      return Array.from(this._mapping.entries()).sort((a, b) => (a[1] > b[1] ? 1 : -1));
    }

    mappingAsPairs() {
      // [original, pseudonyme] — pour l'enregistrement bibliothèque /
      // la restauration ultérieure.
      return Array.from(this._mapping.entries()).map(([orig, pseudo]) => [orig, pseudo]);
    }
  }

  function restoreOriginalNames(text, mappingPairs) {
    // mappingPairs : [[original, pseudonyme], ...]. Remplace chaque
    // pseudonyme par la vraie donnée. Les pseudonymes les plus longs
    // d'abord pour éviter qu'un préfixe commun ("PERSONNE_1" vs
    // "PERSONNE_10") ne soit remplacé partiellement.
    let out = text;
    let count = 0;
    const pairs = [...mappingPairs].sort((a, b) => b[1].length - a[1].length);
    for (const [original, pseudo] of pairs) {
      if (out.includes(pseudo)) {
        out = out.split(pseudo).join(original);
        count++;
      }
    }
    return { text: out, count };
  }

  global.AnonymizerLib = {
    Gazetteer, Anonymizer, detectEntities, buildEntityPatterns,
    restoreOriginalNames, CITY_NAMES, STOPWORDS_TITLECASE, EXCLUDE_ALLCAPS,
  };
})(window);
