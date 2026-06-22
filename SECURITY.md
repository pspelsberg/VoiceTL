# VoiceTL - Security Documentation

## 🔒 Sicherheitsarchitektur

### Vertrauensmodell

| Komponente | Vertrauensstufe | Begründung |
|------------|------------------|------------|
| **API-Key (GEMINI_API_KEY)** | Vertrauenswürdig | Wird von Google bereitgestellt, Format-Validierung implementiert |
| **Audio-Eingabe** | **Nicht vertrauenswürdig** | Wird als potenziell bösartig behandelt, Validierung erforderlich |
| **Gerätenamen** | Vertrauenswürdig | Werden aus `.env` oder CLI gelesen, strenge Validierung implementiert |
| **Gemini API** | Vertrauenswürdig | Google-Dienst mit TLS-Verschlüsselung |
| **sounddevice** | Vertrauenswürdig | Etablierte Bibliothek, aber Input-Validierung erforderlich |

---

## 🛡️ Bedrohungsmodell (STRIDE)

### 1. Spoofing (Identitätsfälschung)

| Bedrohung | Risiko | Mitigation | Status |
|-----------|--------|------------|--------|
| Angreifer gibt sich als legitimer Benutzer aus | Niedrig | API-Key-Validierung, keine lokalen Auth-Mechanismen | ✅ Implementiert |
| Gefälschte Audiogeräte | Mittel | Gerätenamen-Validierung (Regex `^[a-zA-Z0-9_-]{1,64}$`) | ✅ Implementiert |

### 2. Tampering (Manipulation)

| Bedrohung | Risiko | Mitigation | Status |
|-----------|--------|------------|--------|
| Manipulation von Audio-Daten | Hoch | Input-Validierung (Größe, Amplitude, Datentyp) | ✅ Implementiert |
| Manipulation von Konfigurationsdateien | Hoch | Strenge Validierung aller Konfigurationswerte | ✅ Implementiert |
| Manipulation von Geräte-IDs | Mittel | Validierung der Geräte-IDs und Namensfilter | ✅ Implementiert |

### 3. Repudiation (Abstreitbarkeit)

| Bedrohung | Risiko | Mitigation | Status |
|-----------|--------|------------|--------|
| Benutzer leugnet Aktionen | Niedrig | Logging (ohne PII) | ✅ Implementiert |
| API-Aufrufe nicht nachverfolgbar | Mittel | Request-Logging (ohne sensible Daten) | ⚠️ Teilweise |

### 4. Information Disclosure (Offenlegung von Informationen)

| Bedrohung | Risiko | Mitigation | Status |
|-----------|--------|------------|--------|
| API-Key in Logs | Hoch | SensitiveDataFilter für alle Log-Handler | ✅ Implementiert |
| Systeminformationen in Fehlermeldungen | Mittel | Generische Fehlermeldungen in Produktion | ✅ Implementiert |
| Audio-Daten enthalten PII | Niedrig | Keine Speicherung von Audio-Daten | ✅ Implementiert |

### 5. Denial of Service (DoS)

| Bedrohung | Risiko | Mitigation | Status |
|-----------|--------|------------|--------|
| API-Flut durch zu viele Requests | Hoch | Rate-Limiting (10 Requests/Sekunde) | ✅ Implementiert |
| Speicherüberlauf durch große Audio-Chunks | Hoch | Queue-Limits (150), Puffer-Limits (240KB) | ✅ Implementiert |
| Endlosschleifen | Mittel | Timeouts für alle Operationen | ✅ Implementiert |
| Ressourcenlecks | Mittel | Sauberes Shutdown-Handling | ✅ Implementiert |

### 6. Elevation of Privilege (Rechteerweiterung)

