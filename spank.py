"""
spank.py — Windows Edition v5
Port of github.com/taigrr/spank

Now with 4 simultaneous detection methods:

  METHOD 1: Accelerometer  — physical hit/shake on laptop body
  METHOD 2: Microphone     — thud/impact on chassis
  METHOD 3: Touchscreen    — hard slap on the display
  METHOD 4: Gesture Touch  — trackpad AND touchscreen gesture mapping
             Single finger gentle  → soft whisper/breathing sounds
             Two finger touch      → gentle moan sounds
             Two finger pinch/squeeze → squeeze/gasp sounds
             Three fingers         → deeper moan sounds
             Four fingers / palm   → intense grab/gasp sounds
             Fast repeated taps    → escalating sounds (same as sexy mode)

Methods 1-3 share the main sound mode (pain/sexy/halo).
Method 4 has its OWN dedicated audio folder: audio/touch/
  audio/touch/1_single/   — soft, breathy, gentle sounds
  audio/touch/2_double/   — two-finger gentle moan sounds
  audio/touch/3_pinch/    — squeeze/gasp sounds
  audio/touch/4_triple/   — deeper moan sounds
  audio/touch/5_palm/     — intense grab/gasp sounds

USAGE:
  python spank.py --sexy          main modes: pain / sexy / halo / custom
  python spank.py --sexy --no-trackpad   disable gesture touch
  python spank.py --sexy --no-touch      disable touchscreen slap detection
  python spank.py --sexy --no-sensor     disable accelerometer
  python spank.py --sexy --no-mic        disable microphone
  python spank.py --threshold 0.12       accel sensitivity
  python spank.py --mic-db -18           mic sensitivity
  python spank.py --touch-force 10       slap contact threshold
  python spank.py --finger-cooldown 300  ms between gesture sounds (default 300)

SETUP:
  pip install sounddevice numpy scipy pygame
  pip install winrt-runtime   (optional — faster accelerometer)

AUDIO FOLDERS:
  audio/pain/          10 pain sounds (original repo)
  audio/sexy/          60 escalating sounds (original repo)
  audio/halo/          9 halo sounds (original repo)
  audio/touch/
    1_single/          soft / breathing / gentle touch sounds
    2_double/          two-finger gentle moans
    3_pinch/           pinch / squeeze / gasp sounds
    4_triple/          three-finger deeper moans
    5_palm/            full palm / grab / intense sounds
"""

import sys, os, time, math, random, threading, argparse, ctypes
import ctypes.wintypes as wt
from collections import deque

# ── deps ──────────────────────────────────────────────────────────────────────
missing = []
try:    import numpy as np
except: missing.append("numpy")
try:    import sounddevice as sd
except: missing.append("sounddevice")
try:    from scipy.signal import butter, sosfilt
except: missing.append("scipy")
try:    import pygame
except: missing.append("pygame")
if missing:
    print(f"[!] Run:  pip install {' '.join(missing)}")
    sys.exit(1)

# ── CONFIG ────────────────────────────────────────────────────────────────────
COOLDOWN_MS           = 750
GESTURE_COOLDOWN_MS   = 300    # shorter cooldown for gesture sounds
PINCH_SPEED_THRESHOLD = 8      # px/frame delta to detect pinch squeeze vs still hold
POINTER_WINDOW_MS     = 120    # time window to group simultaneous finger contacts

SEXY_MAX_LEVEL        = 60
SEXY_DECAY_RATE       = 0.92
SEXY_SCORE_PER_SLAP   = 8.0
SEXY_MAX_SCORE        = 60.0

ACCEL_POLL_HZ         = 100
ACCEL_THRESHOLD_G     = 0.18
ACCEL_STA_WINDOW      = 20
ACCEL_LTA_WINDOW      = 100
ACCEL_STA_LTA_RATIO   = 2.5

MIC_SAMPLE_RATE       = 44100
MIC_BLOCK_SIZE        = 512
MIC_THRESHOLD_DB      = -20
MIC_BG_ALPHA          = 0.995

TOUCH_MIN_FORCE       = 10

# ── AUDIO ─────────────────────────────────────────────────────────────────────
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(BASE_DIR, "audio")

def list_audio(folder):
    if not os.path.isdir(folder): return []
    exts = {".mp3", ".wav", ".ogg"}
    return sorted([
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if os.path.splitext(f)[1].lower() in exts
    ])

pygame.mixer.pre_init(44100, -16, 2, 512)
pygame.mixer.init()

