import ctypes
import json
import threading
import time
import math
import os
import socket
import sys
import winreg
from ctypes import windll, byref, Structure, c_void_p, c_int, c_ushort, POINTER, c_wchar_p, c_wchar, WINFUNCTYPE

# Librerie esterne
import keyboard
import pystray
from PIL import Image, ImageDraw
import customtkinter as ctk

APP_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_RUN_NAME = "NVFT"

# --- CONFIGURAZIONE ---

CONFIG_FILE = "settings.json"
PRESETS_FILE = "presets.json"
ICON_FILE = "icon.png"
HOTKEY = "ctrl+f10"
LOCAL_PORT = 65432

CURRENT_KEYS_DOWN = set()
RECORDING_MODE = False
RECORDING_CALLBACK = None
OLD_HOTKEY_FOR_RECORD = None
LAST_COMBO_PRESSED = set()

# Configurazione GUI - DARK THEME
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

# Palette dark ultra moderna
BG_COLOR = "#050509"          
CARD_BG = "#12131a"           
CARD_ALT_BG = "#181924"       
BORDER_COLOR = "#2b2e40"      
ACCENT = "#001d5a"            
ACCENT_DARK = "#001d5a"
DANGER = "#5A0302"
SUCCESS = "#359e3b"
TEXT_MAIN = "#ffffff"
TEXT_MUTED = "#9aa0b5"
SECTION_LABEL = "#7a8098"

# DEFAULT SETTINGS
DEFAULT_SETTINGS = {
    "brightness": 0.53,
    "contrast": 0.85,
    "gamma": 2.4,
    "red_scale": 1.0,
    "green_scale": 1.0,
    "blue_scale": 1.0
}

# --- STRUTTURE WINDOWS API ---

class RAMP(Structure):
    _fields_ = [("Red", c_ushort * 256), ("Green", c_ushort * 256), ("Blue", c_ushort * 256)]

class RECT(Structure):
    _fields_ = [("left", c_int), ("top", c_int), ("right", c_int), ("bottom", c_int)]

class MONITORINFOEX(Structure):
    _fields_ = [
        ("cbSize", c_int),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", c_int),
        ("szDevice", c_wchar * 32)
    ]

windll.gdi32.CreateDCW.argtypes = [c_wchar_p, c_wchar_p, c_wchar_p, c_void_p]
windll.gdi32.CreateDCW.restype = c_void_p
windll.gdi32.DeleteDC.argtypes = [c_void_p]
windll.gdi32.SetDeviceGammaRamp.argtypes = [c_void_p, POINTER(RAMP)]
windll.gdi32.GetDeviceGammaRamp.argtypes = [c_void_p, POINTER(RAMP)]
MonitorEnumProc = WINFUNCTYPE(c_int, c_void_p, c_void_p, POINTER(RECT), c_int)

# --- FUNZIONI DI SISTEMA ---

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def get_primary_monitor_name():
    primary_name = []

    def callback(hMonitor, hdcMonitor, lprcMonitor, dwData):
        mon_info = MONITORINFOEX()
        mon_info.cbSize = ctypes.sizeof(MONITORINFOEX)
        if windll.user32.GetMonitorInfoW(hMonitor, byref(mon_info)):
            if mon_info.dwFlags & 1:
                primary_name.append(mon_info.szDevice)
                return 0
        return 1

    windll.user32.EnumDisplayMonitors(None, None, MonitorEnumProc(callback), 0)
    return primary_name[0] if primary_name else None

def get_monitor_dc():
    device_name = get_primary_monitor_name()
    if device_name:
        return windll.gdi32.CreateDCW(None, device_name, None, None)
    return windll.gdi32.CreateDCW("DISPLAY", None, None, None)

def create_linear_ramp():
    ramp = RAMP()
    for i in range(256):
        val = int((i / 255.0) * 65535)
        ramp.Red[i] = ramp.Green[i] = ramp.Blue[i] = val
    return ramp

def set_autostart(enabled: bool):
    exe_path = sys.executable
    # Se è impacchettato in exe, sys.argv[0] è il percorso dell'exe
    if exe_path.lower().endswith("python.exe") or exe_path.lower().endswith("pythonw.exe"):
        target = os.path.abspath(sys.argv[0])
    else:
        target = exe_path

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, APP_RUN_KEY, 0, winreg.KEY_ALL_ACCESS)
    except FileNotFoundError:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, APP_RUN_KEY)

    if enabled:
        winreg.SetValueEx(key, APP_RUN_NAME, 0, winreg.REG_SZ, f'"{target}"')
    else:
        try:
            winreg.DeleteValue(key, APP_RUN_NAME)
        except FileNotFoundError:
            pass

    winreg.CloseKey(key)

