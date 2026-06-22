# VoiceTL - Secure Deployment Guide

## 🚀 Deployment-Übersicht

Dieser Leitfaden beschreibt die sichere Bereitstellung und Konfiguration von VoiceTL in verschiedenen Umgebungen.

---

## 🔐 Sicherheitsvoraussetzungen

### 1. Systemanforderungen

| Anforderung | Empfehlung | Grund |
|-------------|------------|-------|
| **Betriebssystem** | Linux (Ubuntu 22.04+, Fedora 38+, Bazzite) | Beste Unterstützung für PipeWire |
| **Python-Version** | 3.8+ | Erforderlich für asyncio |
| **Benutzerrechte** | Dedizierter Benutzer (nicht root) | Sicherheitsprinzip "Least Privilege" |
| **Speicher** | 2 GB RAM | Für stabile Audio-Verarbeitung |
| **CPU** | 2+ Kerne | Für Echtzeit-Verarbeitung |

### 2. Abhängigkeiten

```bash
# Python-Abhängigkeiten (gepinnt für Sicherheit)
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

# System-Abhängigkeiten (Linux)
sudo apt update && sudo apt install -y \
    pipewire \
    pipewire-pulseaudio \
    pactl
```

---

## 🛡️ Sichere Installation

### 1. Dedizierter Benutzer erstellen

```bash
# Benutzer erstellen (ohne Login-Shell)
sudo useradd -r -s /bin/false voicetl

# Verzeichnis erstellen und Berechtigungen setzen
sudo mkdir -p /opt/voicetl
sudo chown voicetl:voicetl /opt/voicetl
```

### 2. VoiceTL installieren

```bash
# Als voicetl-Benutzer ausführen
sudo -u voicetl bash
cd /opt/voicetl

# Repository klonen
git clone https://github.com/your-org/voicetl.git .

# Virtuelle Umgebung erstellen
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

# Konfiguration kopieren
cp .env.template .env
chmod 600 .env  # Nur Besitzer kann lesen/schreiben
```

### 3. API-Key sicher speichern

**❌ NICHT TUN:**
```bash
# API-Key im Code speichern
GEMINI_API_KEY="your_key_here"

# API-Key in Versionierungssystem committen
git add .env
git commit -m "Add API key"
```

**✅ RICHTIG:**
```bash
# API-Key in .env-Datei (nicht versioniert)
echo "GEMINI_API_KEY=your_actual_key_here" > .env
chmod 600 .env

# .env in .gitignore eintragen
echo ".env" >> .gitignore
git add .gitignore
git commit -m "Add .env to gitignore"
```

### 4. Berechtigungen setzen

```bash
# Verzeichnis-Berechtigungen
chmod 700 /opt/voicetl  # Nur Besitzer hat Zugriff

# Log-Datei-Berechtigungen
chmod 600 /opt/voicetl/voicetl.log

# Konfigurationsdatei-Berechtigungen
chmod 600 /opt/voicetl/.env
```

---

## 🎯 Konfiguration

### 1. Umgebungsvariablen

| Variable | Beschreibung | Standardwert | Beispiel |
|----------|--------------|--------------|----------|
| `GEMINI_API_KEY` | Google Gemini API-Key | - | `sk-...` |
| `OUT_TARGET_LANG` | Zielsprache für eigene Stimme | `en` | `en`, `de`, `fr` |
| `IN_TARGET_LANG` | Zielsprache für Meeting-Ton | `de` | `en`, `de`, `fr` |
| `MIN_VOLUME_THRESHOLD_MIC` | VAD-Schwelle für Mikrofon | `0.01` | `0.001` bis `0.5` |
| `MIN_VOLUME_THRESHOLD_SLACK` | VAD-Schwelle für Slack | `0.01` | `0.001` bis `0.5` |
| `VIRTUAL_MIC_NAME` | Name des virtuellen Mikrofons | `VoiceTL_Mic_Sink` | `^[a-zA-Z0-9_-]{1,64}$` |
| `VIRTUAL_SPK_NAME` | Name des virtuellen Lautsprechers | `VoiceTL_Slack_Out_Sink` | `^[a-zA-Z0-9_-]{1,64}$` |
| `IDLE_TIMEOUT` | Inaktivitäts-Timeout (Sekunden) | `600` | `0` bis `86400` |
| `ENVIRONMENT` | Umgebungsmodus | `production` | `development`, `production` |

### 2. Beispiel-.env-Datei

