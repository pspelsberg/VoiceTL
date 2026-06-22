# code-security-loop-fix

**Typ:** Autonomer Workflow- / Schleifen-Skill  
**Abhängigkeiten:** `code-security-review` (Sub-Skill)  
**Ziel:** Automatisches Identifizieren, Planen, Beheben und Rezensieren von kritischen Sicherheitsfehlern und Warnungen im Quellcode mit abschließender Berichterstattung.

---

## Übersicht

Der Skill `code-security-loop-fix` implementiert einen automatisierten Workflow zur kontinuierlichen Analyse, Behebung und Validierung von Sicherheitsfehlern in Quellcode. Er nutzt den Sub-Skill `code-security-review` als Analyse-Engine und führt eine Schleifenlogik aus, bis entweder alle kritischen Fehler behoben sind oder ein konfigurierbares Limit erreicht wird.

### Kernfunktionen:
- Automatisierte Initialanalyse mit `code-security-review`
- Filterung nach Schweregraden (Critical/Warning)
- Sequenzielle Behebungsplanung und -ausführung
- Syntaxvalidierung nach Code-Änderungen
- Iterative Validierungsschleife
- Generierung eines detaillierten Sicherheitsberichts (`security_report.md`)

---

## Workflow-Algorithmus

### Schritt 1: Initiale Analyse

1. **Analyseaufruf:**
   ```bash
   pi invoke code-security-review --target <quellcode-verzeichnis>
   ```

2. **Ergebniserfassung:**
   - Speichere das Analyseergebnis als strukturierte Daten (JSON/Objekt)
   - Extrahiere:
     - Gefundene Sicherheitslücken mit Metadaten
     - Schweregrade (Critical, Warning, Low, Info)
     - CWE-IDs und Beschreibungen
     - Betroffene Dateien und Zeilen

3. **Initialisierung:**
   - Setze `iteration_count = 0`
   - Erstelle leere Datenstrukturen für:
     - `fix_history` (Historie aller Iterationen)
     - `applied_fixes` (Liste aller durchgeführten Code-Änderungen)

---

### Schritt 2: Filterung & Behebungsplanung

1. **Filterlogik:**
   ```python
   critical_warnings = analyze_results.filter(severity in ["Critical", "Warning"])
   ```

2. **Bedingungsprüfung:**
   - **Fall A: Keine kritischen/warnenden Fehler gefunden**
     - Setze `status = "Erfolgreich bereinigt"`
     - Springe zu Schritt 5 (Berichterstattung)
   
   - **Fall B: Fehler gefunden**
     - Prüfe `iteration_count >= 5` (Schleifenlimit)
       - **Fall B1: Limit erreicht**
         - Setze `status = "Teilweise behoben - Limit erreicht"`
         - Springe zu Schritt 5 (Berichterstattung)
       - **Fall B2: Limit nicht erreicht**
         - Erstelle `fix_plan` als sequenzielle Liste aller gefundenen Fehler
         - Sortiere nach:
           1. Schweregrad (Critical vor Warning)
           2. Dateipriorität (alphabetisch)
           3. Zeilennummer (aufsteigend)
         - Springe zu Schritt 3 (Code-Behebung)

---

### Schritt 3: Automatisierte Code-Behebung (Fix)

1. **Fix-Plan-Ausführung:**
   Für jeden Eintrag im `fix_plan`:
   ```python
   for fix in fix_plan:
       # 1. Code-Änderung anwenden
       apply_code_fix(
           file_path=fix.file,
           line_number=fix.line,
           new_code=fix.suggested_code,
           backup=True
       )
       
       # 2. Fix-Details dokumentieren
       applied_fixes.append({
           "file": fix.file,
           "line": fix.line,
           "cwe": fix.cwe_id,
           "description": fix.description,
           "severity": fix.severity,
           "iteration": iteration_count
       })
   ```

2. **Syntaxvalidierung:**
   - Führe Linter/Parser auf dem modifizierten Code aus
   - Prüfe auf:
     - Syntaxfehler
     - Unvollständige Codeblöcke
     - Inkonsistenzen
   - Falls Validierung fehlschlägt:
     - Rückgängigmachen der Änderungen
     - Protokollierung als nicht-behebbar
     - Fortfahren mit nächstem Eintrag im `fix_plan`

3. **Schleifenzähler aktualisieren:**
   ```python
   iteration_count += 1
   ```

---

### Schritt 4: Validierungsschleife (Re-Review)

1. **Neue Analyse durchführen:**
   ```bash
   pi invoke code-security-review --target <quellcode-verzeichnis>
   ```

