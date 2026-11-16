"""
Tela que a janela do aplicativo mostra ANTES do painel: "Carregando...",
"Falha ao iniciar" e "Painel ja aberto em outra janela".

Ela e um HTML autocontido (sem arquivos externos, sem rede), entregue ao
pywebview como string - aparece assim que o WebView2 fica pronto, sem
depender do servidor interno. main.py troca o estado com
definirEstado(...) via evaluate_js e, quando o servidor responde, carrega
o painel de verdade (load_url).

TELA UNICA: o painel (painel/index.html, #app-splash) abre com uma tela
de carregamento IDENTICA a esta - mesmo cartao, mesma posicao, mesma
lista de etapas - e continua a lista de onde esta parou. Para o usuario
e uma tela so: Servidor interno -> Interface -> Conexao -> Dados.
Ao mudar o visual aqui, mude tambem o #app-splash do painel.

Os botoes chamam a API Python exposta pelo main.py (window.pywebview.api).
"""

import base64
import os

from caminhos import dir_base_bundle

COR_FUNDO = "#f4f5f8"  # mesma cor de fundo da janela (sem "flash" branco)


def _logo_data_uri():
    caminho = os.path.join(dir_base_bundle(), "painel", "assets", "logo.png")
    try:
        with open(caminho, "rb") as arquivo:
            return "data:image/png;base64," + base64.b64encode(arquivo.read()).decode("ascii")
    except OSError:
        return ""


