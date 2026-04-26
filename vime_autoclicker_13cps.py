import json
import threading
import time
from pathlib import Path
from tkinter import messagebox, simpledialog

try:
    import customtkinter as ctk
except ImportError:
    raise SystemExit("Установи customtkinter: pip install customtkinter")

try:
    from pynput import mouse, keyboard
except ImportError:
    raise SystemExit("Установи pynput: pip install pynput")


CONFIG_FILE = Path("config.json")

MAX_CPS = 13
MIN_CPS = 1
DEFAULT_CPS = 13

MIN_MACRO_DELAY_MS = 50
AGGRESSIVE_DELAY_MS = 80

SPECIAL_KEYS = {
    "space": keyboard.Key.space,
    "enter": keyboard.Key.enter,
    "return": keyboard.Key.enter,
    "esc": keyboard.Key.esc,
    "escape": keyboard.Key.esc,
    "shift": keyboard.Key.shift,
    "ctrl": keyboard.Key.ctrl,
    "control": keyboard.Key.ctrl,
    "alt": keyboard.Key.alt,
    "tab": keyboard.Key.tab,
    "backspace": keyboard.Key.backspace,
    "delete": keyboard.Key.delete,
    "up": keyboard.Key.up,
    "down": keyboard.Key.down,
    "left": keyboard.Key.left,
    "right": keyboard.Key.right,
}

for i in range(1, 13):
    SPECIAL_KEYS[f"f{i}"] = getattr(keyboard.Key, f"f{i}")


def clamp_int(value, low, high, default):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


def parse_key(name: str):
    if not name:
        return None
    value = str(name).strip().lower()
    if value in SPECIAL_KEYS:
        return SPECIAL_KEYS[value]
    if len(value) == 1:
        return keyboard.KeyCode.from_char(value)
    return keyboard.KeyCode.from_char(value[0])


def key_to_name(key) -> str:
    if isinstance(key, keyboard.KeyCode):
        return (key.char or "").lower()
    if isinstance(key, keyboard.Key):
        return key.name.lower()
    return str(key).lower()


def same_key(pressed_key, configured_name: str) -> bool:
    return key_to_name(pressed_key) == str(configured_name).strip().lower()


DEFAULT_CONFIG = {
    "cps": DEFAULT_CPS,
    "mouse_button": "ЛКМ",
    "click_mode": "Переключатель",
    "toggle_hotkey": "f6",
    "pause_hotkey": "f7",
    "emergency_hotkey": "f8",
    "macros": {
        "Мост": {
            "hotkey": "f9",
            "repeat": 1,
            "actions": [
                {"type": "mouse", "button": "right", "delay_ms": 120},
                {"type": "key", "key": "d", "mode": "tap", "delay_ms": 120},
                {"type": "key", "key": "space", "mode": "tap", "delay_ms": 140},
                {"type": "mouse", "button": "right", "delay_ms": 160}
            ]
        },
        "Стенка": {"hotkey": "f10", "repeat": 1, "actions": []},
        "Башня": {"hotkey": "f11", "repeat": 1, "actions": []},
        "Лестница": {"hotkey": "f12", "repeat": 1, "actions": []}
    }
}


class ConfigManager:
    @staticmethod
    def load() -> dict:
        if not CONFIG_FILE.exists():
            return json.loads(json.dumps(DEFAULT_CONFIG, ensure_ascii=False))
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return json.loads(json.dumps(DEFAULT_CONFIG, ensure_ascii=False))

        merged = json.loads(json.dumps(DEFAULT_CONFIG, ensure_ascii=False))
        merged.update(data)
        merged["cps"] = clamp_int(merged.get("cps"), MIN_CPS, MAX_CPS, DEFAULT_CPS)
        merged.setdefault("macros", DEFAULT_CONFIG["macros"])
        return merged

    @staticmethod
    def save(config: dict):
        config["cps"] = clamp_int(config.get("cps"), MIN_CPS, MAX_CPS, DEFAULT_CPS)
        CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