def is_autostart_enabled():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, APP_RUN_KEY, 0, winreg.KEY_READ)
        try:
            _val, _type = winreg.QueryValueEx(key, APP_RUN_NAME)
            winreg.CloseKey(key)
            return True
        except FileNotFoundError:
            winreg.CloseKey(key)
            return False
    except FileNotFoundError:
        return False
    
def keys_to_hotkey_string(keys: set[str]) -> str:
    # Ordine “standard”
    order = ["ctrl", "shift", "alt", "alt gr", "windows"]
    mods = []
    others = []

    for k in keys:
        lk = k.lower()
        if lk in order:
            mods.append(lk)
        else:
            others.append(lk)

    # ordina mods secondo "order"
    mods_sorted = [m for m in order if m in mods]
    # ordina gli altri per avere qualcosa di stabile
    others_sorted = sorted(others)

    parts = mods_sorted + others_sorted
    return "+".join(parts)

def global_key_down(event):
    global CURRENT_KEYS_DOWN, LAST_COMBO_PRESSED
    key = event.name
    CURRENT_KEYS_DOWN.add(key)
    LAST_COMBO_PRESSED = CURRENT_KEYS_DOWN.copy()

def global_key_up(event):
    global CURRENT_KEYS_DOWN, LAST_COMBO_PRESSED, RECORDING_MODE, RECORDING_CALLBACK
    key = event.name
    if key in CURRENT_KEYS_DOWN:
        CURRENT_KEYS_DOWN.remove(key)

    if RECORDING_MODE and not CURRENT_KEYS_DOWN and RECORDING_CALLBACK:
        # tutti i tasti rilasciati: usa LAST_COMBO_PRESSED
        combo_str = keys_to_hotkey_string(LAST_COMBO_PRESSED)
        cb = RECORDING_CALLBACK
        RECORDING_CALLBACK = None
        RECORDING_MODE = False
        cb(combo_str)

keyboard.on_press(global_key_down)
keyboard.on_release(global_key_up)

# --- GESTIONE STATO ---

