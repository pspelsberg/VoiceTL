# VoiceTL - Live Voice Translation Agent

VoiceTL (Voice Translation Live) is a lightweight, cross-platform Python tool for real-time bidirectional voice translation. It is specifically designed for use in meeting applications like **Slack Huddles**, MS Teams, or Zoom. 

The tool translates your spoken voice directly into a target language (e.g., German -> English) and routes the translated audio as a virtual microphone. At the same time, it intercepts the meeting audio, translates it back into your language (e.g., English -> German), and plays it back in your headphones.

---

## Features

* **Bidirectional Translation:** Simultaneously translates both your own voice and the voices of your meeting partners.
* **Minimal Latency:** Utilizes the specialized real-time audio model `gemini-3.5-live-translate-preview` via the new `google-genai` WebSocket SDK.
* **Automatic Audio Routing (Linux/PipeWire):** Automatically creates and manages the required virtual null-sinks (`pw-loopback`/`pactl`).
* **Cost Protection & Noise-Gate (VAD):** Integrated volume detection (RMS) streams audio to the Gemini API only when someone is actually speaking, saving token costs.
* **Live Terminal UI:** An animated VU meter level indicator shows you directly in the terminal at what volume threshold your voice is being transmitted.
* **Cross-Platform:** Fully automated on Linux (e.g., Bazzite, SteamOS, Ubuntu), and compatible with Windows (via VB-Cable) and macOS (via BlackHole).

---

## 1. Prerequisites

### Linux (Bazzite / Fedora / Ubuntu / Arch)
Make sure `pipewire-pulseaudio` and `pactl` are installed (installed by default on Bazzite).

### macOS
Install the virtual audio cable **BlackHole 2ch**:
```bash
brew install blackhole-2ch
```

### Windows
Install a virtual audio driver like **VB-Cable** (free at [vb-audio.com](https://vb-audio.com/Cable/)).

---

## 2. Installation & Setup

1. Clone the repository or navigate to the directory.
2. Create a virtual Python environment and install the dependencies:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. Copy the configuration template and adjust it if necessary:
   ```bash
   cp .env.template .env
   ```

---

## 3. Usage

### Step 1: Export API Key in the Terminal
```bash
export GEMINI_API_KEY="YOUR_GEMINI_API_KEY"
```

### Step 2: Check Available Audio Devices (Optional)
If you want to filter specific microphones or headphones, you can list the detected system IDs:
```bash
./venv/bin/python main.py --list-devices
```

### Step 3: Start the Agent
```bash
./venv/bin/python main.py
```
*On Linux, the virtual audio devices are automatically created in the background and the live display starts.*

### Step 4: Audio Settings in the Meeting Tool (e.g., Slack)
Select the following devices in the audio settings of Slack (or Zoom/Teams):
* **Microphone (Input):** `Monitor of VoiceTL_Virtual_Microphone` (or `VoiceTL_Mic_Sink`)
* **Speaker (Output):** `VoiceTL_Virtual_Speaker` (or `VoiceTL_Slack_Out_Sink`)

Your colleagues will now only hear you via the AI-generated, translated voice. You will also hear your colleagues translated.

---

## 4. Controls in the Terminal

* **Press [Enter]:** Pauses/resumes the translation (mutes the transmission).
* **Press 'q' + [Enter]:** Cleanly exits the program and removes the virtual audio devices from your system.

---

## 5. Configuration (.env)

Adjust the behavior in the `.env` file:

* `OUT_TARGET_LANG`: Target language for your voice (default: `en`).
* `IN_TARGET_LANG`: Target language for your colleagues (default: `de`).
* `MIN_VOLUME_THRESHOLD_MIC`: Threshold for your microphone. Increase this value (e.g., `0.02`) if background noise is falsely detected as speech.
* `MIN_VOLUME_THRESHOLD_SLACK`: Threshold for the Slack audio.
* `INPUT_DEVICE_FILTER` / `OUTPUT_DEVICE_FILTER`: Filters device names (e.g., `Yeti` or `SteelSeries`) if you do not want to use the system defaults.