# Use multiple channels so gesture sounds don't cut off main sounds
pygame.mixer.set_num_channels(8)
_main_channel    = pygame.mixer.Channel(0)   # for pain/sexy/halo
_gesture_channel = pygame.mixer.Channel(1)   # for gesture touch sounds
_play_lock       = threading.Lock()

def play_main(path):
    """Play a sound on the main channel (pain/sexy/halo)."""
    if not path or not os.path.isfile(path):
        print(f"  [!] File not found: {path}"); return
    def _do():
        with _play_lock:
            try:
                snd = pygame.mixer.Sound(path)
                _main_channel.play(snd)
            except Exception as e:
                print(f"  [!] Playback error: {e}", file=sys.stderr)
    threading.Thread(target=_do, daemon=True).start()

def play_gesture(path):
    """Play a gesture sound on the gesture channel (overlaps main channel)."""
    if not path or not os.path.isfile(path):
        print(f"  [!] File not found: {path}"); return
    def _do():
        try:
            snd = pygame.mixer.Sound(path)
            _gesture_channel.play(snd)
        except Exception as e:
            print(f"  [!] Gesture playback error: {e}", file=sys.stderr)
    threading.Thread(target=_do, daemon=True).start()


# ── GESTURE SOUND BANK ────────────────────────────────────────────────────────
class GestureSoundBank:
    """
    Loads audio for each gesture category.
    Categories map to finger count and touch style.
    """
    CATEGORIES = {
        1: "1_single",   # single finger gentle touch
        2: "2_double",   # two finger touch / gentle
        3: "3_pinch",    # pinch / squeeze gesture
        4: "4_triple",   # three fingers
        5: "5_palm",     # four+ fingers or full palm
    }

    def __init__(self):
        self.sounds   = {}
        self.last_idx = {}
        touch_dir = os.path.join(AUDIO_DIR, "touch")

        for cat_id, folder_name in self.CATEGORIES.items():
            folder = os.path.join(touch_dir, folder_name)
            files  = list_audio(folder)
            self.sounds[cat_id]   = files
            self.last_idx[cat_id] = -1
            status = f"{len(files)} files" if files else "MISSING — add sounds!"
            print(f"  [gesture] {folder_name:12s} → {status}")

    def play(self, category: int):
        """Play a random sound from category, no back-to-back repeats."""
        sounds = self.sounds.get(category, [])
        if not sounds:
            label = self.CATEGORIES.get(category, "?")
            print(f"  [gesture] *{label}* (no audio)")
            return
        choices = [i for i in range(len(sounds)) if i != self.last_idx[category]] \
                  or list(range(len(sounds)))
        idx = random.choice(choices)
        self.last_idx[category] = idx
        fname = os.path.basename(sounds[idx])
        print(f"  [gesture] cat={category} → {fname}")
        play_gesture(sounds[idx])


# ── MODES (main — pain/sexy/halo) ─────────────────────────────────────────────
class PainMode:
    def __init__(self):
        self.sounds = list_audio(os.path.join(AUDIO_DIR, "pain"))
        self.last_idx = -1
        if not self.sounds: print("  [!] No audio in audio/pain/")
    def on_slap(self, _):
        if not self.sounds: print("  *OW!*"); return
        choices = [i for i in range(len(self.sounds)) if i != self.last_idx] or list(range(len(self.sounds)))
        idx = random.choice(choices); self.last_idx = idx
        print(f"  → {os.path.basename(self.sounds[idx])}")
        play_main(self.sounds[idx])
    def name(self): return "Pain"

class SexyMode:
    def __init__(self):
        self.sounds = list_audio(os.path.join(AUDIO_DIR, "sexy"))
        self.score = 0.0; self.last_time = time.time()
        if not self.sounds: print("  [!] No audio in audio/sexy/")
    def _decay(self):
        now = time.time(); self.score *= SEXY_DECAY_RATE ** (now - self.last_time); self.last_time = now
    def on_slap(self, _):
        self._decay()
        self.score = min(self.score + SEXY_SCORE_PER_SLAP, SEXY_MAX_SCORE)
        level = max(1, math.ceil(self.score))
        print(f"  [sexy] score={self.score:.1f}  level={level}/{SEXY_MAX_LEVEL}")
        if self.sounds: play_main(self.sounds[min(level-1, len(self.sounds)-1)])
        else: print(f"  *level {level} moan*")
    def name(self): return "Sexy"