class DisplayState:
    def __init__(self):
        self.active = False
        self.original_ramp = RAMP()
        self.current_settings = DEFAULT_SETTINGS.copy()
        self.default_settings = DEFAULT_SETTINGS.copy()
        self.presets = {}  # dizionario nome_preset -> impostazioni
        self.ui_callback = None
        self.autostart_enabled = is_autostart_enabled()  
        self.always_on_top = True  # default attivo      

        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    loaded = json.load(f)
                self.current_settings.update(loaded)
                self.default_settings.update(loaded)
                self.autostart_enabled = bool(loaded.get("autostart", False))
                if "always_on_top" in loaded:
                    self.always_on_top = bool(loaded["always_on_top"])
            except:
                pass
        
        # Carica presets salvati
        if os.path.exists(PRESETS_FILE):
            try:
                with open(PRESETS_FILE, 'r') as f:
                    self.presets = json.load(f)
            except:
                self.presets = {}
        
        if not os.path.exists(CONFIG_FILE):
            self.save_settings()
        
        dc = get_monitor_dc()
        if dc:
            if not windll.gdi32.GetDeviceGammaRamp(dc, byref(self.original_ramp)):
                self.original_ramp = create_linear_ramp()
            windll.gdi32.DeleteDC(dc)
        else:
            self.original_ramp = create_linear_ramp()

    def set_ui_callback(self, callback):
        self.ui_callback = callback

    def trigger_ui_update(self):
        if self.ui_callback:
            self.ui_callback()

    def save_settings(self):
        try:
            data = self.current_settings.copy()
            data["autostart"] = self.autostart_enabled
            data["always_on_top"] = self.always_on_top

            # salva anche la hotkey corrente (se impostata)
            if "hotkey" in self.current_settings:
                data["hotkey"] = self.current_settings["hotkey"]

            with open(CONFIG_FILE, 'w') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"Error saving settings: {e}")

    def update_setting(self, key, value):
        self.current_settings[key] = value
        if self.active:
            self.apply_custom_settings()

    def restore_defaults(self):
        dc = get_monitor_dc()
        if dc:
            windll.gdi32.SetDeviceGammaRamp(dc, byref(self.original_ramp))
            windll.gdi32.DeleteDC(dc)
        self.active = False
        self.trigger_ui_update()

    def apply_custom_settings(self):
        try:
            s = self.current_settings

            b_input = float(s["brightness"])
            c_input = float(s["contrast"])
            gamma_val = max(0.1, float(s["gamma"]))
            r_scale = float(s.get("red_scale", 1.0))
            g_scale = float(s.get("green_scale", 1.0))
            b_scale = float(s.get("blue_scale", 1.0))

            brightness_offset = b_input - 0.5
            contrast_gain = c_input * 2.0

            new_ramp = RAMP()
            for i in range(256):
                val = i / 255.0
                val = math.pow(val, 1.0 / gamma_val)
                val = val + brightness_offset
                val = (val - 0.5) * contrast_gain + 0.5
                val = max(0.0, min(1.0, val))

                new_ramp.Red[i] = int(max(0, min(65535, val * 65535 * r_scale)))
                new_ramp.Green[i] = int(max(0, min(65535, val * 65535 * g_scale)))
                new_ramp.Blue[i] = int(max(0, min(65535, val * 65535 * b_scale)))

            dc = get_monitor_dc()
            if dc:
                windll.gdi32.SetDeviceGammaRamp(dc, byref(new_ramp))
                self.active = True
                windll.gdi32.DeleteDC(dc)

            self.trigger_ui_update()
        except Exception as e:
            print(f"Error applying settings: {e}")
            self.restore_defaults()

    def toggle(self):
        if self.active:
            self.restore_defaults()
        else:
            self.apply_custom_settings()
    
    def save_preset(self, preset_name):
        """Salva le impostazioni correnti come preset"""
        preset_data = {
            "brightness": self.current_settings["brightness"],
            "contrast": self.current_settings["contrast"],
            "gamma": self.current_settings["gamma"],
            "red_scale": self.current_settings["red_scale"],
            "green_scale": self.current_settings["green_scale"],
            "blue_scale": self.current_settings["blue_scale"]
        }
        self.presets[preset_name] = preset_data
        self.save_presets_to_file()
    
    def load_preset(self, preset_name):
        """Carica un preset salvato"""
        if preset_name in self.presets:
            preset_data = self.presets[preset_name]
            for key, value in preset_data.items():
                self.current_settings[key] = value
            if self.active:
                self.apply_custom_settings()
            self.trigger_ui_update()
            return True
        return False
    
    def delete_preset(self, preset_name):
        """Elimina un preset"""
        if preset_name in self.presets:
            del self.presets[preset_name]
            self.save_presets_to_file()
            return True
        return False
    
    def rename_preset(self, old_name, new_name):
        """Rinomina un preset"""
        if old_name in self.presets and new_name not in self.presets:
            self.presets[new_name] = self.presets.pop(old_name)
            self.save_presets_to_file()
            return True
        return False
    
    def get_preset_names(self):
        """Ottieni lista nomi preset ordinati alfabeticamente"""
        return sorted(self.presets.keys())
    
    def save_presets_to_file(self):
        """Salva i preset su file"""
        try:
            with open(PRESETS_FILE, 'w') as f:
                json.dump(self.presets, f, indent=4)
        except Exception as e:
            print(f"Error saving presets: {e}")

state = DisplayState()

# --- INTERFACCIA GRAFICA DARK ULTRA MODERNA ---

