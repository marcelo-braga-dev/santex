/*
 * Painel 2.0 - setores: seletor no cabecalho e cadastro (Configuracoes ->
 * Producao -> Setores). Usa o que o index.html expoe em window.PainelNucleo.
 *
 * - Ao abrir: GET /setores. O setor inicial e o do endereco (?setor=), senao
 *   o ultimo escolhido neste aparelho, senao o padrao do servidor (o
 *   primeiro ativo).
 * - Trocar no seletor lembra a escolha neste aparelho e poe ?setor= no
 *   endereco (para mandar o link).
 * - Cadastro: criar, renomear, mudar a ordem, desativar/reativar, apagar
 *   (so setor sem maquinas nem producao) e acrescentar maquinas. Quem nao
 *   pode editar (VPS sem a senha de edicao, aparelho sem PIN) so ve a lista.
 */
(function () {
  "use strict";
  const N = window.PainelNucleo;
  if (!N) return; // index.html antigo
  const CHAVE_LOCAL = "painel_setor";
  const NOME_TIPO = { multi: "Vários por controlador", unitario: "Um controlador por máquina" };
  const esc = N.escaparHtml;
  let estado = null; // resposta do GET /setores
  let editando = null; // slug do setor sendo renomeado
  let ocupado = false;

  function $(id) { return document.getElementById(id); }

  async function buscarSetores() {
    try {
      const res = await fetch(N.CONTROLE_URL + "/setores", { cache: "no-store", headers: N.cabecalhosControle() });
      if (!res.ok) return null;
      return await res.json();
    } catch (e) { return null; } // sem servidor (arquivo local): fica o setor padrao
  }

  function aplicarEstado(dados) {
    if (!dados || !Array.isArray(dados.setores)) return;
    estado = dados;
    N.definirSetores(dados.setores);
    const atual = dados.setores.find((s) => s.setor === N.setorAtual.id);
    if (!atual) N.selecionarSetor(dados.padrao); // o setor aberto foi apagado
    renderCartao();
  }

  function setorDoEndereco() {
    try { return new URLSearchParams(location.search).get("setor") || ""; } catch (e) { return ""; }
  }

  function lembrar(slug) {
    N.gravarLocal(CHAVE_LOCAL, slug);
    if (!history.replaceState) return;
    try {
      const url = new URL(location.href);
      if (slug === estado?.padrao) url.searchParams.delete("setor"); else url.searchParams.set("setor", slug);
      history.replaceState(null, "", url.pathname + url.search + url.hash);
    } catch (e) { /* ok */ }
  }

  async function iniciar() {
    const dados = await buscarSetores();
    if (!dados) { renderCartao(); return; }
    aplicarEstado(dados);
    const existe = (slug) => dados.setores.find((s) => s.setor === slug);
    const doEndereco = setorDoEndereco();
    const lembrado = N.lerLocal(CHAVE_LOCAL, "");
    // pelo endereco abre ate um setor desativado (historico); o lembrado so se ativo
    let alvo = existe(doEndereco) ? doEndereco : "";
    if (!alvo && existe(lembrado) && existe(lembrado).ativo) alvo = lembrado;
    if (!alvo) alvo = dados.padrao;
    if (alvo && alvo !== N.setorAtual.id) N.selecionarSetor(alvo);
  }

  // --- cartao "Setores" ------------------------------------------------------

  function botao(acao, slug, texto, op) {
    op = op || {};
    return `<button class="btn small${op.primario ? " primary" : ""}" type="button" data-st="${acao}" data-slug="${esc(slug)}"` +
      `${op.desativado ? " disabled" : ""}${op.titulo ? ` title="${esc(op.titulo)}"` : ""}>${texto}</button>`;
  }

  let ultimoHtml = "";
  function desenhar(corpo, html) {
    // so redesenha se mudou: o cartao e chamado a cada consulta de permissao
    // e nao pode apagar o que a pessoa esta digitando
    if (html === ultimoHtml && corpo.innerHTML) return;
    ultimoHtml = html;
    corpo.innerHTML = html;
    if (editando) { const c = $("st-renomear"); if (c) { c.focus(); c.select(); } }
  }

  function renderCartao() {
    const corpo = $("cfg-setores-corpo");
    if (!corpo) return;
    if (!estado) {
      desenhar(corpo, `<div class="cfg-nota">${N.servidorOnline ? "Carregando…" : "Disponível com o aplicativo do painel aberto."}</div>`);
      return;
    }
    const pode = N.podeEditar;
    const lista = estado.setores;
    const ativos = lista.filter((s) => s.ativo).length;
    const linhas = lista.map((s, i) => {
      // o setor legado sempre mostra as 4 maquinas do ESP32 multi, configuradas ou nao
      const qtd = s.setor === N.SETOR_LEGADO ? Math.max(4, s.maquinas || 0) : s.maquinas || 0;
      const info = [NOME_TIPO[s.tipoColeta] || s.tipoColeta,
        qtd ? `${qtd} máquina${qtd > 1 ? "s" : ""}` : "sem máquinas"].join(" · ");
      if (pode && editando === s.setor) {
        return `<div class="st-linha"><input class="input" id="st-renomear" maxlength="40" value="${esc(s.nome)}" aria-label="Novo nome do setor" />` +
          `<span class="st-acoes">${botao("salvar-nome", s.setor, "Salvar", { primario: true })}${botao("cancelar", s.setor, "Cancelar")}</span></div>`;
      }
      let acoes = "";
      if (pode) {
        acoes += botao("subir", s.setor, "↑", { desativado: i === 0, titulo: "Subir na lista" });
        acoes += botao("descer", s.setor, "↓", { desativado: i === lista.length - 1, titulo: "Descer na lista" });
        acoes += botao("renomear", s.setor, "Renomear");
        if (s.setor !== N.SETOR_LEGADO) acoes += botao("maquina", s.setor, "+ Máquina", { titulo: "Cadastrar mais uma máquina neste setor" });
        acoes += s.ativo
          ? botao("desativar", s.setor, "Desativar", ativos <= 1 ? { desativado: true, titulo: "Precisa ficar ao menos um setor ativo" } : {})
          : botao("reativar", s.setor, "Reativar");
        if (!s.temDados && lista.length > 1) acoes += botao("apagar", s.setor, "Apagar");
      }
      const selos = (s.setor === N.setorAtual.id ? `<span class="st-selo">aberto</span>` : "") +
        (s.ativo ? "" : `<span class="st-selo off">desativado</span>`);
      return `<div class="st-linha${s.ativo ? "" : " inativo"}"><span class="st-nome">${esc(s.nome)}</span>${selos}` +
        `<span class="st-info">${esc(info)}</span><span class="st-acoes">${acoes}</span></div>`;
    }).join("");
    const novo = pode ? `
      <div class="st-novo">
        <label class="config-field">Novo setor<input class="input" id="st-nome" maxlength="40" placeholder="Ex.: Costura" /></label>
        <label class="config-field">Coleta<select class="select" id="st-tipo">
          <option value="unitario">${NOME_TIPO.unitario}</option><option value="multi">${NOME_TIPO.multi}</option></select></label>
        <label class="config-field">Máquinas<input class="input" id="st-qtd" type="number" min="0" max="64" step="1" value="0" /></label>
      </div>
      <div class="cfg-acoes-dir"><button class="btn primary" type="button" data-st="criar">Criar setor</button></div>` : "";
    const nota = pode
      ? "Desativar tira o setor do seletor, mas o histórico continua nos relatórios. Só dá para apagar setor sem máquinas e sem produção. O nome pode mudar à vontade: o identificador interno, gravado em cada ciclo, não muda."
      : (N.modoNuvem ? "Somente leitura: para alterar os setores, entre com a senha de edição." : "Somente leitura: altere no computador do painel (ou com o PIN).");
    desenhar(corpo, `<div class="st-lista">${linhas}</div>${novo}<div class="st-erro" id="st-erro" role="alert"></div><div class="cfg-nota">${nota}</div>`);
  }

  function erro(texto) { const e = $("st-erro"); if (e) e.textContent = texto || ""; }

  async function enviar(corpo) {
    let res, dados;
    try {
      res = await N.postControle("/setores", corpo);
      dados = await res.json().catch(() => ({}));
    } catch (e) {
      erro(e && e.somenteLeitura ? "Sem permissão para alterar." : "Servidor indisponível.");
      return null;
    }
    if (!res.ok || !dados.ok) { erro(dados.erro || dados.mensagem || "Não foi possível salvar."); return null; }
    erro("");
    return dados;
  }

  async function maquinasDoSetor(slug) {
    const res = await fetch(N.CONTROLE_URL + "/config?setor=" + encodeURIComponent(slug), { cache: "no-store" });
    if (!res.ok) throw new Error("config");
    return Object.keys((await res.json()).maquinas || {}).map(Number).filter((n) => n >= 1 && n <= 64);
  }

  async function acrescentarMaquinas(slug, quantas) {
    const existentes = await maquinasDoSetor(slug);
    let proxima = existentes.length ? Math.max(...existentes) + 1 : 1;
    const maquinas = {};
    for (let i = 0; i < quantas && proxima <= 64; i++, proxima++) maquinas[proxima] = { nome: `Máquina ${proxima}`, metrosPorMin: 0 };
    if (!Object.keys(maquinas).length) { erro("Limite de 64 máquinas por setor."); return false; }
    const res = await N.postControle("/config", { setor: slug, maquinas });
    if (!res.ok) { erro("Não foi possível cadastrar as máquinas."); return false; }
    if (slug === N.setorAtual.id) N.recarregarConfig(); // a tela do setor aberto ganha os cartoes novos
    return true;
  }

  async function mover(slug, delta) {
    const lista = estado.setores.slice();
    const i = lista.findIndex((s) => s.setor === slug), j = i + delta;
    if (i < 0 || j < 0 || j >= lista.length) return;
    [lista[i], lista[j]] = [lista[j], lista[i]];
    // renumera so os que mudaram (cada um vira uma alteracao sincronizada)
    let ultimo = null;
    for (let k = 0; k < lista.length; k++) {
      if (lista[k].ordem !== k) { ultimo = await enviar({ acao: "editar", setor: lista[k].setor, ordem: k }); if (!ultimo) break; }
    }
    if (ultimo) aplicarEstado(ultimo);
  }

  async function acao(tipo, slug) {
    const s = estado && estado.setores.find((x) => x.setor === slug);
    if (tipo === "criar") {
      const nome = ($("st-nome").value || "").trim();
      const qtd = Math.max(0, Math.min(64, Math.round(Number($("st-qtd").value) || 0)));
      if (!nome) { erro("Informe o nome do setor."); $("st-nome").focus(); return; }
      const r = await enviar({ acao: "criar", nome, tipoColeta: $("st-tipo").value });
      if (!r) return;
      if (qtd) await acrescentarMaquinas(r.setor.setor, qtd);
      aplicarEstado((await buscarSetores()) || r);
      N.avisoFlutuante(`Setor “${r.setor.nome}” criado.`);
      return;
    }
    if (!s) return;
    if (tipo === "renomear") { editando = slug; renderCartao(); return; }
    if (tipo === "cancelar") { editando = null; renderCartao(); return; }
    if (tipo === "salvar-nome") {
      const nome = ($("st-renomear").value || "").trim();
      if (!nome) { erro("Informe o nome do setor."); return; }
      if (nome === s.nome) { editando = null; renderCartao(); return; }
      const r = await enviar({ acao: "editar", setor: slug, nome });
      if (r) { editando = null; aplicarEstado(r); }
      return;
    }
    if (tipo === "subir" || tipo === "descer") { await mover(slug, tipo === "subir" ? -1 : 1); return; }
    if (tipo === "desativar" || tipo === "reativar") {
      if (tipo === "desativar" && !confirm(`Desativar o setor “${s.nome}”?\n\nEle sai do seletor, mas o histórico continua nos relatórios. Dá para reativar depois.`)) return;
      const r = await enviar({ acao: "editar", setor: slug, ativo: tipo === "reativar" });
      if (r) aplicarEstado(r);
      return;
    }
    if (tipo === "apagar") {
      if (!confirm(`Apagar o setor “${s.nome}”?\n\nEle não tem máquinas nem produção. Os turnos e o calendário dele também são apagados.`)) return;
      const r = await enviar({ acao: "apagar", setor: slug });
      if (r) aplicarEstado(r);
      return;
    }
    if (tipo === "maquina") {
      try {
        if (await acrescentarMaquinas(slug, 1)) aplicarEstado(await buscarSetores());
      } catch (e) { erro("Servidor indisponível."); }
    }
  }

  document.addEventListener("click", async (ev) => {
    const b = ev.target.closest("#cfg-setores-corpo [data-st]");
    if (!b || b.disabled || ocupado) return;
    ocupado = true;
    try { await acao(b.dataset.st, b.dataset.slug); } finally { ocupado = false; }
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Enter") return;
    if (ev.target.id === "st-renomear") document.querySelector('#cfg-setores-corpo [data-st="salvar-nome"]')?.click();
    else if (ev.target.id === "st-nome") document.querySelector('#cfg-setores-corpo [data-st="criar"]')?.click();
  });
  const seletor = $("sector-select");
  if (seletor) seletor.addEventListener("change", (ev) => { lembrar(ev.target.value); renderCartao(); });

  window.PainelSetores = {
    renderCartao,
    async recarregar() { const d = await buscarSetores(); if (d) aplicarEstado(d); else renderCartao(); },
  };
  iniciar();
})();