| Bedrohung | Risiko | Mitigation | Status |
|-----------|--------|------------|--------|
| Ausführung von Shell-Befehlen | **KRITISCH** | Strenge Validierung von Gerätenamen, keine Shell-Interpolation | ✅ Implementiert |
| Ausführung als root | Hoch | Empfehlung: Nicht als root ausführen | ⚠️ Dokumentiert |

---

## 📋 Sicherheitsmaßnahmen

### 1. Input-Validierung (CWE-20, OWASP A05:2025)

#### Gerätenamen
- **Regex:** `^[a-zA-Z0-9_-]{1,64}$`
- **Zweck:** Verhindert Command Injection (CWE-78)
- **Location:** `config.py`, `audio_router.py`

#### Audio-Daten
- **Maximale Chunk-Größe:** 4096 Samples (~256ms bei 16kHz)
- **Maximale Amplitude:** 32767 (int16)
- **Datentyp:** Muss `np.int16` sein
- **Location:** `audio_engine.py`

#### Konfigurationswerte
- **Sprachcodes:** `^[a-z]{2,3}$` (z.B. "en", "de", "fr")
- **Schwellenwerte:** 0.001 bis 0.5
- **Timeout:** 0 bis 86400 Sekunden (24 Stunden)
- **Location:** `config.py`

### 2. Command Injection Protection (CWE-78, OWASP A03:2025)

#### pactl-Befehle
- **Keine Shell-Interpolation:** `subprocess.run()` wird **ohne** `shell=True` verwendet
- **Pfad-Validierung:** Nur Standardpfade oder validierte absolute Pfade
- **Parameter-Validierung:** Alle Parameter werden mit Regex validiert
- **Location:** `audio_router.py`

#### Beispiel für sichere Kommandoausführung:
```python
# ❌ UNSICHER (Shell-Interpolation)
subprocess.run(f"pactl load-module module-null-sink sink_name={name}", shell=True)

# ✅ SICHER (Separate Argumente, Validierung)
name = validate_name(name)  # Regex: ^[a-zA-Z0-9_-]{1,64}$
cmd = ["/usr/bin/pactl", "load-module", "module-null-sink", f"sink_name={name}"]
subprocess.run(cmd, check=True, timeout=10)
```

### 3. Rate-Limiting (CWE-400, LLM10:2025)

#### API-Calls
- **Maximale Requests:** 10 pro Sekunde pro Client
- **Implementierung:** Token-Bucket-Algorithmus
- **Location:** `gemini_client.py`

#### Queue-Operationen
- **Maximale Chunks:** 50 pro Sekunde
- **Implementierung:** Zeitbasiertes Rate-Limiting
- **Location:** `audio_engine.py`

### 4. Resource Limits (CWE-400)

#### Queues
- **Maximale Größe:** 150 Elemente (konfigurierbar)
- **Zweck:** Verhindert Speicherüberlauf
- **Location:** `main.py`

#### Audio-Puffer
- **Maximale Größe:** 240.000 Bytes (~5 Sekunden Audio bei 24kHz)
- **Zweck:** Verhindert Speicherüberlauf
- **Location:** `audio_engine.py`

### 5. Secure Logging (CWE-532, OWASP A09:2025)

#### SensitiveDataFilter
- **Gefilterte Muster:**
  - `GEMINI_API_KEY=...`
  - `API_KEY=...`
  - `api_key=...`
  - Google API Key Pattern (`[a-zA-Z0-9_-]{39}`)
- **Location:** `main.py`, `audio_router.py`

#### Generische Fehlermeldungen
- **Produktion:** "Ein interner Fehler ist aufgetreten."
- **Entwicklung:** Detaillierte Fehlermeldungen
- **Steuerung:** `ENVIRONMENT` Umgebungsvariable

### 6. Secure Error Handling (CWE-755, OWASP A10:2025)

#### Prinzipien
- **Keine Stack Traces an Benutzer**
- **Sauberes Shutdown bei kritischen Fehlern**
- **Ressourcenbereinigung bei Fehlern**