class SettingsApp(ctk.CTk):
    def __init__(self, state_obj):
        super().__init__()
        
        self.attributes("-topmost", True)

        self.display_state = state_obj
        self.display_state.set_ui_callback(self.thread_safe_update)
        
        # always on top secondo preferenza
        self.attributes("-topmost", self.display_state.always_on_top)

        self.title("NVFT Control")
        self.geometry("420x650")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.recording_hotkey = False

        # Sfondo principale
        self.configure(fg_color=BG_COLOR)

        # Layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        

        # --- HEADER ---
        self.header_frame = ctk.CTkFrame(
            self,
            corner_radius=0,
            fg_color=BG_COLOR
        )
        self.header_frame.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 10))

        self.lbl_title = ctk.CTkLabel(
            self.header_frame,
            text="Night Vision",
            font=("Segoe UI", 24, "bold"),
            text_color=TEXT_MAIN
        )
        self.lbl_title.pack(side="left")

        self.status_badge = ctk.CTkLabel(
            self.header_frame,
            text="OFF",
            font=("Segoe UI", 12, "bold"),
            text_color=TEXT_MAIN,
            fg_color=DANGER,
            corner_radius=999,
            width=60,
            height=24
        )
        self.status_badge.pack(side="right", pady=4)

        # Click sul badge -> toggle filtro
        self.status_badge.bind("<Button-1>", lambda e: self.toggle_via_gui())

        # --- CONTENUTO SCROLLABILE ---
        self.scroll_frame = ctk.CTkScrollableFrame(
            self,
            corner_radius=16,
            fg_color=BG_COLOR,
            border_width=0
        )
        self.scroll_frame.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 8))

        # CARD 1: Luminance
        self.create_section_header("LUMINANCE")

        self.card_luminance = ctk.CTkFrame(
            self.scroll_frame,
            corner_radius=14,
            fg_color=CARD_BG,
            border_width=1,
            border_color=BORDER_COLOR
        )
        self.card_luminance.pack(fill="x", pady=(0, 14))

        self.sliders = {}
        self.create_slider(self.card_luminance, "Brightness", "brightness", 0.0, 1.0, 0.01)
        self.create_slider(self.card_luminance, "Contrast", "contrast", 0.0, 1.0, 0.01)
        self.create_slider(self.card_luminance, "Gamma", "gamma", 0.1, 5.0, 0.1)

        # CARD 2: Color Balance
        self.create_section_header("COLOR CHANNELS")

        self.card_color = ctk.CTkFrame(
            self.scroll_frame,
            corner_radius=14,
            fg_color=CARD_ALT_BG,
            border_width=1,
            border_color=BORDER_COLOR
        )
        self.card_color.pack(fill="x", pady=(0, 14))

        self.create_slider(self.card_color, "Red Boost", "red_scale", 0.0, 2.0, 0.05)
        self.create_slider(self.card_color, "Green Boost", "green_scale", 0.0, 2.0, 0.05)
        self.create_slider(self.card_color, "Blue Boost", "blue_scale", 0.0, 2.0, 0.05)

        # CARD 3: Presets
        self.create_section_header("PRESETS")

        self.card_presets = ctk.CTkFrame(
            self.scroll_frame,
            corner_radius=14,
            fg_color=CARD_BG,
            border_width=1,
            border_color=BORDER_COLOR
        )
        self.card_presets.pack(fill="x", pady=(0, 14))

        self.build_presets_section(self.card_presets)

        self.create_section_header("GENERAL")

        self.card_general = ctk.CTkFrame(
            self.scroll_frame,
            corner_radius=14,
            fg_color=CARD_BG,
            border_width=1,
            border_color=BORDER_COLOR
        )
        self.card_general.pack(fill="x", pady=(0, 14))

        self.build_general_settings(self.card_general)

        self.update_status_visuals()

    def create_section_header(self, text):
        lbl = ctk.CTkLabel(
            self.scroll_frame,
            text=text,
            font=("Segoe UI", 11, "bold"),
            text_color=SECTION_LABEL
        )
        lbl.pack(anchor="w", padx=4, pady=(8, 6))

    def create_slider(self, parent, label_text, setting_key, min_val, max_val, step):
        container = ctk.CTkFrame(parent, fg_color="transparent")
        container.pack(fill="x", padx=14, pady=8)

        head = ctk.CTkFrame(container, fg_color="transparent")
        head.pack(fill="x", pady=(0, 2))

        lbl = ctk.CTkLabel(
            head,
            text=label_text,
            font=("Segoe UI", 13, "bold"),
            text_color=TEXT_MAIN
        )
        lbl.pack(side="left")

        val_lbl = ctk.CTkLabel(
            head,
            text="0.00",
            font=("Consolas", 12),
            text_color=TEXT_MUTED
        )
        val_lbl.pack(side="right")

        slider = ctk.CTkSlider(
            container,
            from_=min_val,
            to=max_val,
            number_of_steps=int((max_val - min_val) / step),
            border_width=0,
            height=18,
            fg_color="#1f2230",
            progress_color=ACCENT,
            button_color="#f5f5f5",
            button_hover_color="#e0e0e0"
        )
        slider.pack(fill="x", pady=(2, 0))

        # Valore iniziale
        current_val = self.display_state.current_settings.get(
            setting_key,
            self.display_state.default_settings.get(setting_key, 1.0)
        )
        slider.set(current_val)
        val_lbl.configure(text=f"{current_val:.2f}")

        def on_change(val):
            v = float(val)
            val_lbl.configure(text=f"{v:.2f}")
            self.display_state.update_setting(setting_key, v)

        slider.configure(command=on_change)

        # Doppio click per reset al default
        def on_double_click(event):
            default_val = self.display_state.default_settings.get(setting_key, 1.0)
            slider.set(default_val)
            val_lbl.configure(text=f"{default_val:.2f}")
            self.display_state.update_setting(setting_key, float(default_val))

        slider.bind("<Double-Button-1>", on_double_click)

        self.sliders[setting_key] = {"slider": slider, "label": val_lbl}

    def thread_safe_update(self):
        self.after(0, self.update_status_visuals)

    def toggle_via_gui(self):
        self.display_state.toggle()

    def update_status_visuals(self):
        is_active = self.display_state.active
        if is_active:
            self.status_badge.configure(text="ACTIVE", fg_color=SUCCESS)

        else:
            self.status_badge.configure(text="OFF", fg_color=DANGER)


    def hide_window(self):
        self.display_state.save_settings()
        self.withdraw()

    def show_window(self):
        self.deiconify()
        self.lift()
        self.attributes("-topmost", self.display_state.always_on_top)
        self.focus_force()
        
    def build_general_settings(self, parent):
        # Shortcut row
        row1 = ctk.CTkFrame(parent, fg_color="transparent")
        row1.pack(fill="x", padx=14, pady=(10, 6))

        lbl_shortcut = ctk.CTkLabel(
            row1,
            text="Toggle shortcut",
            font=("Segoe UI", 13),
            text_color=TEXT_MAIN
        )
        lbl_shortcut.pack(side="left")

        self.shortcut_var = ctk.StringVar(
            value=self.display_state.current_settings.get("hotkey", HOTKEY)
        )
        self.shortcut_entry = ctk.CTkEntry(
            row1,
            textvariable=self.shortcut_var,
            width=180,
            font=("Consolas", 12),
            corner_radius=8,
            state="readonly"
        )
        self.shortcut_entry.pack(side="right")

        # click = entra in modalità ascolto
        self.shortcut_entry.bind("<Button-1>", lambda e: self.start_hotkey_recording())

        # Etichetta hint sotto
        hint = ctk.CTkLabel(
            parent,
            text="Example: ctrl+f10, alt+shift+f9",
            font=("Segoe UI", 12, "bold"),
            text_color=TEXT_MUTED
        )
        hint.pack(anchor="e", padx=14, pady=(0, 8))

        # Checkbox avvio automatico
        row2 = ctk.CTkFrame(parent, fg_color="transparent")
        row2.pack(fill="x", padx=14, pady=(6, 12))

        lbl_autostart = ctk.CTkLabel(
            row2,
            text="Launch at system startup",
            font=("Segoe UI", 12),
            text_color=TEXT_MAIN
        )
        lbl_autostart.pack(side="left")

        self.autostart_var = ctk.BooleanVar(value=self.display_state.autostart_enabled)
        self.autostart_checkbox = ctk.CTkCheckBox(
            row2,
            text="",                      # niente testo qui
            variable=self.autostart_var,
            onvalue=True,
            offvalue=False,
            fg_color=ACCENT,
            hover_color=ACCENT_DARK,
            border_color=BORDER_COLOR,
            command=self.on_autostart_toggled
        )
        self.autostart_checkbox.pack(side="right")
        
        # ROW 3: always on top
        row3 = ctk.CTkFrame(parent, fg_color="transparent")
        row3.pack(fill="x", padx=14, pady=(4, 12))

        lbl_topmost = ctk.CTkLabel(
            row3,
            text="Set always on top",
            font=("Segoe UI", 12),
            text_color=TEXT_MAIN
        )
        lbl_topmost.pack(side="left")

        self.topmost_var = ctk.BooleanVar(value=self.display_state.always_on_top)
        self.topmost_checkbox = ctk.CTkCheckBox(
            row3,
            text="",
            variable=self.topmost_var,
            onvalue=True,
            offvalue=False,
            fg_color=ACCENT,
            hover_color=ACCENT_DARK,
            border_color=BORDER_COLOR,
            command=self.on_topmost_toggled
        )
        self.topmost_checkbox.pack(side="right")
        
    def on_shortcut_changed(self):
        new_hotkey = self.shortcut_var.get().strip()
        if not new_hotkey:
            return

        # rimuovi vecchia hotkey
        old_hotkey = self.display_state.current_settings.get("hotkey", HOTKEY)
        try:
            keyboard.remove_hotkey(old_hotkey)
        except:
            pass

        # registra nuova
        try:
            keyboard.add_hotkey(new_hotkey, hotkey_handler)
            self.display_state.current_settings["hotkey"] = new_hotkey
            self.display_state.save_settings()
        except Exception as e:
            print(f"Invalid hotkey '{new_hotkey}': {e}")
            # rollback valore UI
            self.shortcut_var.set(old_hotkey)

    def on_autostart_toggled(self):
        value = bool(self.autostart_var.get())
        self.display_state.autostart_enabled = value
        set_autostart(value)
        self.display_state.save_settings()

    def start_hotkey_recording(self):
        global HOTKEY

        if self.recording_hotkey:
            return

        self.recording_hotkey = True

        old_hotkey = self.display_state.current_settings.get("hotkey", HOTKEY)

        # disabilita temporaneamente la vecchia hotkey
        try:
            keyboard.remove_hotkey(old_hotkey)
        except:
            pass

        # feedback visivo
        self.shortcut_entry.configure(state="normal")
        self.shortcut_var.set("Press the new shortcut...")
        self.shortcut_entry.configure(state="readonly")

        def worker():
            new_hotkey = None
            try:
                # blocca finché l'utente preme e rilascia una combinazione
                new_hotkey = keyboard.read_hotkey(suppress=True)
            except Exception as e:
                print(f"Error reading hotkey: {e}")

            def apply_result():
                self.recording_hotkey = False

                # se non è stata letta nessuna combinazione, ripristina la vecchia
                if not new_hotkey:
                    self.shortcut_var.set(old_hotkey)
                    try:
                        keyboard.add_hotkey(old_hotkey, hotkey_handler)
                    except:
                        pass
                    return

                # prova a registrare la nuova
                try:
                    keyboard.add_hotkey(new_hotkey, hotkey_handler)
                    self.display_state.current_settings["hotkey"] = new_hotkey
                    self.display_state.save_settings()
                    self.shortcut_var.set(new_hotkey)
                    HOTKEY = new_hotkey
                except Exception as e:
                    print(f"Invalid hotkey '{new_hotkey}': {e}")
                    self.shortcut_var.set(old_hotkey)
                    try:
                        keyboard.add_hotkey(old_hotkey, hotkey_handler)
                    except:
                        pass

            # torna nel main thread Tk
            self.after(0, apply_result)

        threading.Thread(target=worker, daemon=True).start()

    def on_topmost_toggled(self):
        value = bool(self.topmost_var.get())
        self.display_state.always_on_top = value
        self.display_state.save_settings()
        self.attributes("-topmost", value)
    
    def build_presets_section(self, parent):
        """Costruisce la sezione per gestire i preset"""
        # Container per lista preset e bottoni
        list_container = ctk.CTkFrame(parent, fg_color="transparent")
        list_container.pack(fill="x", padx=14, pady=(10, 6))

        # Label
        lbl_presets = ctk.CTkLabel(
            list_container,
            text="Saved Presets",
            font=("Segoe UI", 13, "bold"),
            text_color=TEXT_MAIN
        )
        lbl_presets.pack(anchor="w", pady=(0, 8))

        # Frame per la lista di preset (scrollabile se necessario)
        self.presets_list_frame = ctk.CTkFrame(
            list_container,
            fg_color=CARD_ALT_BG,
            corner_radius=8,
            border_width=1,
            border_color=BORDER_COLOR
        )
        self.presets_list_frame.pack(fill="x", pady=(0, 10))

        self.update_presets_list()

        # Bottoni azione
        buttons_frame = ctk.CTkFrame(list_container, fg_color="transparent")
        buttons_frame.pack(fill="x")

        # Bottone Salva nuovo preset
        btn_save = ctk.CTkButton(
            buttons_frame,
            text="💾 Save Current",
            font=("Segoe UI", 12, "bold"),
            fg_color=SUCCESS,
            hover_color="#2d8532",
            corner_radius=8,
            height=36,
            command=self.show_save_preset_dialog
        )
        btn_save.pack(side="left", expand=True, fill="x", padx=(0, 4))

        # Bottone Gestisci preset
        btn_manage = ctk.CTkButton(
            buttons_frame,
            text="⚙️ Manage",
            font=("Segoe UI", 12, "bold"),
            fg_color=ACCENT,
            hover_color=ACCENT_DARK,
            corner_radius=8,
            height=36,
            command=self.show_manage_presets_dialog
        )
        btn_manage.pack(side="right", expand=True, fill="x", padx=(4, 0))

    def update_presets_list(self):
        """Aggiorna la lista dei preset visualizzati"""
        # Pulisci lista attuale
        for widget in self.presets_list_frame.winfo_children():
            widget.destroy()

        preset_names = self.display_state.get_preset_names()
        
        if not preset_names:
            # Messaggio se non ci sono preset
            no_presets_lbl = ctk.CTkLabel(
                self.presets_list_frame,
                text="No presets saved yet",
                font=("Segoe UI", 11),
                text_color=TEXT_MUTED
            )
            no_presets_lbl.pack(pady=12)
        else:
            # Mostra max 5 preset, poi scroll
            for idx, preset_name in enumerate(preset_names[:5]):
                preset_row = ctk.CTkFrame(
                    self.presets_list_frame,
                    fg_color="transparent"
                )
                preset_row.pack(fill="x", padx=8, pady=4)

                # Nome preset
                name_lbl = ctk.CTkLabel(
                    preset_row,
                    text=preset_name,
                    font=("Segoe UI", 12),
                    text_color=TEXT_MAIN,
                    anchor="w"
                )
                name_lbl.pack(side="left", fill="x", expand=True)

                # Bottone Load
                btn_load = ctk.CTkButton(
                    preset_row,
                    text="Load",
                    width=60,
                    height=28,
                    font=("Segoe UI", 11),
                    fg_color=ACCENT,
                    hover_color=ACCENT_DARK,
                    corner_radius=6,
                    command=lambda name=preset_name: self.load_preset(name)
                )
                btn_load.pack(side="right")
            
            if len(preset_names) > 5:
                more_lbl = ctk.CTkLabel(
                    self.presets_list_frame,
                    text=f"+ {len(preset_names) - 5} more...",
                    font=("Segoe UI", 10),
                    text_color=TEXT_MUTED
                )
                more_lbl.pack(pady=(4, 8))

    def show_save_preset_dialog(self):
        """Mostra dialog per salvare un nuovo preset"""
        dialog = ctk.CTkInputDialog(
            text="Enter a name for this preset:",
            title="Save Preset"
        )
        preset_name = dialog.get_input()
        
        if preset_name and preset_name.strip():
            preset_name = preset_name.strip()
            
            # Controlla se esiste già
            if preset_name in self.display_state.presets:
                # Chiedi conferma sovrascrittura
                confirm = ctk.CTkInputDialog(
                    text=f"Preset '{preset_name}' already exists.\nType 'yes' to overwrite:",
                    title="Confirm Overwrite"
                )
                response = confirm.get_input()
                if response and response.lower() != 'yes':
                    return
            
            self.display_state.save_preset(preset_name)
            self.update_presets_list()

    def load_preset(self, preset_name):
        """Carica un preset"""
        if self.display_state.load_preset(preset_name):
            # Aggiorna tutti gli slider
            for key, widgets in self.sliders.items():
                val = self.display_state.current_settings.get(key, 1.0)
                widgets["slider"].set(val)
                widgets["label"].configure(text=f"{val:.2f}")

    def show_manage_presets_dialog(self):
        """Mostra finestra per gestire (rinominare/eliminare) preset"""
        preset_names = self.display_state.get_preset_names()
        
        if not preset_names:
            return
        
        # Crea finestra popup
        manage_window = ctk.CTkToplevel(self)
        manage_window.title("Manage Presets")
        manage_window.geometry("380x450")
        manage_window.resizable(False, False)
        manage_window.configure(fg_color=BG_COLOR)
        manage_window.attributes("-topmost", True)
        
        # Centra la finestra
        manage_window.transient(self)
        manage_window.grab_set()
        
        # Header
        header = ctk.CTkLabel(
            manage_window,
            text="Manage Presets",
            font=("Segoe UI", 20, "bold"),
            text_color=TEXT_MAIN
        )
        header.pack(pady=(20, 10), padx=20)
        
        # Frame scrollabile per lista preset
        scroll_frame = ctk.CTkScrollableFrame(
            manage_window,
            fg_color=CARD_BG,
            corner_radius=12,
            border_width=1,
            border_color=BORDER_COLOR
        )
        scroll_frame.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        
        def refresh_list():
            for widget in scroll_frame.winfo_children():
                widget.destroy()
            
            current_presets = self.display_state.get_preset_names()
            
            if not current_presets:
                manage_window.destroy()
                self.update_presets_list()
                return
            
            for preset_name in current_presets:
                preset_frame = ctk.CTkFrame(
                    scroll_frame,
                    fg_color=CARD_ALT_BG,
                    corner_radius=8,
                    border_width=1,
                    border_color=BORDER_COLOR
                )
                preset_frame.pack(fill="x", pady=6, padx=4)
                
                # Nome
                name_lbl = ctk.CTkLabel(
                    preset_frame,
                    text=preset_name,
                    font=("Segoe UI", 13),
                    text_color=TEXT_MAIN,
                    anchor="w"
                )
                name_lbl.pack(side="left", padx=12, pady=10, fill="x", expand=True)
                
                # Bottoni
                btn_container = ctk.CTkFrame(preset_frame, fg_color="transparent")
                btn_container.pack(side="right", padx=8, pady=6)
                
                # Rename
                btn_rename = ctk.CTkButton(
                    btn_container,
                    text="Rename",
                    width=70,
                    height=28,
                    font=("Segoe UI", 11),
                    fg_color=ACCENT,
                    hover_color=ACCENT_DARK,
                    corner_radius=6,
                    command=lambda name=preset_name: rename_preset(name)
                )
                btn_rename.pack(side="left", padx=2)
                
                # Delete
                btn_delete = ctk.CTkButton(
                    btn_container,
                    text="Delete",
                    width=70,
                    height=28,
                    font=("Segoe UI", 11),
                    fg_color=DANGER,
                    hover_color="#450201",
                    corner_radius=6,
                    command=lambda name=preset_name: delete_preset(name)
                )
                btn_delete.pack(side="left", padx=2)
        
        def rename_preset(old_name):
            dialog = ctk.CTkInputDialog(
                text=f"Enter new name for '{old_name}':",
                title="Rename Preset"
            )
            new_name = dialog.get_input()
            
            if new_name and new_name.strip() and new_name.strip() != old_name:
                new_name = new_name.strip()
                if self.display_state.rename_preset(old_name, new_name):
                    refresh_list()
                    self.update_presets_list()
        
        def delete_preset(preset_name):
            if self.display_state.delete_preset(preset_name):
                refresh_list()
                self.update_presets_list()
        
        refresh_list()
        
        # Bottone chiudi
        btn_close = ctk.CTkButton(
            manage_window,
            text="Close",
            font=("Segoe UI", 12, "bold"),
            fg_color=BORDER_COLOR,
            hover_color="#3a3d50",
            corner_radius=8,
            height=36,
            command=manage_window.destroy
        )
        btn_close.pack(pady=(0, 20), padx=20, fill="x")


