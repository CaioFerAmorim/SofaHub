"""Integração com o sistema: teclado/mouse, energia da tela e iniciar com o Windows."""
import logging
import sys
import time
from pathlib import Path

log = logging.getLogger("sofahub")
WINDOWS = sys.platform == "win32"

if WINDOWS:
    # Coordenadas em pixels reais da tela (sem a escala de 150%/200% do Windows atrapalhar o clique).
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# ------------------------------------------------------------------
# Teclado e mouse (pynput). Sem pynput/sem tela → modo simulado (testes).
# ------------------------------------------------------------------
try:
    from pynput.keyboard import Controller as _KB, Key
    from pynput.mouse import Controller as _MS, Button

    kb, ms = _KB(), _MS()
    INPUT_OK = True
except Exception as e:
    log.warning("teclado/mouse em modo simulado: %s", e)
    INPUT_OK = False

    class _Fake:
        def __init__(self, nome): self._n = nome
        def __getattr__(self, attr):
            if attr.startswith("_"):
                raise AttributeError(attr)
            return lambda *a, **k: log.info("[sim] %s.%s%s", self._n, attr, a)

    class _Names:
        def __getattr__(self, attr): return f"<{attr}>"

    kb, ms = _Fake("teclado"), _Fake("mouse")
    Key = Button = _Names()

NOMES = {
    "esc": "esc", "enter": "enter", "space": "space", "tab": "tab",
    "backspace": "backspace", "delete": "delete",
    "up": "up", "down": "down", "left": "left", "right": "right",
    "home": "home", "end": "end", "pageup": "page_up", "pagedown": "page_down",
    "alt": "alt", "ctrl": "ctrl", "shift": "shift", "win": "cmd", "capslock": "caps_lock",
    "playpause": "media_play_pause", "next": "media_next", "prev": "media_previous",
    "volup": "media_volume_up", "voldown": "media_volume_down", "mute": "media_volume_mute",
    **{f"f{i}": f"f{i}" for i in range(1, 13)},
}


def tecla(nome: str):
    n = nome.strip().lower()
    if n in NOMES:
        return getattr(Key, NOMES[n])
    if len(n) == 1:
        return n
    raise ValueError(f"tecla desconhecida: {nome}")


def apertar(spec: str):
    """Aperta uma combinação: 'f', 'ctrl+l', 'alt+f4', 'shift+n'."""
    partes = [tecla(p) for p in spec.split("+") if p.strip()]
    if not partes:
        return
    *mods, final = partes
    for m in mods:
        kb.press(m)
    try:
        kb.press(final)
        kb.release(final)
    finally:
        for m in reversed(mods):
            kb.release(m)


def botao(nome):
    return getattr(Button, {"right": "right", "middle": "middle"}.get(nome, "left"))


# --- Mouse em coordenadas absolutas: chamadas diretas do Windows, em pixels reais da tela ---
def _tela():
    if WINDOWS:
        import ctypes
        u = ctypes.windll.user32
        return u.GetSystemMetrics(0), u.GetSystemMetrics(1)
    return 1920, 1080


def _pos():
    if WINDOWS:
        import ctypes
        from ctypes import wintypes
        p = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(p))
        return p.x, p.y
    try:
        return ms.position
    except Exception:
        return 0, 0


def _mover(x, y):
    if WINDOWS:
        import ctypes
        ctypes.windll.user32.SetCursorPos(int(x), int(y))
    else:
        ms.position = (int(x), int(y))


def _clicar():
    if WINDOWS:
        import ctypes
        u = ctypes.windll.user32
        u.mouse_event(0x0002, 0, 0, 0, 0)   # botão esquerdo pressionado
        time.sleep(0.05)
        u.mouse_event(0x0004, 0, 0, 0, 0)   # solto
    else:
        ms.press(Button.left)
        time.sleep(0.05)
        ms.release(Button.left)


def clique_tela(fx: float, fy: float):
    """Clique num ponto da tela dado em fração (0..1) da largura/altura."""
    w, h = _tela()
    clique_px(min(max(fx, 0.0), 1.0) * (w - 1), min(max(fy, 0.0), 1.0) * (h - 1))


def clique_px(x: float, y: float):
    """Clique de mouse de verdade no pixel (x, y) da tela.
    Usado no play: o Chrome só libera play/tela cheia em alguns players com um clique real."""
    w, h = _tela()
    alvo = (int(min(max(x, 0), w - 1)), int(min(max(y, 0), h - 1)))
    _mover(*alvo)
    time.sleep(0.05)
    _clicar()
    log.info("clique em %s (tela %sx%s)", alvo, w, h)
    # o cursor fica no lugar: a extensão pode pedir um 2º clique (clique_aqui)


def clique_aqui():
    """Clique onde o cursor já está (2ª tentativa do play)."""
    _clicar()
    log.info("2º clique em %s", _pos())


def estacionar_cursor():
    """Leva o cursor para o canto inferior direito, onde fica praticamente invisível."""
    w, h = _tela()
    _mover(w - 1, h - 1)


def copiar(texto: str):
    """Copia para a área de transferência do Windows (sem abrir janela de console)."""
    if not WINDOWS:
        return
    import subprocess
    try:
        subprocess.run(["clip"], input=texto.encode("utf-16"), creationflags=0x08000000, timeout=5)
    except Exception as e:
        log.warning("não deu para copiar: %s", e)


# ------------------------------------------------------------------
# Energia
# ------------------------------------------------------------------
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002


def manter_acordado():
    """Impede a suspensão automática enquanto o SofaHub roda (a tela ainda apaga).
    Vale para a thread que chamou — chamar na thread principal, que vive até o fim."""
    if WINDOWS:
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)


def tela_ativa():
    """Reinicia o contador de inatividade da tela, sem mexer no mouse."""
    if WINDOWS:
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(ES_DISPLAY_REQUIRED)


def ligar_tela():
    """Acende a tela se ela apagou por inatividade."""
    if WINDOWS:
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(ES_DISPLAY_REQUIRED)
    # um "chacoalhão" de 1px no mouse garante que o Windows registre atividade
    ms.move(1, 0)
    ms.move(-1, 0)


# ------------------------------------------------------------------
# Iniciar com o Windows (registro do usuário, sem precisar de admin)
# ------------------------------------------------------------------
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NOME = "SofaHub"


def _comando_inicio():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = pythonw if pythonw.exists() else Path(sys.executable)
    script = Path(__file__).resolve().with_name("sofahub.py")
    return f'"{exe}" "{script}"'


def inicio_ativo() -> bool:
    if not WINDOWS:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NOME)
            return True
    except OSError:
        return False


def definir_inicio(ativo: bool):
    if not WINDOWS:
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if ativo:
            winreg.SetValueEx(k, RUN_NOME, 0, winreg.REG_SZ, _comando_inicio())
        else:
            try:
                winreg.DeleteValue(k, RUN_NOME)
            except FileNotFoundError:
                pass
