import sounddevice as sd
import numpy as np
import logging
import asyncio
import threading
import time
from typing import Optional, Tuple, Dict, Any

logger = logging.getLogger("VoiceTL.AudioEngine")

def find_audio_device(name_filter: str, is_input: bool) -> Optional[int]:
    """
    Sucht ein Audiogerät anhand eines Namensfilters.
    Gibt die Geräte-ID zurück oder None, wenn kein passendes Gerät gefunden wurde.
    """
    import re
    
    # Validierung des Namensfilters (CWE-20, OWASP A05:2025)
    if name_filter:
        if not re.match(r'^[a-zA-Z0-9 _\-\.\(\)]+$', name_filter):
            logger.warning(f"Ungültiger Gerätefilter: '{name_filter}'. Nur alphanumerische Zeichen, Leerzeichen, Bindestriche, Punkte und Klammern sind erlaubt.")
            return None
    
    devices = sd.query_devices()
    for idx, dev in enumerate(devices):
        # Validierung der Index-Grenzen (CWE-125)
        if idx < 0 or idx >= len(devices):
            continue
            
        # Prüfe, ob es die richtige Richtung (Input/Output) ist
        if is_input and dev['max_input_channels'] == 0:
            continue
        if not is_input and dev['max_output_channels'] == 0:
            continue
            
        # Wenn kein Filter angegeben ist, überspringen wir das manuelle Suchen (nimmt Default)
        if not name_filter:
            continue
            
        if name_filter.lower() in dev['name'].lower():
            logger.info(f"Gerät gefunden für Filter '{name_filter}': {dev['name']} (ID: {idx})")
            return idx
            
    return None

def list_available_devices():
    """Gibt alle verfügbaren Audiogeräte formatiert aus."""
    devices = sd.query_devices()
    print("\n=== Verfügbare Audiogeräte ===")
    print(f"{'ID':<4} | {'Richtung':<10} | {'Kanäle (In/Out)':<15} | {'Standard-Rate':<14} | {'Name'}")
    print("-" * 80)
    for idx, dev in enumerate(devices):
        direction = "Input" if dev['max_input_channels'] > 0 and dev['max_output_channels'] == 0 else \
                    "Output" if dev['max_output_channels'] > 0 and dev['max_input_channels'] == 0 else \
                    "In/Out"
        channels = f"{dev['max_input_channels']}/{dev['max_output_channels']}"
        print(f"{idx:<4} | {direction:<10} | {channels:<15} | {int(dev['default_samplerate']):<14} | {dev['name']}")
    print("===============================\n")

