import asyncio
import logging
import re
import sys
import signal
import os
from config import config
from audio_router import VirtualAudioDeviceManager
from audio_engine import AudioStream, find_audio_device, list_available_devices
from gemini_client import GeminiTranslationClient
from terminal_ui import TerminalUI, KeyboardListener

# Logging konfigurieren mit Rotation und verschiedenen Ebenen (CWE-200 mitigation)
import logging.handlers


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


class SensitiveDataFilter(logging.Filter):
    """
    Filtert sensible Daten aus Log-Nachrichten (CWE-532, OWASP A09:2025).
    """
    def __init__(self):
        super().__init__()
        self.sensitive_patterns = [
            r'GEMINI_API_KEY=[^\s]+',
            r'API_KEY=[^\s]+',
            r'api_key=[^\s]+',
            r'[a-zA-Z0-9_-]{39}'  # Google API Key Pattern
        ]

    def filter(self, record):
        for pattern in self.sensitive_patterns:
            record.msg = re.sub(pattern, '[REDACTED_API_KEY]', str(record.msg))
            if record.args:
                record.args = tuple(
                    re.sub(pattern, '[REDACTED_API_KEY]', str(arg)) if isinstance(arg, str) else arg
                    for arg in record.args
                )
        return True

# Haupt-Logger für die Anwendung (Parent-Logger für die gesamte Hierarchie)
parent_logger = logging.getLogger("VoiceTL")
parent_logger.setLevel(logging.DEBUG)

# Logger speziell für main.py (propagiert an VoiceTL)
logger = logging.getLogger("VoiceTL.Main")

# Datei-Handler mit Rotation (max 10MB, 5 Backups)
file_handler = logging.handlers.RotatingFileHandler(
    "voicetl.log",
    maxBytes=10 * 1024 * 1024,  # 10 MB
    backupCount=5,
    encoding="utf-8"
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
))

# Console-Handler für Fehler (stderr)
console_handler = logging.StreamHandler(sys.stderr)
console_handler.setLevel(logging.ERROR)
console_handler.setFormatter(logging.Formatter(
    "%(asctime)s - ERROR - %(name)s - %(message)s"
))

# Debug-Handler für detaillierte Protokollierung (optional, nur bei Bedarf aktivieren)
debug_handler = logging.StreamHandler(sys.stdout)
debug_handler.setLevel(logging.DEBUG)
debug_handler.setFormatter(logging.Formatter(
    "%(asctime)s - DEBUG - %(name)s - %(filename)s:%(lineno)d - %(message)s"
))
# Standardmäßig deaktiviert, kann bei Bedarf aktiviert werden

# Handler dem Parent-Logger hinzufügen, damit alle Sub-Logger geschützt sind
parent_logger.addHandler(file_handler)
parent_logger.addHandler(console_handler)

# SensitiveDataFilter zu allen Handlern des Parent-Loggers hinzufügen (CWE-532, OWASP A09:2025)
sensitive_filter = SensitiveDataFilter()
for handler in parent_logger.handlers:
    handler.addFilter(sensitive_filter)

# debug_handler nur bei Bedarf aktivieren
# logger.addHandler(debug_handler)

