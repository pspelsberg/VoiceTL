import sys
import os
import re
import shutil
import subprocess
import logging

logger = logging.getLogger("VoiceTL.AudioRouter")


def safe_error_message(e: Exception, context: str) -> str:
    """
    Gibt eine sichere, generische Fehlermeldung zurück.
    Filtert sensible Daten aus Fehlermeldungen (CWE-532, OWASP A09:2025).
    """
    sensitive_patterns = [
        r'GEMINI_API_KEY=[^\s]+',
        r'API_KEY=[^\s]+',
        r'api_key=[^\s]+',
        r'[a-zA-Z0-9_-]{39}'  # Google API Key Pattern
    ]
    
    error_str = str(e)
    for pattern in sensitive_patterns:
        error_str = re.sub(pattern, '[REDACTED_API_KEY]', error_str)
    
    if os.getenv("ENVIRONMENT", "production") == "development":
        return f"[{context}] {error_str}"
    else:
        return f"[{context}] Ein interner Fehler ist aufgetreten."

class VirtualAudioDeviceManager:
    def __init__(self, virtual_mic_name: str, virtual_spk_name: str):
        self.virtual_mic_name = virtual_mic_name
        self.virtual_spk_name = virtual_spk_name
        self.loaded_modules = []
        self.is_linux = sys.platform.startswith("linux")
        # Absoluten Pfad zu pactl ermitteln, um PATH-Hijacking zu verhindern (CWE-426 Mitigation)
        self._pactl_path = self._find_pactl_path() if self.is_linux else None
    
    def _find_pactl_path(self) -> Optional[str]:
        """
        Findet und validiert den Pfad zu pactl (CWE-426, CWE-256).
        """
        # 1. Standardpfade prüfen (kein PATH-Hijacking)
        standard_paths = [
            "/usr/bin/pactl",
            "/bin/pactl",
            "/usr/local/bin/pactl"
        ]
        for path in standard_paths:
            if os.path.exists(path) and os.access(path, os.X_OK):
                # 2. Validierung: Datei muss ein reguläres Binary sein
                if os.path.isfile(path):
                    return path
        
        # 3. Falls nicht in Standardpfaden, shutil.which verwenden (aber validieren)
        pactl_path = shutil.which("pactl")
        if pactl_path:
            # Validierung: Pfad muss absolut sein und keine verdächtigen Zeichen enthalten
            if os.path.isabs(pactl_path) and re.match(r'^[a-zA-Z0-9_/\-\.]+$', pactl_path):
                return pactl_path
        
        return None

    def setup_devices(self) -> bool:
        """Erstellt die virtuellen Audiogeräte (nur unter Linux)."""
        # Validate virtual device names before use (CWE-78 mitigation)
        import re
        for name, label in [
            (self.virtual_mic_name, "VIRTUAL_MIC_NAME"),
            (self.virtual_spk_name, "VIRTUAL_SPK_NAME")
        ]:
            if not re.match(r'^[a-zA-Z0-9_-]+$', name):
                logger.error(f"Ungültiger {label}: '{name}'. Nur alphanumerische Zeichen, Unterstriche und Bindestriche sind erlaubt.")
                return False

        if not self.is_linux:
            logger.info(
                f"Betriebssystem '{sys.platform}' erkannt. "
                f"Bitte stelle sicher, dass virtuelle Audiokabel installiert sind:\n"
                f"  - Windows: VB-Cable (https://vb-audio.com/Cable/)\n"
                f"  - macOS: BlackHole 2ch (brew install blackhole-2ch)"
            )
            return True

        logger.info("Richte virtuelle Audiogeräte unter Linux (PipeWire/PulseAudio) ein...")
        try:
            # 1. Erstelle das virtuelle Mikrofon (Sink, von dem Slack als Monitor aufnehmen kann)
            mic_id = self._create_null_sink(
                self.virtual_mic_name,
                "VoiceTL_Virtual_Microphone"
            )
            if mic_id:
                self.loaded_modules.append(mic_id)
                logger.info(f"Virtuelles Mikrofon '{self.virtual_mic_name}' erstellt (Module ID: {mic_id}).")
            else:
                logger.error("Fehler beim Erstellen des virtuellen Mikrofons.")
                return False

            # 2. Erstelle den virtuellen Lautsprecher (Sink, in den Slack ausgibt und den wir abgreifen)
            spk_id = self._create_null_sink(
                self.virtual_spk_name,
                "VoiceTL_Virtual_Speaker"
            )
            if spk_id:
                self.loaded_modules.append(spk_id)
                logger.info(f"Virtueller Lautsprecher '{self.virtual_spk_name}' erstellt (Module ID: {spk_id}).")
            else:
                logger.error("Fehler beim Erstellen des virtuellen Lautsprechers.")
                self.cleanup_devices()
                return False

            return True
        except Exception as e:
            logger.error(f"Unerwarteter Fehler bei der PipeWire-Konfiguration: {e}")
            logger.info("Versuche fortzufahren... Stelle sicher, dass PipeWire läuft.")
            return False

    def cleanup_devices(self):
        """Entfernt die erstellten virtuellen Audiogeräte beim Beenden."""
        if not self.is_linux or not self.loaded_modules:
            return

        logger.info("Entferne virtuelle Audiogeräte...")
        for module_id in reversed(self.loaded_modules):
            try:
                # Validate module_id is a digit before using in command (CWE-88 mitigation)
                if not str(module_id).isdigit():
                    logger.warning(f"Ungültige Modul-ID: {module_id}. Überspringe.")
                    continue
                
                # Sichere Kommandozusammenstellung (CWE-78 Mitigation)
                cmd = [self._pactl_path, "unload-module", str(module_id)]
                subprocess.run(
                    cmd,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=10  # Prevent hanging (CWE-400 mitigation)
                )
                logger.info(f"Virtuelles Gerät mit Module ID {module_id} entfernt.")
            except subprocess.TimeoutExpired:
                logger.warning(f"Timeout beim Entfernen von Modul {module_id}")
            except subprocess.CalledProcessError as e:
                # Sichere Fehlerbehandlung - keine sensiblen Daten in Logs (CWE-532)
                error_msg = e.stderr.decode().strip() if e.stderr else "Unbekannter Fehler"
                logger.warning(f"Konnte virtuelles Gerät {module_id} nicht entfernen: {error_msg}")
            except Exception as e:
                logger.warning(f"Fehler beim Entfernen von Gerät {module_id}: {safe_error_message(e, 'audio_router')}")
        self.loaded_modules.clear()

    def _create_null_sink(self, name: str, description: str) -> str:
        """Führt den pactl-Befehl aus, um ein Null-Sink zu erstellen und gibt die Modul-ID zurück."""
        # Strengere Validierung zur Verhinderung von Command Injection (CWE-78, OWASP A03:2025)
        import re
        if not re.match(r'^[a-zA-Z0-9_-]{1,64}$', name):
            logger.error(f"Ungültiger Sink-Name: '{name}'. Nur alphanumerische Zeichen, Unterstriche und Bindestriche (1-64 Zeichen) sind erlaubt.")
            raise ValueError(f"Invalid sink name: {name}. Only alphanumeric, underscore, and hyphen (1-64 chars) allowed.")

        # Validierung der Beschreibung (CWE-20)
        if not re.match(r'^[a-zA-Z0-9 _-]{1,128}$', description):
            logger.error(f"Ungültige Beschreibung: '{description}'. Nur alphanumerische Zeichen, Leerzeichen und Bindestriche (1-128 Zeichen) sind erlaubt.")
            raise ValueError(f"Invalid description: {description}. Only alphanumeric, space, and hyphen (1-128 chars) allowed.")

        if not self._pactl_path:
            logger.error("Befehl 'pactl' nicht im PATH gefunden. Ist PulseAudio/PipeWire installiert?")
            return ""

        # Sichere Kommandozusammenstellung - KEINE Shell-Interpolation (CWE-78 Mitigation)
        cmd = [
            self._pactl_path,
            "load-module",
            "module-null-sink",
            f"sink_name={name}",
            f"sink_properties=device.description={description}"
        ]
        try:
            result = subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10  # Prevent hanging (CWE-400 mitigation)
            )
            # Die Ausgabe von pactl load-module ist die Modul-ID (z. B. '24')
            module_id = result.stdout.decode().strip()
            if module_id.isdigit():
                return module_id
            logger.error(f"Unerwartete Modul-ID erhalten: {module_id}")
            return ""
        except subprocess.TimeoutExpired:
            logger.error("pactl Befehl timeout nach 10 Sekunden")
            return ""
        except subprocess.CalledProcessError as e:
            logger.error(f"pactl Befehl fehlgeschlagen: {e.stderr.decode().strip()}")
            return ""
        except FileNotFoundError:
            logger.error("Befehl 'pactl' nicht gefunden. Ist PulseAudio/PipeWire installiert?")
            return ""
        except Exception as e:
            logger.error(f"Unerwarteter Fehler bei der Modulerstellung: {e}")
            return ""