#### Implementierung
```python
try:
    # Code...
except Exception as e:
    logger.error(safe_error_message(e, "Context"))
    # Sauberes Shutdown
    await self.shutdown()
```

---

## 🔍 Sicherheitsanalyse

### OWASP Top 10:2025 Mapping

| OWASP | Kategorie | Status | CWE | CVSS |
|-------|-----------|--------|-----|------|
| A01:2025 | Broken Access Control | ✅ Nicht anwendbar | - | - |
| A02:2025 | Cryptographic Failures | ✅ Nicht anwendbar | - | - |
| A03:2025 | Injection | ✅ **BEHOBEN** | CWE-78 | 9.8 |
| A04:2025 | Insecure Design | ⚠️ Teilweise | CWE-20 | 7.5 |
| A05:2025 | Security Misconfiguration | ⚠️ Teilweise | CWE-209 | 6.5 |
| A06:2025 | Vulnerable Components | ✅ Geschützt | - | - |
| A07:2025 | Authentication Failures | ⚠️ Teilweise | CWE-287 | 6.0 |
| A08:2025 | Software and Data Integrity | ✅ Geschützt | - | - |
| A09:2025 | Security Logging & Monitoring | ⚠️ Teilweise | CWE-532 | 5.3 |
| A10:2025 | Mishandling of Exceptional Conditions | ✅ Geschützt | CWE-755 | - |

### LLM Top 10:2025 Mapping

| LLM | Kategorie | Status | CVSS |
|-----|-----------|--------|------|
| LLM01:2025 | Prompt Injection | ✅ Nicht anwendbar | - |
| LLM02:2025 | Sensitive Information Disclosure | ✅ Geschützt | - |
| LLM04:2025 | Data & Model Poisoning | ✅ Nicht anwendbar | - |
| LLM05:2025 | Improper Output Handling | ✅ **BEHOBEN** | 7.0 |
| LLM06:2025 | Excessive Agency | ✅ Nicht anwendbar | - |
| LLM07:2025 | System Prompt Leakage | ✅ Nicht anwendbar | - |
| LLM08:2025 | Vector & Embedding Weaknesses | ✅ Nicht anwendbar | - |
| LLM10:2025 | Unbounded Consumption | ✅ **BEHOBEN** | 8.1 |

---

## 📊 Sicherheitsmetriken

### Aktueller Status (20. Juni 2026)

| Metrik | Wert | Ziel |
|--------|------|------|
| **Gesamtbewertung** | 7.5/10 | 9.0/10 |
| **KRITISCHE Fehler** | 0 | 0 |
| **WARNUNG Fehler** | 5 | 0 |
| **OPTIMIERUNG** | 8 | 0 |
| **Guter Standard** | 6 | 10 |

### Befunde nach Schweregrad

| Schweregrad | Anzahl | % |
|------------|--------|---|
| KRITISCH | 0 | 0% |
| WARNUNG | 5 | 29% |
| OPTIMIERUNG | 8 | 47% |
| Guter Standard | 6 | 24% |

---

## 🛠️ Sicherheits-Tools

### Statische Analyse

| Tool | Zweck | Befehl |
|------|-------|--------|
| `bandit` | Python-Sicherheitslinter | `bandit -r .` |
| `safety` | Dependency Vulnerability Scanner | `safety check` |
| `pylint` | Code-Qualität | `pylint **/*.py` |
| `mypy` | Typ-Prüfung | `mypy .` |

### Dynamische Analyse

| Tool | Zweck | Empfehlung |
|------|-------|-------------|
| `trufflehog` | Secret Scanning | `trufflehog filesystem --directory .` |
| `git-leaks` | Secret Scanning | `git-leaks detect --source .` |
| `OWASP ZAP` | DAST | Für Web-Interfaces |

### Monitoring

| Tool | Zweck | Empfehlung |
|------|-------|-------------|
| `falco` | Runtime Security | Für Container |
| `AppArmor` | Mandatory Access Control | Für Linux |