_HTML = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8" />
<title>Painel de Produção</title>
<style>
  :root { --accent: #e25508; --accent-deep: #b93a0b; --ink: #0f172a; --ink-2: #526077; --ink-3: #8a97ad; --border: #e2e7f0;
          --good: #2f9e56; --critical: #d0453a; --warning: #b8720f; }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; }
  body {
    display: flex; flex-direction: column; font-family: "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif; color: var(--ink);
    background:
      radial-gradient(900px 500px at 85% -10%, rgba(226, 85, 8, 0.10), transparent 60%),
      linear-gradient(rgba(15, 23, 42, 0.04) 1px, transparent 1px) 0 0 / 32px 32px,
      linear-gradient(90deg, rgba(15, 23, 42, 0.04) 1px, transparent 1px) 0 0 / 32px 32px,
      __FUNDO__;
    -webkit-user-select: none; user-select: none;
  }
  .faixa { height: 64px; flex: none; background: linear-gradient(100deg, #a8350a 0%, #c9470b 50%, #ea580c 100%); box-shadow: 0 6px 24px rgba(194, 65, 12, 0.3); }
  main { flex: 1; display: flex; align-items: center; justify-content: center; padding: 24px; }
  .card {
    width: min(460px, 100%); padding: 34px 34px 28px; border-radius: 20px; background: #fff; border: 1px solid var(--border);
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05), 0 24px 60px rgba(15, 23, 42, 0.12); text-align: center; position: relative; overflow: hidden;
  }
  .card::before { content: ""; position: absolute; inset: 0 0 auto 0; height: 4px; background: linear-gradient(90deg, var(--accent), #f59e0b); }
  .logo { height: 44px; max-width: 220px; object-fit: contain; margin-bottom: 14px; }
  .titulo { font-size: 20px; font-weight: 700; letter-spacing: -0.01em; }
  .sub { margin-top: 4px; font-size: 13px; color: var(--ink-2); }

  .indicador { position: relative; width: 74px; height: 74px; margin: 24px auto 16px; }
  .spinner { width: 100%; height: 100%; border-radius: 50%; border: 5px solid #fde6d6; border-top-color: var(--accent); animation: girar 0.9s linear infinite; }
  .spinner::after { content: ""; position: absolute; inset: 14px; border-radius: 50%; border: 3px solid transparent; border-bottom-color: #f59e0b; animation: girar 1.4s linear infinite reverse; }
  @keyframes girar { to { transform: rotate(360deg); } }
  .icone { display: none; width: 74px; height: 74px; border-radius: 50%; align-items: center; justify-content: center; }
  .icone svg { width: 36px; height: 36px; }
  body[data-estado="falha"] .icone { display: flex; background: #fdecea; color: var(--critical); }
  body[data-estado="duplicado"] .icone { display: flex; background: #fff4e5; color: var(--warning); }
  body:not([data-estado="carregando"]) .spinner { display: none; }
  .ico-falha, .ico-duplicado { display: none; }
  body[data-estado="falha"] .ico-falha, body[data-estado="duplicado"] .ico-duplicado { display: block; }

  .mensagem { font-size: 15px; font-weight: 600; min-height: 22px; }
  body[data-estado="falha"] .mensagem { color: var(--critical); }
  .etapa { margin-top: 6px; font-size: 12.5px; color: var(--ink-2); }
  .etapa:empty { display: none; }

  /* lista de etapas (a mesma do #app-splash do painel) */
  .etapas { list-style: none; margin: 18px auto 0; padding: 0; width: fit-content; text-align: left; display: flex; flex-direction: column; gap: 9px; }
  .etapas li { display: flex; align-items: center; gap: 10px; font-size: 13px; color: var(--ink-3); }
  .etapas li::before { content: ""; width: 16px; height: 16px; border-radius: 50%; flex: none; box-sizing: border-box; border: 2px solid #dfe4ee; }
  .etapas li.atual { color: var(--ink-2); }
  .etapas li.atual::before { border-color: #fde6d6; border-top-color: var(--accent); animation: girar 0.9s linear infinite; }
  .etapas li.ok { color: var(--ink); }
  .etapas li.ok::before { border: none; background: var(--good) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Cpath d='M4 8.5l2.5 2.5L12 5.5' fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") center / 14px no-repeat; }
  .etapas li.erro { color: var(--critical); }
  .etapas li.erro::before { border-color: var(--critical); }
  body[data-estado="duplicado"] .etapas { display: none; }

  .demora { display: none; margin-top: 14px; padding: 9px 12px; border-radius: 10px; background: #fff7ed; color: #9a3412; font-size: 12px; }
  body.demorando[data-estado="carregando"] .demora { display: block; }

  .detalhe { display: none; margin-top: 14px; text-align: left; font-size: 12px; color: var(--ink-2); }
  .detalhe summary { cursor: pointer; font-weight: 600; }
  .detalhe pre { margin: 8px 0 0; padding: 10px; max-height: 140px; overflow: auto; border-radius: 8px; background: #f6f7fa; border: 1px solid var(--border);
                 font-family: "Cascadia Code", Consolas, monospace; font-size: 11px; white-space: pre-wrap; word-break: break-word; -webkit-user-select: text; user-select: text; }
  body.tem-detalhe .detalhe { display: block; }

  .acoes { display: none; gap: 10px; justify-content: center; flex-wrap: wrap; margin-top: 22px; }
  body:not([data-estado="carregando"]) .acoes { display: flex; }
  button {
    height: 38px; padding: 0 18px; border-radius: 10px; border: 1px solid #cdd5e4; background: #fff; color: var(--ink);
    font: inherit; font-size: 13px; font-weight: 600; cursor: pointer;
  }
  button:hover { border-color: var(--accent); color: var(--accent); }
  button.primario { background: linear-gradient(135deg, var(--accent), var(--accent-deep)); border-color: transparent; color: #fff; box-shadow: 0 6px 18px rgba(226, 85, 8, 0.28); }
  button.primario:hover { color: #fff; filter: brightness(1.08); }
  button:disabled { opacity: 0.5; cursor: wait; }
  [hidden] { display: none !important; }
  .rodape { padding: 0 0 18px; text-align: center; font-size: 11.5px; color: var(--ink-3); }
  @media (prefers-reduced-motion: reduce) { .spinner, .spinner::after, .etapas li.atual::before { animation-duration: 3s; } }
</style>
</head>
<body data-estado="carregando">
  <div class="faixa"></div>
  <main>
    <div class="card" role="status" aria-live="polite">
      __LOGO__
      <div class="titulo">Painel de Produção</div>
      <div class="sub">Acompanhamento de produção e rendimento</div>

      <div class="indicador">
        <div class="spinner"></div>
        <div class="icone">
          <svg class="ico-falha" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2"/><path d="M12 7.5v5.5M12 16.5v.01" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>
          <svg class="ico-duplicado" viewBox="0 0 24 24" fill="none"><rect x="3" y="7" width="13" height="12" rx="2" stroke="currentColor" stroke-width="2"/><path d="M8 7V5h13v12h-5" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>
        </div>
      </div>

      <div class="mensagem" id="mensagem">Abrindo o painel…</div>
      <div class="etapa" id="etapa"></div>
      <ul class="etapas" id="etapas">
        <li class="atual">Servidor interno</li>
        <li>Interface</li>
        <li>Conexão com o aplicativo</li>
        <li>Dados de produção</li>
      </ul>
      <div class="demora">Está demorando mais que o normal. Na primeira abertura do dia o Windows pode levar alguns segundos a mais.</div>

      <details class="detalhe"><summary>Detalhes técnicos</summary><pre id="detalhe"></pre></details>

      <div class="acoes">
        <button class="primario" id="btn-tentar" type="button" onclick="acao('tentar_novamente', this)">Tentar novamente</button>
        <button id="btn-abrir" type="button" onclick="acao('abrir_assim_mesmo', this)" hidden>Usar esta janela mesmo assim</button>
        <button id="btn-log" type="button" onclick="acao('abrir_log', this)">Abrir registro de erros</button>
      </div>
    </div>
  </main>
  <div class="rodape">Se o problema continuar, feche todas as janelas do Painel e abra de novo.</div>
<script>
  var inicio = Date.now();
  setInterval(function () {
    document.body.classList.toggle("demorando", Date.now() - inicio > 12000);
  }, 1000);

  // passo = indice da etapa em andamento (0 = Servidor interno, 1 = Interface).
  function marcarPasso(passo, falhou) {
    document.querySelectorAll("#etapas li").forEach(function (li, i) {
      li.className = i < passo ? "ok" : i === passo ? (falhou ? "erro" : "atual") : "";
    });
  }

  // Chamado pelo main.py (evaluate_js). e = { estado, mensagem, etapa, detalhe, passo }
  function definirEstado(e) {
    if (e.estado && e.estado !== document.body.dataset.estado) {
      document.body.dataset.estado = e.estado;
      if (e.estado === "carregando") inicio = Date.now();
    }
    if (e.mensagem !== undefined) document.getElementById("mensagem").textContent = e.mensagem;
    // sub-texto so nos estados de falha/aviso (no carregamento, a lista de etapas ja diz tudo)
    document.getElementById("etapa").textContent = e.estado === "carregando" ? "" : (e.etapa || "");
    if (typeof e.passo === "number") marcarPasso(e.passo, e.estado === "falha");
    var det = e.detalhe || "";
    document.getElementById("detalhe").textContent = det;
    document.body.classList.toggle("tem-detalhe", !!det);
    document.getElementById("btn-abrir").hidden = e.estado !== "duplicado";
    document.querySelectorAll("button").forEach(function (b) { b.disabled = false; });
  }

  function acao(nome, botao) {
    if (!window.pywebview || !window.pywebview.api || !window.pywebview.api[nome]) return;
    botao.disabled = true;
    if (nome === "tentar_novamente") definirEstado({ estado: "carregando", mensagem: "Abrindo o painel…", passo: 0, detalhe: "" });
    window.pywebview.api[nome]();
    if (nome === "abrir_log") setTimeout(function () { botao.disabled = false; }, 1500);
  }
</script>
</body>
</html>
"""


def html_tela_inicial():
    logo = _logo_data_uri()
    return (
        _HTML.replace("__FUNDO__", COR_FUNDO)
        .replace("__LOGO__", f'<img class="logo" src="{logo}" alt="" />' if logo else "")
    )
