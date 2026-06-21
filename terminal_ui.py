import sys
import asyncio
import logging
import threading
from typing import Callable
from config import Config

logger = logging.getLogger("VoiceTL.TerminalUI")

def make_vu_bar(rms: float, threshold: float, max_chars: int = 10) -> str:
    """Erstellt eine grafische VU-Meter-Zeile mit Schwellenwert-Markierung."""
    # RMS auf Bereich 0.0 bis 0.05 skalieren
    val = min(rms / 0.05, 1.0)
    num_chars = int(val * max_chars)
    
    thresh_val = min(threshold / 0.05, 1.0)
    thresh_pos = int(thresh_val * max_chars)
    
    bar = ""
    for i in range(max_chars):
        if i < num_chars:
            if i >= thresh_pos:
                bar += "█"  # Aktiv über Threshold (wird gesendet)
            else:
                bar += "▒"  # Pegel registriert aber unter Threshold
        else:
            if i == thresh_pos:
                bar += "│"  # Schwellenwert-Linie
            else:
                bar += "░"  # Stille
    return bar

class KeyboardListener:
    """
    Liest asynchron Tastatureingaben im Hintergrund-Thread (cross-platform kompatibel).
    """
    def __init__(self, callback: Callable[[str], None], loop: asyncio.AbstractEventLoop):
        self.callback = callback
        self.loop = loop
        self.is_running = False
        self.thread = None

    def start(self):
        self.is_running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.is_running = False

    def _run(self):
        while self.is_running:
            try:
                line = sys.stdin.readline()
                if not line:  # EOF erreicht (z. B. stdin geschlossen oder im Hintergrund)
                    break
                line = line.strip().lower()
                if not self.is_running:
                    break
                # Callback im asyncio Thread ausführen
                self.loop.call_soon_threadsafe(self.callback, line)
            except Exception:
                break

class TerminalUI:
    """
    Erstellt ein schickes Live-VU-Meter und gibt den Status der Übersetzungen aus.
    """
    def __init__(
        self, 
        config: Config,
        out_stream,  # AudioStream ausgehend
        in_stream,   # AudioStream eingehend
        out_client,  # GeminiTranslationClient ausgehend
        in_client    # GeminiTranslationClient eingehend
    ):
        self.config = config
        self.out_stream = out_stream
        self.in_stream = in_stream
        self.out_client = out_client
        self.in_client = in_client
        
        self.is_running = False
        self.is_paused = False
        self.task = None

    def start(self):
        self.is_running = True
        self.task = asyncio.create_task(self._update_loop())
        # Header ausgeben
        print("\n" + "=" * 60)
        print("   VoiceTL - Live Voice Translation Agent gestartet")
        print("=" * 60)
        print(f"   Eigener Ton (Out)   : {self.config.out_target_lang.upper()}")
        print(f"   Kollegen Ton (In)   : {self.config.in_target_lang.upper()}")
        print("-" * 60)
        print("   Befehle im Terminal:")
        print("     - [Enter] drücken  : Pause an/aus")
        print("     - 'q' + [Enter]    : Beenden")
        print("=" * 60 + "\n")

    def stop(self):
        self.is_running = False
        if self.task:
            self.task.cancel()
        # Zeile freigeben beim Beenden
        sys.stdout.write("\n")
        sys.stdout.flush()

    def toggle_pause(self):
        self.is_paused = not self.is_paused
        
        # Streams pausieren/fortsetzen
        if self.out_stream:
            self.out_stream.is_paused = self.is_paused
        if self.in_stream:
            self.in_stream.is_paused = self.is_paused
            
        # Clients pausieren/fortsetzen (verursacht autom. Disconnect bei Pause zur Ressourcenschonung)
        if self.out_client:
            self.out_client.is_paused = self.is_paused
        if self.in_client:
            self.in_client.is_paused = self.is_paused
            
        if self.is_paused:
            logger.info("Übersetzung PAUSIERT (API-Verbindung getrennt).")
        else:
            logger.info("Übersetzung FORTGESETZT (Verbindung wird aufgebaut).")

    async def _update_loop(self):
        while self.is_running:
            try:
                # 10 mal pro Sekunde aktualisieren
                await asyncio.sleep(0.1)
                self._draw()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Fehler beim Zeichnen der UI: {e}")

    def _draw(self):
        if self.is_paused:
            status_text = "PAUSIERT (Drücke Enter zum Fortsetzen)"
            # VU-Bars zeigen Null an
            out_bar = "░" * 10
            in_bar = "░" * 10
        else:
            # 1. Ausgehende Leitung (Mic)
            out_status = "Aktiv" if self.out_stream.current_rms >= self.config.min_volume_threshold_mic else "Stille"
            out_conn = "Verbunden" if self.out_client.is_connected else "Verbinde..."
            out_trans = " (Übersetzt)" if self.out_client.is_translating else ""
            
            # 2. Eingehende Leitung (Slack Out)
            in_status = "Aktiv" if self.in_stream.current_rms >= self.config.min_volume_threshold_slack else "Stille"
            in_conn = "Verbunden" if self.in_client.is_connected else "Verbinde..."
            in_trans = " (Übersetzt)" if self.in_client.is_translating else ""
            
            out_bar = make_vu_bar(self.out_stream.current_rms, self.config.min_volume_threshold_mic, 10)
            in_bar = make_vu_bar(self.in_stream.current_rms, self.config.min_volume_threshold_slack, 10)
            
            status_text = (
                f"Out: {out_conn:<10} | In: {in_conn:<10}"
            )

        # UI Zeile zusammenbauen (löscht die Zeile davor mit \r und \033[K)
        sys.stdout.write(
            f"\r[MIC: {out_bar}] [SLACK: {in_bar}] | {status_text}\033[K"
        )
        sys.stdout.flush()
