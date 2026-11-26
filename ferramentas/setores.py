"""
Cadastro de setores (2.0): regras de criar, editar, desativar e apagar.

O setor e identificado pelo SLUG ("enfestadeiras", "costura-2"), gerado do
nome na criacao e gravado em todas as tabelas (ciclos, maquinas, turnos...).
Por isso o slug NUNCA muda: renomear muda so o nome exibido.

Desativar tira o setor do seletor do painel, mas o historico continua nos
relatorios. Apagar so e permitido para setor sem ciclos e sem maquinas.

O cadastro inteiro sincroniza com a VPS como o item global "setores"
(ferramentas/nuvem.py): lista completa, aplicada por aplicar_lista().
"""

import re
import unicodedata

TIPOS_COLETA = ("multi", "unitario")  # 1 ESP32 -> varias maquinas | 1 ESP32 por maquina
MAX_SETORES = 50
_RE_SLUG = re.compile(r"^[a-z][a-z0-9-]{0,39}$")


class ErroSetor(ValueError):
    """Pedido invalido - a mensagem vai para o painel como esta."""


def gerar_slug(nome):
    """"Costura Reta 2" -> "costura-reta-2" (sem acento, so a-z, 0-9 e -)."""
    texto = unicodedata.normalize("NFKD", str(nome or "")).encode("ascii", "ignore").decode("ascii").lower()
    texto = re.sub(r"[^a-z0-9]+", "-", texto).strip("-")
    texto = re.sub(r"^[^a-z]+", "", texto)  # comeca sempre por letra
    return texto[:40].rstrip("-")


def slug_valido(slug):
    return bool(_RE_SLUG.match(str(slug or "")))


def _nome(valor):
    nome = " ".join(str(valor or "").split())[:40]
    if not nome:
        raise ErroSetor("Informe o nome do setor.")
    return nome


def _tipo(valor, padrao="multi"):
    tipo = str(valor or padrao)
    if tipo not in TIPOS_COLETA:
        raise ErroSetor("Tipo de coleta inválido.")
    return tipo


def _ordem(valor, padrao):
    try:
        return max(0, min(int(valor), 999))
    except (TypeError, ValueError):
        return padrao


def _nome_repetido(banco, nome, exceto=None):
    alvo = nome.casefold()
    return any(s["nome"].casefold() == alvo and s["setor"] != exceto for s in banco.listar_setores())


def criar(banco, dados):
    """dados: {"nome", "tipoColeta"?, "ordem"?}. Devolve o setor criado."""
    nome = _nome(dados.get("nome"))
    tipo = _tipo(dados.get("tipoColeta"))
    existentes = banco.listar_setores()
    if len(existentes) >= MAX_SETORES:
        raise ErroSetor(f"Limite de {MAX_SETORES} setores.")
    if _nome_repetido(banco, nome):
        raise ErroSetor("Já existe um setor com esse nome.")
    base = gerar_slug(nome)
    if not base:
        raise ErroSetor("O nome precisa ter ao menos uma letra.")
    usados = {s["setor"] for s in existentes}
    slug, n = base, 2
    while slug in usados or not slug_valido(slug):
        sufixo = f"-{n}"
        slug = base[:40 - len(sufixo)] + sufixo
        n += 1
    ordem = _ordem(dados.get("ordem"), max((s["ordem"] for s in existentes), default=-1) + 1)
    banco.salvar_setor(slug, nome, tipo, ordem, True)
    return banco.obter_setor(slug)


def editar(banco, dados):
    """dados: {"setor", "nome"?, "tipoColeta"?, "ordem"?, "ativo"?}."""
    atual = banco.obter_setor(str(dados.get("setor") or ""))
    if atual is None:
        raise ErroSetor("Setor não encontrado.")
    nome = _nome(dados["nome"]) if "nome" in dados else atual["nome"]
    if _nome_repetido(banco, nome, exceto=atual["setor"]):
        raise ErroSetor("Já existe um setor com esse nome.")
    tipo = _tipo(dados.get("tipoColeta"), atual["tipoColeta"])
    ordem = _ordem(dados.get("ordem"), atual["ordem"])
    ativo = bool(dados["ativo"]) if "ativo" in dados else atual["ativo"]
    if not ativo and atual["ativo"] and not any(s["ativo"] for s in banco.listar_setores() if s["setor"] != atual["setor"]):
        raise ErroSetor("Precisa ficar ao menos um setor ativo.")
    banco.salvar_setor(atual["setor"], nome, tipo, ordem, ativo)
    return banco.obter_setor(atual["setor"])


def apagar(banco, setor):
    atual = banco.obter_setor(str(setor or ""))
    if atual is None:
        raise ErroSetor("Setor não encontrado.")
    if len(banco.listar_setores()) <= 1:
        raise ErroSetor("Precisa existir ao menos um setor.")
    if not banco.apagar_setor(atual["setor"]):
        raise ErroSetor("Este setor já tem máquinas ou produção registrada: desative em vez de apagar "
                        "(o histórico continua nos relatórios).")
    if not any(s["ativo"] for s in banco.listar_setores()):  # apagou o unico ativo
        primeiro = banco.listar_setores()[0]
        banco.salvar_setor(primeiro["setor"], primeiro["nome"], primeiro["tipoColeta"], primeiro["ordem"], True)


def setor_padrao(banco):
    """O setor que o painel abre quando nenhum e pedido: o primeiro ativo."""
    ativos = banco.listar_setores(incluir_inativos=False)
    return (ativos or banco.listar_setores())[0]["setor"]


def resolver(banco, pedido):
    """Setor pedido pelo painel (?setor= ou "setor" no corpo). Vazio = o
    padrao; desconhecido = None (o servidor responde 404)."""
    pedido = str(pedido or "").strip()
    if not pedido:
        return setor_padrao(banco)
    return pedido if banco.obter_setor(pedido) else None


# -- sincronizacao com a VPS (item global "setores") -------------------------

def lista_para_sync(banco):
    return [{"setor": s["setor"], "nome": s["nome"], "tipoColeta": s["tipoColeta"],
             "ordem": s["ordem"], "ativo": s["ativo"]} for s in banco.listar_setores()]


def aplicar_lista(banco, lista):
    """Aplica o cadastro completo vindo do outro lado: cria/atualiza os da
    lista e apaga os que sumiram dela - so se nao tiverem dados (setor com
    dados nunca some: fica como estava). Itens invalidos sao ignorados."""
    if not isinstance(lista, list):
        raise ValueError("lista de setores invalida")
    vistos = set()
    for item in lista[:MAX_SETORES]:
        if not isinstance(item, dict) or not slug_valido(item.get("setor")):
            continue
        try:
            nome, tipo = _nome(item.get("nome")), _tipo(item.get("tipoColeta"))
        except ErroSetor:
            continue
        banco.salvar_setor(item["setor"], nome, tipo, _ordem(item.get("ordem"), 0), bool(item.get("ativo", True)))
        vistos.add(item["setor"])
    if not vistos:
        return
    for s in banco.listar_setores():
        if s["setor"] not in vistos:
            banco.apagar_setor(s["setor"])  # nao apaga se tiver dados
    if not any(s["ativo"] for s in banco.listar_setores()):
        primeiro = banco.listar_setores()[0]
        banco.salvar_setor(primeiro["setor"], primeiro["nome"], primeiro["tipoColeta"], primeiro["ordem"], True)