2. **Ergebnisvergleich:**
   - Vergleiche neue Analyse mit vorheriger Iteration
   - Aktualisiere `fix_history` mit:
     - Anzahl behobener Fehler
     - Anzahl neuer Fehler
     - Schweregradverteilung

3. **Schleifenentscheidung:**
   - Springe zurück zu Schritt 2 (Filterung & Behebungsplanung)

---

### Schritt 5: Berichterstattung (Exit)

1. **Berichtsgenerierung:**
   Erstelle die Datei `security_report.md` mit folgendem Inhalt:

   ```markdown
   # Security Review & Fix Report

   ## Zusammenfassung
   - **Status:** [Erfolgreich bereinigt / Teilweise behoben - Limit erreicht]
   - **Iterationen:** {iteration_count}
   - **Gesamtfehler (initial):** {initial_error_count}
   - **Behobene Fehler:** {fixed_error_count}
   - **Verbliebene Fehler:** {remaining_error_count}
   
   ## Historie der Iterationen
   
   | Iteration | Datum/Zeit | Gefundene Fehler | Behobene Fehler | Schweregradverteilung |
   |-----------|------------|------------------|-----------------|----------------------|
   | 1         | ...        | {count}          | {count}         | Critical: X, Warning: Y |
   | 2         | ...        | {count}          | {count}         | ...                  |
   | ...       | ...        | ...              | ...             | ...                  |
   
   ## Details der Behebungen (Fixes)
   
   | Datei | Zeile | Schwachstelle (CWE) | Beschreibung des Fixes |
   |-------|-------|---------------------|------------------------|
   | {file}| {line}| {cwe_id}            | {fix_description}      |
   | ...   | ...   | ...                 | ...                    |
   
   ## Verbliebene Risiken & Hinweise
   
   ### Ignorierte Meldungen (Low/Info)
   - {liste_der_ignorierten_meldungen}
   
   ### Nicht behebbare Fehler
   - {liste_der_nicht_behebbaren_fehler}
   ```

2. **Ausgabe:**
   - Speichere den Bericht im Root-Verzeichnis des analysierten Projekts
   - Gib Pfad zum Bericht aus: `security_report.md`
   - Falls im CI/CD-Kontext: Setze Exit-Code entsprechend dem Status

---

## Technische Implementierung

### Abhängigkeiten

| Abhängigkeit | Version | Zweck |
|--------------|---------|-------|
| `code-security-review` | >=1.0.0 | Sicherheitsanalyse-Engine |
| `pi` | >=2.0.0 | Skill-Infrastruktur |
| `python` | >=3.8 | Hauptimplementierungssprache |
| `linters` | variabel | Syntaxvalidierung |

### Konfiguration

Erstelle eine Konfigurationsdatei `config.yaml` im Skill-Verzeichnis:

```yaml
# code-security-loop-fix/config.yaml
loop:
  max_iterations: 5
  backup_files: true
  validation:
    enabled: true
    linters: ["eslint", "pylint", "rubocop"]  # je nach Projekt
  report:
    output_path: "./security_report.md"
    include_details: true
```

### Fehlerbehandlung

| Fehlerfall | Behandlung |
|------------|------------|
| Analyse fehlgeschlagen | Abbruch mit Fehlerprotokoll, kein Bericht |
| Code-Änderung fehlgeschlagen | Rückgängigmachen, Protokollierung, Fortfahren |
| Validierung fehlgeschlagen | Änderungen verwerfen, als nicht-behebbar markieren |
| Schleifenlimit erreicht | Vorzeitiger Abbruch mit Statusmeldung |

---

## Beispiel-Workflow

```
1. Initialanalyse: 12 Fehler gefunden (5 Critical, 7 Warning)
2. Iteration 1: 5 Critical behoben, 2 neue Critical gefunden → 5 behoben, 7 neu
3. Iteration 2: 7 Warning behoben, 1 Critical übrig → 12 behoben, 1 neu
4. Iteration 3: 1 Critical behoben → 13 behoben, 0 neu
5. Iteration 4: Keine Fehler mehr gefunden → Erfolgreicher Abschluss

Finaler Bericht:
- Status: Erfolgreich bereinigt
- Iterationen: 4
- Behobene Fehler: 13
- Verbliebene Fehler: 0
```

---

## Integration in CI/CD-Pipelines

### GitHub Actions Beispiel

```yaml
name: Security Loop Fix

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  security-fix:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Run code-security-loop-fix
        uses: ./code-security-loop-fix
        id: security-fix
        with:
          target: "."
          max_iterations: 5
      
      - name: Upload Security Report
        uses: actions/upload-artifact@v3
        with:
          name: security-report
          path: security_report.md
      
      - name: Fail on remaining critical issues
        if: steps.security-fix.outputs.remaining_critical > 0
        run: exit 1
```