class HaloMode:
    def __init__(self):
        self.sounds = list_audio(os.path.join(AUDIO_DIR, "halo"))
        self.last_idx = -1
        if not self.sounds: print("  [!] No audio in audio/halo/")
    def on_slap(self, _):
        if not self.sounds: print("  *Halo death*"); return
        choices = [i for i in range(len(self.sounds)) if i != self.last_idx] or list(range(len(self.sounds)))
        idx = random.choice(choices); self.last_idx = idx
        print(f"  → {os.path.basename(self.sounds[idx])}")
        play_main(self.sounds[idx])
    def name(self): return "Halo"


# ── DETECTION: Accelerometer ──────────────────────────────────────────────────
def try_windows_sensor():
    if sys.platform != "win32": return None
    try:
        from winrt.windows.devices.sensors import Accelerometer  # type: ignore
        accel = Accelerometer.get_default()
        if accel is None: raise RuntimeError("none")
        accel.report_interval = max(accel.minimum_report_interval, 10)
        def get():
            r = accel.get_current_reading()
            return (r.acceleration_x, r.acceleration_y, r.acceleration_z) if r else None
        print("  ✓ Accelerometer via WinRT"); return get
    except: pass
    try:
        import subprocess
        ps = ("[Windows.Devices.Sensors.Accelerometer,Windows.Devices.Sensors,ContentType=WindowsRuntime]|Out-Null;"
              "$a=[Windows.Devices.Sensors.Accelerometer]::GetDefault();"
              "if($a){$r=$a.GetCurrentReading();\"$($r.AccelerationX),$($r.AccelerationY),$($r.AccelerationZ)\"}else{'NONE'}")
        r = subprocess.run(["powershell","-NoProfile","-Command",ps], capture_output=True, text=True, timeout=6)
        line = r.stdout.strip()
        if "NONE" in line or not line or r.returncode != 0: raise RuntimeError("none")
        map(float, line.split(","))  # validate
        print("  ✓ Accelerometer via PowerShell/WinRT")
        print("  ℹ  pip install winrt-runtime for better performance")
        def get():
            try:
                rv = subprocess.run(["powershell","-NoProfile","-Command",ps],
                                    capture_output=True, text=True, timeout=2)
                ln = rv.stdout.strip()
                if not ln or "NONE" in ln: return None
                x,y,z = map(float, ln.split(",")); return (x,y,z)
            except: return None
        return get
    except: pass
    return None

def run_accelerometer_detection(on_trigger, stop_event):
    get_reading = try_windows_sensor()
    if get_reading is None:
        print("  [sensor] No accelerometer found — skipping (mic still running)")
        return
    print(f"  ✓ Accelerometer active | {ACCEL_POLL_HZ}Hz | threshold: {ACCEL_THRESHOLD_G}g")
    interval = 1.0 / ACCEL_POLL_HZ
    sta_buf = deque(maxlen=ACCEL_STA_WINDOW)
    lta_buf = deque(maxlen=ACCEL_LTA_WINDOW)
    last_trig = 0.0
    while not stop_event.is_set():
        t0 = time.perf_counter()
        reading = get_reading()
        if reading:
            x,y,z = reading
            mag = math.sqrt(x*x + y*y + z*z)
            sta_buf.append(mag); lta_buf.append(mag)
            if len(sta_buf) == ACCEL_STA_WINDOW and len(lta_buf) >= ACCEL_LTA_WINDOW//2:
                sta = sum(sta_buf)/len(sta_buf); lta = sum(lta_buf)/len(lta_buf)
                ratio = sta/(lta+1e-9); dev = mag-lta; now = time.time()
                if dev > ACCEL_THRESHOLD_G and ratio > ACCEL_STA_LTA_RATIO:
                    if (now-last_trig)*1000 > COOLDOWN_MS:
                        last_trig = now
                        print(f"  HIT! spike={dev:.3f}g STA/LTA={ratio:.2f}")
                        threading.Thread(target=on_trigger, daemon=True).start()
        rem = interval - (time.perf_counter()-t0)
        if rem > 0: time.sleep(rem)