def resample_audio(audio_data: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """
    Führt ein schnelles Software-Resampling von int16 PCM-Daten mittels linearer Interpolation durch.
    """
    if len(audio_data) == 0:
        return audio_data
    if orig_sr == target_sr:
        return audio_data
        
    duration = len(audio_data) / orig_sr
    num_target_samples = int(duration * target_sr)
    
    indices = np.linspace(0, len(audio_data) - 1, num_target_samples)
    resampled = np.interp(indices, np.arange(len(audio_data)), audio_data)
    
    return resampled.astype(np.int16)

class AudioStream:
    """
    Verwaltet das nicht-blockierende Aufnehmen und Abspielen für eine Übersetzungsrichtung.
    """
    def __init__(
        self, 
        input_device_id: Optional[int], 
        output_device_id: Optional[int],
        input_rate: int = 16000, 
        output_rate: int = 24000,
        volume_threshold: float = 0.01
    ):
        self.input_device_id = input_device_id
        self.output_device_id = output_device_id
        self.target_input_rate = input_rate
        self.target_output_rate = output_rate
        self.volume_threshold = volume_threshold

        # Ausgewählte Raten (können sich nach Device-Abfrage ändern)
        self.actual_input_rate = input_rate
        self.actual_output_rate = output_rate
        self.need_input_resample = False
        self.need_output_resample = False

        # Queue für Audio-Input (von Mic zu Gemini)
        self.input_queue: Optional[asyncio.Queue] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None

        # Thread-sicherer Puffer für Audio-Output (von Gemini zu Lautsprecher)
        self.output_buffer = bytearray()
        self.output_lock = threading.Lock()

        # Monitoring
        self.current_rms = 0.0
        self.is_active = False
        self.is_paused = False

        self.stream: Optional[sd.Stream] = None

    def _determine_rates(self):
        """Ermittelt die optimalen Sampleraten für die Hardware."""
        # Input-Rate prüfen
        in_dev = sd.query_devices(self.input_device_id) if self.input_device_id is not None else sd.query_devices(device=None, kind='input')
        default_in_rate = int(in_dev['default_samplerate'])
        
        # Versuche 16kHz direkt, sonst Default-Rate und Software-Resampling
        try:
            sd.check_input_settings(
                device=self.input_device_id, 
                channels=1, 
                dtype='int16', 
                samplerate=self.target_input_rate
            )
            self.actual_input_rate = self.target_input_rate
            self.need_input_resample = False
        except Exception:
            logger.info(f"Eingabegerät unterstützt {self.target_input_rate}Hz nicht nativ. Nutze {default_in_rate}Hz + Resampling.")
            self.actual_input_rate = default_in_rate
            self.need_input_resample = True

        # Output-Rate prüfen
        out_dev = sd.query_devices(self.output_device_id) if self.output_device_id is not None else sd.query_devices(device=None, kind='output')
        default_out_rate = int(out_dev['default_samplerate'])

        try:
            sd.check_output_settings(
                device=self.output_device_id, 
                channels=1, 
                dtype='int16', 
                samplerate=self.target_output_rate
            )
            self.actual_output_rate = self.target_output_rate
            self.need_output_resample = False
        except Exception:
            logger.info(f"Ausgabegerät unterstützt {self.target_output_rate}Hz nicht nativ. Nutze {default_out_rate}Hz + Resampling.")
            self.actual_output_rate = default_out_rate
            self.need_output_resample = True

    def start(self, loop: asyncio.AbstractEventLoop, input_queue: asyncio.Queue):
        """Startet den bidirektionalen Stream."""
        self.loop = loop
        self.input_queue = input_queue
        self._determine_rates()

        # Chunk-Größe für Aufnahme (ca. 32ms)
        # 16000 Hz * 0.032s = 512 Samples
        # Wenn wir resamplen müssen, passen wir die Blockgröße entsprechend an
        block_size = int(self.actual_input_rate * 0.032)

        logger.info(f"Starte AudioStream: Input ID={self.input_device_id} ({self.actual_input_rate}Hz), "
                    f"Output ID={self.output_device_id} ({self.actual_output_rate}Hz)")


        # sounddevice erlaubt es, unterschiedliche Raten für In/Out festzulegen,
        # indem wir den Stream manuell über separate Parameter oder einheitliche Rate konfigurieren.
        # Da ein sd.Stream in der Regel EINE einheitliche Samplerate nutzt,
        # konfigurieren wir den Stream auf die actual_input_rate.
        # Das bedeutet, der Output läuft ebenfalls auf actual_input_rate und wir resamplen den
        # Gemini-Output von 24kHz auf actual_input_rate!
        
        # Korrektur für einheitlichen Stream-Takt:
        self.actual_output_rate = self.actual_input_rate
        if self.actual_output_rate != self.target_output_rate:
            self.need_output_resample = True

        self.stream = sd.Stream(
            device=(self.input_device_id, self.output_device_id),
            samplerate=self.actual_input_rate,
            channels=1,
            dtype='int16',
            blocksize=block_size,
            callback=self._audio_callback
        )
        
        self.is_active = True
        self.stream.start()

    def stop(self):
        """Stoppt den Stream."""
        self.is_active = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        logger.info("AudioStream gestoppt.")

    def write_output_data(self, data: bytes):
        """Fügt empfangenes übersetztes Audio dem Ausgabepuffer hinzu und resamplet es falls nötig."""
        if self.actual_output_rate != 24000:
            audio_array = np.frombuffer(data, dtype=np.int16)
            resampled = resample_audio(audio_array, 24000, self.actual_output_rate)
            data = resampled.tobytes()
        
        # Maximale Puffergröße: ~5 Sekunden Audio bei 24kHz/16bit/Mono (CWE-400 Mitigation)
        MAX_OUTPUT_BUFFER_SIZE = 240000
        with self.output_lock:
            # 1. Puffer bereinigen, wenn zu groß (CWE-400 mitigation)
            if len(self.output_buffer) > MAX_OUTPUT_BUFFER_SIZE:
                self.output_buffer.clear()
                logger.warning("Audio-Puffer bereinigt (zu groß geworden).")
            
            # 2. Neue Daten hinzufügen
            if len(self.output_buffer) + len(data) > MAX_OUTPUT_BUFFER_SIZE:
                # Ältere Daten abschneiden, um Platz zu machen
                excess = (len(self.output_buffer) + len(data)) - MAX_OUTPUT_BUFFER_SIZE
                del self.output_buffer[:excess]
            self.output_buffer.extend(data)

    def _safe_put_nowait(self, data_bytes: bytes):
        """Schiebt Daten in die Queue mit Rate-Limiting; verwirft bei Überlauf das älteste Element."""
        if not self.input_queue:
            return
        
        # Rate Limiting: Max 50 Chunks pro Sekunde (CWE-400 mitigation)
        current_time = time.time()
        if hasattr(self, '_last_queue_put'):
            elapsed = current_time - self._last_queue_put
            if elapsed < 0.02:  # 20ms = 50/s
                return  # Zu schnell, verwerfen
        self._last_queue_put = current_time
        
        try:
            self.input_queue.put_nowait(data_bytes)
        except asyncio.QueueFull:
            try:
                # Ältestes Paket verwerfen, um Platz zu machen
                self.input_queue.get_nowait()
                self.input_queue.put_nowait(data_bytes)
            except Exception:
                pass

    def _audio_callback(self, indata, outdata, frames, time, status):
        """Der C-Callback-Thread für Audio I/O."""
        if status:
            logger.warning(f"Audio-Status-Meldung: {status}")

        if not self.is_active:
            outdata.fill(0)
            return
            
        # Input validation: Check audio data bounds (CWE-20, OWASP A05:2025)
        MAX_SAMPLES = 4096  # 256ms bei 16kHz
        MAX_AMPLITUDE = 32767  # Max für int16
        
        if indata.size > MAX_SAMPLES:
            logger.warning(f"Ungültige Audio-Chunk-Größe: {indata.size} samples (Max: {MAX_SAMPLES}).")
            outdata.fill(0)
            return
        
        # Prüfe Amplitudenwerte (CWE-125: Out-of-bounds Read)
        if np.any(indata > 32767) or np.any(indata < -32768):
            logger.warning(f"Audio-Chunk enthält ungültige Amplitudenwerte (über {MAX_AMPLITUDE}).")
            outdata.fill(0)
            return
        
        # Prüfe Datenform (muss int16 sein)
        if indata.dtype != np.int16:
            logger.warning(f"Ungültiger Datentyp: {indata.dtype} (erwartet int16).")
            outdata.fill(0)
            return

        # ==========================================
        # 1. INPUT HANDLING (Aufnahme -> Queue)
        # ==========================================
        raw_input = indata[:, 0] # Mono-Kanal extrahieren
        
        # Berechne RMS für Lautstärke-Gating (VAD)
        # Konvertiere kurz in Float für RMS
        float_input = raw_input.astype(np.float32) / 32768.0
        rms = np.sqrt(np.mean(float_input ** 2)) if len(float_input) > 0 else 0.0
        self.current_rms = rms

        if rms >= self.volume_threshold and not self.is_paused:
            # Resampling auf 16kHz falls nötig
            if self.need_input_resample:
                processed_input = resample_audio(raw_input, self.actual_input_rate, self.target_input_rate)
            else:
                processed_input = raw_input.copy()
                
            # In bytes umwandeln und in die Asyncio-Queue schieben
            data_bytes = processed_input.tobytes()
            if self.loop and self.input_queue:
                self.loop.call_soon_threadsafe(self._safe_put_nowait, data_bytes)

        # ==========================================
        # 2. OUTPUT HANDLING (Puffer -> Lautsprecher)
        # ==========================================
        if self.is_paused:
            outdata.fill(0)
            with self.output_lock:
                self.output_buffer.clear()
            return
        # Wie viele Bytes benötigt der Ausgabepuffer für diesen Callback?
        # Frames * 2 Bytes (da int16)
        bytes_needed = frames * 2
        
        with self.output_lock:
            if len(self.output_buffer) >= bytes_needed:
                # Genügend Daten vorhanden
                chunk = self.output_buffer[:bytes_needed]
                del self.output_buffer[:bytes_needed]
            else:
                # Zu wenig Daten -> wir spielen das ab was da ist und füllen mit Stille auf (Underflow)
                chunk = bytes(self.output_buffer)
                self.output_buffer.clear()
                chunk += b'\x00' * (bytes_needed - len(chunk))

        # Konvertiere die Bytes zurück in Numpy int16
        out_array = np.frombuffer(chunk, dtype=np.int16)

        # Wenn die Samplerate von Gemini (24kHz) sich von der Stream-Output-Rate unterscheidet,
        # müssen wir den Output resamplen.
        # Da wir den Gemini-Ton stückweise erhalten, ist es oft einfacher, den Ton VOR dem
        # Schreiben in den buffer zu resamplen oder hier im Callback.
        # Der Einfachheit halber resamplen wir den Ton direkt beim Eintreffen in write_output_data!
        # Daher ist hier keine weitere Konvertierung nötig, da das bereits im Haupt-Thread gelöst wird.
        
        outdata[:, 0] = out_array
