"""Ícone automático dos atalhos: baixa o ícone que o próprio site publica (apple-touch-icon,
<link rel="icon">, favicon) e guarda uma cópia em PNG na pasta de dados do usuário."""
import io
import logging
import re
from html import unescape
from urllib.parse import urljoin, urlparse

log = logging.getLogger("sofahub")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0 Safari/537.36")
MAX_PAGINA = 1_500_000
MAX_ICONE = 1_000_000
TAM_FINAL = 256


async def _baixar(sessao, url, limite):
    async with sessao.get(url, headers={"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"},
                          allow_redirects=True, max_redirects=5) as r:
        if r.status != 200 or not str(r.url).startswith("https://"):
            return None, ""
        dados = await r.content.read(limite + 1)
        if len(dados) > limite:
            return None, ""
        return dados, r.headers.get("Content-Type", "")


def _candidatos(html, base):
    """Ícones declarados na página, do mais provável de ser bonito ao menos."""
    achados = []
    for tag in re.findall(r"<link\b[^>]*>", html, flags=re.I):
        atrib = {k.lower(): unescape(v) for k, _, v in
                 re.findall(r'([\w-]+)\s*=\s*(["\'])(.*?)\2', tag, flags=re.S)}
        rel = atrib.get("rel", "").lower()
        href = atrib.get("href")
        if not href or "icon" not in rel or href.lower().endswith(".svg") or "mask-icon" in rel:
            continue
        tam = 0
        m = re.search(r"(\d+)x\d+", atrib.get("sizes", ""))
        if m:
            tam = int(m.group(1))
        elif "apple-touch-icon" in rel:
            tam = 180
        achados.append((tam, urljoin(base, href)))
    achados.sort(key=lambda t: -t[0])
    urls = [u for _, u in achados]
    raiz = "{0.scheme}://{0.netloc}".format(urlparse(base))
    urls += [raiz + "/apple-touch-icon.png", raiz + "/favicon.ico"]
    vistos, saida = set(), []
    for u in urls:
        if u.startswith("https://") and u not in vistos:
            vistos.add(u)
            saida.append(u)
    return saida[:8]


def _para_png(dados):
    """Abre com o Pillow (descarta o que não for imagem) e devolve um PNG limpo."""
    from PIL import Image
    img = Image.open(io.BytesIO(dados))
    if getattr(img, "n_frames", 1) > 1 and img.format == "ICO":
        img.size = max(img.info.get("sizes", [img.size]))   # .ico: pega o maior tamanho
    img = img.convert("RGBA")
    if max(img.size) > TAM_FINAL:
        img.thumbnail((TAM_FINAL, TAM_FINAL), Image.LANCZOS)
    saida = io.BytesIO()
    img.save(saida, "PNG", optimize=True)
    return img.size[0], saida.getvalue()


async def buscar_icone(sessao, url_site):
    """PNG do ícone do site, ou None. Prefere ícones grandes (≥ 96 px)."""
    if not url_site.startswith("https://"):
        return None
    try:
        pagina, tipo = await _baixar(sessao, url_site, MAX_PAGINA)
    except Exception as e:
        log.info("ícone: não abriu %s (%s)", url_site, e)
        pagina, tipo = None, ""
    html = pagina.decode("utf-8", "replace") if pagina and "html" in tipo else ""
    melhor = None
    for u in _candidatos(html, url_site):
        try:
            dados, _ = await _baixar(sessao, u, MAX_ICONE)
            if not dados:
                continue
            lado, png = _para_png(dados)
        except Exception:
            continue
        if lado >= 96:
            return png
        if lado >= 32 and (melhor is None or lado > melhor[0]):
            melhor = (lado, png)
    return melhor[1] if melhor else None