# ── DETECTION: Microphone ─────────────────────────────────────────────────────
def run_mic_detection(on_trigger, stop_event):
    sos = butter(4, 400.0/(MIC_SAMPLE_RATE/2), btype='low', output='sos')
    bg_rms = [0.005]; last_trig = [0.0]
    ratio_thr = 10**(-MIC_THRESHOLD_DB/20.0)
    print(f"  ✓ Microphone active | trigger: {MIC_THRESHOLD_DB} dB above background")
    def callback(indata, frames, time_info, status):
        if stop_event.is_set(): raise sd.CallbackStop()
        mono = indata[:,0] if indata.ndim > 1 else indata.flatten()
        filtered = sosfilt(sos, mono)
        rms = float(np.sqrt(np.mean(filtered**2)) + 1e-9)
        bg_rms[0] = MIC_BG_ALPHA*bg_rms[0] + (1-MIC_BG_ALPHA)*rms
        ratio = rms/(bg_rms[0]+1e-9); now = time.time()
        if ratio > ratio_thr and (now-last_trig[0])*1000 > COOLDOWN_MS:
            last_trig[0] = now
            db = 20*math.log10(ratio)
            print(f"  HIT! +{db:.1f} dB above background")
            threading.Thread(target=on_trigger, daemon=True).start()
        if rms < bg_rms[0]*0.3: bg_rms[0] *= 0.97
    try:
        with sd.InputStream(samplerate=MIC_SAMPLE_RATE, blocksize=MIC_BLOCK_SIZE,
                            channels=1, dtype='float32', callback=callback):
            while not stop_event.is_set(): time.sleep(0.05)
    except Exception as e:
        print(f"  [!] Microphone error: {e}")


