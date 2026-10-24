"""SofaHub — roda nos ícones ocultos da barra de tarefas e liga junto com o Windows."""
import logging
import os
import sys
import webbrowser
from logging.handlers import RotatingFileHandler

import servidor
import sistema

servidor.limpar_log_antigo(servidor.DATA_DIR / "sofahub.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[RotatingFileHandler(servidor.DATA_DIR / "sofahub.log", maxBytes=500_000, backupCount=1, encoding="utf-8")],
)
log = logging.getLogger("sofahub")


def aviso_fatal(msg):
    log.error(msg)
    if sistema.WINDOWS:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, "SofaHub", 0x10)
    else:
        print(msg)
    sys.exit(1)


def ja_aberto(porta) -> bool:
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{porta}/api/info", timeout=2) as r:
            return json.load(r).get("app") == "sofahub"
    except Exception:
        return False


def main():
    import pystray
    from PIL import Image

    srv = servidor.Servidor()
    try:
        srv.iniciar()
    except OSError:
        if ja_aberto(srv.porta):   # abriu de novo pelo atalho: só mostra a tela de configuração
            webbrowser.open(f"http://127.0.0.1:{srv.porta}/configurar")
            sys.exit(0)
        aviso_fatal(f"A porta {srv.porta} já está em uso.\nO SofaHub já está aberto? Veja nos ícones ocultos.")

    sistema.manter_acordado()   # thread principal vive até o fim → vale a sessão inteira
    log.info("SofaHub %s iniciado em %s", servidor.VERSAO, srv.endereco)   # o PIN não vai para o log

    def alternar_inicio(icon, item):
        sistema.definir_inicio(not sistema.inicio_ativo())

    def sair(icon, item):
        srv.parar()
        icon.stop()

    def configurar(icon=None, item=None):
        webbrowser.open(srv.endereco_local)

    menu = pystray.Menu(
        pystray.MenuItem(lambda i: f"SofaHub {servidor.VERSAO} — {srv.cfg['nome']}", None, enabled=False),
        pystray.MenuItem("Configurar / conectar celular", configurar, default=True),   # também no duplo clique
        pystray.MenuItem(lambda i: f"Celular: {srv.endereco}", None, enabled=False),
        pystray.MenuItem(lambda i: f"PIN de pareamento: {srv.pin}", None, enabled=False),
        pystray.MenuItem(lambda i: "Extensão do navegador: " + ("conectada" if srv.ext_on else "desconectada"),
                         None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Iniciar com o Windows", alternar_inicio,
                         checked=lambda i: sistema.inicio_ativo(), visible=sistema.WINDOWS),
        pystray.MenuItem("Abrir pasta do SofaHub", lambda i, it: os.startfile(servidor.DATA_DIR)
                         if sistema.WINDOWS else webbrowser.open(str(servidor.DATA_DIR))),
        pystray.MenuItem(lambda i: f"Esquecer celulares pareados ({len(srv.tokens)})",
                         lambda i, it: srv.esquecer_celulares()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Sair", sair),
    )
    icon = pystray.Icon("SofaHub", Image.open(servidor.WEB_DIR / "icon-192.png"), "SofaHub", menu)
    srv.ao_mudar = icon.update_menu

    def alerta(msg):
        try:
            icon.notify(msg, "SofaHub")
        except Exception:
            pass
    srv.ao_alerta = alerta

    def ao_iniciar(icon):
        icon.visible = True
        if not srv.tokens or "--configurar" in sys.argv:   # primeira vez (ou recém-instalado): tela de configuração
            configurar()

    icon.run(setup=ao_iniciar)


if __name__ == "__main__":
    main()