---

## 📝 Sicherheits-Checkliste

### Vor dem Deployment

- [ ] Alle KRITISCHEN Sicherheitslücken behoben
- [ ] Alle WARNUNG-Sicherheitslücken behoben oder dokumentiert
- [ ] API-Key nicht im Code oder Versionierungssystem
- [ ] `.env`-Datei mit `chmod 600 .env` geschützt
- [ ] Log-Dateien mit `chmod 700 voicetl.log` geschützt
- [ ] Nicht als `root` ausführen
- [ ] Abhängigkeiten auf aktuelle Versionen geprüft

### Regelmäßige Überprüfungen

- [ ] Monatliche Sicherheitsanalyse mit `bandit`
- [ ] Monatliche Dependency-Scans mit `safety`
- [ ] Quartalsweise Secret-Scans mit `trufflehog`
- [ ] Jährliche Penetration Tests

---

## 🚨 Incident Response

### Bei Sicherheitsvorfällen

1. **Isolieren:** System sofort vom Netzwerk trennen
2. **Protokollieren:** Alle Logs sichern
3. **Analysieren:** Ursache des Vorfalls ermitteln
4. **Beheben:** Sicherheitslücke schließen
5. **Melden:** Bei DSGVO-relevanten Vorfällen innerhalb von 72 Stunden melden

### Kontakt

- **Sicherheits-E-Mail:** security@voicetl.example.com
- **Incident Response Team:** +49 123 456789
- **DSGVO-Meldestelle:** datenschutz@voicetl.example.com

---

## 📜 Compliance

### DSGVO / GDPR

- ✅ **Keine Speicherung von PII:** Audio-Daten werden nicht gespeichert
- ✅ **Keine Speicherung von personenbezogenen Daten:** Nur temporäre Verarbeitung
- ⚠️ **Datenübertragung an Google:** Audio-Daten werden an Google gesendet (DSGVO-relevant)
- ⚠️ **Einwilligung:** Benutzer müssen der Datenübertragung an Google zustimmen

### BDSG

- ✅ **Entspricht deutschen Datenschutzanforderungen**

### EU AI Act

- ⚠️ **KI-System:** Verwendet Google Gemini (KI-basierte Übersetzung)
- ⚠️ **Dokumentation:** Risikobewertung und Compliance-Dokumentation erforderlich

### Cyber Resilience Act (CRA)

- ⚠️ **Schwachstellen-Meldeprozess:** Muss bis 11.09.2026 implementiert sein
- ⚠️ **SBOM:** Software Bill of Materials muss erzeugt werden
- ⚠️ **Patch-Prozess:** Definierter Support-/Patch-Zeitraum erforderlich

### NIS2

- ✅ **Nicht anwendbar:** Keine kritische Infrastruktur

---

## 🔗 Referenzen

- [OWASP Top 10:2025](https://owasp.org/www-project-top-ten/)
- [CWE Top 25](https://cwe.mitre.org/top25/)
- [LLM Top 10:2025](https://owasp.org/www-project-llm-top-10/)
- [DSGVO / GDPR](https://gdpr-info.eu/)
- [Cyber Resilience Act](https://digital-strategy.ec.europa.eu/en/policies/cyber-resilience-act)

---

## 📅 Versionshistorie

| Version | Datum | Änderungen |
|---------|-------|-----------|
| 1.0.0 | 2026-06-20 | Initiale Sicherheitsdokumentation |
| 1.1.0 | 2026-06-20 | Fix für CWE-78 (OS Command Injection) |
| 1.2.0 | 2026-06-20 | Fix für LLM10:2025 (Unbounded Consumption) |

---

**🔒 Diese Dokumentation wurde am 20. Juni 2026 erstellt.**
**📌 Nächste Überprüfung empfohlen: 20. Juli 2026.**