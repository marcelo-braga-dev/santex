"""
Testes da etapa 1.4 da 2.0: resumo por dia (resumo_dia), consultas por
periodo e as rotas /api/v2/ciclos, /api/v2/resumo e /dados?desde=. Tudo em
pasta temporaria (preparacao do test_backend).

    python -m unittest discover -s testes -v
"""

import gzip
import json
import os
import random
import sqlite3
import sys
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_backend import novo_banco, servidor  # noqa: E402

import banco_dados  # noqa: E402
from banco_dados import partes_por_dia  # noqa: E402


def tabela_resumo(b, setor=None):
    con = sqlite3.connect(b.caminho)
    try:
        sql = "SELECT setor, maquina, dia, ciclos, ROUND(segundos_ligada, 3) FROM resumo_dia WHERE ciclos != 0 OR segundos_ligada > 0.001"
        return sorted(con.execute(sql + (" AND setor = ?" if setor else ""), (setor,) if setor else ()).fetchall())
    finally:
        con.close()


class TesteResumoDia(unittest.TestCase):
    def test_partes_por_dia(self):
        self.assertEqual(partes_por_dia("2026-12-01 10:00:00", 600), [("2026-12-01", 1, 600.0)])
        # passa da meia-noite: o tempo e dividido, o ciclo conta no dia do fim
        self.assertEqual(partes_por_dia("2026-12-02 00:10:00", 1800),
                         [("2026-12-02", 1, 600.0), ("2026-12-01", 0, 1200.0)])
        # termina exatamente a meia-noite (nao entra em laco)
        self.assertEqual(partes_por_dia("2026-12-02 00:00:00", 300), [("2026-12-02", 1, 0.0), ("2026-12-01", 0, 300.0)])
        # mais de um dia inteiro
        partes = partes_por_dia("2026-12-03 01:00:00", 2 * 86400)
        self.assertEqual([p[0] for p in partes], ["2026-12-03", "2026-12-02", "2026-12-01"])
        self.assertAlmostEqual(sum(p[2] for p in partes), 2 * 86400)
        self.assertEqual(partes_por_dia("?", 10), [])
        self.assertEqual(partes_por_dia("2026-12-01T10:00:00", 60), [("2026-12-01", 1, 60.0)])  # com T tambem

    def test_quem_entra_no_resumo(self):
        self.assertTrue(banco_dados.conta_no_resumo(None, ""))  # Serial
        self.assertTrue(banco_dados.conta_no_resumo("AA-1", "CURTO"))
        self.assertFalse(banco_dados.conta_no_resumo("AA-1", "SEM_HORA"))  # sem relogio: hora do download
        self.assertTrue(banco_dados.conta_no_resumo("NOTEBOOK-SERIAL-1", "SEM_HORA"))  # chegada real
        self.assertFalse(banco_dados.conta_no_resumo(None, "simulado"))

    def test_incremental_igual_ao_recalculo(self):
        b = novo_banco()
        sorteio = random.Random(7)
        base = datetime(2026, 12, 1, 5, 0, 0)
        for i in range(1, 400):
            fim = base + timedelta(minutes=sorteio.randint(0, 6 * 24 * 60))
            obs = sorteio.choice(["", "", "", "CURTO", "SEM_HORA", "SIMULADO"])
            setor = sorteio.choice(["enfestadeiras", "costura"])
            b.gravar_ciclo_remoto(setor, f"ESP{i % 5}-SERIE{i % 5}", i, sorteio.randint(1, 6), i, "?", "?",
                                  sorteio.uniform(5, 5400), obs, fim.strftime("%Y-%m-%d %H:%M:%S"))
        b.gravar_ciclo("enfestadeiras", 2, 1, "0", "1000", 42.0, "")  # Serial (hora do PC)
        incremental = tabela_resumo(b)
        self.assertGreater(len(incremental), 20)
        b.recalcular_resumo()
        self.assertEqual(tabela_resumo(b), incremental)
        b.recalcular_resumo("costura")  # so um setor: o outro fica igual
        self.assertEqual(tabela_resumo(b), incremental)

    def test_hora_completada_depois_entra_uma_vez(self):
        b = novo_banco()
        # chegou sem hora (fica fora do resumo) e depois com a hora real
        b.gravar_ciclo_remoto("enfestadeiras", "AA0000000000-SERIE1", 5, 1, 5, "1000", "61000", 60.0, "SEM_HORA",
                              "2026-12-10 09:00:00")
        self.assertEqual(b.resumo("enfestadeiras", "2026-12-01", "2026-12-31"), [])
        self.assertTrue(b.gravar_ciclo_remoto("enfestadeiras", "AA0000000000-SERIE1", 5, 1, 5,
                                              "2026-12-08T07:00:00", "2026-12-08T07:01:00", 60.0, "", "2026-12-08 07:01:00"))
        self.assertEqual(b.resumo("enfestadeiras", "2026-12-01", "2026-12-31"),
                         [{"dia": "2026-12-08", "ciclos": 1, "segundosLigada": 60.0}])
        # repetir nao soma de novo
        self.assertFalse(b.gravar_ciclo_remoto("enfestadeiras", "AA0000000000-SERIE1", 5, 1, 5,
                                               "2026-12-08T07:00:00", "2026-12-08T07:01:00", 60.0, "", "2026-12-08 07:01:00"))
        self.assertEqual(b.resumo("enfestadeiras", "2026-12-01", "2026-12-31")[0]["ciclos"], 1)

    def test_banco_da_1x_ganha_o_resumo_ao_abrir(self):
        b = novo_banco()
        b.gravar_ciclo_remoto("enfestadeiras", "AA-S1", 1, 3, 1, "?", "?", 100.0, "", "2026-12-05 10:00:00")
        con = sqlite3.connect(b.caminho)  # como um banco da 1.7.5: sem resumo nem marca
        con.execute("DELETE FROM resumo_dia")
        con.execute("DELETE FROM segredos WHERE chave = 'resumo_dia_versao'")
        con.commit()
        con.close()
        b2 = type(b)(b.caminho)
        self.assertEqual(b2.resumo("enfestadeiras", "2026-12-05", "2026-12-05", "maquina"),
                         [{"maquina": 3, "ciclos": 1, "segundosLigada": 100.0}])
        self.assertEqual(b2.total_ciclos("enfestadeiras"), 1)  # os ciclos nao mudam

    def test_agrupamentos_e_filtros(self):
        b = novo_banco()
        for i, (maq, fim) in enumerate([(1, "2026-12-01 08:00:00"), (2, "2026-12-01 09:00:00"),
                                        (1, "2026-12-02 08:00:00"), (3, "2026-12-03 08:00:00")], start=1):
            b.gravar_ciclo_remoto("costura", "C-S", i, maq, i, "?", "?", 60.0, "", fim)
        self.assertEqual([l["ciclos"] for l in b.resumo("costura", "2026-12-01", "2026-12-03")], [2, 1, 1])
        self.assertEqual(b.resumo("costura", "2026-12-01", "2026-12-02", "maquina"),
                         [{"maquina": 1, "ciclos": 2, "segundosLigada": 120.0}, {"maquina": 2, "ciclos": 1, "segundosLigada": 60.0}])
        self.assertEqual(len(b.resumo("costura", "2026-12-01", "2026-12-03", "dia_maquina", [1])), 2)
        # CSV por periodo (pelo fim do ciclo) e por maquina
        self.assertEqual(len(b.csv_do_setor("costura", desde="2026-12-02").splitlines()), 3)  # cabecalho + 2
        self.assertEqual(len(b.csv_do_setor("costura", desde="2026-12-01", ate="2026-12-01").splitlines()), 3)
        self.assertEqual(len(b.csv_do_setor("costura", maquinas=[1]).splitlines()), 3)


