import asyncio
import logging
from google import genai
from google.genai import types
from google.genai.errors import APIError

logger = logging.getLogger("VoiceTL.GeminiClient")

class GeminiTranslationClient:
    """
    Verwaltet die WebSocket-Verbindung zur Gemini Live API für eine Übersetzungsrichtung.
    """
    def __init__(self, api_key: str, target_lang: str, direction_name: str):
        self.api_key = api_key
        self.target_lang = target_lang
        self.direction_name = direction_name
        self.client = genai.Client(api_key=self.api_key)
        self.model = "gemini-3.5-live-translate-preview"
        self.is_running = False
        self.session = None
        
        # Rate limiting configuration (CWE-400, LLM10:2025 mitigation)
        self.max_requests_per_second = 10  # Harte Obergrenze
        self.request_counter = 0
        self.last_second = 0
        self.rate_limit_lock = asyncio.Lock()
        self.min_request_interval = 0.1  # Minimum 100ms between requests (10 requests/second max)
        self.last_request_time = 0.0
        
        # Status für UI
        self.is_connected = False
        self.is_translating = False
        self.is_paused = False

    async def start(self, input_queue: asyncio.Queue, audio_stream):
        """Startet den Client und verbindet sich zur Gemini Live API."""
        self.is_running = True
        
        # Konfiguration für Echtzeit-Übersetzung (Dolmetscher-Modus)
        config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            translation_config=types.TranslationConfig(
                target_language_code=self.target_lang,
                echo_target_language=False
            ),
        )

        while self.is_running:
            if self.is_paused:
                self.is_connected = False
                self.is_translating = False
                self.session = None
                await asyncio.sleep(0.5)
                continue

            try:
                self.is_connected = False
                logger.info(f"[{self.direction_name}] Verbinde zur Live API (Zielsprache: {self.target_lang})...")
                
                async with self.client.aio.live.connect(model=self.model, config=config) as session:
                    self.session = session
                    self.is_connected = True
                    logger.info(f"[{self.direction_name}] Verbindung erfolgreich hergestellt.")
                    
                    # Queue leeren, um alten Ton zu verwerfen und API-Flut zu verhindern
                    while not input_queue.empty():
                        try:
                            input_queue.get_nowait()
                            input_queue.task_done()
                        except (asyncio.QueueEmpty, ValueError):
                            break
                    
                    # Tasks für Senden und Empfangen starten
                    send_task = asyncio.create_task(self._send_loop(input_queue))
                    receive_task = asyncio.create_task(self._receive_loop(audio_stream))
                    
                    # Warten bis einer der Tasks abbricht ODER der Client pausiert wird
                    while self.is_running and not self.is_paused and not send_task.done() and not receive_task.done():
                        await asyncio.sleep(0.2)
                    
                    # Offene Tasks abbrechen
                    for task in (send_task, receive_task):
                        if not task.done():
                            task.cancel()
                        
                    # Exceptions ausgeben falls vorhanden
                    for task in (send_task, receive_task):
                        try:
                            if task.done() and task.exception():
                                raise task.exception()
                        except asyncio.CancelledError:
                            pass
                            
            except asyncio.CancelledError:
                logger.info(f"[{self.direction_name}] Client abgebrochen.")
                break
            except APIError as e:
                logger.error(f"[{self.direction_name}] Gemini API Fehler: {e}")
            except Exception as e:
                logger.error(f"[{self.direction_name}] Unerwarteter Fehler: {e}")
                
            self.is_connected = False
            self.is_translating = False
            self.session = None
            
            if self.is_running and not self.is_paused:
                logger.info(f"[{self.direction_name}] Wiederverbindung in 3 Sekunden...")
                await asyncio.sleep(3)
            elif not self.is_running:
                break

    def stop(self):
        """Beendet den Client sauber."""
        self.is_running = False
        self.is_connected = False
        self.is_translating = False
        self.session = None

    async def _send_loop(self, input_queue: asyncio.Queue):
        """Liest Audio aus der Queue und sendet es an die Gemini API."""
        while self.is_running and self.session and not self.is_paused:
            try:
                chunk = await input_queue.get()
                
                # Vorkehrung zur Beendung der Queue-Warteschlange
                if chunk is None:
                    input_queue.task_done()
                    break
                
                # Rate limiting mit Token Bucket (CWE-400, LLM10:2025 mitigation)
                async with self.rate_limit_lock:
                    current_time = asyncio.get_event_loop().time()
                    
                    # Reset counter every second
                    if current_time - self.last_second >= 1.0:
                        self.request_counter = 0
                        self.last_second = current_time
                    
                    # Check if we've hit the rate limit
                    if self.request_counter >= self.max_requests_per_second:
                        # Wait until next second
                        await asyncio.sleep(1.0 - (current_time - self.last_second))
                        continue
                    
                    self.request_counter += 1
                
                # Additional rate limiting: Ensure minimum interval between requests
                current_time = asyncio.get_event_loop().time()
                elapsed = current_time - self.last_request_time
                if elapsed < self.min_request_interval:
                    await asyncio.sleep(self.min_request_interval - elapsed)
                
                # Sende Audio-Chunk an Gemini
                # Da wir mit der Live Translate API arbeiten, verwenden wir send_realtime_input
                await self.session.send_realtime_input(
                    media=types.Blob(
                        data=chunk,
                        mime_type="audio/pcm"
                    )
                )
                self.last_request_time = asyncio.get_event_loop().time()
                input_queue.task_done()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[{self.direction_name}] Fehler beim Senden von Audio: {e}")
                break

    def _validate_audio_data(self, audio_bytes: bytes) -> bool:
        """
        Validiert empfangene Audio-Daten (LLM05:2025, CWE-20).
        """
        import numpy as np
        
        # 1. Länge prüfen (max 100KB pro Chunk)
        MAX_AUDIO_CHUNK_SIZE = 100 * 1024
        if len(audio_bytes) > MAX_AUDIO_CHUNK_SIZE:
            logger.warning(f"Audio-Chunk zu groß: {len(audio_bytes)} Bytes (Max: {MAX_AUDIO_CHUNK_SIZE})")
            return False
        
        # 2. Prüfen, ob es sich um gültige PCM-Daten handelt
        try:
            audio_array = np.frombuffer(audio_bytes, dtype=np.int16)
            if len(audio_array) == 0:
                logger.warning("Leerer Audio-Chunk erhalten")
                return False
            
            # 3. Amplituden prüfen (int16: -32768 bis 32767)
            if np.any(audio_array > 32767) or np.any(audio_array < -32768):
                logger.warning("Audio-Chunk enthält ungültige Amplitudenwerte")
                return False
            
            return True
        except Exception as e:
            logger.warning(f"Ungültiges Audio-Format: {e}")
            return False

    def _validate_server_message(self, message) -> bool:
        """
        Validiert eine Server-Nachricht (LLM05:2025, CWE-20).
        """
        # 1. Prüfen, ob message gültig ist
        if message is None:
            return False
        
        # 2. Prüfen, ob server_content vorhanden ist
        if not hasattr(message, 'server_content'):
            return False
        
        return True

    async def _receive_loop(self, audio_stream):
        """Empfängt Audio von Gemini und validiert es vor dem Schreiben."""
        while self.is_running and self.session and not self.is_paused:
            try:
                async for message in self.session.receive():
                    # Validierung der Server-Nachricht (LLM05:2025)
                    if not self._validate_server_message(message):
                        logger.warning("Ungültige Server-Nachricht erhalten")
                        continue
                    
                    server_content = message.server_content
                    if server_content is not None:
                        # VAD-Statusaktualisierung für die Live-Pegelanzeige
                        self.is_translating = True
                        
                        model_turn = server_content.model_turn
                        if model_turn is not None:
                            for part in model_turn.parts:
                                if part.inline_data is not None:
                                    # Empfangene Audio-Bytes abrufen
                                    audio_bytes = part.inline_data.data
                                    
                                    # Validierung der Audio-Daten (LLM05:2025)
                                    if not self._validate_audio_data(audio_bytes):
                                        logger.warning("Ungültige Audio-Daten von Gemini erhalten. Verwerfe.")
                                        continue
                                    
                                    # In den Ausgabepuffer des Audio-Streams schreiben
                                    audio_stream.write_output_data(audio_bytes)
                                    
                        # Wenn Gemini mit der Antwort fertig ist, setzen wir den Status zurück
                        if server_content.turn_complete:
                            self.is_translating = False
                            
                    # Wenn die Antwort unterbrochen wurde (barge-in)
                    if server_content and server_content.interrupted:
                        logger.info(f"[{self.direction_name}] Gemini-Antwort unterbrochen.")
                        self.is_translating = False
                        # Leere ggf. den Ausgabepuffer des Audio-Streams um Alt-Audio zu löschen
                        # In einem Live-Übersetzer ist das meistens sinnvoll
                        with audio_stream.output_lock:
                            audio_stream.output_buffer.clear()
                            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[{self.direction_name}] Fehler beim Empfangen von Audio: {e}")
                break
