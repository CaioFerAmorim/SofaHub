"""Navegadores compatíveis com a extensão (todos baseados no Chromium) e detecção do navegador padrão."""
import os
import shutil
import sys
from pathlib import Path

WINDOWS = sys.platform == "win32"

# id, nome, executável, caminhos comuns (relativos a Arquivos de Programas / AppData\Local),
# prefixos do ProgId do Windows e página de extensões
CATALOGO = [
    {"id": "chrome", "nome": "Google Chrome", "exe": "chrome.exe",
     "caminhos": ["Google/Chrome/Application/chrome.exe"], "progid": ["ChromeHTML"],
     "extensoes": "chrome://extensions/", "linux": ["google-chrome", "chromium", "chromium-browser"]},
    {"id": "edge", "nome": "Microsoft Edge", "exe": "msedge.exe",
     "caminhos": ["Microsoft/Edge/Application/msedge.exe"], "progid": ["MSEdgeHTM"],
     "extensoes": "edge://extensions/", "linux": ["microsoft-edge"]},
    {"id": "vivaldi", "nome": "Vivaldi", "exe": "vivaldi.exe",
     "caminhos": ["Vivaldi/Application/vivaldi.exe"], "progid": ["VivaldiHTM"],
     "extensoes": "vivaldi://extensions/", "linux": ["vivaldi", "vivaldi-stable"]},
    {"id": "brave", "nome": "Brave", "exe": "brave.exe",
     "caminhos": ["BraveSoftware/Brave-Browser/Application/brave.exe"], "progid": ["BraveHTML"],
     "extensoes": "brave://extensions/", "linux": ["brave-browser", "brave"]},
    {"id": "opera", "nome": "Opera", "exe": "opera.exe",
     "caminhos": ["Programs/Opera/opera.exe", "Opera/opera.exe"], "progid": ["OperaStable"],
     "extensoes": "opera://extensions/", "linux": ["opera"]},
    {"id": "operagx", "nome": "Opera GX", "exe": "opera.exe",
     "caminhos": ["Programs/Opera GX/opera.exe", "Opera GX/opera.exe"], "progid": ["Opera GXStable"],
     "extensoes": "opera://extensions/", "linux": []},
]
POR_ID = {n["id"]: n for n in CATALOGO}


def _app_paths(exe):
    """Caminho registrado pelo instalador do navegador (App Paths do Windows)."""
    if not WINDOWS:
        return None
    import winreg
    for raiz in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(raiz, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as k:
                valor = winreg.QueryValueEx(k, "")[0]
                if valor and Path(valor.strip('"')).is_file():
                    return valor.strip('"')
        except OSError:
            pass
    return None


def _procurar(n):
    if WINDOWS:
        bases = [os.environ.get(v) for v in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)")]
        for rel in n["caminhos"]:
            for b in filter(None, bases):
                p = Path(b) / rel
                if p.is_file():
                    return str(p)
        if n["id"] == "operagx":   # Opera e Opera GX usam o mesmo opera.exe: o GX só pelo caminho
            return None
        p = _app_paths(n["exe"])
        if p and n["id"] == "opera" and "opera gx" in p.lower():
            return None
        return p
    for nome in n["linux"]:
        p = shutil.which(nome)
        if p:
            return p
    return None


def instalados():
    """[{id, nome, exe, extensoes}] dos navegadores compatíveis encontrados neste PC."""
    saida = []
    for n in CATALOGO:
        exe = _procurar(n)
        if exe and all(exe.lower() != s["exe"].lower() for s in saida):
            saida.append({"id": n["id"], "nome": n["nome"], "exe": exe, "extensoes": n["extensoes"]})
    return saida


def padrao_do_sistema():
    """id do navegador padrão do Windows, se for um dos compatíveis (Firefox não é)."""
    if not WINDOWS:
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice") as k:
            progid = winreg.QueryValueEx(k, "ProgId")[0]
    except OSError:
        return None
    # do mais específico ao menos ("Opera GXStable" antes de "OperaStable")
    for n in sorted(CATALOGO, key=lambda n: -max(len(p) for p in n["progid"])):
        if any(progid.startswith(p) for p in n["progid"]):
            return n["id"]
    return None
