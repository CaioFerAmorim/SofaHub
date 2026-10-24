"""Servidor do SofaHub: serve o app do celular e faz a ponte celular ↔ PC ↔ extensão do Chrome."""
import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import quote_plus

from aiohttp import web, WSMsgType

import sistema
from sistema import kb, ms, Key, apertar, botao

VERSAO = "0.7.1"
log = logging.getLogger("sofahub")

APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def _pasta_dados() -> Path:
    """Onde ficam PIN, celulares pareados, logs e o perfil do navegador.
    - Rodando pelo código-fonte: a própria pasta do projeto.
    - .exe portátil (tem tokens.json ou portable.txt ao lado): ao lado do .exe.
    - .exe instalado: %LOCALAPPDATA%\\SofaHub — atualizar/reinstalar nunca apaga os dados."""
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent
    exe_dir = Path(sys.executable).parent
    if (exe_dir / "tokens.json").exists() or (exe_dir / "portable.txt").exists():
        return exe_dir
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    pasta = Path(base) / "SofaHub"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


DATA_DIR = _pasta_dados()
WEB_DIR = APP_DIR / "web"
CONFIG_FILE = DATA_DIR / "config.json"
PRESETS_FILE = DATA_DIR / "presets.json"
TOKENS_FILE = DATA_DIR / "tokens.json"
EXT_DIR = DATA_DIR / "extensao"
PERFIL_DIR = DATA_DIR / "perfil-navegador"   # perfil exclusivo: logins e extensão ficam aqui

TAM_MAX_MSG = 64 * 1024   # mensagens do celular/extensão são pequenas


def preparar_arquivos():
    """Copia presets e extensão para a pasta de dados (editáveis e com caminho fixo)."""
    (DATA_DIR / "icones").mkdir(exist_ok=True)
    if not PRESETS_FILE.exists() and (APP_DIR / "presets.json").exists():
        shutil.copy(APP_DIR / "presets.json", PRESETS_FILE)
    if APP_DIR != DATA_DIR and (APP_DIR / "extensao").exists():
        shutil.copytree(APP_DIR / "extensao", EXT_DIR, dirs_exist_ok=True)


def ler_json(caminho, padrao):
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return padrao
    except json.JSONDecodeError as e:
        log.error("%s inválido: %s", caminho.name, e)
        return padrao


def salvar_json(caminho, dados):
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")   # grava inteiro e troca: nunca fica pela metade
    tmp.write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, caminho)


def ip_local():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))   # não envia nada; só descobre a interface de saída
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


# ------------------------------------------------------------------
# Segurança
# ------------------------------------------------------------------
CGNAT = ipaddress.ip_network("100.64.0.0/10")   # Tailscale


def rede_privada(ip: str) -> bool:
    """Aceita só aparelhos da rede de casa (e do Tailscale), nunca endereços da internet."""
    try:
        a = ipaddress.ip_address((ip or "").split("%")[0])
    except ValueError:
        return False
    if getattr(a, "ipv4_mapped", None):
        a = a.ipv4_mapped
    return a.is_private or a.is_loopback or a.is_link_local or (a.version == 4 and a in CGNAT)


def origem_privada(origin: str) -> bool:
    """Origem http(s) de um aparelho da rede local (o app aberto a partir de outro SofaHub)."""
    m = re.fullmatch(r"https?://(\[[0-9a-fA-F:]+\]|[^/:]+)(:\d{1,5})?", origin or "")
    if not m:
        return False
    host = m.group(1).strip("[]")
    return host == "localhost" or rede_privada(host)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def limitar(v, lo, hi, padrao=0):
    try:
        return max(lo, min(hi, int(float(v))))
    except (TypeError, ValueError):
        return padrao


# Comandos de página que o celular pode repassar à extensão — qualquer outro é recusado
COMANDOS_SITE = {"up", "down", "left", "right", "ok", "voltar", "proximo", "anterior", "cinema",
                 "servidor", "playpause", "seek", "cursor", "diag"}

DIGITOS_PIN = 6
TENTATIVAS_POR_PIN = 5