# ── DETECTION: Touch + Trackpad Gesture ───────────────────────────────────────
def run_gesture_touch_detection(on_slap_trigger, gesture_bank, stop_event):
    """
    Unified handler for BOTH touchscreen and trackpad via Windows Pointer API.

    Gesture mapping:
      1 finger  gentle/still      → cat 1  (single soft touch)
      2 fingers together          → cat 2  (two-finger gentle)
      2 fingers moving inward     → cat 3  (pinch / squeeze)
      3 fingers                   → cat 4  (triple / deeper)
      4+ fingers or large area    → cat 5  (full palm / grab)
      Hard single tap (high force)→ fires on_slap_trigger (screen slap mode)

    The trackpad and touchscreen both send WM_POINTER events on Windows —
    this handler catches both surfaces with the same logic.
    """
    if sys.platform != "win32":
        print("  [gesture] Skipping — not Windows")
        return

    user32   = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    WM_DESTROY     = 0x0002
    WM_TOUCH       = 0x0240
    WM_POINTERDOWN = 0x0246
    WM_POINTERUP   = 0x0247
    WM_POINTERUPDATE = 0x0245
    WM_QUIT        = 0x0012
    CS_HREDRAW     = 0x0002
    CS_VREDRAW     = 0x0001
    IDC_ARROW      = 32512
    COLOR_WINDOW   = 5

    # ── pointer state tracking ────────────────────────────────────────────────
    # Maps pointer_id → {down_time, x, y, area, prev_x, prev_y}
    active_pointers = {}
    pointer_lock    = threading.Lock()
    last_gesture_time = [0.0]

    # For pinch detection: track distance between 2 fingers over time
    pinch_history = deque(maxlen=6)  # recent inter-finger distances

    def get_touch_info(pointer_id):
        """Read contact area and pressure from Windows pointer API."""
        class POINTER_INFO(ctypes.Structure):
            _fields_ = [("pointerType",ctypes.c_uint),("pointerId",ctypes.c_uint),
                        ("frameId",ctypes.c_uint),("pointerFlags",ctypes.c_uint),
                        ("sourceDevice",wt.HANDLE),("hwndTarget",wt.HWND),
                        ("ptPixelLocation",wt.POINT),("ptHimetricLocation",wt.POINT),
                        ("ptPixelLocationRaw",wt.POINT),("ptHimetricLocationRaw",wt.POINT),
                        ("dwTime",ctypes.c_ulong),("historyCount",ctypes.c_uint),
                        ("inputData",ctypes.c_int),("dwKeyStates",ctypes.c_ulong),
                        ("PerformanceCount",ctypes.c_ulonglong),("ButtonChangeType",ctypes.c_int)]
        class PTI(ctypes.Structure):
            _fields_ = [("pointerInfo",POINTER_INFO),("touchFlags",ctypes.c_uint),
                        ("touchMask",ctypes.c_uint),("rcContact",wt.RECT),
                        ("rcContactRaw",wt.RECT),("orientation",ctypes.c_uint),
                        ("pressure",ctypes.c_uint)]
        pti = PTI()
        if user32.GetPointerTouchInfo(pointer_id, ctypes.byref(pti)):
            rc = pti.rcContact
            area = abs(rc.right-rc.left) + abs(rc.bottom-rc.top)
            return area, pti.pressure, pti.pointerInfo.ptPixelLocation.x, pti.pointerInfo.ptPixelLocation.y
        return 0, 0, 0, 0

    def classify_and_play(finger_count, avg_area, is_pinching, is_heavy):
        """Decide which gesture category to fire based on touch profile."""
        now = time.time()
        if (now - last_gesture_time[0]) * 1000 < GESTURE_COOLDOWN_MS:
            return
        last_gesture_time[0] = now

        # Hard single tap with large force → slap trigger (screen hit)
        if finger_count == 1 and is_heavy:
            threading.Thread(target=on_slap_trigger, daemon=True).start()
            return

        # Pinch/squeeze gesture (2 fingers moving together)
        if finger_count == 2 and is_pinching:
            gesture_bank.play(3)   # pinch / squeeze / gasp
            return

        # Map finger count to category
        if finger_count == 1:
            gesture_bank.play(1)   # single gentle touch
        elif finger_count == 2:
            gesture_bank.play(2)   # two finger gentle
        elif finger_count == 3:
            gesture_bank.play(4)   # three finger deeper
        else:
            gesture_bank.play(5)   # four+ / palm grab

    WNDPROCTYPE = ctypes.WINFUNCTYPE(ctypes.c_long, wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM)

    def wnd_proc(hwnd, msg, wParam, lParam):
        if msg == WM_POINTERDOWN:
            pointer_id = wParam & 0xFFFF
            area, pressure, x, y = get_touch_info(pointer_id)
            now = time.time()

            with pointer_lock:
                active_pointers[pointer_id] = {
                    "down_time": now, "x": x, "y": y,
                    "area": area, "pressure": pressure,
                    "prev_x": x, "prev_y": y
                }
                count = len(active_pointers)
                avg_area = sum(p["area"] for p in active_pointers.values()) / max(count, 1)
                is_heavy = (area > TOUCH_MIN_FORCE * 3 or pressure > 200)

                # Pinch: check if 2 fingers are moving toward each other
                is_pinching = False
                if count == 2:
                    pts = list(active_pointers.values())
                    dist = math.sqrt((pts[0]["x"]-pts[1]["x"])**2 + (pts[0]["y"]-pts[1]["y"])**2)
                    pinch_history.append(dist)
                    if len(pinch_history) >= 3:
                        # pinch = distance decreasing rapidly
                        delta = pinch_history[-3] - pinch_history[-1]
                        is_pinching = delta > PINCH_SPEED_THRESHOLD

            # Small delay to let simultaneous fingers register together
            def _delayed_classify(fc, aa, ip, ih):
                time.sleep(0.08)
                with pointer_lock:
                    real_count = len(active_pointers)
                    real_avg   = sum(p["area"] for p in active_pointers.values()) / max(real_count, 1)
                classify_and_play(real_count, real_avg, ip, ih)

            threading.Thread(target=_delayed_classify,
                             args=(count, avg_area, is_pinching, is_heavy),
                             daemon=True).start()

        elif msg == WM_POINTERUPDATE:
            pointer_id = wParam & 0xFFFF
            area, pressure, x, y = get_touch_info(pointer_id)
            with pointer_lock:
                if pointer_id in active_pointers:
                    p = active_pointers[pointer_id]
                    p["prev_x"] = p["x"]; p["prev_y"] = p["y"]
                    p["x"] = x; p["y"] = y
                    p["area"] = area; p["pressure"] = pressure

                # Continuous pinch detection during movement
                if len(active_pointers) == 2:
                    pts = list(active_pointers.values())
                    dist = math.sqrt((pts[0]["x"]-pts[1]["x"])**2 + (pts[0]["y"]-pts[1]["y"])**2)
                    pinch_history.append(dist)
                    if len(pinch_history) >= 3:
                        delta = pinch_history[-3] - pinch_history[-1]
                        if delta > PINCH_SPEED_THRESHOLD:
                            now = time.time()
                            if (now - last_gesture_time[0]) * 1000 > GESTURE_COOLDOWN_MS:
                                last_gesture_time[0] = now
                                gesture_bank.play(3)  # squeeze sound during pinch movement

        elif msg == WM_POINTERUP:
            pointer_id = wParam & 0xFFFF
            with pointer_lock:
                active_pointers.pop(pointer_id, None)

        elif msg == WM_TOUCH:
            # Legacy fallback for older drivers
            count = wParam & 0xFFFF
            class TOUCHINPUT(ctypes.Structure):
                _fields_ = [("x",ctypes.c_long),("y",ctypes.c_long),("hSource",wt.HANDLE),
                            ("dwID",ctypes.c_ulong),("dwFlags",ctypes.c_ulong),("dwMask",ctypes.c_ulong),
                            ("dwTime",ctypes.c_ulong),("dwExtraInfo",ctypes.c_ulonglong),
                            ("cxContact",ctypes.c_ulong),("cyContact",ctypes.c_ulong)]
            arr = (TOUCHINPUT * count)()
            if user32.GetTouchInputInfo(lParam, count, arr, ctypes.sizeof(TOUCHINPUT)):
                total_area = sum(ti.cxContact + ti.cyContact for ti in arr)
                avg_area   = total_area / count if count else 0
                classify_and_play(count, avg_area, False, avg_area > 500)
                user32.CloseTouchInputHandle(lParam)

        elif msg == WM_DESTROY:
            user32.PostQuitMessage(0)

        return user32.DefWindowProcW(hwnd, msg, wParam, lParam)

    # ── create hidden window ──────────────────────────────────────────────────
    class WNDCLASSEX(ctypes.Structure):
        _fields_ = [("cbSize",ctypes.c_uint),("style",ctypes.c_uint),("lpfnWndProc",ctypes.c_void_p),
                    ("cbClsExtra",ctypes.c_int),("cbWndExtra",ctypes.c_int),("hInstance",wt.HANDLE),
                    ("hIcon",wt.HANDLE),("hCursor",wt.HANDLE),("hbrBackground",wt.HANDLE),
                    ("lpszMenuName",wt.LPCWSTR),("lpszClassName",wt.LPCWSTR),("hIconSm",wt.HANDLE)]
    try:
        hInstance  = kernel32.GetModuleHandleW(None)
        class_name = "SpankGestureWindow"
        wc = WNDCLASSEX()
        wc.cbSize      = ctypes.sizeof(WNDCLASSEX)
        wc.style       = CS_HREDRAW | CS_VREDRAW
        wc.lpfnWndProc = ctypes.cast(WNDPROCTYPE(wnd_proc), ctypes.c_void_p)
        wc.hInstance   = hInstance
        wc.hCursor     = user32.LoadCursorW(None, ctypes.cast(IDC_ARROW, wt.LPCWSTR))
        wc.hbrBackground = COLOR_WINDOW + 1
        wc.lpszClassName = class_name

        if not user32.RegisterClassExW(ctypes.byref(wc)):
            raise RuntimeError("RegisterClassExW failed")

        hwnd = user32.CreateWindowExW(0, class_name, "SpankGesture", 0,
                                       0, 0, 1, 1, None, None, hInstance, None)
        if not hwnd: raise RuntimeError("CreateWindowExW failed")

        user32.RegisterTouchWindow(hwnd, 0x00000001)
        try: user32.EnableMouseInPointer(True)
        except: pass

        print("  ✓ Gesture touch active (trackpad + touchscreen)")
        print("    1 finger → soft touch sounds")
        print("    2 fingers → gentle moan sounds")
        print("    2 fingers pinching → squeeze/gasp sounds")
        print("    3 fingers → deeper moan sounds")
        print("    4+ fingers / palm → intense grab sounds")

        msg_s = wt.MSG()
        while not stop_event.is_set():
            ret = user32.PeekMessageW(ctypes.byref(msg_s), None, 0, 0, 1)
            if ret:
                if msg_s.message == WM_QUIT: break
                user32.TranslateMessage(ctypes.byref(msg_s))
                user32.DispatchMessageW(ctypes.byref(msg_s))
            else:
                time.sleep(0.004)  # 4ms poll

        user32.DestroyWindow(hwnd)
        user32.UnregisterClassW(class_name, hInstance)

    except Exception as e:
        print(f"  [gesture] Could not start: {e}")


