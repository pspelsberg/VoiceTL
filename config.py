import os
import re
import argparse
from dotenv import load_dotenv

# Lade .env Datei falls vorhanden
load_dotenv()

class Config:
    def __init__(self):
        # 1. Defaults aus der Umgebung / .env laden
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.out_target_lang = os.getenv("OUT_TARGET_LANG", "en")
        self.in_target_lang = os.getenv("IN_TARGET_LANG", "de")
        
        try:
            self.min_volume_threshold_mic = float(os.getenv("MIN_VOLUME_THRESHOLD_MIC", "0.01"))
        except ValueError:
            self.min_volume_threshold_mic = 0.01

        try:
            self.min_volume_threshold_slack = float(os.getenv("MIN_VOLUME_THRESHOLD_SLACK", "0.01"))
        except ValueError:
            self.min_volume_threshold_slack = 0.01
            
        self.input_device_filter = os.getenv("INPUT_DEVICE_FILTER", "")
        self.output_device_filter = os.getenv("OUTPUT_DEVICE_FILTER", "")
        
        self.virtual_mic_name = os.getenv("VIRTUAL_MIC_NAME", "VoiceTL_Mic_Sink")
        self.virtual_spk_name = os.getenv("VIRTUAL_SPK_NAME", "VoiceTL_Slack_Out_Sink")

        try:
            self.idle_timeout = float(os.getenv("IDLE_TIMEOUT", "600"))
        except ValueError:
            self.idle_timeout = 600.0

        # 2. CLI Argumente parsen
        self._parse_args()

    def _parse_args(self):
        parser = argparse.ArgumentParser(
            description="VoiceTL: Echtzeit-Voice-Translator für Slack Huddles."
        )
        
        parser.add_argument(
            "-o", "--out-lang", 
            type=str, 
            default=self.out_target_lang,
            help=f"Zielsprache ausgehend (Standard: {self.out_target_lang})"
        )
        parser.add_argument(
            "-i", "--in-lang", 
            type=str, 
            default=self.in_target_lang,
            help=f"Zielsprache eingehend (Standard: {self.in_target_lang})"
        )
        parser.add_argument(
            "-m", "--mic-threshold", 
            type=float, 
            default=self.min_volume_threshold_mic,
            help=f"VAD-Schwellenwert für Mikrofon (Standard: {self.min_volume_threshold_mic})"
        )
        parser.add_argument(
            "-s", "--slack-threshold", 
            type=float, 
            default=self.min_volume_threshold_slack,
            help=f"VAD-Schwellenwert für Slack-In (Standard: {self.min_volume_threshold_slack})"
        )
        parser.add_argument(
            "--input-device", 
            type=str, 
            default=self.input_device_filter,
            help="Filter für echtes Mikrofon-Eingangsgerät"
        )
        parser.add_argument(
            "--output-device", 
            type=str, 
            default=self.output_device_filter,
            help="Filter für echtes Kopfhörer-Ausgangsgerät"
        )
        parser.add_argument(
            "--list-devices", 
            action="store_true",
            help="Listet alle verfügbaren Audiogeräte auf und beendet das Skript."
        )
        parser.add_argument(
            "--idle-timeout", 
            type=float, 
            default=self.idle_timeout,
            help=f"Inaktivitäts-Timeout in Sekunden bis zum automatischen API-Standby (Standard: {self.idle_timeout}, 0 zum Deaktivieren)"
        )
        
        args = parser.parse_args()
        
        # CLI Overrides anwenden
        self.out_target_lang = args.out_lang
        self.in_target_lang = args.in_lang
        self.min_volume_threshold_mic = args.mic_threshold
        self.min_volume_threshold_slack = args.slack_threshold
        self.input_device_filter = args.input_device
        self.output_device_filter = args.output_device
        self.list_devices = args.list_devices
        self.idle_timeout = args.idle_timeout

        # Falls ein Key in den CLI-Args übergeben werden soll, kann das hier ergänzt werden.
        # Aber der Standardweg ist über die Umgebung (GEMINI_API_KEY).
        if not self.api_key:
            self.api_key = os.environ.get("GEMINI_API_KEY")

    def validate_api_key(self, api_key: str) -> bool:
        """
        Validiert den API-Key-Format (CWE-287, OWASP A07:2025).
        Google API Keys haben typischerweise 39 Zeichen (Base64-ähnlich).
        """
        if not api_key:
            return False
        # Google API Keys haben typischerweise 39 Zeichen
        if len(api_key) != 39:
            return False
        # Nur alphanumerische Zeichen und Unterstriche
        if not re.match(r'^[a-zA-Z0-9_-]+$', api_key):
            return False
        return True

    def validate(self):
        """Validiert die Konfiguration."""
        if not self.api_key and not self.list_devices:
            raise ValueError(
                "Kein Gemini API-Key gefunden! Bitte setze die Umgebungsvariable "
                "GEMINI_API_KEY (z.B. `export GEMINI_API_KEY='...'`) oder trage sie in eine .env-Datei ein."
            )
        
        # API-Key-Format-Validierung (CWE-287)
        if self.api_key and not self.validate_api_key(self.api_key):
            raise ValueError(
                f"Ungültiger API-Key-Format: '{self.api_key[:8]}...'. "
                f"Erwartet 39 alphanumerische Zeichen (Google API Key Format)."
            )
            
        # Virtuelle Gerätenamen auf sicheres Muster validieren (CWE-78, OWASP A03:2025)
        import re
        for name, label in [
            (self.virtual_mic_name, "VIRTUAL_MIC_NAME"),
            (self.virtual_spk_name, "VIRTUAL_SPK_NAME")
        ]:
            if not re.match(r"^[a-zA-Z0-9_-]{1,64}$", name):
                raise ValueError(
                    f"Ungültiger Name für {label}: '{name}'. "
                    f"Nur alphanumerische Zeichen, Unterstriche und Bindestriche (1-64 Zeichen) sind erlaubt."
                )
        
        # Validierung von Spracheinstellungen (CWE-20: Input Validation)
        lang_pattern = re.compile(r'^[a-z]{2,3}$')
        if not lang_pattern.match(self.out_target_lang):
            raise ValueError(
                f"Ungültiger OUT_TARGET_LANG: '{self.out_target_lang}'. "
                f"Erwartet Sprachcode wie 'en', 'de', 'fr' (2-3 Kleinbuchstaben)."
            )
        if not lang_pattern.match(self.in_target_lang):
            raise ValueError(
                f"Ungültiger IN_TARGET_LANG: '{self.in_target_lang}'. "
                f"Erwartet Sprachcode wie 'en', 'de', 'fr' (2-3 Kleinbuchstaben)."
            )
        
        # Validierung von Schwellenwerten (CWE-20: Input Validation)
        # Erlaubt Werte zwischen 0.0 (VAD deaktiviert/immer senden) und 0.5 (realistische Obergrenze)
        MIN_THRESHOLD = 0.0
        MAX_THRESHOLD = 0.5
        if not (MIN_THRESHOLD <= self.min_volume_threshold_mic <= MAX_THRESHOLD):
            raise ValueError(
                f"Ungültiger MIN_VOLUME_THRESHOLD_MIC: {self.min_volume_threshold_mic}. "
                f"Wert muss zwischen {MIN_THRESHOLD} und {MAX_THRESHOLD} liegen."
            )
        if not (MIN_THRESHOLD <= self.min_volume_threshold_slack <= MAX_THRESHOLD):
            raise ValueError(
                f"Ungültiger MIN_VOLUME_THRESHOLD_SLACK: {self.min_volume_threshold_slack}. "
                f"Wert muss zwischen {MIN_THRESHOLD} und {MAX_THRESHOLD} liegen."
            )
        
        # Validierung von Timeout-Werten (CWE-20: Input Validation)
        MAX_IDLE_TIMEOUT = 86400  # 24 Stunden Maximum
        if self.idle_timeout < 0 or self.idle_timeout > MAX_IDLE_TIMEOUT:
            raise ValueError(
                f"Ungültiger IDLE_TIMEOUT: {self.idle_timeout}. "
                f"Wert muss zwischen 0 und {MAX_IDLE_TIMEOUT} Sekunden liegen."
            )

# Globale Instanz
config = Config()
