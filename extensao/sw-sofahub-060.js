// Liga a extensão ao SofaHub (programa no PC) e repassa os comandos do celular para a aba.
const AGENTE = 'ws://127.0.0.1:8765/ext';
const DEBUG = false;   // true = avisos de diagnóstico no celular
let ws = null;

function conectar() {
  if (ws && ws.readyState <= 1) return;
  try { ws = new WebSocket(AGENTE); } catch { ws = null; return; }
  ws.onmessage = e => tratar(JSON.parse(e.data)).catch(err => aviso('Erro: ' + err.message));
  ws.onopen = () => { if (DEBUG) aviso('DBG extensao ' + chrome.runtime.getManifest().version + ' conectada'); };
  ws.onclose = () => { ws = null; setTimeout(conectar, 3000); };
  ws.onerror = () => {};
}

// Mensagem a cada 20 s mantém o service worker vivo (o Chrome o encerra após 30 s parado).
setInterval(() => { if (ws && ws.readyState === 1) ws.send('{"t":"ping"}'); else conectar(); }, 20000);
chrome.alarms.create('sofahub', { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener(conectar);
chrome.runtime.onStartup.addListener(conectar);
chrome.runtime.onInstalled.addListener(conectar);
conectar();

const espera = ms => new Promise(r => setTimeout(r, ms));

function aviso(msg) {
  if (ws && ws.readyState === 1) ws.send(JSON.stringify({ t: 'aviso', msg }));
}

async function abaAtiva() {
  let [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (!tab) [tab] = await chrome.tabs.query({ active: true });
  return tab;
}

async function janelaPrincipal() {
  try { return await chrome.windows.getLastFocused({ populate: true, windowTypes: ['normal'] }); }
  catch { return null; }
}

async function abrir(url) {
  const win = await janelaPrincipal();
  if (!win || !win.tabs || !win.tabs.length) {
    await chrome.windows.create({ url, state: 'fullscreen', focused: true });
    return;
  }
  const tab = win.tabs.find(t => t.active) || win.tabs[0];
  await chrome.tabs.update(tab.id, { url, active: true });
  const outras = win.tabs.filter(t => t.id !== tab.id).map(t => t.id);
  if (outras.length) await chrome.tabs.remove(outras);   // experiência de TV: uma aba só
  await chrome.windows.update(win.id, { state: 'fullscreen', focused: true });
}

/* ================= Gestos "reais" (Chrome DevTools Protocol) =================
   O Chrome só deixa entrar em tela cheia e dar play com som depois de um clique
   de verdade. Pelo protocolo de depuração os cliques contam como do usuário. */
const anexadas = new Set();
chrome.debugger.onDetach.addListener(src => anexadas.delete(src.tabId));
chrome.tabs.onRemoved.addListener(id => anexadas.delete(id));

async function cdp(tabId, metodo, params = {}) {
  if (!anexadas.has(tabId)) {
    try { await chrome.debugger.attach({ tabId }, '1.3'); }
    catch (e) { if (!/already attached/i.test(e.message)) throw e; }
    anexadas.add(tabId);
  }
  return chrome.debugger.sendCommand({ tabId }, metodo, params);
}

// Se o clique abrir um anúncio (que fechamos na hora), o Chrome às vezes não confirma o
// evento: um limite de tempo evita que o play fique travado esperando.
const comLimite = (p, ms) => Promise.race([p, espera(ms)]);

async function clique(tabId, x, y) {
  const p = { x: Math.round(x), y: Math.round(y) };
  await comLimite(cdp(tabId, 'Input.dispatchMouseEvent', { type: 'mouseMoved', ...p }), 1500);
  await comLimite(cdp(tabId, 'Input.dispatchMouseEvent', { type: 'mousePressed', ...p, button: 'left', clickCount: 1 }), 1500);
  await comLimite(cdp(tabId, 'Input.dispatchMouseEvent', { type: 'mouseReleased', ...p, button: 'left', clickCount: 1 }), 1500);
}

// Tela cheia nativa do elemento marcado pela página (o iframe do player): igual ao botão do player.
const EXPR_TELA_CHEIA = `(async () => {
  const el = document.querySelector('[data-sofahub-player]');
  if (!el) return 'sem player';
  if (document.fullscreenElement === el) return 'ok';
  try { await el.requestFullscreen({ navigationUI: 'hide' }); return 'ok'; }
  catch (e) { return 'erro: ' + e.message; }
})()`;

async function telaCheia(tabId) {
  const r = await cdp(tabId, 'Runtime.evaluate', {
    expression: EXPR_TELA_CHEIA, userGesture: true, awaitPromise: true, returnByValue: true,
  });
  const v = r && r.result && r.result.value;
  if (v !== 'ok') throw new Error(v || 'falhou');
  return true;
}

// Pergunta aos frames da aba. Frames de anúncio podem demorar muito para "fechar" a conversa,
// então cada pergunta tem limite de tempo; quem tem a resposta responde na hora.
async function perguntar(tabId, msg, opcoes = {}, ms = 900) {
  try {
    return await Promise.race([chrome.tabs.sendMessage(tabId, msg, opcoes), espera(ms).then(() => null)]);
  } catch { return null; }
}
const estadoVideo = tabId => perguntar(tabId, { c: 'estado_video' });
const centroPlayer = tabId => perguntar(tabId, { c: 'rect_player' }, { frameId: 0 });

// Clica no play do player até o vídeo estar tocando.
// (Se o 1º clique abrir anúncio, a aba do anúncio é fechada e clica de novo.)
const temPortao = async tabId => !!(await perguntar(tabId, { c: 'portao' }));

// Ponto da página → pixel real da tela, com a janela em qualquer posição/tamanho e qualquer escala do Windows.
function pontoNaTela(c) {
  // o ponto nunca sai da área da página: um site mal-intencionado não consegue mandar
  // o clique real para fora do Chrome (barra de tarefas, outros programas...)
  c.x = Math.min(Math.max(c.x, 2), c.vw - 2);
  c.y = Math.min(Math.max(c.y, 2), c.vh - 2);
  if (c.cheia) return { x: Math.round(c.x * c.dpr), y: Math.round(c.y * c.dpr) };
  const borda = Math.max(0, (c.ow - c.vw) / 2);           // borda lateral da janela
  const topo = Math.max(0, c.oh - c.vh - borda);          // barra de abas + endereço
  return { x: Math.round((c.sx + borda + c.x) * c.dpr), y: Math.round((c.sy + topo + c.y) * c.dpr) };
}

// Devolve true (tocando), 'portao' (o site pediu verificação "você é humano") ou false.
// A verificação nunca é clicada automaticamente: quem resolve é você, pela aba Mouse.
async function tocar(tabId) {
  if (await temPortao(tabId)) return 'portao';
  // 1º: a API do próprio player (JW Player) — sem clique, sem mira, sem camada de anúncio
  chrome.tabs.sendMessage(tabId, { c: 'api_play' }).catch(() => {});
  for (let k = 0; k < 6; k++) {
    await espera(300);
    const s0 = await estadoVideo(tabId);
    if (s0 && !s0.paused) return true;
  }
  // 2º: clique no botão de play (players sem API; o Chrome só libera play/tela cheia com clique real)
  for (let tentativa = 0; tentativa < 4; tentativa++) {
    if (await temPortao(tabId)) return 'portao';
    const st = await estadoVideo(tabId);
    if (st && !st.paused) return true;
    const c = await centroPlayer(tabId);
    if (!c) return false;
    // mira no botão de play de dentro do player, se ele tiver um
    const alvo = await perguntar(tabId, { c: 'alvo_play' });
    if (alvo && c.w) { c.x = c.l + alvo.fx * c.w; c.y = c.t + alvo.fy * c.h; }
    if (DEBUG) aviso(`DBG tocar#${tentativa} estado=${JSON.stringify(st)} alvo=${JSON.stringify(alvo)} clique=${Math.round(c.x)},${Math.round(c.y)} de ${c.vw}x${c.vh} sofahub=${!!(ws && ws.readyState === 1)}`);
    // clique de mouse real pelo SofaHub; sem o SofaHub conectado, clique simulado pelo Chrome.
    await perguntar(tabId, { c: 'liberar_top', x: c.x, y: c.y }, { frameId: 0 });
    const sofahub = ws && ws.readyState === 1;
    const enviar = o => ws.send(JSON.stringify(o));
    if (sofahub) enviar({ t: 'clique_px', ...pontoNaTela(c) });
    else await clique(tabId, c.x, c.y);
    // O 1º clique costuma ser "engolido" por camada de anúncio; se o vídeo não começou,
    // clica de novo no mesmo lugar.
    await espera(sofahub ? 1100 : 350);   // tempo do movimento do mouse + clique
    let s2 = await estadoVideo(tabId);
    if (s2 && !s2.paused) { if (sofahub) enviar({ t: 'estacionar' }); return true; }
    if (sofahub) enviar({ t: 'clique_aqui' }); else await clique(tabId, c.x, c.y);
    for (let k = 0; k < 7; k++) {
      await espera(400);
      s2 = await estadoVideo(tabId);
      if (s2 && !s2.paused) { if (sofahub) enviar({ t: 'estacionar' }); return true; }
    }
    if (sofahub) enviar({ t: 'estacionar' });
  }
  return (await temPortao(tabId)) ? 'portao' : false;
}

async function playPause(tabId) {
  const st = await estadoVideo(tabId);
  if (DEBUG) aviso('DBG playpause estado=' + JSON.stringify(st));
  if (st && !st.paused) {
    chrome.tabs.sendMessage(tabId, { c: 'api_pause' }).catch(() => {});
    await espera(250);
    const st2 = await estadoVideo(tabId);
    if (st2 && !st2.paused) await perguntar(tabId, { c: 'pausar' });
    return 'pausou';
  }
  const r = await tocar(tabId);
  return r === 'portao' ? 'portao' : r ? 'tocou' : 'falhou';
}

/* ================= Comandos vindos do celular ================= */
let buscaPendente = null;   // a página de busca abre e o content script pede o texto quando carregar

const urlOk = u => typeof u === 'string' && /^https?:\/\//i.test(u);

async function tratar(m) {
  if (!m || m.t !== 'cmd') return;
  if ((m.c === 'abrir' || m.c === 'buscar_pagina') && !urlOk(m.url)) return aviso('Endereço inválido');

  if (m.c === 'abrir') return abrir(m.url);

  if (m.c === 'buscar_pagina') {
    buscaPendente = { q: m.q, url: m.url, ate: Date.now() + 20000 };
    return abrir(m.url);
  }

  if (m.c === 'fechar') {
    for (const w of await chrome.windows.getAll()) await chrome.windows.remove(w.id);
    return;
  }

  const tab = await abaAtiva();
  if (!tab) return aviso('Nenhuma aba aberta');
  // vai para todos os frames (página + player); não espera ninguém responder
  chrome.tabs.sendMessage(tab.id, m).catch(e => {
    if (!/port closed|Receiving end/i.test(e.message)) aviso('A página ainda está carregando — tente de novo');
  });
}

/* ================= Pedidos da página ================= */
function responderAsync(promessa, responder, falha) {
  promessa.then(responder).catch(e => { console.warn('[SofaHub]', e); responder(falha(e)); });
  return true;
}

chrome.runtime.onMessage.addListener((m, sender, responder) => {
  const tabId = sender.tab && sender.tab.id;
  if (DEBUG && m.t !== 'aviso' && m.t !== 'repassar') aviso('DBG bg recebeu ' + m.t + ' tab=' + tabId);

  if (m.t === 'pegar_busca') {
    const b = buscaPendente;
    const mesmaPagina = b && sender.url && new URL(sender.url).pathname === new URL(b.url).pathname;
    if (b && mesmaPagina && b.ate > Date.now()) { buscaPendente = null; responder({ q: b.q }); }
    else responder({ q: null });
    return;
  }
  if (m.t === 'tela_cheia')
    return responderAsync(telaCheia(tabId).then(() => ({ ok: true })), responder, e => ({ ok: false, erro: e.message }));
  if (m.t === 'tocar')
    return responderAsync(tocar(tabId).then(r => ({ acao: r === 'portao' ? 'portao' : r ? 'tocou' : 'falhou' })), responder, () => ({ acao: 'falhou' }));
  if (m.t === 'playpause')
    return responderAsync(playPause(tabId).then(acao => ({ acao })), responder, () => ({ acao: 'falhou' }));

  if (m.t === 'aviso') aviso(m.msg);
  else if (m.t === 'repassar' && tabId !== undefined) chrome.tabs.sendMessage(tabId, m.cmd).catch(() => {});
});

// Pop-ups de anúncio: a aba do filme volta para a frente na hora e o anúncio é fechado
// depois de alguns segundos (alguns players só liberam o vídeo se o anúncio "abriu").
const FECHAR_ANUNCIO_MS = 15000;
chrome.tabs.onCreated.addListener(tab => {
  if (tab.openerTabId === undefined) return;
  if (DEBUG) aviso('DBG anuncio aberto (aba ' + tab.id + ')');
  setTimeout(() => chrome.tabs.update(tab.openerTabId, { active: true }).catch(() => {}), 150);
  setTimeout(() => chrome.tabs.remove(tab.id).catch(() => {}), FECHAR_ANUNCIO_MS);
});
chrome.windows.onCreated.addListener(win => {
  if (win.type !== 'popup') return;
  setTimeout(() => chrome.windows.remove(win.id).catch(() => {}), FECHAR_ANUNCIO_MS);
});