```bash
# VoiceTL Konfiguration
GEMINI_API_KEY=sk_your_api_key_here_39_chars

# Zielsprachen
OUT_TARGET_LANG=en
IN_TARGET_LANG=de

# VAD-Schwellenwerte (0.001 - 0.5)
MIN_VOLUME_THRESHOLD_MIC=0.01
MIN_VOLUME_THRESHOLD_SLACK=0.01

# Virtuelle Gerätenamen (nur [a-zA-Z0-9_-])
VIRTUAL_MIC_NAME=VoiceTL_Mic_Sink
VIRTUAL_SPK_NAME=VoiceTL_Slack_Out_Sink

# Inaktivitäts-Timeout (0 - 86400 Sekunden)
IDLE_TIMEOUT=600

# Umgebungsmodus (development = detaillierte Fehler)
ENVIRONMENT=production
```

### 3. Validierung der Konfiguration

```bash
# Konfiguration validieren
./venv/bin/python -c "from config import config; config.validate(); print('Konfiguration OK')"
```

---

## 🚀 Starten und Stoppen

### 1. Manuell starten

```bash
# Als voicetl-Benutzer
sudo -u voicetl /opt/voicetl/venv/bin/python /opt/voicetl/main.py
```

### 2. Als Systemd-Service (empfohlen)

#### Service-Datei erstellen

```bash
sudo nano /etc/systemd/system/voicetl.service
```

```ini
[Unit]
Description=VoiceTL - Live Voice Translation Agent
After=network.target pipewire.service
Requires=pipewire.service

[Service]
Type=simple
User=voicetl
Group=voicetl
WorkingDirectory=/opt/voicetl
EnvironmentFile=/opt/voicetl/.env
ExecStart=/opt/voicetl/venv/bin/python /opt/voicetl/main.py
Restart=on-failure
RestartSec=5s
StandardOutput=journal
StandardError=journal
SyslogIdentifier=voicetl

# Sicherheitsoptionen
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/voicetl

[Install]
WantedBy=multi-user.target
```

#### Service aktivieren und starten

```bash
# Service laden
sudo systemctl daemon-reload

# Service starten
sudo systemctl start voicetl

# Service aktivieren (automatischer Start beim Boot)
sudo systemctl enable voicetl

# Status prüfen
sudo systemctl status voicetl

# Logs anzeigen
sudo journalctl -u voicetl -f
```

### 3. Stoppen

```bash
# Service stoppen
sudo systemctl stop voicetl

# Service deaktivieren
sudo systemctl disable voicetl
```

---

## 🔒 Sicherheitshärtung

### 1. Firewall-Konfiguration

```bash
# Nur ausgehende Verbindungen zu Google-APIs erlauben
sudo ufw allow out to 142.250.0.0/16  # Google IP-Bereich
sudo ufw allow out to 209.85.0.0/16   # Google IP-Bereich
sudo ufw allow out to 216.239.0.0/16  # Google IP-Bereich

# Alle anderen ausgehenden Verbindungen blockieren (optional)
sudo ufw default deny out

# Eingehende Verbindungen blockieren (VoiceTL benötigt keine eingehenden Ports)
sudo ufw default deny in
```

### 2. AppArmor-Profil (Linux)

```bash
# AppArmor-Profil erstellen
sudo nano /etc/apparmor.d/usr.bin.voicetl
```

```apparmor
#include <tunables/global>

/opt/voicetl/venv/bin/python {
  #include <abstractions/base>
  
  # Erlaubte Dateien
  /opt/voicetl/** r,
  /opt/voicetl/.env r,
  /opt/voicetl/voicetl.log rw,
  
  # Erlaubte Binaries
  /usr/bin/pactl ix,
  
  # Netzwerkzugriff
  network inet,
  
  # Verhindere Zugriff auf sensible Dateien
  deny /etc/** rw,
  deny /home/** rw,
  deny /root/** rw,
  
  # Capabilities
  capability net_bind_service,
  capability sys_admin,
}
```

```bash
# AppArmor laden
sudo apparmor_parser -r /etc/apparmor.d/usr.bin.voicetl
sudo systemctl restart apparmor
```

### 3. SELinux-Konfiguration (falls aktiviert)

```bash
# SELinux-Kontext für VoiceTL-Verzeichnis setzen
sudo chcon -R -t user_home_t /opt/voicetl

# Falls nötig: Benutzerdefinierten Kontext erstellen
sudo semanage fcontext -a -t voicetl_t "/opt/voicetl(/.*)?"
sudo restorecon -Rv /opt/voicetl
```

---

## 📊 Monitoring und Logging

### 1. Log-Rotation

```bash
# Logrotate-Konfiguration
sudo nano /etc/logrotate.d/voicetl
```

```logrotate
/opt/voicetl/voicetl.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 600 voicetl voicetl
    maxsize 10M
    maxage 90
}
```

### 2. Log-Analyse

```bash
# Logs analysieren
grep -i "error\|warning\|critical" /opt/voicetl/voicetl.log

# API-Fehler zählen
grep -c "API Error" /opt/voicetl/voicetl.log

# Rate-Limit-Warnungen
grep -c "Rate limit" /opt/voicetl/voicetl.log
```

### 3. System-Monitoring