class AutoClicker:
    def __init__(self, app):
        self.app = app
        self.mouse = mouse.Controller()
        self.active = threading.Event()
        self.paused = threading.Event()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        while not self.stop_event.is_set():
            if self.active.is_set() and not self.paused.is_set():
                cps = clamp_int(self.app.get_cps(), MIN_CPS, MAX_CPS, DEFAULT_CPS)
                btn = mouse.Button.left if self.app.get_mouse_button() == "ЛКМ" else mouse.Button.right
                self.mouse.click(btn, 1)
                time.sleep(1 / cps)
            else:
                time.sleep(0.02)

    def start(self):
        self.active.set()
        self.app.set_status(True)

    def stop(self):
        self.active.clear()
        self.app.set_status(False)

    def toggle(self):
        self.stop() if self.active.is_set() else self.start()

    def toggle_pause(self):
        if self.paused.is_set():
            self.paused.clear()
            self.app.set_pause_status(False)
        else:
            self.paused.set()
            self.app.set_pause_status(True)

    def emergency_stop(self):
        self.active.clear()
        self.paused.clear()
        self.app.set_status(False)
        self.app.set_pause_status(False)

    def shutdown(self):
        self.stop_event.set()
        self.active.clear()


class MacroRunner:
    def __init__(self, app):
        self.app = app
        self.mouse = mouse.Controller()
        self.keyboard = keyboard.Controller()
        self.running = set()
        self.lock = threading.Lock()

    def run_macro(self, name: str, macro: dict):
        with self.lock:
            if name in self.running:
                return
            self.running.add(name)
        threading.Thread(target=self._run_macro_thread, args=(name, macro), daemon=True).start()

    def _run_macro_thread(self, name: str, macro: dict):
        try:
            actions = macro.get("actions", [])
            repeat = clamp_int(macro.get("repeat", 1), 1, 100, 1)
            for _ in range(repeat):
                for action in actions:
                    if self.app.emergency_requested:
                        return
                    self._execute_action(action)
        finally:
            with self.lock:
                self.running.discard(name)

    def _execute_action(self, action: dict):
        action_type = action.get("type")
        delay_ms = clamp_int(action.get("delay_ms", MIN_MACRO_DELAY_MS), MIN_MACRO_DELAY_MS, 5000, MIN_MACRO_DELAY_MS)

        if action_type == "mouse":
            button_name = str(action.get("button", "right")).lower()
            btn = mouse.Button.left if button_name in ("left", "лкм") else mouse.Button.right
            self.mouse.click(btn, 1)
        elif action_type == "key":
            key = parse_key(action.get("key", ""))
            mode = str(action.get("mode", "tap")).lower()
            if key is not None:
                if mode == "press":
                    self.keyboard.press(key)
                elif mode == "release":
                    self.keyboard.release(key)
                else:
                    self.keyboard.press(key)
                    time.sleep(0.03)
                    self.keyboard.release(key)
        elif action_type == "wait":
            pass

        time.sleep(delay_ms / 1000)