class TesteRotasPeriodo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = servidor._ServidorExclusivo(("::1", 0), servidor.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://[::1]:{cls.srv.server_address[1]}"
        b = servidor.banco
        if not b.obter_setor("tinturaria"):
            import setores
            setores.criar(b, {"nome": "Tinturaria", "tipoColeta": "unitario"})
        for i, (maq, fim) in enumerate([(1, "2026-10-01 08:00:00"), (2, "2026-10-01 23:50:00"),
                                        (1, "2026-10-02 08:00:00")], start=1):
            b.gravar_ciclo_remoto("tinturaria", "TINT-S", i, maq, i, "?", "?", 1200.0, "", fim)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def pedir(self, caminho, cabecalhos=None):
        req = urllib.request.Request(self.base + caminho, headers=cabecalhos or {})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                corpo = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    corpo = gzip.decompress(corpo)
                return r.status, corpo, r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    def test_resumo_por_periodo(self):
        st, corpo, _ = self.pedir("/api/v2/resumo?setor=tinturaria&de=2026-10-01&ate=2026-10-02&agrupar=dia")
        r = json.loads(corpo)
        self.assertEqual(st, 200)
        self.assertEqual([(l["dia"], l["ciclos"]) for l in r["linhas"]], [("2026-10-01", 2), ("2026-10-02", 1)])
        self.assertEqual(r["totais"], {"ciclos": 3, "segundosLigada": 3600.0})
        st, corpo, _ = self.pedir("/api/v2/resumo?setor=tinturaria&de=2026-10-01&ate=2026-10-02&agrupar=maquina&maquinas=2")
        self.assertEqual(json.loads(corpo)["linhas"], [{"maquina": 2, "ciclos": 1, "segundosLigada": 1200.0}])
        for ruim in ("de=2026-10-05&ate=2026-10-01", "de=01/10/2026", "agrupar=turno", "agrupar=x", "maquinas=0",
                     "de=2000-01-01&ate=2026-10-01"):
            with self.subTest(ruim=ruim):
                self.assertEqual(self.pedir(f"/api/v2/resumo?setor=tinturaria&{ruim}")[0], 400)
        self.assertEqual(self.pedir("/api/v2/resumo?setor=nao-existe")[0], 404)

    def test_ciclos_por_periodo_csv_e_json(self):
        st, corpo, _ = self.pedir("/api/v2/ciclos?setor=tinturaria&de=2026-10-01&ate=2026-10-01")
        linhas = corpo.decode().splitlines()
        self.assertEqual((st, linhas[0]), (200, "maquina,ciclo,inicio_ms,fim_ms,duracao_s,obs,registrado_em"))
        self.assertEqual(len(linhas), 3)
        st, corpo, _ = self.pedir("/api/v2/ciclos?setor=tinturaria&de=2026-10-01&ate=2026-10-02&formato=json&maquinas=1")
        r = json.loads(corpo)
        self.assertEqual([(c["maquina"], c["fim"]) for c in r["ciclos"]],
                         [(1, "2026-10-01 08:00:00"), (1, "2026-10-02 08:00:00")])
        self.assertEqual(self.pedir("/api/v2/ciclos?setor=tinturaria&de=2025-01-01&ate=2026-10-01")[0], 400)  # > 400 dias

    def test_dados_desde_tem_etag_propria(self):
        st, todo, cab_todo = self.pedir("/dados?setor=tinturaria")
        st2, janela, cab_janela = self.pedir("/dados?setor=tinturaria&desde=2026-10-02")
        self.assertEqual((st, st2), (200, 200))
        self.assertEqual(len(todo.decode().splitlines()), 4)
        self.assertEqual(len(janela.decode().splitlines()), 2)
        self.assertNotEqual(cab_todo["ETag"], cab_janela["ETag"])
        self.assertEqual(self.pedir("/dados?setor=tinturaria&desde=2026-10-02", {"If-None-Match": cab_janela["ETag"]})[0], 304)
        self.assertEqual(self.pedir("/dados?setor=tinturaria&desde=ontem")[0], 400)

    def test_dados_incrementais_somam_o_mesmo_que_a_carga_completa(self):
        # fase 2: carga completa (X-Ultimo-Id) + so os novos (apos=) == carga completa de novo
        b = servidor.banco
        import setores
        if not b.obter_setor("estamparia"):
            setores.criar(b, {"nome": "Estamparia"})
        b.gravar_ciclo_remoto("estamparia", "EST000-ESTAMPA1", 1, 1, 1, "?", "?", 60.0, "", "2026-10-10 08:00:00")
        for desde in ("", "&desde=2026-10-10"):
            with self.subTest(desde=desde):
                st, base, cab = self.pedir(f"/dados?setor=estamparia{desde}")
                ultimo = int(cab["X-Ultimo-Id"])
                self.assertGreater(ultimo, 0)
                # nada novo: so o cabecalho, o id nao muda
                st, novos, cab2 = self.pedir(f"/dados?setor=estamparia{desde}&apos={ultimo}")
                self.assertEqual((st, len(novos.decode().splitlines()), int(cab2["X-Ultimo-Id"])), (200, 1, ultimo))
                # chegam 2 ciclos novos e 1 antigo atrasado (fora da janela de "desde")
                n = 10 if not desde else 20
                b.gravar_ciclo_remoto("estamparia", "EST000-ESTAMPA1", n, 2, n, "?", "?", 60.0, "", "2026-10-11 09:00:00")
                b.gravar_ciclo_remoto("estamparia", "EST000-ESTAMPA1", n + 1, 1, n + 1, "?", "?", 60.0, "", "2026-10-01 09:00:00")
                b.gravar_ciclo_remoto("estamparia", "EST000-ESTAMPA1", n + 2, 3, n + 2, "?", "?", 60.0, "", "2026-10-11 10:00:00")
                st, novos, cab3 = self.pedir(f"/dados?setor=estamparia{desde}&apos={ultimo}")
                linhas = novos.decode().splitlines()[1:]
                self.assertEqual(len(linhas), 3 if not desde else 2)
                self.assertGreater(int(cab3["X-Ultimo-Id"]), ultimo)  # avanca tambem sobre o atrasado
                acumulado = base.decode().rstrip("\n").split("\n") + linhas
                st, completo, cab4 = self.pedir(f"/dados?setor=estamparia{desde}")
                self.assertEqual(completo.decode().rstrip("\n").split("\n"), acumulado)
                self.assertEqual(cab4["X-Ultimo-Id"], cab3["X-Ultimo-Id"])
        self.assertEqual(self.pedir("/dados?setor=estamparia&apos=x")[0], 400)


if __name__ == "__main__":
    unittest.main()
