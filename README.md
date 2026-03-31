# 🍑👋🏻🗣️🫦Spank ur laptop — Windows Edition🪟

> *A faithful Windows port of [taigrr/spank](https://github.com/taigrr/spank)*

Slap your Windows laptop, it moans back.

> "this is the most amazing thing i've ever seen" — [@kenwheeler](https://x.com/kenwheeler) *(about the original)*

The original `spank` is a macOS-only tool that uses Apple Silicon's built-in **Bosch BMI286 IMU accelerometer** (accessed via Apple's proprietary `IOKit HID` framework) to detect physical hits on a MacBook and play audio responses.

This port brings the **exact same experience to Windows** — without needing Apple's hardware. Instead, it uses a **4-in-1 parallel detection approach** that works on virtually any Windows laptop, including touchscreen 2-in-1s like the Asus Vivobook Flip.

---

## ⚡ Do You Have a Windows Accelerometer? Check First!

**Run this in PowerShell before installing:**

```powershell
Get-PnpDevice | Where-Object { $_.FriendlyName -match "sensor|accelero|gyro|motion|HID Sensor" } | Select-Object FriendlyName, Status
```

Or check visually: press `Win + X` → **Device Manager** → look for a **"Sensors"** category.

| Result | What it means |
|---|---|
| ✅ Sensor found, Status: OK | Full accelerometer support — closest to the Mac original |
| ✅ Sensor found, Status: Error | Sensor exists but driver issue — try `pip install winrt-runtime` |
| ❌ Nothing found | No hardware accelerometer — **read below, don't worry** |

### No Accelerometer? You Still Get 3 Out of 4 Methods

The accelerometer is just **one of four** detection methods. If your laptop has no accelerometer, the script detects this automatically, skips it silently, and the **remaining 3 methods run perfectly**:

```
❌  Accelerometer  — skipped automatically
✅  Microphone     — detects body thuds via low-frequency impulse analysis
✅  Touchscreen    — detects hard screen slaps via WM_POINTER contact area
✅  Gesture Touch  — detects finger/palm touches on trackpad + touchscreen
```

This means **any Windows laptop works** — even old ones with zero sensors. You just need a microphone (built into every laptop). And if you have a touchscreen, you get two bonus methods.

**Laptops most likely to have a Windows accelerometer:**
- Microsoft Surface Pro / Surface Laptop (all models)
- Asus Vivobook Flip / ZenBook Flip (360° hinge models) ✅ *confirmed*
- Lenovo Yoga / ThinkPad X1 Yoga
- HP Spectre x360 / Envy x360
- Dell XPS 13 2-in-1 / Inspiron 2-in-1
- Any convertible/tablet that auto-rotates the screen

---

## How We Solved the Sensor Problem

### The Challenge

| | Mac (Original) | Windows (This Port) |
|---|---|---|
| **Sensor** | Apple Silicon BMI286 IMU | Varies by laptop |
| **API** | Apple IOKit HID (proprietary) | Windows Sensor API / WinRT |
| **Touch slap** | Not used | ✅ Full WM_POINTER hook |
| **Gesture touch** | Not applicable | ✅ Multi-finger gesture mapping |
| **Language** | Go (compiled binary) | Python |
| **Requires sudo** | Yes | Optional (Admin recommended) |

The Mac version has one job: read Apple's private accelerometer API. On Windows, there's no single equivalent — so rather than pick one inferior substitute, we run **four detection methods simultaneously in parallel threads**, each targeting a different interaction with the laptop.

---

## The 4-in-1 Detection Approach

All four methods run at the same time. A shared cooldown lock prevents double-triggering if multiple methods catch the same hit.

```
You interact with the laptop
        │
        ├──► [Thread 1] Accelerometer (Windows Sensor API / WinRT)
        │         Reads the built-in g-sensor — the same chip Windows
        │         uses for screen auto-rotation on 2-in-1 laptops.
        │         Uses the same STA/LTA + peak deviation algorithm as
        │         the original Mac code. Best for hits on the body.
        │         → Auto-skipped silently if no accelerometer found.
        │
        ├──► [Thread 2] Microphone (Low-frequency thud detection)
        │         Reads the mic in real-time. A 400 Hz low-pass filter
        │         isolates chassis impact thuds from speech/keyboard
        │         noise. Detects slaps on palm rest, lid, or sides.
        │         → Works on EVERY laptop. Universal method.
        │
        ├──► [Thread 3] Touchscreen slap (WM_POINTER contact area)
        │         Hard slap on screen = large contact area = triggers
        │         main sound mode (pain / sexy / halo).
        │         → Requires touchscreen. Auto-skipped if none found.
        │
        └──► [Thread 4] Gesture Touch (trackpad + touchscreen)
                  Multi-finger gesture mapping. Each touch style
                  maps to a dedicated intimate sound category.
                  Runs on its own audio channel so it overlaps
                  with main sounds without cutting them off.
                  → Works on any Precision Touchpad or touchscreen.

        Threads 1–3 → shared 750ms cooldown → main sound 🔊
        Thread 4    → own 300ms cooldown    → gesture sound 🔊
        Both channels play simultaneously without interrupting each other.
```

### Method 1 — Windows Sensor API Accelerometer

We access the laptop's built-in accelerometer via the **WinRT Sensor API** (`Windows.Devices.Sensors.Accelerometer`). This is the closest Windows equivalent to Apple's IOKit accelerometer on Mac.

Detection algorithm (same as the original Mac code):
- Poll at 100 Hz
- Compute short-term average (STA) over 20 samples
- Compute long-term average (LTA) over 100 samples
- Trigger when: `peak deviation > threshold_g` AND `STA/LTA ratio > 2.5`

### Method 2 — Microphone Thud Detection

A hard slap on a laptop chassis creates a broadband low-frequency impulse (50–400 Hz). We:
1. Apply a 4th-order Butterworth low-pass filter at 400 Hz
2. Compute RMS energy per audio block
3. Maintain an adaptive background RMS (slow exponential average)
4. Trigger when the spike is `N dB` above background

Completely ignores speech and keyboard noise — both are higher-frequency and lower-energy than a body slap.

### Method 3 — Touchscreen Hard Slap

Uses a hidden Win32 message-only window with `RegisterTouchWindow()`. Every `WM_POINTERDOWN` event reports the contact area via `GetPointerTouchInfo()`. A gentle swipe has a tiny footprint; a hard slap covers a much larger area. Fires the main sound mode.

### Method 4 — Gesture Touch (Trackpad + Touchscreen)

Windows Precision Touchpad and touchscreen both send `WM_POINTER` events. We track all simultaneous pointer IDs, measure contact area and inter-finger distance, and map each gesture:

| Gesture | Detection | Sound Folder |
|---|---|---|
| 1 finger gentle | Single pointer, small area | `audio/touch/1_single/` — soft, breathy |
| 2 fingers | Two pointers within 120ms | `audio/touch/2_double/` — gentle moan |
| 2 fingers pinching | Inter-finger distance decreasing | `audio/touch/3_pinch/` — squeeze / gasp |
| 3 fingers | Three simultaneous pointers | `audio/touch/4_triple/` — deeper moan |
| 4+ fingers / palm | Four+ pointers or large area | `audio/touch/5_palm/` — intense grab |
| Hard single tap | High contact force | Fires main sexy/pain mode |

---

## Mac vs Windows Comparison

| Feature | Mac Original | Windows Port (v5) |
|---|---|---|
| **Physical hit detection** | ✅ Hardware IMU (IOKit HID) | ✅ Accelerometer + Mic + Touch + Gesture |
| **Touchscreen slap** | ❌ Not applicable | ✅ WM_POINTER contact area |
| **Mic thud detection** | ❌ Not needed | ✅ 400 Hz LPF + adaptive RMS |
| **Gesture touch** | ❌ Not applicable | ✅ 5-category finger/palm mapping |
| **Pain mode** | ✅ 10 sounds, no repeats | ✅ Same |
| **Sexy mode** | ✅ 60-level exponential decay | ✅ Same algorithm |
| **Halo mode** | ✅ Random death sounds | ✅ Same |
| **Custom mode** | ✅ `--custom /path` | ✅ Same |
| **Intimate gesture sounds** | ❌ | ✅ Dedicated `audio/touch/` bank |
| **Dual audio channels** | ❌ | ✅ Gestures + slap play simultaneously |
| **Cooldown** | 750ms | 750ms main / 300ms gesture |
| **Language** | Go | Python |
| **Dependencies** | None (single binary) | `sounddevice numpy scipy pygame` |
| **Admin required** | `sudo` always | Recommended, not required for mic |

---

## Where to Get All the Sound Files

### Pain, Sexy, and Halo sounds (Methods 1–3)

These come from the **original taigrr/spank repository**:

1. Go to **[https://github.com/taigrr/spank/releases/latest](https://github.com/taigrr/spank/releases/latest)**
2. Download the `.tar.gz` or `.zip` archive
3. Extract it — inside you'll find the `audio/` folder
4. Copy `audio/pain/`, `audio/sexy/`, and `audio/halo/` next to your `spank.py`

**Exact files included:**

| Folder | Files | Description |
|---|---|---|
| `audio/pain/` | `00_Ow.mp3` … `09_That_stings.mp3` (10 files) | Pain/protest — random, no repeats |
| `audio/sexy/` | `01.mp3` … `60.mp3` (60 files) | Sexy — level 1 (mildest) to 60 (most intense) |
| `audio/halo/` | `00.mp3` … `08.mp3` (9 files) | Halo death sounds — random, no repeats |

---

### Gesture Touch sounds (Method 4 — `audio/touch/`)

These are **your own sounds** — source and drop them in. Any MP3, WAV, or OGG works. Aim for 5–10 short clips (1–3 seconds) per folder for good variety.

**Free royalty-free sources by category:**

#### `audio/touch/1_single/` — Soft / breathy / gentle touch
- **[Pixabay](https://pixabay.com/sound-effects/search/breathing/)** (free, no attribution needed) — search: *"soft breath"*, *"exhale gentle"*, *"whisper"*
- **[ElevenLabs SFX](https://elevenlabs.io/sound-effects/asmr)** (free AI generator) — generate custom ASMR breathing from a text prompt, e.g. *"soft feminine exhale, intimate, quiet"*

#### `audio/touch/2_double/` — Two-finger gentle moan
- **[Pixabay](https://pixabay.com/sound-effects/search/moan/)** — search: *"soft moan"*, *"gentle sigh"*
- **[Freesound.org](https://freesound.org)** (free, CC license) — search: *"moan gentle"*, filter by CC0

#### `audio/touch/3_pinch/` — Pinch / squeeze / gasp
- **[Pixabay](https://pixabay.com/sound-effects/search/gasp/)** — search: *"gasp"*, *"sharp inhale"*, *"surprised breath"*
- **[Freesound.org](https://freesound.org)** — search: *"gasp female"*, *"sharp breath"*

#### `audio/touch/4_triple/` — Three-finger deeper moan
- **[Pixabay](https://pixabay.com/sound-effects/search/moan/)** — search: *"deep moan"*, *"pleasure moan"*
- **[Freesound.org](https://freesound.org)** — search: *"moan"*, filter CC0

#### `audio/touch/5_palm/` — Full palm / grab / intense
- **[Pixabay](https://pixabay.com/sound-effects/search/gasp/)** — search: *"intense gasp"*, *"pleasure gasp"*
- **[Freesound.org](https://freesound.org)** — search: *"intense moan"*, *"intimate exclamation"*

> **Format tip:** Convert any WAV files to MP3 using [Audacity](https://www.audacityteam.org/) (free) to keep sizes small and loading fast.

---

## Requirements

- Windows 10 or 11
- Python 3.8+
- Built-in microphone (universal — every laptop has one)
- Touchscreen optional (enables Methods 3 and 4 on screen)
- Accelerometer optional (enables Method 1 — 2-in-1 laptops)

Tested on: **Asus Vivobook 14 Flip TP3407** (Intel Core Ultra 5 226V)

---

## Installation

### Step 1 — Clone this repo

```powershell
git clone https://github.com/YOUR_USERNAME/spank-windows.git
cd spank-windows
```

Or create the folder structure from scratch:

```powershell
.\setup_spank.ps1
```

### Step 2 — Check for accelerometer (optional)

```powershell
Get-PnpDevice | Where-Object { $_.FriendlyName -match "sensor|accelero|gyro|motion|HID Sensor" } | Select-Object FriendlyName, Status
```

No result? The script handles it automatically — move on.

### Step 3 — Install Python dependencies

A `requirements.txt` is included in this repo. Install everything in one command:

```powershell
pip install -r requirements.txt
```

> **Virtual environment tip:** If you get a *"Unable to create process"* or *"system cannot find the file"* error, your venv path may be broken (common if your project folder name has parentheses or special characters). Use this instead:
> ```powershell
> python -m pip install -r requirements.txt
> ```

Then install the optional accelerometer package separately — it gives Python native WinRT sensor access at 100 Hz. Without it the script falls back to a PowerShell bridge that still works but polls slower (~5 Hz):

```powershell
pip install winrt-runtime
```

> `winrt-runtime` is Windows-only and intentionally left out of `requirements.txt` so the file stays cross-platform. Install it manually on Windows.

### Step 4 — Get the audio files

**Pain / Sexy / Halo** → from [taigrr/spank releases](https://github.com/taigrr/spank/releases/latest)

**Gesture sounds** → your own files from [Pixabay](https://pixabay.com/sound-effects/) or [Freesound.org](https://freesound.org) into each `audio/touch/` subfolder

### Step 5 — Enable microphone access

**Settings → Privacy & Security → Microphone** → enable for desktop apps

### Step 6 — Run it

```powershell
python spank.py --sexy
```

> Run PowerShell as Administrator for the best accelerometer access.

---

## All Run Commands — Test Every Mode on Your Laptop

Copy-paste any command below into PowerShell from your project folder to test each mode and combination. This helps you figure out which detection methods are working on your specific laptop.

```powershell
# ── FULL POWER (all 4 methods active) ──────────────────────────────
python spank.py                                                  # pain mode,  all 4 methods
python spank.py --sexy                                           # sexy mode,  all 4 methods  ← recommended
python spank.py --halo                                           # halo mode,  all 4 methods
python spank.py --custom C:\sounds                               # Custom folder

# ── Disable individual detectors ────────────────────────────────────
python spank.py --sexy --no-sensor                               # Skip accelerometer
python spank.py --sexy --no-mic                                  # Skip microphone
python spank.py --sexy --no-touch                                # Skip touchscreen slap
python spank.py --sexy --no-gesture                              # Skip gesture touch

# ── WITH ACCELEROMETER ──────────────────────────────────────────────
python spank.py --sexy --no-mic --no-touch --no-gesture          # accelerometer only
python spank.py --sexy --no-touch --no-gesture                   # accelerometer + mic
python spank.py --sexy --no-mic --no-gesture                     # accelerometer + touchscreen
python spank.py --sexy --no-mic --no-touch                       # accelerometer + gesture trackpad
python spank.py --sexy --no-mic                                  # accelerometer + touch + gesture

# ── WITHOUT ACCELEROMETER ───────────────────────────────────────────
python spank.py --sexy --no-sensor --no-mic                      # touchscreen + gesture trackpad
python spank.py --sexy --no-sensor --no-touch --no-gesture       # microphone only
python spank.py --sexy --no-sensor --no-mic --no-touch           # gesture trackpad only
python spank.py --sexy --no-sensor --no-mic --no-gesture         # touchscreen only
python spank.py --sexy --no-sensor --no-gesture                  # mic + touchscreen
python spank.py --sexy --no-sensor --no-touch                    # mic + gesture trackpad
python spank.py --sexy --no-sensor                               # mic + touchscreen + gesture

# ── SENSITIVITY TUNING ──────────────────────────────────────────────
python spank.py --sexy --threshold 0.10                          # more sensitive accelerometer
python spank.py --sexy --threshold 0.30                          # less sensitive accelerometer
python spank.py --sexy --mic-db -25                              # more sensitive mic
python spank.py --sexy --mic-db -15                              # less sensitive mic
python spank.py --sexy --touch-force 5                           # more sensitive touchscreen
python spank.py --sexy --touch-force 30                          # less sensitive touchscreen
python spank.py --sexy --finger-cooldown 150                     # faster gesture response
python spank.py --sexy --finger-cooldown 500                     # slower gesture response
```

> **How to verify each method is working on your laptop:**
> 1. Run `python spank.py --sexy --no-mic --no-touch --no-gesture` → shake/hit the laptop body → if sound plays, your accelerometer works
> 2. Run `python spank.py --sexy --no-sensor --no-touch --no-gesture` → slap the palm rest hard → if sound plays, your mic detection works
> 3. Run `python spank.py --sexy --no-sensor --no-mic --no-gesture` → slap the screen hard → if sound plays, your touchscreen detection works
> 4. Run `python spank.py --sexy --no-sensor --no-mic --no-touch` → place 2-3 fingers on trackpad → if sound plays, your gesture detection works
>
> Once you know which methods work, use the matching combination command above as your daily driver.

---

## Modes

**Pain mode** (default): Randomly plays from 10 pain/protest audio clips. Never repeats the same sound back-to-back.

**Sexy mode** (`--sexy`): Exponential decay scoring — rapid slaps climb to level 60, pauses let it cool. Identical logic to the Mac original.

**Halo mode** (`--halo`): Random Halo death sounds. No back-to-back repeats.

**Custom mode** (`--custom`): Random files from any folder you point it at.

**Gesture mode** (always active): Maps each finger/palm gesture to a dedicated sound from `audio/touch/`. Plays on its own audio channel simultaneously with any main mode.

---

## Sensitivity Tuning

### Accelerometer (`--threshold`)
| Value | Use when... |
|---|---|
| `0.05–0.12` | Light taps should trigger |
| `0.18` | Default — balanced |
| `0.25–0.40` | Only hard hits |

### Microphone (`--mic-db`)
| Value | Use when... |
|---|---|
| `-25` or lower | Quiet room, light slaps |
| `-20` | Default |
| `-15` or higher | Noisy environment |

### Touch force (`--touch-force`)
| Value | Feel |
|---|---|
| `5` | Most taps trigger |
| `10` | Default — swipes ignored |
| `30` | Hard slaps only |

### Gesture cooldown (`--finger-cooldown`)
| Value | Feel |
|---|---|
| `150ms` | Very responsive |
| `300ms` | Default |
| `500ms` | Slow, deliberate |

---

## Project Structure

```
spank-windows/
├── spank.py                # Main script (v5)
├── setup_spank.ps1         # PowerShell auto-setup
├── README.md
├── .gitignore
└── audio/
    ├── pain/               # 10 sounds  → original repo
    ├── sexy/               # 60 sounds  → original repo
    ├── halo/               # 9 sounds   → original repo
    ├── custom/             # your own   → --custom flag
    └── touch/
        ├── 1_single/       # single finger  → Pixabay / ElevenLabs
        ├── 2_double/       # two fingers    → Pixabay / Freesound
        ├── 3_pinch/        # pinch gesture  → Pixabay / Freesound
        ├── 4_triple/       # three fingers  → Pixabay / Freesound
        └── 5_palm/         # full palm      → Pixabay / Freesound
```

---

## Troubleshooting

**No sound?** — Check audio files exist in the correct folder. Run `pip install pygame`.

**Accelerometer not detected?** — Run the PowerShell check command above. Try `pip install winrt-runtime`. If still nothing, the other 3 methods work fine automatically — no action needed.

**Microphone not working?** — Settings → Privacy & Security → Microphone → enable for desktop apps. Run `python -c "import sounddevice; print(sounddevice.query_devices())"` to list devices.

**Touchscreen slap not triggering?** — Try `--touch-force 3`. Make sure you're hitting firmly — gentle taps are intentionally filtered. Check Device Manager → Human Interface Devices.

**Gesture sounds silent?** — Make sure `audio/touch/` subfolders have audio files in them. Try `--finger-cooldown 150`.

**False triggers?** — Raise `--threshold` or `--mic-db`. Disable the noisiest method with `--no-mic` or `--no-sensor`.

---

## Credits

- Original project: [taigrr/spank](https://github.com/taigrr/spank) by [@taigrr](https://github.com/taigrr)
- Sensor algorithm ported from [olvvier/apple-silicon-accelerometer](https://github.com/olvvier/apple-silicon-accelerometer)
- Windows port by [YOUR_USERNAME](https://github.com/YOUR_USERNAME)

---

## License

MIT — same as the original project.

`audio/pain/`, `audio/sexy/`, `audio/halo/` belong to [taigrr/spank](https://github.com/taigrr/spank) — get them from their releases page. `audio/touch/` files are user-supplied and not included in this repo.