class VoiceTLApp:
    def __init__(self):
        self.device_manager = None
        self.out_stream = None
        self.in_stream = None
        self.out_client = None
        self.in_client = None
        self.ui = None
        self.listener = None
        self.loop = None
        self._is_shutting_down = False

    async def run(self):
        self.loop = asyncio.get_running_loop()
        
        # 1. Konfiguration validieren
        try:
            config.validate()
        except ValueError as e:
            print(f"\nFehler: {e}", file=sys.stderr)
            sys.exit(1)

        # 2. Falls --list-devices gewählt wurde, Geräte anzeigen und beenden
        if config.list_devices:
            list_available_devices()
            sys.exit(0)

        # 3. Virtuelle Audiogeräte einrichten (unter Linux)
        self.device_manager = VirtualAudioDeviceManager(
            config.virtual_mic_name, 
            config.virtual_spk_name
        )
        if not self.device_manager.setup_devices() and self.device_manager.is_linux:
            print("\nFehler: Virtuelle Audiogeräte konnten unter Linux nicht initialisiert werden.", file=sys.stderr)
            logger.error("Virtuelle Audiogeräte konnten unter Linux nicht initialisiert werden.")
            sys.exit(1)

        # 4. Audiogeräte-IDs ermitteln
        logger.info("Ermittle Audiogeräte...")
        
        # Physische Geräte suchen
        real_mic_id = find_audio_device(config.input_device_filter, is_input=True)
        real_spk_id = find_audio_device(config.output_device_filter, is_output=False)
        
        # Virtuelle Geräte suchen
        # Für den ausgehenden Pfad schreiben wir in das virtuelle Mikrofon (Output des Skripts)
        virt_mic_id = find_audio_device(config.virtual_mic_name, is_output=False)
        
        # Für den eingehenden Pfad lesen wir vom Monitor des virtuellen Lautsprechers (Input des Skripts)
        # Unter PipeWire hat der Monitor oft ".monitor" im Namen oder denselben Namen als Input-Gerät
        virt_spk_id = find_audio_device(config.virtual_spk_name, is_input=True)

        logger.info(f"Gerätezuordnung:\n"
                    f"  - Physisches Mic: ID {real_mic_id} (Standard falls None)\n"
                    f"  - Virtuelles Mic (Out): ID {virt_mic_id}\n"
                    f"  - Virtueller Speaker (In): ID {virt_spk_id}\n"
                    f"  - Physische Kopfhörer: ID {real_spk_id} (Standard falls None)")

        if self.device_manager.is_linux:
            if virt_mic_id is None or virt_spk_id is None:
                print("\nFehler: Die erstellten virtuellen Audiogeräte konnten in sounddevice nicht gefunden werden.", file=sys.stderr)
                logger.error("Die erstellten virtuellen Audiogeräte konnten in sounddevice nicht gefunden werden.")
                sys.exit(1)
        else:
            if virt_mic_id is None:
                logger.warning(f"Virtuelles Mikrofon '{config.virtual_mic_name}' nicht gefunden. "
                               f"Stelle sicher, dass es erstellt wurde.")
            if virt_spk_id is None:
                logger.warning(f"Virtueller Lautsprecher '{config.virtual_spk_name}' nicht gefunden. "
                               f"Stelle sicher, dass es erstellt wurde.")

        # 5. Async-Queues initialisieren (maximale Puffergröße zur Vermeidung von Speicherüberlauf und API-Fluten)
        out_queue = asyncio.Queue(maxsize=150)
        in_queue = asyncio.Queue(maxsize=150)

        # 6. Audio-Streams initialisieren
        # Out-Stream: Liest von physischem Mic, gibt aus in virtuelles Mic
        self.out_stream = AudioStream(
            input_device_id=real_mic_id,
            output_device_id=virt_mic_id,
            input_rate=16000,
            output_rate=24000,
            volume_threshold=config.min_volume_threshold_mic
        )

        # In-Stream: Liest von virtuellem Lautsprecher, gibt aus in physische Kopfhörer
        self.in_stream = AudioStream(
            input_device_id=virt_spk_id,
            output_device_id=real_spk_id,
            input_rate=16000,
            output_rate=24000,
            volume_threshold=config.min_volume_threshold_slack
        )

        # 7. Gemini Clients initialisieren
        self.out_client = GeminiTranslationClient(
            api_key=config.api_key,
            target_lang=config.out_target_lang,
            direction_name="MIC -> SLACK"
        )
        
        self.in_client = GeminiTranslationClient(
            api_key=config.api_key,
            target_lang=config.in_target_lang,
            direction_name="SLACK -> HEADSET"
        )

        # 8. Terminal UI initialisieren
        self.ui = TerminalUI(
            config=config,
            out_stream=self.out_stream,
            in_stream=self.in_stream,
            out_client=self.out_client,
            in_client=self.in_client
        )

        # 9. Keyboard Listener initialisieren
        self.listener = KeyboardListener(self._handle_keyboard_input, self.loop)

        # 10. Signal Handler für sauberes Beenden per Ctrl+C
        def handle_signal():
            logger.info("Signal empfangen, beende...")
            asyncio.create_task(self.shutdown())
            
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                self.loop.add_signal_handler(sig, handle_signal)
            except NotImplementedError:
                # Unter Windows nicht unterstützt, dort greift KeyboardListener
                pass

        # 11. Komponenten starten
        self.out_stream.start(self.loop, out_queue)
        self.in_stream.start(self.loop, in_queue)
        
        self.ui.start()
        self.listener.start()

        # Starte die Gemini Clients parallel als Hintergrund-Tasks
        self.out_client_task = asyncio.create_task(
            self.out_client.start(out_queue, self.out_stream)
        )
        self.in_client_task = asyncio.create_task(
            self.in_client.start(in_queue, self.in_stream)
        )

        # Starte den Idle-Monitor-Task
        self.idle_monitor_task = asyncio.create_task(self._monitor_idle())

        # Halte das Programm am Laufen, bis es abgebrochen wird
        try:
            await asyncio.gather(self.out_client_task, self.in_client_task, self.idle_monitor_task)
        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()

    def _handle_keyboard_input(self, command: str):
        """Reagiert auf Tastatureingaben im Terminal."""
        if command == 'q':
            logger.info("Beenden-Befehl über Terminal empfangen.")
            asyncio.create_task(self.shutdown())
        else:
            # Enter oder andere Taste toggelt die Pause
            self.ui.toggle_pause()

    async def shutdown(self):
        """Führt ein sauberes Herunterfahren aller Komponenten durch."""
        if self._is_shutting_down:
            return
        self._is_shutting_down = True
        logger.info("Shutdown eingeleitet...")
        
        # Keyboard Listener stoppen
        if self.listener:
            self.listener.stop()
            
        # UI stoppen
        if self.ui:
            self.ui.stop()
            
        # Gemini-Clients stoppen
        if self.out_client:
            self.out_client.stop()
        if self.in_client:
            self.in_client.stop()

        # Tasks abbrechen
        if hasattr(self, 'idle_monitor_task') and not self.idle_monitor_task.done():
            self.idle_monitor_task.cancel()
        if hasattr(self, 'out_client_task') and not self.out_client_task.done():
            self.out_client_task.cancel()
        if hasattr(self, 'in_client_task') and not self.in_client_task.done():
            self.in_client_task.cancel()

        # Audio-Streams stoppen
        if self.out_stream:
            self.out_stream.stop()
        if self.in_stream:
            self.in_stream.stop()

        # Virtuelle Audiogeräte entfernen
        if self.device_manager:
            self.device_manager.cleanup_devices()

        logger.info("Shutdown abgeschlossen.")
        
        # Warten bis alle Tasks wirklich beendet sind, dann Programm beenden
        await asyncio.sleep(0.5)
        sys.exit(0)

    async def _monitor_idle(self):
        """Überwacht die Sprachaktivität und pausiert automatisch bei Inaktivität."""
        timeout = config.idle_timeout
        if timeout <= 0:
            return  # Deaktiviert
            
        logger.info(f"Idle-Monitor gestartet (Timeout: {timeout}s).")
        last_active = asyncio.get_event_loop().time()
        auto_paused = False
        
        while not self._is_shutting_down:
            try:
                await asyncio.sleep(1.0)
                
                # VAD-Status prüfen (Stimmenaktivität)
                mic_active = self.out_stream.current_rms >= config.min_volume_threshold_mic
                slack_active = self.in_stream.current_rms >= config.min_volume_threshold_slack
                
                now = asyncio.get_event_loop().time()
                if mic_active or slack_active:
                    last_active = now
                    if self.ui.is_paused and auto_paused:
                        logger.info("Sprachaktivität erkannt. Reconnect wird automatisch eingeleitet...")
                        auto_paused = False
                        self.ui.toggle_pause()
                else:
                    if not self.ui.is_paused and (now - last_active) > timeout:
                        logger.info(f"Keine Aktivität seit {timeout} Sekunden. Pausiere automatisch zur Einsparung von API-Kosten...")
                        auto_paused = True
                        self.ui.toggle_pause()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Fehler im Idle-Monitor: {e}")

if __name__ == "__main__":
    app = VoiceTLApp()
    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        pass
