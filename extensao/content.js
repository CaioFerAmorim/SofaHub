// Roda em todas as páginas e frames: navegação estilo TV, player e tela cheia.
(() => {
  if (window.__sofahub) return;
  window.__sofahub = true;

  const TOP = window === window.top;
  const HOST = location.hostname.replace(/^www\./, '');

  // Ajustes por site:
  //  player   → páginas de vídeo (seleciona o servidor e entra em tela cheia sozinho)
  //  servidor → servidor de vídeo preferido, clicado automaticamente
  //  inicio   → onde a primeira seta cai em cada tipo de página
  const SITES = {
    // 'exemplo.com': {
    //   player: /^\/(episodios|filmes)\//,   // caminho das páginas que têm o player
    //   servidor: /^\s*1\b/i,                 // texto do botão do servidor de vídeo preferido
    //   reserva: [2, 3],                       // servidores para tentar se o preferido não carregar
    //   inicio: [{ caminho: /^\/series\//, texto: /^\s*temporada/i }],
    // },
  };
  const SITE = SITES[HOST] || {};

  const espera = ms => new Promise(r => setTimeout(r, ms));
  const bg = msg => chrome.runtime.sendMessage(msg).catch(() => null);
  const avisar = msg => bg({ t: 'aviso', msg });
  const repassar = cmd => bg({ t: 'repassar', cmd });

  /* ================= Aviso na tela (OSD) ================= */
  function osd(txt) {
    let d = document.getElementById('__sofahub_osd');
    if (!d) {
      d = document.createElement('div');
      d.id = '__sofahub_osd';
      Object.assign(d.style, {
        position: 'fixed', top: '6%', right: '4%', zIndex: 2147483647, background: 'rgba(0,0,0,.78)',
        color: '#fff', font: '600 26px system-ui,Segoe UI,sans-serif', padding: '14px 24px',
        borderRadius: '14px', pointerEvents: 'none', transition: 'opacity .25s', opacity: 0,
      });
      (document.body || document.documentElement).appendChild(d);
    }
    d.textContent = txt;
    d.style.opacity = 1;
    clearTimeout(osd.t);
    osd.t = setTimeout(() => (d.style.opacity = 0), 1800);
  }
  const tempo = s => {
    if (!isFinite(s)) return '--:--';
    s = Math.floor(s);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = String(s % 60).padStart(2, '0');
    return h ? `${h}:${String(m).padStart(2, '0')}:${x}` : `${m}:${x}`;
  };

  /* ================= Vídeo (no frame que tiver o player) ================= */
  function videoPrincipal() {
    let best = null, area = 0;
    for (const v of document.querySelectorAll('video')) {
      const r = v.getBoundingClientRect();
      const a = r.width * r.height;
      if (a >= 40000 && a > area) { best = v; area = a; }   // ignora vídeos pequenos (anúncios)
    }
    return best;
  }

  // Onde clicar para dar play neste frame: o botão de play mais perto do centro, ou o centro.
  // Botões de "continuar de onde parou" têm prioridade (janelas "Continuar assistindo?").
  const RETOMAR = /^\s*(continuar|continuar assistindo|continue|retomar|resume)\s*$/i;
  function botaoRetomar() {
    const els = [...document.querySelectorAll('button, [role=button], a, div, span')].filter(el => {
      const t = (el.textContent || '').trim();
      if (t.length > 25 || !RETOMAR.test(t)) return false;
      const r = el.getBoundingClientRect(), st = getComputedStyle(el);
      return r.width >= 20 && r.height >= 14 && st.visibility !== 'hidden' && st.display !== 'none' && Number(st.opacity) > 0.05;
    });
    els.sort((a, b) => a.textContent.length - b.textContent.length);
    if (!els[0]) return null;
    const r = els[0].getBoundingClientRect();
    const x = r.left + r.width / 2, y = r.top + r.height / 2;
    return { x, y, removidas: liberarPonto(x, y, els[0]), em: cadeia(document.elementFromPoint(x, y)) };
  }

  function acharPortao() {
    return document.querySelector('[class*=captcha-gate], [class*=captcha_gate]');
  }
  function cadeia(e) {   // "div.a > button.b" para diagnóstico
    const partes = [];
    for (let i = 0; e && i < 4; i++, e = e.parentElement)
      partes.push(e.tagName.toLowerCase() + (typeof e.className === 'string' && e.className ? '.' + e.className.trim().split(/\s+/).slice(0, 2).join('.') : ''));
    return partes.join(' < ');
  }
  // Camadas transparentes de anúncio ("clickjacking") ficam por cima dos botões do player e
  // roubam o clique. Desliga o clique nelas até o ponto (x, y) chegar ao elemento certo.
  function liberarPonto(x, y, alvoEl) {
    let removidas = 0;
    for (let i = 0; i < 8; i++) {
      const e = document.elementFromPoint(x, y);
      if (!e || e === alvoEl || alvoEl.contains(e) || e.contains(alvoEl)) break;
      e.style.setProperty('pointer-events', 'none', 'important');
      removidas++;
    }
    return removidas;
  }

  function alvoPlay() {
    const retomar = botaoRetomar();
    if (retomar) return { fx: retomar.x / innerWidth, fy: retomar.y / innerHeight, botao: true, retomar: true, removidas: retomar.removidas, em: retomar.em };
    const cx = innerWidth / 2, cy = innerHeight / 2;
    const sel = 'button, [role=button], [class*=play i], [id*=play i], [aria-label*=play i], [aria-label*=reprod i], [title*=play i], svg';
    let best = null, dist = Infinity;
    for (const el of document.querySelectorAll(sel)) {
      const r = el.getBoundingClientRect();
      if (r.width < 16 || r.height < 16 || r.width > innerWidth * 0.6 || r.height > innerHeight * 0.6) continue;
      const st = getComputedStyle(el);
      if (st.visibility === 'hidden' || st.display === 'none' || Number(st.opacity) < 0.05) continue;
      const x = r.left + r.width / 2, y = r.top + r.height / 2;
      const d = Math.hypot(x - cx, y - cy);
      if (d < dist && d < Math.min(innerWidth, innerHeight) * 0.3) { dist = d; best = { x, y, el }; }
    }
    if (best) liberarPonto(best.x, best.y, best.el);
    const p = best || { x: cx, y: cy };
    return { fx: p.x / innerWidth, fy: p.y / innerHeight, botao: !!best };
  }

  // Diagnóstico: registra onde os cliques reais caem (ligado só durante testes)
  let rastrearCliques = false;
  ['pointerdown', 'click'].forEach(tipo => document.addEventListener(tipo, ev => {
    if (!rastrearCliques) return;
    avisar(`CLIQUE ${tipo} ${TOP ? 'TOP' : location.host} trusted=${ev.isTrusted} em ${Math.round(ev.clientX)},${Math.round(ev.clientY)} alvo=${cadeia(ev.target)} defaultPrevented=${ev.defaultPrevented}`);
  }, true));

  chrome.runtime.onMessage.addListener((m, _s, responder) => {
    if (m.c === 'rastrear') { rastrearCliques = true; return; }
    if (m.c === 'api_play' || m.c === 'api_pause') {   // pede ao player (API dele) — só nos frames com vídeo/JW Player
      if (document.querySelector('video, .jwplayer, [id*=jwplayer]')) window.postMessage({ __sofahub: 'api', acao: m.c === 'api_play' ? 'play' : 'pause' }, '*');
      return;
    }
    if (m.c === 'diag') {                  // diagnóstico: cada frame descreve o que tem
      const vids = [...document.querySelectorAll('video')].map(v => {
        const r = v.getBoundingClientRect();
        return `${Math.round(r.width)}x${Math.round(r.height)} paused=${v.paused} t=${v.currentTime.toFixed(1)} muted=${v.muted}`;
      });
      const a = alvoPlay();
      const e = document.elementFromPoint(a.fx * innerWidth, a.fy * innerHeight);
      if (a.retomar) avisar(`DIAG continuar em ${a.fx.toFixed(3)},${a.fy.toFixed(3)} camadas removidas=${a.removidas} sob o alvo: ${a.em}`);
      avisar(`DIAG ${TOP ? 'TOP' : 'frame'} ${location.host}${location.pathname.slice(0, 25)} ${innerWidth}x${innerHeight} ` +
        `cursorOculto=${!!document.getElementById('__sofahub_cursor')} videos=[${vids.join(' | ')}] iframes=${document.querySelectorAll('iframe').length} alvo=${a.fx.toFixed(2)},${a.fy.toFixed(2)} botao=${a.botao} ` +
        `el=${e ? e.tagName + '.' + String(e.className && e.className.baseVal !== undefined ? e.className.baseVal : e.className).slice(0, 40) : '-'}`);
      return;
    }
    if (m.c === 'portao') {                // portão "verifique que você é humano" na tela?
      const g = document.querySelector('[class*=captcha-gate], [class*=captcha_gate]') ||
        [...document.querySelectorAll('div, p, span')].find(e => /verificar que voc[eê] [eé] humano/i.test(e.textContent || '') && (e.textContent || '').length < 120);
      if (g && g.getBoundingClientRect().width > 0) responder({ portao: true });
      return;
    }
    if (m.c === 'alvo_play') {             // só o frame do player (iframe grande) responde
      if (!TOP && innerWidth >= 320 && innerHeight >= 180) { const a = alvoPlay(); if (a.botao) responder(a); }
      return;
    }
    const v = videoPrincipal();
    if (m.c === 'estado_video') {           // só o frame com vídeo responde
      if (v) responder({ paused: v.paused, t: v.currentTime });
      return;
    }
    if (v) {
      if (m.c === 'pausar') { v.pause(); osd('❚❚'); }
      else if (m.c === 'osd') osd(m.txt);
      else if (m.c === 'seek') {
        const d = Number(m.s) || 10;
        const fim = isFinite(v.duration) ? v.duration - 1 : Infinity;
        v.currentTime = Math.max(0, Math.min(fim, v.currentTime + d));
        osd(`${d > 0 ? '⏩ +' : '⏪ '}${Math.abs(d)}s   ${tempo(v.currentTime)} / ${tempo(v.duration)}`);
      }
    }
    if (!TOP) return;
    if (m.c === 'liberar_top') {          // camada da página por cima do iframe do player
      const el = playerPrincipal();
      responder({ removidas: el ? liberarPonto(m.x, m.y, el) : 0 });
      return;
    }
    if (m.c === 'rect_player') {
      const el = playerPrincipal();
      if (el) { const r = el.getBoundingClientRect(); responder({ x: r.left + r.width / 2, y: r.top + r.height / 2, l: r.left, t: r.top, w: r.width, h: r.height, vw: innerWidth, vh: innerHeight,
        sx: screenX, sy: screenY, ow: outerWidth, oh: outerHeight, dpr: devicePixelRatio, cheia: !!document.fullscreenElement }); }
      return;
    }
    comandoPagina(m).catch(e => avisar('Erro: ' + e.message));
  });

  if (!TOP) return;   // daqui para baixo, só na página principal

  // o 2º clique rápido não pode virar "seleção" azul da página
  try {
    const st = document.createElement('style');
    st.textContent = 'iframe, video, [class*=player]{-webkit-user-select:none!important;user-select:none!important}';
    (document.head || document.documentElement).appendChild(st);
  } catch {}

  /* ================= Navegação por setas ================= */
  const SEL = 'a[href], button, [role=button], [role=link], [role=tab], [role=option], [role=menuitem], li[data-value], input:not([type=hidden]), select, textarea, [tabindex]:not([tabindex="-1"]), [onclick]';
  let atual = null;

  function visivel(el) {
    const r = el.getBoundingClientRect();
    if (r.width < 6 || r.height < 6) return false;
    const s = getComputedStyle(el);
    return s.visibility !== 'hidden' && s.display !== 'none' && Number(s.opacity) > 0.05;
  }

  function candidatos() {
    const tela = innerWidth * innerHeight;
    const els = [...document.querySelectorAll(SEL)].filter(el => {
      if (el.disabled || el.closest('#__sofahub_osd,#__sofahub_foco')) return false;
      if (!visivel(el)) return false;
      const r = el.getBoundingClientRect();
      return r.width * r.height < tela * 0.5;   // contêineres gigantes não contam
    });
    const set = new Set(els);                    // card com vários links dentro → só o mais externo
    return els.filter(el => {
      for (let p = el.parentElement; p; p = p.parentElement) if (set.has(p)) return false;
      return true;
    });
  }

  let abaixoDe = null;   // depois de uma busca, começa no primeiro resultado (abaixo do campo)
  function inicial(els) {
    for (const regra of SITE.inicio || []) {   // ex.: página da série → começa em "Temporada"
      if (!regra.caminho.test(location.pathname)) continue;
      const el = els.find(e => regra.texto.test((e.textContent || e.value || '').trim()));
      if (el) return el;
    }
    let alvo = { x: innerWidth * 0.25, y: innerHeight * 0.45 }, limite = -Infinity;
    if (abaixoDe && abaixoDe.isConnected) {
      const r = abaixoDe.getBoundingClientRect();
      limite = r.bottom - 2;
      alvo = { x: 0, y: r.bottom };
    }
    let best = null, dist = Infinity;
    for (const el of els) {
      if (el.matches('input, textarea, select')) continue;
      const r = el.getBoundingClientRect();
      if (r.top < limite || r.bottom < 0 || r.top > innerHeight) continue;
      const d = Math.hypot(r.left + r.width / 2 - alvo.x, r.top + r.height / 2 - alvo.y);
      if (d < dist) { dist = d; best = el; }
    }
    if (best) abaixoDe = null;
    return best || els[0];
  }

  const sobreposicao = (a1, a2, b1, b2) => Math.min(a2, b2) - Math.max(a1, b1) > 0;

  function mover(dir) {
    const els = candidatos();
    if (!els.length) return;
    if (!atual || !atual.isConnected || !els.includes(atual)) { marcar(inicial(els)); return; }
    const a = atual.getBoundingClientRect();
    const ax = a.left + a.width / 2, ay = a.top + a.height / 2;
    let best = null, melhor = Infinity;
    for (const el of els) {
      if (el === atual) continue;
      const r = el.getBoundingClientRect();
      const dx = r.left + r.width / 2 - ax, dy = r.top + r.height / 2 - ay;
      let prim, orto;
      if (dir === 'right' || dir === 'left') {
        prim = dir === 'right' ? dx : -dx;
        orto = sobreposicao(a.top, a.bottom, r.top, r.bottom) ? 0 : Math.abs(dy);
      } else {
        prim = dir === 'down' ? dy : -dy;
        orto = sobreposicao(a.left, a.right, r.left, r.right) ? 0 : Math.abs(dx);
      }
      if (prim <= 8 || orto > prim * 2) continue;
      const score = prim + orto * 2.5;
      if (score < melhor) { melhor = score; best = el; }
    }
    if (best) marcar(best);
    else if (dir === 'down' || dir === 'up') window.scrollBy({ top: (dir === 'down' ? 1 : -1) * innerHeight * 0.6, behavior: 'smooth' });
  }

  // Moldura laranja sobre o item selecionado
  let foco = null, focoT = null, focoRaf = 0;
  function moldura() {
    if (!foco) {
      foco = document.createElement('div');
      foco.id = '__sofahub_foco';
      Object.assign(foco.style, {
        position: 'fixed', zIndex: 2147483647, pointerEvents: 'none', border: '4px solid #ff7a1a',
        borderRadius: '10px', boxShadow: '0 0 0 4px rgba(255,122,26,.25), 0 0 24px rgba(255,122,26,.6)',
        transition: 'left .12s, top .12s, width .12s, height .12s, opacity .3s', opacity: 0,
      });
      document.documentElement.appendChild(foco);
    }
    return foco;
  }
  function acompanhar() {
    if (atual && atual.isConnected && foco && foco.style.opacity !== '0') {
      const r = atual.getBoundingClientRect();
      Object.assign(foco.style, { left: r.left - 6 + 'px', top: r.top - 6 + 'px', width: r.width + 12 + 'px', height: r.height + 12 + 'px' });
      focoRaf = requestAnimationFrame(acompanhar);
    } else focoRaf = 0;
  }
  function esconderMoldura() { if (foco) foco.style.opacity = 0; }
  function marcar(el) {
    if (!el) return;
    atual = el;
    const r = el.getBoundingClientRect();
    if (r.top < 80 || r.bottom > innerHeight - 20) el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    try { el.focus({ preventScroll: true }); } catch {}
    const f = moldura();
    f.style.opacity = 1;
    if (!focoRaf) acompanhar();
    clearTimeout(focoT);
    focoT = setTimeout(esconderMoldura, 8000);
  }

  function ok() {
    if (!atual || !atual.isConnected) { mover('down'); return; }
    const el = atual;
    if (el.tagName === 'SELECT') { osd('◀ ▶ trocam a opção'); return; }
    if (el.matches('input, textarea')) { el.focus(); avisar('Campo selecionado — digite na aba Mouse e Teclado'); return; }
    const link = el.closest('a[href]');
    if (link && link.target === '_blank') { location.href = link.href; return; }   // nova aba seria fechada como pop-up
    el.click();
    marcar(el);
  }

  function trocarOpcao(sel, passo) {
    const i = Math.max(0, Math.min(sel.options.length - 1, sel.selectedIndex + passo));
    if (i === sel.selectedIndex) return;
    sel.selectedIndex = i;
    sel.dispatchEvent(new Event('input', { bubbles: true }));
    sel.dispatchEvent(new Event('change', { bubbles: true }));
    osd(sel.options[i].text.trim());
  }

  /* ================= Botões do site ================= */
  // Elemento clicável mais interno cujo texto casa com a expressão.
  function acharPorTexto(re, max = 30) {
    const els = [...document.querySelectorAll('a, button, [role=button], li, [onclick], div, span')].filter(el => {
      const t = (el.textContent || '').trim();
      return t.length < max && re.test(t) && visivel(el);
    });
    els.sort((a, b) => a.textContent.length - b.textContent.length);
    return els[0] ? (els[0].closest('a, button, [role=button], li, [onclick]') || els[0]) : null;
  }

  /* ================= Busca ================= */
  function acharBusca() {
    return document.querySelector('input[type=search], input[name=s], input[name=q], input[name=search], input[name=busca], input[placeholder*="esquis" i], input[placeholder*="busca" i], input[placeholder*="earch" i]');
  }
  function definirValor(inp, v) {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    setter.call(inp, v);   // funciona também em sites React/Vue
    inp.dispatchEvent(new Event('input', { bubbles: true }));
    inp.dispatchEvent(new Event('change', { bubbles: true }));
  }
  async function buscar(q) {
    let inp = acharBusca();
    for (let i = 0; !inp && i < 20; i++) { await espera(250); inp = acharBusca(); }
    if (!inp) { avisar('Não achei o campo de busca nesta página'); return; }
    inp.focus();
    definirValor(inp, q);
    await espera(150);
    for (const type of ['keydown', 'keypress', 'keyup'])
      inp.dispatchEvent(new KeyboardEvent(type, { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
    if (inp.form) { try { inp.form.requestSubmit(); } catch { try { inp.form.submit(); } catch {} } }
    inp.blur();
    atual = null;
    abaixoDe = inp;
    osd(`🔎 ${q}`);
  }

  /* ================= Player e tela cheia ================= */
  function playerPrincipal() {
    let best = null, area = 0;
    for (const el of document.querySelectorAll('iframe, video')) {
      const r = el.getBoundingClientRect();
      const a = r.width * r.height;
      if (r.width >= 320 && r.height >= 180 && a > area) { best = el; area = a; }
    }
    return best;
  }
  // Espera um player aparecer (ou trocar, quando muda de servidor).
  async function esperarPlayer(antes, srcAntes) {
    for (let i = 0; i < 40; i++) {
      const p = playerPrincipal();
      if (p && (!antes || p !== antes || p.src !== srcAntes)) return p;
      await espera(400);
    }
    return null;
  }

  let querTelaCheia = false;   // você pediu tela cheia (e não saiu dela pelo controle)
  let ocupado = false;         // durante play/troca de servidor a tela cheia pode cair (anúncio) → volta sozinha

  // Plano B, só se o Chrome recusar a tela cheia de verdade: aumenta o player com CSS.
  let cssEl = null;
  const ANC = 'data-sofahub-anc';
  function cinemaCSS(ligar) {
    if (ligar) {
      const el = playerPrincipal();
      if (!el) return false;
      if (!document.getElementById('__sofahub_css')) {
        const st = document.createElement('style');
        st.id = '__sofahub_css';
        st.textContent = `
          [data-sofahub-cinema]{position:fixed!important;inset:0!important;width:100vw!important;height:100vh!important;
            max-width:none!important;max-height:none!important;margin:0!important;border:0!important;
            z-index:2147483646!important;background:#000!important;transform:none!important}
          [${ANC}]{transform:none!important;filter:none!important;z-index:2147483646!important}
          html.__sofahub_cinema, html.__sofahub_cinema body{overflow:hidden!important}`;
        document.documentElement.appendChild(st);
      }
      cssEl = el;
      el.setAttribute('data-sofahub-cinema', '');
      for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) p.setAttribute(ANC, '');
      document.documentElement.classList.add('__sofahub_cinema');
      return true;
    }
    if (cssEl) cssEl.removeAttribute('data-sofahub-cinema');
    document.querySelectorAll(`[${ANC}]`).forEach(e => e.removeAttribute(ANC));
    document.documentElement.classList.remove('__sofahub_cinema');
    cssEl = null;
    return true;
  }

  const emTelaCheia = () => !!document.fullscreenElement || !!cssEl;

  function avisoTela(txt) {   // em tela cheia só o player aparece: o aviso vai para dentro dele
    if (document.fullscreenElement && document.fullscreenElement.tagName === 'IFRAME') repassar({ c: 'osd', txt });
    else osd(txt);
  }

  async function entrarTelaCheia() {
    const el = playerPrincipal();
    if (!el) { avisar('Nenhum player nesta página'); return false; }
    document.querySelectorAll('[data-sofahub-player]').forEach(e => e !== el && e.removeAttribute('data-sofahub-player'));
    el.setAttribute('data-sofahub-player', '');
    querTelaCheia = true;
    esconderMoldura();
    if (document.fullscreenElement === el) return true;
    const r = await bg({ t: 'tela_cheia' });
    if (r && r.ok) { if (cssEl) cinemaCSS(false); return true; }
    if (r && r.erro) console.warn('[SofaHub] tela cheia nativa falhou:', r.erro);
    return cinemaCSS(true);
  }

  function sairTelaCheia() {
    querTelaCheia = false;
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    cinemaCSS(false);
  }

  document.addEventListener('fullscreenchange', () => {
    if (!document.fullscreenElement && !ocupado) querTelaCheia = false;   // saiu pelo Esc etc.
  });

  async function comOcupado(fn) {
    ocupado = true;
    try { return await fn(); }
    finally {
      await espera(400);
      ocupado = false;
      if (querTelaCheia && !emTelaCheia()) await entrarTelaCheia();   // anúncio derrubou a tela cheia
    }
  }

  // Verificação "você é humano" na tela: o SofaHub não clica nela — tenta outro servidor
  // da reserva ou pede para você tocar pela aba Mouse.
  let reservaUsada = 0;
  async function seTravouTrocar(acao) {
    if (acao !== 'portao') return false;
    const proximo = (SITE.reserva || [])[reservaUsada++];
    if (!proximo) { avisar('O site pediu uma verificação "você é humano". Na aba Mouse, leve o cursor até ela e toque.'); return true; }
    avisar(`Servidor travado na verificação — trocando para o servidor ${proximo}`);
    setTimeout(() => escolherServidor(proximo), 0);
    return true;
  }

  const tocar = () => comOcupado(async () => {
    const r = await bg({ t: 'tocar' });
    if (r && await seTravouTrocar(r.acao)) return;
    if (!r || r.acao !== 'tocou') avisar('Não consegui dar play. Tente OK de novo ou use o Mouse');
  });

  const playPause = () => comOcupado(async () => {
    const r = await bg({ t: 'playpause' });
    if (r && await seTravouTrocar(r.acao)) return;
    if (r && r.acao === 'falhou') avisar('Não consegui dar play. Tente de novo ou use o Mouse');
  });

  // Troca de servidor (1, 2, 3... na página do vídeo): clica, espera o novo player, tela cheia e play.
  async function escolherServidor(n) {
    const el = acharPorTexto(new RegExp(`^\\s*${n}\\s*\\.\\s*\\S`), 40);
    if (!el) { avisar(`Servidor ${n} não encontrado nesta página`); return; }
    const antes = playerPrincipal();
    const srcAntes = antes && antes.src;
    await comOcupado(async () => {
      el.click();
      avisoTela(`Servidor: ${el.textContent.trim().replace(/\s+/g, ' ')}`);
      const p = await esperarPlayer(antes, srcAntes);
      if (!p) { avisar('O player não carregou'); return; }
      await espera(800);
      await entrarTelaCheia();
      await espera(500);
      const r = await bg({ t: 'tocar' });
      if (r && r.acao === 'portao') { setTimeout(() => seTravouTrocar('portao'), 0); return; }
      if (!r || r.acao !== 'tocou') avisar('Aperte OK para dar play');
    });
  }

  /* ================= Página de episódio/filme ================= */
  // Seleciona o servidor preferido, espera o player e entra em tela cheia.
  // Veio de ⏮/⏭ → já começa a tocar. Veio da lista → espera você apertar OK.
  function veioDeProximo() {
    try {
      const t = Number(sessionStorage.getItem('sofahub_autoplay'));
      sessionStorage.removeItem('sofahub_autoplay');
      return t && Date.now() - t < 60000;
    } catch { return false; }
  }

  let autoCancelado = false;

  async function autoPlayer() {
    if (!SITE.player || !SITE.player.test(location.pathname)) return;
    const autoplay = veioDeProximo();
    await espera(700);
    if (!playerPrincipal()) {
      let servidor = null;
      for (let i = 0; i < 10 && !servidor; i++) {
        if (SITE.servidor) servidor = acharPorTexto(SITE.servidor, 40);
        if (!servidor) await espera(300);
      }
      if (servidor) servidor.click();
      else {   // sem lista de servidores: clica no centro da capa do player
        const caixa = [...document.querySelectorAll('[id*=player i], [class*=player i]')]
          .filter(visivel).map(el => el.getBoundingClientRect())
          .filter(r => r.width >= 400 && r.height >= 220)
          .sort((a, b) => b.width * b.height - a.width * a.height)[0];
        if (caixa) {
          const alvo = document.elementFromPoint(caixa.left + caixa.width / 2, caixa.top + caixa.height / 2);
          if (alvo) alvo.click();
        }
      }
    }
    if (!(await esperarPlayer()) || autoCancelado) return;
    await espera(600);
    if (autoCancelado) return;
    // Primeiro o play, com a página normal (o 1º clique costuma ir para o anúncio e o 2º dá play);
    // só depois a tela cheia — assim o anúncio não derruba a tela cheia no meio dos cliques.
    esconderMoldura();
    await espera(autoplay ? 500 : 300);
    await tocar();
    if (!autoCancelado) await entrarTelaCheia();
  }

  /* ================= Comandos ================= */
  async function comandoPagina(m) {
    switch (m.c) {
      case 'up': case 'down': case 'left': case 'right':
        if (emTelaCheia()) {   // em tela cheia: ◀▶ = −10/+10 s · ▲▼ = sai da tela cheia
          if (m.c === 'left' || m.c === 'right') repassar({ c: 'seek', s: m.c === 'right' ? 10 : -10 });
          else { autoCancelado = true; sairTelaCheia(); osd('Tela cheia desligada'); }
          return;
        }
        if (atual && atual.tagName === 'SELECT' && (m.c === 'left' || m.c === 'right')) return trocarOpcao(atual, m.c === 'right' ? 1 : -1);
        return mover(m.c);
      case 'ok':
        if (emTelaCheia()) return playPause();
        return ok();
      case 'playpause':
        return playPause();
      case 'voltar':
        if (emTelaCheia()) { autoCancelado = true; sairTelaCheia(); return; }
        return history.back();
      case 'proximo':
      case 'anterior': {
        const re = m.c === 'proximo' ? /^pr[oó]ximo\b/i : /^anterior\b/i;
        try { sessionStorage.setItem('sofahub_autoplay', String(Date.now())); } catch {}
        const el = acharPorTexto(re);
        if (el) el.click();
        else avisar(`Botão “${m.c === 'proximo' ? 'Próximo' : 'Anterior'}” não encontrado`);
        return;
      }
      case 'cinema':   // botão "Tela cheia" do celular
        if (emTelaCheia()) { autoCancelado = true; sairTelaCheia(); osd('Tela cheia desligada'); }
        else await entrarTelaCheia();
        return;
      case 'servidor':
        autoCancelado = true;
        return escolherServidor(Number(m.s) || 1);
      case 'busca':
        return buscar(String(m.q || ''));
      case 'cursor': {
        const { cursorOculto } = await chrome.storage.local.get('cursorOculto');
        const esconder = cursorOculto === false;   // padrão: escondido
        await chrome.storage.local.set({ cursorOculto: esconder });
        avisoTela(esconder ? 'Mouse escondido' : 'Mouse visível');
        avisar(esconder ? '🖱 Mouse escondido' : '🖱 Mouse visível');
        return;
      }
    }
  }

  /* ================= Ao carregar ================= */
  (async () => {
    const r = await bg({ t: 'pegar_busca' });
    if (r && r.q) return buscar(r.q);
    autoPlayer();
  })();
})();