# --- TRAY ICON & THREADING ---

def create_image():
    icon_path = resource_path(ICON_FILE)
    if os.path.exists(icon_path):
        try:
            return Image.open(icon_path)
        except:
            pass

    img = Image.new('RGB', (64, 64), (255, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, 44, 44], fill=(255, 255, 255))
    return img

def run_tray(app_ref):
    def toggle_window():
        # se è visibile, nascondi; se è nascosta, mostra
        if app_ref.state() == "normal":
            app_ref.after(0, app_ref.hide_window)
        else:
            app_ref.after(0, app_ref.show_window)

    def on_open(icon, item):
        toggle_window()

    def on_exit(icon, item):
        state.save_settings()
        state.restore_defaults()
        icon.stop()
        app_ref.quit()
        os._exit(0)

    icon = pystray.Icon(
        "NVFT",
        create_image(),
        menu=pystray.Menu(
            pystray.MenuItem("Settings", on_open, default=True),
            pystray.MenuItem("Toggle ON/OFF", lambda i, it: state.toggle()),
            pystray.MenuItem("Exit", on_exit)
        )
    )

    # opzionale: click sull’icona tray fa toggle della finestra
    def on_clicked(icon, item):
        toggle_window()
    icon._MENU_CLICK = on_clicked  # hack: dipende dalla versione di pystray

    icon.run()