# ── DETECTION: Touchscreen hard slap (separate from gesture) ──────────────────
def run_touch_slap_detection(on_trigger, stop_event):
    """
    Detects hard SLAPS on the touchscreen (high force single contact).
    Separate from gesture detection — this fires the main sound mode.
    """
    if sys.platform != "win32": return

    user32   = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    WM_POINTERDOWN = 0x0246
    WM_DESTROY     = 0x0002
    WM_QUIT        = 0x0012
    CS_HREDRAW     = 0x0002
    CS_VREDRAW     = 0x0001
    IDC_ARROW      = 32512
    COLOR_WINDOW   = 5

    last_trig = [0.0]

    class WNDCLASSEX(ctypes.Structure):
        _fields_ = [("cbSize",ctypes.c_uint),("style",ctypes.c_uint),("lpfnWndProc",ctypes.c_void_p),
                    ("cbClsExtra",ctypes.c_int),("cbWndExtra",ctypes.c_int),("hInstance",wt.HANDLE),
                    ("hIcon",wt.HANDLE),("hCursor",wt.HANDLE),("hbrBackground",wt.HANDLE),
                    ("lpszMenuName",wt.LPCWSTR),("lpszClassName",wt.LPCWSTR),("hIconSm",wt.HANDLE)]

    WNDPROCTYPE = ctypes.WINFUNCTYPE(ctypes.c_long, wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM)

    def wnd_proc(hwnd, msg, wParam, lParam):
        if msg == WM_POINTERDOWN:
            pointer_id = wParam & 0xFFFF
            now = time.time()
            contact_size = 255
            try:
                class POINTER_INFO(ctypes.Structure):
                    _fields_ = [("pointerType",ctypes.c_uint),("pointerId",ctypes.c_uint),
                                ("frameId",ctypes.c_uint),("pointerFlags",ctypes.c_uint),
                                ("sourceDevice",wt.HANDLE),("hwndTarget",wt.HWND),
                                ("ptPixelLocation",wt.POINT),("ptHimetricLocation",wt.POINT),
                                ("ptPixelLocationRaw",wt.POINT),("ptHimetricLocationRaw",wt.POINT),
                                ("dwTime",ctypes.c_ulong),("historyCount",ctypes.c_uint),
                                ("inputData",ctypes.c_int),("dwKeyStates",ctypes.c_ulong),
                                ("PerformanceCount",ctypes.c_ulonglong),("ButtonChangeType",ctypes.c_int)]
                class PTI(ctypes.Structure):
                    _fields_ = [("pointerInfo",POINTER_INFO),("touchFlags",ctypes.c_uint),
                                ("touchMask",ctypes.c_uint),("rcContact",wt.RECT),
                                ("rcContactRaw",wt.RECT),("orientation",ctypes.c_uint),
                                ("pressure",ctypes.c_uint)]
                pti = PTI()
                if user32.GetPointerTouchInfo(pointer_id, ctypes.byref(pti)):
                    rc = pti.rcContact
                    contact_size = abs(rc.right-rc.left) + abs(rc.bottom-rc.top)
                    contact_size = max(contact_size, pti.pressure//4)
            except: pass

            if contact_size >= TOUCH_MIN_FORCE and (now-last_trig[0])*1000 > COOLDOWN_MS:
                last_trig[0] = now
                print(f"  TOUCH SLAP! contact={contact_size}")
                threading.Thread(target=on_trigger, daemon=True).start()
        elif msg == WM_DESTROY:
            user32.PostQuitMessage(0)
        return user32.DefWindowProcW(hwnd, msg, wParam, lParam)

    try:
        hInstance  = kernel32.GetModuleHandleW(None)
        class_name = "SpankTouchSlapWindow"
        wc = WNDCLASSEX()
        wc.cbSize = ctypes.sizeof(WNDCLASSEX); wc.style = CS_HREDRAW|CS_VREDRAW
        wc.lpfnWndProc = ctypes.cast(WNDPROCTYPE(wnd_proc), ctypes.c_void_p)
        wc.hInstance = hInstance
        wc.hCursor = user32.LoadCursorW(None, ctypes.cast(IDC_ARROW, wt.LPCWSTR))
        wc.hbrBackground = COLOR_WINDOW+1
        wc.lpszClassName = class_name
        if not user32.RegisterClassExW(ctypes.byref(wc)): raise RuntimeError("register failed")
        hwnd = user32.CreateWindowExW(0, class_name, "SpankTouchSlap", 0, 0,0,1,1, None,None,hInstance,None)
        if not hwnd: raise RuntimeError("create failed")
        user32.RegisterTouchWindow(hwnd, 0x00000001)
        try: user32.EnableMouseInPointer(True)
        except: pass
        print("  ✓ Touchscreen slap detection active")
        msg_s = wt.MSG()
        while not stop_event.is_set():
            ret = user32.PeekMessageW(ctypes.byref(msg_s), None, 0, 0, 1)
            if ret:
                if msg_s.message == WM_QUIT: break
                user32.TranslateMessage(ctypes.byref(msg_s))
                user32.DispatchMessageW(ctypes.byref(msg_s))
            else:
                time.sleep(0.005)
        user32.DestroyWindow(hwnd)
        user32.UnregisterClassW(class_name, hInstance)
    except Exception as e:
        print(f"  [touch-slap] Could not start: {e}")


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    global ACCEL_THRESHOLD_G, MIC_THRESHOLD_DB, TOUCH_MIN_FORCE, GESTURE_COOLDOWN_MS

    p = argparse.ArgumentParser(description="spank.py Windows Edition v5")
    p.add_argument("--sexy",             action="store_true")
    p.add_argument("--halo",             action="store_true")
    p.add_argument("--no-touch",         action="store_true", help="Disable touchscreen slap")
    p.add_argument("--no-sensor",        action="store_true", help="Disable accelerometer")
    p.add_argument("--no-mic",           action="store_true", help="Disable microphone")
    p.add_argument("--no-gesture",       action="store_true", help="Disable gesture touch mode")
    p.add_argument("--threshold",        type=float, default=ACCEL_THRESHOLD_G)
    p.add_argument("--mic-db",           type=float, default=MIC_THRESHOLD_DB)
    p.add_argument("--touch-force",      type=int,   default=TOUCH_MIN_FORCE)
    p.add_argument("--finger-cooldown",  type=int,   default=GESTURE_COOLDOWN_MS,
                   help="ms between gesture sounds (default 300)")
    p.add_argument("--custom",           type=str)
    args = p.parse_args()

    ACCEL_THRESHOLD_G   = args.threshold
    MIC_THRESHOLD_DB    = args.mic_db
    TOUCH_MIN_FORCE     = args.touch_force
    GESTURE_COOLDOWN_MS = args.finger_cooldown

    # Main sound mode
    if args.sexy:   mode = SexyMode()
    elif args.halo: mode = HaloMode()
    elif args.custom:
        sounds = list_audio(args.custom); last = [-1]
        class _C:
            def on_slap(self,_):
                if not sounds: print("  *sound*"); return
                c=[i for i in range(len(sounds)) if i!=last[0]] or list(range(len(sounds)))
                i=random.choice(c); last[0]=i; play_main(sounds[i])
            def name(self): return "Custom"
        mode = _C()
    else: mode = PainMode()

    # Gesture sound bank (dedicated audio/touch/ folder)
    print()
    print("  Loading gesture sounds...")
    gesture_bank = GestureSoundBank()

    # Shared cooldown for methods 1-3 (accel / mic / touch-slap)
    last_main_trigger = [0.0]
    main_lock         = threading.Lock()

    def on_main_trigger():
        with main_lock:
            now = time.time()
            if (now - last_main_trigger[0]) * 1000 < COOLDOWN_MS: return
            last_main_trigger[0] = now
        slap_count[0] += 1
        print(f"  SLAP #{slap_count[0]}", end="  ")
        mode.on_slap(slap_count[0])

    slap_count = [0]

    print()
    print("╔══════════════════════════════════════════════════════╗")
    print(f"║  spank.py  Windows Edition v5  [{mode.name():^16}] ║")
    print("╚══════════════════════════════════════════════════════╝")
    print()
    print("  Starting all 4 detection methods simultaneously...")
    print()

    stop_event = threading.Event()
    threads    = []

    def launch(name, fn, *fn_args):
        t = threading.Thread(target=fn, args=fn_args, daemon=True, name=name)
        t.start(); threads.append(t)

    if not args.no_sensor:
        launch("accel",   run_accelerometer_detection, on_main_trigger, stop_event)
    else:
        print("  [sensor]  disabled")

    if not args.no_mic:
        launch("mic",     run_mic_detection,            on_main_trigger, stop_event)
    else:
        print("  [mic]     disabled")

    if not args.no_touch:
        launch("touch",   run_touch_slap_detection,     on_main_trigger, stop_event)
    else:
        print("  [touch]   disabled")

    if not args.no_gesture:
        launch("gesture", run_gesture_touch_detection,  on_main_trigger, gesture_bank, stop_event)
    else:
        print("  [gesture] disabled")

    print()
    print("  Ready! Touch the trackpad or screen to hear sounds.")
    print("  Slap the body/screen for main sounds. Ctrl+C to quit.")
    print()

    try:
        while any(t.is_alive() for t in threads):
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n  Stopping all detectors...")

    stop_event.set()
    time.sleep(0.4)
    pygame.mixer.quit()
    print("  Goodbye.")

if __name__ == "__main__":
    main()