class HotkeyListener:
    def __init__(self, app):
        self.app = app
        self.listener = keyboard.Listener(on_press=self.on_press, on_release=self.on_release)
        self.listener.daemon = True
        self.listener.start()

    def on_press(self, key):
        cfg = self.app.get_config_snapshot()

        if same_key(key, cfg.get("emergency_hotkey", "f8")):
            self.app.emergency_requested = True
            self.app.autoclicker.emergency_stop()
            return

        if same_key(key, cfg.get("pause_hotkey", "f7")):
            self.app.autoclicker.toggle_pause()
            return

        mode = cfg.get("click_mode", "Переключатель")
        if same_key(key, cfg.get("toggle_hotkey", "f6")):
            self.app.emergency_requested = False
            if mode == "Переключатель":
                self.app.autoclicker.toggle()
            else:
                self.app.autoclicker.start()
            return

        for name, macro in cfg.get("macros", {}).items():
            if same_key(key, macro.get("hotkey", "")):
                self.app.emergency_requested = False
                self.app.macro_runner.run_macro(name, macro)
                return

    def on_release(self, key):
        cfg = self.app.get_config_snapshot()
        if cfg.get("click_mode") == "Удержание" and same_key(key, cfg.get("toggle_hotkey", "f6")):
            self.app.autoclicker.stop()

    def shutdown(self):
        self.listener.stop()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("Автокликер 13 CPS + макросы")
        self.geometry("900x650")
        self.minsize(850, 600)

        self.config_data = ConfigManager.load()
        self.emergency_requested = False

        self.autoclicker = AutoClicker(self)
        self.macro_runner = MacroRunner(self)
        self.hotkeys = HotkeyListener(self)

        self._build_ui()
        self._load_values_to_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        title = ctk.CTkLabel(self, text="Автокликер Minecraft/VimeWorld", font=("Arial", 24, "bold"))
        title.grid(row=0, column=0, columnspan=2, pady=(18, 10))

        left = ctk.CTkFrame(self)
        left.grid(row=1, column=0, padx=(18, 9), pady=10, sticky="nsew")
        left.grid_columnconfigure(0, weight=1)

        right = ctk.CTkFrame(self)
        right.grid(row=1, column=1, padx=(9, 18), pady=10, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(7, weight=1)

        ctk.CTkLabel(left, text="Клики", font=("Arial", 18, "bold")).grid(row=0, column=0, pady=(16, 8))
        self.status_label = ctk.CTkLabel(left, text="Статус: OFF", font=("Arial", 18, "bold"))
        self.status_label.grid(row=1, column=0, pady=8)
        self.pause_label = ctk.CTkLabel(left, text="Пауза: OFF")
        self.pause_label.grid(row=2, column=0, pady=3)

        self.cps_value = ctk.IntVar(value=DEFAULT_CPS)
        self.cps_label = ctk.CTkLabel(left, text="CPS: 13 / 13")
        self.cps_label.grid(row=3, column=0, pady=(12, 4))
        self.cps_slider = ctk.CTkSlider(left, from_=MIN_CPS, to=MAX_CPS, number_of_steps=MAX_CPS - MIN_CPS, command=self.on_cps_change)
        self.cps_slider.grid(row=4, column=0, padx=25, pady=8, sticky="ew")

        self.mouse_button_var = ctk.StringVar(value="ЛКМ")
        self.mouse_menu = ctk.CTkOptionMenu(left, values=["ЛКМ", "ПКМ"], variable=self.mouse_button_var)
        self.mouse_menu.grid(row=5, column=0, padx=25, pady=8, sticky="ew")

        self.click_mode_var = ctk.StringVar(value="Переключатель")
        self.mode_menu = ctk.CTkOptionMenu(left, values=["Переключатель", "Удержание"], variable=self.click_mode_var)
        self.mode_menu.grid(row=6, column=0, padx=25, pady=8, sticky="ew")

        self.toggle_hotkey_entry = self._labeled_entry(left, 7, "Hotkey клика / удержания", "f6")
        self.pause_hotkey_entry = self._labeled_entry(left, 9, "Hotkey паузы", "f7")
        self.emergency_hotkey_entry = self._labeled_entry(left, 11, "Экстренное выключение", "f8")

        buttons = ctk.CTkFrame(left, fg_color="transparent")
        buttons.grid(row=13, column=0, pady=18, padx=25, sticky="ew")
        buttons.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(buttons, text="Start", command=self.start_clicker).grid(row=0, column=0, padx=(0, 5), sticky="ew")
        ctk.CTkButton(buttons, text="Stop", command=self.stop_clicker).grid(row=0, column=1, padx=(5, 0), sticky="ew")
        ctk.CTkButton(left, text="Сохранить настройки", command=self.save_from_ui).grid(row=14, column=0, padx=25, pady=(0, 16), sticky="ew")

        ctk.CTkLabel(right, text="Макросы строительства", font=("Arial", 18, "bold")).grid(row=0, column=0, pady=(16, 8))
        self.macro_name_var = ctk.StringVar(value="Мост")
        self.macro_menu = ctk.CTkOptionMenu(right, values=list(self.config_data.get("macros", {}).keys()), variable=self.macro_name_var, command=lambda _: self.load_macro_to_editor())
        self.macro_menu.grid(row=1, column=0, padx=25, pady=7, sticky="ew")

        self.macro_hotkey_entry = self._labeled_entry(right, 2, "Hotkey макроса", "f9")
        self.macro_repeat_entry = self._labeled_entry(right, 4, "Повторения макроса", "1")

        ctk.CTkLabel(right, text="Действия макроса в JSON:").grid(row=6, column=0, pady=(10, 4))
        self.actions_text = ctk.CTkTextbox(right, height=230)
        self.actions_text.grid(row=7, column=0, padx=25, pady=8, sticky="nsew")

        macro_buttons = ctk.CTkFrame(right, fg_color="transparent")
        macro_buttons.grid(row=8, column=0, padx=25, pady=8, sticky="ew")
        macro_buttons.grid_columnconfigure((0, 1, 2), weight=1)
        ctk.CTkButton(macro_buttons, text="Сохранить", command=self.save_macro_from_editor).grid(row=0, column=0, padx=3, sticky="ew")
        ctk.CTkButton(macro_buttons, text="Новый", command=self.create_macro).grid(row=0, column=1, padx=3, sticky="ew")
        ctk.CTkButton(macro_buttons, text="Удалить", command=self.delete_macro).grid(row=0, column=2, padx=3, sticky="ew")

        self.warning_label = ctk.CTkLabel(right, text="Минимальная задержка действия: 50 мс. Ниже — программа сама поднимет значение.", wraplength=380)
        self.warning_label.grid(row=9, column=0, padx=25, pady=(6, 16), sticky="ew")

    def _labeled_entry(self, parent, row, label, default):
        ctk.CTkLabel(parent, text=label).grid(row=row, column=0, padx=25, pady=(8, 2), sticky="w")
        entry = ctk.CTkEntry(parent)
        entry.insert(0, default)
        entry.grid(row=row + 1, column=0, padx=25, pady=(0, 6), sticky="ew")
        return entry

    def _load_values_to_ui(self):
        cps = clamp_int(self.config_data.get("cps"), MIN_CPS, MAX_CPS, DEFAULT_CPS)
        self.cps_slider.set(cps)
        self.on_cps_change(cps)
        self.mouse_button_var.set(self.config_data.get("mouse_button", "ЛКМ"))
        self.click_mode_var.set(self.config_data.get("click_mode", "Переключатель"))
        self._set_entry(self.toggle_hotkey_entry, self.config_data.get("toggle_hotkey", "f6"))
        self._set_entry(self.pause_hotkey_entry, self.config_data.get("pause_hotkey", "f7"))
        self._set_entry(self.emergency_hotkey_entry, self.config_data.get("emergency_hotkey", "f8"))
        self.refresh_macro_menu()
        self.load_macro_to_editor()

    def _set_entry(self, entry, value):
        entry.delete(0, "end")
        entry.insert(0, str(value))

    def on_cps_change(self, value):
        cps = clamp_int(round(float(value)), MIN_CPS, MAX_CPS, DEFAULT_CPS)
        self.cps_value.set(cps)
        self.cps_label.configure(text=f"CPS: {cps} / {MAX_CPS}")

    def get_cps(self):
        return self.cps_value.get()

    def get_mouse_button(self):
        return self.mouse_button_var.get()

    def get_config_snapshot(self):
        self.update_config_from_ui(no_save=True)
        return json.loads(json.dumps(self.config_data, ensure_ascii=False))

    def update_config_from_ui(self, no_save=False):
        self.config_data["cps"] = clamp_int(self.cps_value.get(), MIN_CPS, MAX_CPS, DEFAULT_CPS)
        self.config_data["mouse_button"] = self.mouse_button_var.get()
        self.config_data["click_mode"] = self.click_mode_var.get()
        self.config_data["toggle_hotkey"] = self.toggle_hotkey_entry.get().strip() or "f6"
        self.config_data["pause_hotkey"] = self.pause_hotkey_entry.get().strip() or "f7"
        self.config_data["emergency_hotkey"] = self.emergency_hotkey_entry.get().strip() or "f8"
        if not no_save:
            ConfigManager.save(self.config_data)

    def start_clicker(self):
        self.emergency_requested = False
        self.autoclicker.start()

    def stop_clicker(self):
        self.autoclicker.stop()

    def set_status(self, is_on: bool):
        self.after(0, lambda: self.status_label.configure(text=f"Статус: {'ON' if is_on else 'OFF'}"))

    def set_pause_status(self, is_paused: bool):
        self.after(0, lambda: self.pause_label.configure(text=f"Пауза: {'ON' if is_paused else 'OFF'}"))

    def save_from_ui(self):
        self.update_config_from_ui()
        messagebox.showinfo("Сохранено", "Настройки сохранены в config.json")

    def refresh_macro_menu(self):
        names = list(self.config_data.get("macros", {}).keys()) or ["Без макросов"]
        self.macro_menu.configure(values=names)
        if self.macro_name_var.get() not in names:
            self.macro_name_var.set(names[0])

    def load_macro_to_editor(self):
        name = self.macro_name_var.get()
        macro = self.config_data.get("macros", {}).get(name, {"hotkey": "f9", "repeat": 1, "actions": []})
        self._set_entry(self.macro_hotkey_entry, macro.get("hotkey", "f9"))
        self._set_entry(self.macro_repeat_entry, macro.get("repeat", 1))
        self.actions_text.delete("1.0", "end")
        self.actions_text.insert("1.0", json.dumps(macro.get("actions", []), ensure_ascii=False, indent=2))

    def save_macro_from_editor(self):
        name = self.macro_name_var.get().strip()
        if not name or name == "Без макросов":
            messagebox.showwarning("Ошибка", "Сначала создай макрос.")
            return
        try:
            actions = json.loads(self.actions_text.get("1.0", "end").strip() or "[]")
            if not isinstance(actions, list):
                raise ValueError("actions должен быть списком")
        except Exception as exc:
            messagebox.showerror("Ошибка JSON", f"Проверь список действий.\n\n{exc}")
            return

        warnings = self.validate_macro_actions(actions)
        self.config_data.setdefault("macros", {})[name] = {
            "hotkey": self.macro_hotkey_entry.get().strip() or "f9",
            "repeat": clamp_int(self.macro_repeat_entry.get(), 1, 100, 1),
            "actions": actions,
        }
        ConfigManager.save(self.config_data)
        self.refresh_macro_menu()
        text = "Макрос сохранён."
        if warnings:
            text += "\n\nПредупреждение:\n" + "\n".join(warnings)
        messagebox.showinfo("Готово", text)

    def validate_macro_actions(self, actions):
        warnings = []
        for idx, action in enumerate(actions, start=1):
            delay = clamp_int(action.get("delay_ms", MIN_MACRO_DELAY_MS), MIN_MACRO_DELAY_MS, 5000, MIN_MACRO_DELAY_MS)
            if delay < AGGRESSIVE_DELAY_MS:
                warnings.append(f"Действие #{idx}: задержка {delay} мс выглядит агрессивно. Лучше 80–150 мс.")
            action["delay_ms"] = delay
        return warnings

    def create_macro(self):
        name = simpledialog.askstring("Новый макрос", "Название макроса:", parent=self)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        self.config_data.setdefault("macros", {})[name] = {"hotkey": "f9", "repeat": 1, "actions": []}
        self.macro_name_var.set(name)
        self.refresh_macro_menu()
        self.load_macro_to_editor()
        ConfigManager.save(self.config_data)

    def delete_macro(self):
        name = self.macro_name_var.get()
        if name in self.config_data.get("macros", {}):
            del self.config_data["macros"][name]
            ConfigManager.save(self.config_data)
            self.refresh_macro_menu()
            self.load_macro_to_editor()

    def on_close(self):
        self.update_config_from_ui(no_save=False)
        self.autoclicker.shutdown()
        self.hotkeys.shutdown()
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()