```bash
# CPU-Auslastung
htop -p $(pgrep -u voicetl python)

# Speichernutzung
ps -u voicetl -o pid,rss,cmd | grep python

# Netzwerkverbindungen
sudo ss -tupn | grep voicetl
```

---

## 🔄 Updates und Wartung

### 1. VoiceTL aktualisieren

```bash
# Als voicetl-Benutzer
sudo -u voicetl bash
cd /opt/voicetl

# Repository aktualisieren
git pull origin main

# Abhängigkeiten aktualisieren
./venv/bin/pip install -r requirements.txt --upgrade

# Service neu starten
sudo systemctl restart voicetl
```

### 2. Sicherheitsupdates

```bash
# System-Updates
sudo apt update && sudo apt upgrade -y

# Python-Abhängigkeiten prüfen
./venv/bin/pip list --outdated

# Sicherheitslücken in Abhängigkeiten prüfen
./venv/bin/pip install safety
./venv/bin/safety check
```

### 3. Regelmäßige Sicherheitsprüfungen

```bash
# Monatlich: bandit
./venv/bin/pip install bandit
./venv/bin/bandit -r /opt/voicetl

# Monatlich: Secret-Scanning
./venv/bin/pip install trufflehog
./venv/bin/trufflehog filesystem --directory /opt/voicetl

# Quartalsweise: Manuelle Überprüfung
# - Konfiguration prüfen
# - Logs analysieren
# - Berechtigungen überprüfen
```

---

## 🚨 Fehlerbehebung

### Häufige Probleme

#### 1. pactl nicht gefunden

```bash
# PipeWire installieren
sudo apt install pipewire pipewire-pulseaudio

# Service neu starten
sudo systemctl restart pipewire

# Benutzer zur audio-Gruppe hinzufügen
sudo usermod -aG audio voicetl
```

#### 2. Kein Audio-Gerät gefunden

```bash
# Verfügbare Geräte anzeigen
./venv/bin/python main.py --list-devices

# Gerätefilter anpassen
nano .env
# INPUT_DEVICE_FILTER=Yeti
# OUTPUT_DEVICE_FILTER=SteelSeries
```

#### 3. API-Key ungültig

```bash
# API-Key prüfen
./venv/bin/python -c "from config import config; config.validate(); print('API-Key OK')"

# Neuen API-Key generieren
# 1. Google Cloud Console öffnen
# 2. Neue API-Keys generieren
# 3. .env-Datei aktualisieren
```

#### 4. Berechtigungsfehler

```bash
# Berechtigungen prüfen
ls -la /opt/voicetl

# Berechtigungen korrigieren
sudo chown -R voicetl:voicetl /opt/voicetl
sudo chmod 700 /opt/voicetl
sudo chmod 600 /opt/voicetl/.env
```

---

## 📝 Checklisten

### Vor dem Deployment

- [ ] Dedizierter Benutzer `voicetl` erstellt
- [ ] Verzeichnis `/opt/voicetl` mit richtigen Berechtigungen
- [ ] API-Key in `.env` gespeichert (nicht im Code)
- [ ] `.env`-Datei mit `chmod 600` geschützt
- [ ] Abhängigkeiten installiert (`requirements.txt`)
- [ ] PipeWire/PulseAudio installiert
- [ ] Konfiguration validiert
- [ ] Firewall-Regeln konfiguriert
- [ ] AppArmor/SELinux-Profil erstellt (optional)

### Nach dem Deployment

- [ ] Service gestartet und aktiviert
- [ ] Status mit `systemctl status voicetl` geprüft
- [ ] Logs mit `journalctl -u voicetl -f` überprüft
- [ ] Audio-Geräte mit `--list-devices` geprüft
- [ ] Funktionstest durchgeführt

### Regelmäßige Wartung

- [ ] Monatliche Sicherheitsprüfungen
- [ ] Quartalsweise Secret-Scans
- [ ] Jährliche Penetration Tests
- [ ] Regelmäßige Updates

---

## 📚 Referenzen

- [VoiceTL Dokumentation](README.md)
- [Sicherheitsdokumentation](SECURITY.md)
- [OWASP Top 10:2025](https://owasp.org/www-project-top-ten/)
- [CWE Top 25](https://cwe.mitre.org/top25/)
- [Systemd Dokumentation](https://www.freedesktop.org/software/systemd/man/systemd.service.html)
- [AppArmor Dokumentation](https://wiki.ubuntu.com/AppArmor)

---

## 📅 Versionshistorie

| Version | Datum | Änderungen |
|---------|-------|-----------|
| 1.0.0 | 2026-06-20 | Initiale Deployment-Dokumentation |

---

**🔒 Diese Dokumentation wurde am 20. Juni 2026 erstellt.**
**📌 Nächste Überprüfung empfohlen: 20. Juli 2026.**