# ------------------------------------------------------------------
class Navegador:
    def __init__(self, cfg):
        self.cfg = cfg
        self.proc = None

    def achar(self):
        if self.cfg.get("navegador"):
            return self.cfg["navegador"]
        bases = [os.environ.get(v) for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        for rel in ("Google/Chrome/Application/chrome.exe", "Microsoft/Edge/Application/msedge.exe"):
            for b in filter(None, bases):
                p = Path(b) / rel
                if p.exists():
                    return str(p)
        for nome in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
            p = shutil.which(nome)
            if p:
                return p
        return None

    def abrir(self, url):
        if not re.match(r"https?://", url or ""):
            raise ValueError("endereço inválido")
        exe = self.achar()
        if not exe:
            raise RuntimeError("Chrome/Edge não encontrado — defina 'navegador' no config.json")
        self.proc = subprocess.Popen([
            exe,
            f"--user-data-dir={PERFIL_DIR}",
            f"--load-extension={EXT_DIR}",   # ignorado no Chrome novo; aí vale a instalação manual
            "--start-fullscreen",
            "--no-first-run",
            "--no-default-browser-check",
            "--hide-crash-restore-bubble",
            "--disable-session-crashed-bubble",
            "--autoplay-policy=no-user-gesture-required",
            "--silent-debugger-extension-api",   # sem a faixa amarela "começou a depurar este navegador"
            url,
        ])

    def abrir_extensoes(self):
        """Abre a página de extensões do perfil do SofaHub (para 'Carregar sem compactação')."""
        exe = self.achar()
        if not exe:
            raise RuntimeError("Chrome/Edge não encontrado")
        pagina = "edge://extensions/" if "msedge" in exe.lower() else "chrome://extensions/"
        # se o perfil já estiver aberto, o Chrome só abre uma janela nova nele
        subprocess.Popen([exe, f"--user-data-dir={PERFIL_DIR}", "--no-first-run",
                                      "--no-default-browser-check", pagina])

    def fechar(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None


class AltTab:
    """Segura o Alt entre toques: cada toque avança uma janela; solta 1,2 s depois."""

    def __init__(self):
        self.segurando = False
        self.timer = None

    async def tocar(self, reverso=False):
        if not self.segurando:
            kb.press(Key.alt)
            self.segurando = True
        if reverso:
            kb.press(Key.shift)
        kb.press(Key.tab)
        kb.release(Key.tab)
        if reverso:
            kb.release(Key.shift)
        if self.timer:
            self.timer.cancel()
        self.timer = asyncio.create_task(self._depois())

    async def _depois(self):
        try:
            await asyncio.sleep(1.2)
        except asyncio.CancelledError:
            return
        self.soltar()

    def soltar(self):
        if self.segurando:
            kb.release(Key.alt)
            self.segurando = False


# Sem extensão, o controle cai nestas teclas reais (funciona "mais ou menos").
FALLBACK = {
    "up": "up", "down": "down", "left": "left", "right": "right", "ok": "enter",
    "voltar": "alt+left", "playpause": "playpause", "cinema": "f11",
}


# ------------------------------------------------------------------
class Servidor:
    def __init__(self):
        preparar_arquivos()
        self.cfg = {"nome": socket.gethostname(), "porta": 8765, "navegador": ""}
        self.cfg.update(ler_json(CONFIG_FILE, {}))
        self.cfg.setdefault("id", uuid.uuid4().hex[:12])
        salvar_json(CONFIG_FILE, self.cfg)
        self.tokens = self._carregar_tokens()
        self.pin = self._novo_pin()
        self.tentativas = 0        # erros com o PIN atual
        self.bloqueios = 0         # quantas vezes já bloqueou (o tempo dobra a cada vez)
        self.bloqueado_ate = 0.0
        self.nav = Navegador(self.cfg)
        self.alttab = AltTab()
        self.celulares = set()
        self.ext = None            # WebSocket da extensão do Chrome
        self.loop = None
        self.erro = None
        self._pronto = threading.Event()
        self._salvar_visto = 0.0
        self.ao_mudar = lambda: None    # avisa a bandeja (ex.: extensão conectou)
        self.ao_alerta = lambda msg: None   # notificação do Windows (ex.: PIN errado várias vezes)

    # ---------------- tokens e PIN ----------------
    def _carregar_tokens(self):
        """tokens.json guarda só o hash de cada token. Tokens antigos (em texto) são convertidos
        na hora — os celulares já pareados continuam funcionando, sem novo PIN."""
        bruto = ler_json(TOKENS_FILE, {})
        tokens, mudou = {}, False
        for chave, info in bruto.items():
            info = info if isinstance(info, dict) else {}
            if info.get("hash"):
                tokens[chave] = info
            else:
                tokens[hash_token(chave)] = {**info, "hash": True}
                mudou = True
        if mudou:
            salvar_json(TOKENS_FILE, tokens)
            log.info("tokens convertidos para hash (%d)", len(tokens))
        return tokens

    def _novo_pin(self):
        return f"{secrets.randbelow(10 ** DIGITOS_PIN):0{DIGITOS_PIN}d}"

    def token_valido(self, token) -> bool:
        if not isinstance(token, str) or not 16 <= len(token) <= 128:
            return False
        info = self.tokens.get(hash_token(token))
        if not info:
            return False
        agora = time.time()
        info["visto"] = time.strftime("%Y-%m-%d %H:%M")
        if agora - self._salvar_visto > 600:   # grava "visto por último" no máximo a cada 10 min
            self._salvar_visto = agora
            salvar_json(TOKENS_FILE, self.tokens)
        return True

    def esquecer_celulares(self):
        self.tokens = {}
        salvar_json(TOKENS_FILE, self.tokens)
        self.pin = self._novo_pin()
        for ws in list(self.celulares):
            asyncio.run_coroutine_threadsafe(ws.close(), self.loop)
        self.ao_mudar()

    # ---------------- dados ----------------
    @property
    def porta(self):
        return int(self.cfg["porta"])

    @property
    def endereco(self):
        return f"http://{ip_local()}:{self.porta}"

    @property
    def ext_on(self):
        return self.ext is not None and not self.ext.closed

    def presets(self):
        return ler_json(PRESETS_FILE, [])

    def preset(self, pid):
        for p in self.presets():
            if p.get("id") == pid:
                return p
        raise ValueError("atalho não existe")

    # ---------------- HTTP ----------------
    async def h_info(self, req):
        return web.json_response({"app": "sofahub", "id": self.cfg["id"], "nome": self.cfg["nome"], "versao": VERSAO})

    async def h_auth(self, req):
        token = req.query.get("token")
        if req.method == "POST":
            try:
                token = (await req.json()).get("token")
            except Exception:
                token = None
        ok = self.token_valido(token)
        return web.json_response({"ok": ok}, status=200 if ok else 401)

    async def h_parear(self, req):
        agora = time.time()
        if agora < self.bloqueado_ate:
            espera = int(self.bloqueado_ate - agora) + 1
            return web.json_response({"erro": f"Muitas tentativas. Aguarde {espera // 60 + 1} min."}, status=429)
        if req.content_type != "application/json":   # força a checagem de CORS do navegador
            return web.json_response({"erro": "formato inválido"}, status=415)
        try:
            dados = await req.json()
        except Exception:
            return web.json_response({"erro": "formato inválido"}, status=400)
        pin = str(dados.get("pin", "")).strip()
        if not hmac.compare_digest(pin.encode(), self.pin.encode()):
            self.tentativas += 1
            log.warning("PIN errado vindo de %s (%d/%d)", req.remote, self.tentativas, TENTATIVAS_POR_PIN)
            if self.tentativas >= TENTATIVAS_POR_PIN:
                # troca o PIN e bloqueia por um tempo que dobra a cada vez (1, 2, 4... até 60 min)
                self.tentativas = 0
                self.bloqueios += 1
                self.bloqueado_ate = agora + 60 * min(60, 2 ** (self.bloqueios - 1))
                self.pin = self._novo_pin()
                self.ao_mudar()
                self.ao_alerta(f"Alguém errou o PIN {TENTATIVAS_POR_PIN} vezes ({req.remote}). "
                               "O PIN foi trocado — veja o novo no menu do SofaHub.")
            return web.json_response({"erro": "PIN incorreto"}, status=403)
        self.tentativas = 0
        self.bloqueios = 0
        token = secrets.token_urlsafe(32)
        self.tokens[hash_token(token)] = {"hash": True, "dispositivo": str(dados.get("dispositivo", "celular"))[:40],
                                          "criado": time.strftime("%Y-%m-%d %H:%M"), "ip": req.remote}
        salvar_json(TOKENS_FILE, self.tokens)
        self.pin = self._novo_pin()   # cada PIN vale para um pareamento só
        log.info("celular pareado: %s (%s)", self.tokens[hash_token(token)]["dispositivo"], req.remote)
        self.ao_mudar()
        return web.json_response({"token": token, "nome": self.cfg["nome"]})

    async def h_arquivo(self, req):
        nome = req.match_info.get("nome") or "index.html"
        if nome == "configurar.html":   # essa só pelo /configurar, no próprio notebook
            raise web.HTTPNotFound()
        caminho = (WEB_DIR / nome).resolve()
        if WEB_DIR.resolve() not in caminho.parents or not caminho.is_file():
            raise web.HTTPNotFound()
        resp = web.FileResponse(caminho)
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    async def h_icone(self, req):
        """Ícones próprios dos atalhos: ficam na pasta de dados, em icones/ (sobrevivem às atualizações)."""
        pasta = (DATA_DIR / "icones").resolve()
        caminho = (pasta / req.match_info["nome"]).resolve()
        if pasta not in caminho.parents or not caminho.is_file() or \
                caminho.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):   # sem SVG: pode ter script
            raise web.HTTPNotFound()
        return web.FileResponse(caminho)

    # ---------------- tela de configuração (só no próprio notebook) ----------------
    def _local_ok(self, req) -> bool:
        """Só o navegador do próprio notebook, abrindo o endereço local do SofaHub.
        Checa também Host/Origin: um site qualquer aberto no PC não consegue ler o PIN."""
        if req.remote not in ("127.0.0.1", "::1"):
            return False
        locais = {f"127.0.0.1:{self.porta}", f"localhost:{self.porta}", f"[::1]:{self.porta}"}
        if req.host not in locais:
            return False
        origem = req.headers.get("Origin")
        return origem is None or origem in {f"http://{h}" for h in locais}

    @property
    def endereco_local(self):
        return f"http://127.0.0.1:{self.porta}/configurar"

    async def h_configurar(self, req):
        if not self._local_ok(req):
            raise web.HTTPNotFound()
        resp = web.FileResponse(WEB_DIR / "configurar.html")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    async def h_local_estado(self, req):
        if not self._local_ok(req):
            raise web.HTTPNotFound()
        link = f"{self.endereco}/#pin={self.pin}"
        try:
            import segno
            qr = segno.make(link, error="m").svg_inline(scale=7, border=2, dark="#000", light="#fff")
        except Exception as e:   # sem a biblioteca: a página mostra só o endereço e o PIN
            log.warning("QR indisponível: %s", e)
            qr = ""
        resp = web.json_response({
            "nome": self.cfg["nome"], "versao": VERSAO, "endereco": self.endereco, "pin": self.pin,
            "qr": qr, "pareados": len(self.tokens), "ext": self.ext_on,
            "pasta_extensao": str(EXT_DIR), "navegador": bool(self.nav.achar()),
            "inicio": sistema.inicio_ativo(),
        })
        resp.headers["Cache-Control"] = "no-store"
        return resp

    async def h_local_extensoes(self, req):
        if not self._local_ok(req) or req.content_type != "application/json":
            raise web.HTTPNotFound()
        sistema.copiar(str(EXT_DIR))   # é só colar (Ctrl+V) na janela "Carregar sem compactação"
        try:
            self.nav.abrir_extensoes()
        except Exception as e:
            return web.json_response({"erro": str(e)}, status=500)
        return web.json_response({"ok": True})

    async def h_local_inicio(self, req):
        if not self._local_ok(req) or req.content_type != "application/json":
            raise web.HTTPNotFound()
        sistema.definir_inicio(bool((await req.json()).get("ativo")))
        self.ao_mudar()
        return web.json_response({"inicio": sistema.inicio_ativo()})

    # ---------------- celular ----------------
    def _hello(self):
        return {"t": "hello", "nome": self.cfg["nome"], "presets": self.presets(),
                "ext": self.ext_on, "input": sistema.INPUT_OK}

    async def para_celulares(self, msg):
        for ws in list(self.celulares):
            try:
                await ws.send_json(msg)
            except Exception:
                pass

    async def h_ws_celular(self, req):
        if not self.token_valido(req.query.get("token")):
            raise web.HTTPUnauthorized()
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=TAM_MAX_MSG)
        await ws.prepare(req)
        self.celulares.add(ws)
        try:
            await ws.send_json(self._hello())
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    m = json.loads(msg.data)
                    if not isinstance(m, dict):
                        raise ValueError("mensagem inválida")
                    await self.comando(m, ws)
                except Exception as e:
                    log.warning("comando falhou: %s", e)
                    await ws.send_json({"t": "erro", "msg": str(e)[:200]})
        finally:
            self.celulares.discard(ws)
        return ws

    async def abrir_url(self, url):
        if not re.match(r"https?://", url or ""):
            raise ValueError("endereço inválido no atalho")
        sistema.ligar_tela()
        if self.ext_on:
            await self.ext.send_json({"t": "cmd", "c": "abrir", "url": url})
        else:
            self.nav.abrir(url)

    async def comando(self, m, ws):
        t = m.get("t")
        if t == "move":
            ms.move(limitar(m.get("dx"), -3000, 3000), limitar(m.get("dy"), -3000, 3000))
        elif t == "click":
            ms.click(botao(m.get("b")), 2 if m.get("double") else 1)
        elif t == "button":
            (ms.press if m.get("down") else ms.release)(botao(m.get("b")))
        elif t == "scroll":
            ms.scroll(limitar(m.get("dx"), -50, 50), limitar(m.get("dy"), -50, 50))
        elif t == "key":
            self.alttab.soltar()
            apertar(str(m.get("k", ""))[:40])
        elif t == "text":
            kb.type(str(m.get("s", ""))[:500])
        elif t == "alttab":
            await self.alttab.tocar(bool(m.get("rev")))
        elif t == "ligar":
            sistema.ligar_tela()
        elif t == "estacionar":
            sistema.estacionar_cursor()
        elif t == "preset":
            p = self.preset(m.get("id"))
            await self.abrir_url(p["url"])
            await ws.send_json({"t": "ok", "msg": f"Abrindo {p['nome']}"})
        elif t == "site":
            await self.comando_site(m, ws)
        elif t == "close":
            if self.ext_on:
                await self.ext.send_json({"t": "cmd", "c": "fechar"})
            self.nav.fechar()
        else:
            raise ValueError("comando desconhecido")

    async def comando_site(self, m, ws):
        c = m.get("c")
        p = self.preset(m["id"]) if m.get("id") else None
        q = str(m.get("q", ""))[:200]
        if c == "inicio" and p:
            return await self.abrir_url(p["url"])
        if c == "busca" and p and p.get("busca"):
            return await self.abrir_url(p["busca"].replace("{q}", quote_plus(q)))
        if c == "busca" and p and p.get("busca_pagina") and self.ext_on:
            # abre a página de busca do site; a extensão preenche o campo quando carregar
            sistema.ligar_tela()
            return await self.ext.send_json({"t": "cmd", "c": "buscar_pagina", "url": p["busca_pagina"], "q": q})
        if c not in COMANDOS_SITE:
            raise ValueError("comando não permitido")
        sistema.tela_ativa()   # sem mexer no mouse: senão o cursor e os controles do player reaparecem
        if self.ext_on:
            # repassa só campos conhecidos, com valores conferidos
            fwd = {"t": "cmd", "c": c}
            if "s" in m:
                fwd["s"] = limitar(m.get("s"), -600, 600)
            if p:
                fwd["id"] = p["id"]
            return await self.ext.send_json(fwd)
        # sem extensão: aproximação com teclas reais
        if c == "seek":
            return apertar("right" if limitar(m.get("s"), -600, 600, 10) > 0 else "left")
        if c in FALLBACK:
            return apertar(FALLBACK[c])
        raise ValueError("Essa função precisa da extensão do Chrome (veja o README)")

    # ---------------- extensão ----------------
    async def h_ws_ext(self, req):
        # Só a extensão: conexão da própria máquina E vinda de uma extensão do Chrome.
        # (Sites comuns também conseguem abrir WebSocket para 127.0.0.1, mas o navegador
        #  sempre envia a origem verdadeira deles — https://… — e não dá para falsificar.)
        origem = req.headers.get("Origin", "")
        if req.remote not in ("127.0.0.1", "::1") or not origem.startswith("chrome-extension://"):
            log.warning("conexão recusada na /ext: %s origem=%r", req.remote, origem[:80])
            raise web.HTTPForbidden()
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=TAM_MAX_MSG)
        await ws.prepare(req)
        if self.ext_on:
            await self.ext.close()
        self.ext = ws
        log.info("extensão conectada (%s)", origem)
        await self.para_celulares({"t": "ext", "on": True})
        self.ao_mudar()
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    m = json.loads(msg.data)
                except ValueError:
                    continue
                if not isinstance(m, dict):
                    continue
                t = m.get("t")
                if t == "aviso":
                    await self.para_celulares({"t": "ok", "msg": str(m.get("msg", ""))[:300]})
                elif t == "clique_os":
                    await asyncio.to_thread(sistema.clique_tela, float(m.get("fx", 0.5)), float(m.get("fy", 0.5)))
                elif t == "clique_px":
                    await asyncio.to_thread(sistema.clique_px, float(m.get("x", 0)), float(m.get("y", 0)))
                elif t == "clique_aqui":
                    await asyncio.to_thread(sistema.clique_aqui)
                elif t == "estacionar":
                    await asyncio.to_thread(sistema.estacionar_cursor)
        finally:
            if self.ext is ws:
                self.ext = None
                log.info("extensão desconectada")
                await self.para_celulares({"t": "ext", "on": False})
                self.ao_mudar()
        return ws

    # ---------------- ciclo de vida ----------------
    def criar_app(self):
        @web.middleware
        async def protecao(req, handler):
            # 1) só aparelhos da rede de casa/Tailscale — nada vindo da internet
            if not rede_privada(req.remote):
                log.warning("acesso recusado de %s", req.remote)
                return web.Response(status=403)
            origem = req.headers.get("Origin")
            if req.path in ("/ws", "/ext"):
                return await handler(req)
            # 2) CORS só para o app aberto a partir de outro SofaHub da rede (busca na rede)
            if req.method == "OPTIONS":
                resp = web.Response()
            else:
                resp = await handler(req)
            if origem and origem_privada(origem):
                resp.headers["Access-Control-Allow-Origin"] = origem
                resp.headers["Vary"] = "Origin"
                resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
                resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
                resp.headers["Access-Control-Allow-Private-Network"] = "true"
            # 3) cabeçalhos de proteção do app
            resp.headers["X-Content-Type-Options"] = "nosniff"
            resp.headers["Referrer-Policy"] = "no-referrer"
            resp.headers["X-Frame-Options"] = "DENY"
            if req.path in ("/", "/configurar") or req.path.endswith(".html"):
                resp.headers["Content-Security-Policy"] = (
                    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                    "img-src 'self' data:; connect-src 'self' http: https: ws: wss:; "
                    "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            return resp

        app = web.Application(middlewares=[protecao], client_max_size=TAM_MAX_MSG)
        app.router.add_get("/api/info", self.h_info)
        app.router.add_get("/api/auth", self.h_auth)
        app.router.add_post("/api/auth", self.h_auth)
        app.router.add_post("/api/pair", self.h_parear)
        app.router.add_get("/ws", self.h_ws_celular)
        app.router.add_get("/ext", self.h_ws_ext)
        app.router.add_get("/icones/{nome}", self.h_icone)
        app.router.add_get("/configurar", self.h_configurar)
        app.router.add_get("/api/local/estado", self.h_local_estado)
        app.router.add_post("/api/local/extensoes", self.h_local_extensoes)
        app.router.add_post("/api/local/inicio", self.h_local_inicio)
        app.router.add_get("/", self.h_arquivo)
        app.router.add_get("/{nome}", self.h_arquivo)
        return app

    def _rodar(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        # access_log desligado: os endereços carregam o token do celular e não podem ir para o log
        runner = web.AppRunner(self.criar_app(), access_log=None)
        self.loop.run_until_complete(runner.setup())
        try:
            self.loop.run_until_complete(web.TCPSite(runner, "0.0.0.0", self.porta).start())
        except OSError as e:
            self.erro = e
            self._pronto.set()
            return
        self._pronto.set()
        self.loop.run_forever()
        self.alttab.soltar()
        self.loop.run_until_complete(runner.cleanup())

    def iniciar(self):
        threading.Thread(target=self._rodar, daemon=True, name="servidor").start()
        self._pronto.wait(10)
        if self.erro:
            raise self.erro

    def parar(self):
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)


def limpar_log_antigo(caminho: Path):
    """Versões antigas gravavam o token do celular no log: apaga essas marcas."""
    for arq in (caminho, caminho.with_name(caminho.name + ".1")):
        try:
            txt = arq.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            continue
        limpo = re.sub(r"token=[A-Za-z0-9_\-]+", "token=***", txt)
        limpo = re.sub(r"\(PIN \d+\)", "", limpo)
        if limpo != txt:
            arq.write_text(limpo, encoding="utf-8")


if __name__ == "__main__":   # modo terminal, sem ícone na bandeja (útil para depurar)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    s = Servidor()
    s.iniciar()
    sistema.manter_acordado()
    print(f"SofaHub {VERSAO} — {s.cfg['nome']}\nCelular: {s.endereco}\nPIN: {s.pin}", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        s.parar()