# --- GESTIONE SOCKET ---

def try_send_command_to_existing_instance():
    try:
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client_socket.settimeout(0.1)
        client_socket.sendto(b"TOGGLE", ("127.0.0.1", LOCAL_PORT))
        client_socket.close()
        return True
    except Exception:
        return False

def start_command_listener(state_obj):
    def listener():
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            server_socket.bind(("127.0.0.1", LOCAL_PORT))
            while True:
                data, addr = server_socket.recvfrom(1024)
                if data == b"TOGGLE":
                    state_obj.toggle()
        except Exception as e:
            print(f"Listener error: {e}")

    t = threading.Thread(target=listener, daemon=True)
    t.start()

def hotkey_handler():
    state.toggle()
    time.sleep(0.2)

def main():
    global HOTKEY
    
    test_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        test_socket.bind(("127.0.0.1", LOCAL_PORT))
        test_socket.close()
    except OSError:
        try_send_command_to_existing_instance()
        sys.exit(0)
        
    start_command_listener(state)
    HOTKEY = state.current_settings.get("hotkey", HOTKEY)
    keyboard.add_hotkey(HOTKEY, hotkey_handler)

    app = SettingsApp(state)

    # All’avvio: solo tray, finestra nascosta
    app.withdraw()

    tray_thread = threading.Thread(target=run_tray, args=(app,), daemon=True)
    tray_thread.start()

    app.mainloop()


if __name__ == "__main__":
    main()