### Command-Line Interface

```bash
# Grundlegender Aufruf
pi invoke code-security-loop-fix --target /pfad/zum/projekt

# Mit benutzerdefiniertem Limit
pi invoke code-security-loop-fix --target /pfad/zum/projekt --max-iterations 3

# Nur Analyse ohne Fix (Dry-Run)
pi invoke code-security-loop-fix --target /pfad/zum/projekt --dry-run true
```

---

## Metriken & Logging

### Protokollierte Metriken

- `iteration_count`: Anzahl der durchgeführten Schleifen
- `fixed_errors`: Gesamtzahl behobener Fehler
- `remaining_errors`: Anzahl verbleibender Fehler nach Abschluss
- `fix_success_rate`: Erfolgsquote der Code-Änderungen
- `validation_failures`: Anzahl fehlgeschlagener Validierungen

### Log-Format

```json
{
  "timestamp": "2026-06-20T12:00:00Z",
  "iteration": 3,
  "action": "fix_applied",
  "file": "src/main.py",
  "line": 42,
  "cwe": "CWE-89",
  "severity": "Critical",
  "status": "success",
  "message": "SQL Injection vulnerability fixed"
}
```

---

## Sicherheit & Compliance

### Sicherheitsaspekte

- **Backup-Strategie:** Automatische Erstellung von Backups vor Code-Änderungen
- **Validierung:** Syntaxprüfung nach jeder Änderung
- **Rollback:** Möglichkeit zum Rückgängigmachen aller Änderungen
- **Protokollierung:** Detaillierte Audit-Logs für Compliance

### Compliance-Anforderungen

- **DSGVO:** Keine personenbezogenen Daten werden verarbeitet
- **ISO 27001:** Vollständige Protokollierung aller Änderungen
- **OWASP Top 10:** Behandlung der Top 10 Schwachstellen
- **CWE Top 25:** Fokus auf die häufigsten Schwachstellen

---

## Fehlerbehebung & Debugging

### Häufige Probleme

| Problem | Ursache | Lösung |
|---------|---------|--------|
| Endlosschleife | Fehler wird nicht behoben | Analyse der Fix-Logik überprüfen |
| Validierungsfehler | Syntaxfehler nach Fix | Linter-Konfiguration anpassen |
| Performance-Probleme | Große Codebasen | Parallelisierung oder Batch-Verarbeitung |

### Debug-Modi

```bash
# Verbose Logging
pi invoke code-security-loop-fix --target /pfad --verbose true

# Troubleshooting-Modus
pi invoke code-security-loop-fix --target /pfad --debug true

# Dry-Run (nur Analyse, keine Änderungen)
pi invoke code-security-loop-fix --target /pfad --dry-run true
```

---

## Erweiterte Funktionen

### 1. Priorisierungslogik

Erweiterte Priorisierung nach:
- **Angriffsvektor:** Remote vs. lokal
- **Auswirkung:** Datenverlust, Code-Ausführung, Denial of Service
- **Exploit-Verfügbarkeit:** Öffentlich bekannte Exploits

### 2. Team-Integration

- **Slack/Teams-Benachrichtigungen** bei kritischen Fehlern
- **Jira-Ticket-Erstellung** für verbleibende Fehler
- **E-Mail-Berichte** für Compliance-Zwecke

### 3. Automatische Pull Requests

```yaml
# GitHub Actions Integration
- name: Create PR with fixes
  if: steps.security-fix.outputs.remaining_critical == 0
  uses: peter-evans/create-pull-request@v3
  with:
    commit-message: "Security fixes applied by code-security-loop-fix"
    title: "Security: Fix critical vulnerabilities"
    body: "Automated security fixes from code-security-loop-fix"
```

---

## Dokumentation & Support

### Benutzerdokumentation

- **README.md:** Enthält Installationsanweisungen und Beispiele
- **CHANGELOG.md:** Versionshistorie und Änderungen
- **FAQ.md:** Häufig gestellte Fragen und Antworten

### Support

- **GitHub Issues:** Für Bug-Reports und Feature-Anfragen
- **Discord/Slack:** Community-Support
- **Enterprise Support:** Kommerzieller Support verfügbar

---

## Versionierung

| Version | Datum | Änderungen |
|---------|-------|-----------|
| 1.0.0 | 2026-06-20 | Initiale Version |
| 1.1.0 | ... | Erweiterte Priorisierung, CI/CD-Integration |
| 1.2.0 | ... | Team-Integration, Automatische PRs |

---

## Lizenz

MIT License

Copyright (c) 2026 VoiceTL

Permission is hereby granted... [Standard MIT License Text]
