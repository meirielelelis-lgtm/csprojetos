#!/usr/bin/env python3
"""
Robô de atualização do painel de proposições.

Busca na API de Dados Abertos da Câmara dos Deputados as proposições de um
deputado (por padrão, Célio Studart) e grava o resultado em docs/dados.json,
que é o arquivo lido pela página.

Não precisa instalar nada: usa só a biblioteca padrão do Python.

Variáveis que podem ser ajustadas (no arquivo .github/workflows/atualizar.yml):
  DEPUTADO_ID   id do deputado na Câmara (Célio Studart = 204488)
  TIPOS         tipos de proposição, separados por vírgula
  ANO_INICIAL   primeiro ano a ser buscado
  COMPLETA=1    força a atualização completa de todas as proposições
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

API = os.environ.get("CAMARA_API", "https://dadosabertos.camara.leg.br/api/v2").rstrip("/")
DEPUTADO_ID = int(os.environ.get("DEPUTADO_ID", "204488"))
TIPOS = os.environ.get("TIPOS", "PL,PLP,PEC,PDL")
ANO_INICIAL = int(os.environ.get("ANO_INICIAL", "2015"))
AQUI = os.path.dirname(os.path.abspath(__file__))
SAIDA = os.environ.get("SAIDA", os.path.join(AQUI, "..", "docs", "dados.json"))
HISTORICO_GUARDADO = 8   # quantas tramitações recentes guardar por proposição
TRABALHADORES = 4        # requisições simultâneas (não aumentar muito: a Câmara limita)


def log(*a):
    print(*a, flush=True)


def baixar(caminho_ou_url, params=None, tentativas=6):
    url = caminho_ou_url if caminho_ou_url.startswith("http") else API + caminho_ou_url
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, safe=",")
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={
                "Accept": "application/json",
                "User-Agent": "painel-proposicoes/1.0 (GitHub Actions)",
            })
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            espera = 2 ** i + (10 if e.code == 429 else 0)
            log(f"  aviso: HTTP {e.code} em {url} (tentando de novo em {espera}s)")
        except Exception as e:  # rede instável, timeout etc.
            espera = 2 ** i
            log(f"  aviso: {e} em {url} (tentando de novo em {espera}s)")
        time.sleep(espera)
    raise RuntimeError(f"Não foi possível acessar {url}")


def paginar(caminho, params):
    url = API + caminho + "?" + urllib.parse.urlencode(params, safe=",")
    itens = []
    while url:
        r = baixar(url)
        if not r:
            break
        itens += r.get("dados", [])
        url = next((l.get("href") for l in r.get("links", []) if l.get("rel") == "next"), None)
    return itens


def id_da_uri(uri):
    try:
        return int(str(uri).rstrip("/").split("/")[-1])
    except (ValueError, AttributeError):
        return None


def legislatura_do_ano(ano):
    # 56ª legislatura começou em 2019; cada uma dura 4 anos
    return 56 + (int(ano) - 2019) // 4


def mapa_de_partidos(ano_final):
    """id do deputado -> {legislatura: (partido, uf)}"""
    mapa = {}
    for leg in range(legislatura_do_ano(ANO_INICIAL), legislatura_do_ano(ano_final) + 1):
        for d in paginar("/deputados", {"idLegislatura": leg, "itens": 100, "ordem": "ASC", "ordenarPor": "nome"}):
            mapa.setdefault(d["id"], {})[leg] = (d.get("siglaPartido") or "", d.get("siglaUf") or "")
    return mapa


def partido_de(mapa, dep_id, ano):
    por_leg = mapa.get(dep_id)
    if not por_leg:
        return "", ""
    leg = legislatura_do_ano(ano)
    if leg in por_leg:
        return por_leg[leg]
    return por_leg[max(por_leg)]


def corta(texto, limite):
    texto = (texto or "").strip()
    return texto if len(texto) <= limite else texto[: limite - 3].rstrip() + "..."


def montar(item, partidos):
    pid = item["id"]
    det = (baixar(f"/proposicoes/{pid}") or {}).get("dados") or {}
    st = det.get("statusProposicao") or {}

    autores_api = (baixar(f"/proposicoes/{pid}/autores") or {}).get("dados") or []
    autores_api = sorted(autores_api, key=lambda a: (a.get("ordemAssinatura") or 9999))
    autores = []
    for a in autores_api:
        dep_id = id_da_uri(a.get("uri")) if "deputados" in str(a.get("uri")) else None
        partido, uf = partido_de(partidos, dep_id, item.get("ano") or 2019) if dep_id else ("", "")
        autores.append({"id": dep_id, "nome": a.get("nome"), "tipo": a.get("tipo"), "partido": partido, "uf": uf})
    principal = bool(autores) and autores[0].get("id") == DEPUTADO_ID

    tram = (baixar(f"/proposicoes/{pid}/tramitacoes") or {}).get("dados") or []
    tram = sorted(tram, key=lambda t: (t.get("dataHora") or "", t.get("sequencia") or 0), reverse=True)
    historico = [{
        "data": t.get("dataHora"),
        "orgao": t.get("siglaOrgao"),
        "tramitacao": t.get("descricaoTramitacao"),
        "situacao": t.get("descricaoSituacao"),
        "despacho": corta(t.get("despacho"), 500),
    } for t in tram[:HISTORICO_GUARDADO]]

    return {
        "id": pid,
        "tipo": item.get("siglaTipo") or det.get("siglaTipo"),
        "numero": item.get("numero") or det.get("numero"),
        "ano": item.get("ano") or det.get("ano"),
        "ementa": (det.get("ementa") or item.get("ementa") or "").strip(),
        "apresentacao": det.get("dataApresentacao"),
        "situacao": st.get("descricaoSituacao"),
        "tramitacao": st.get("descricaoTramitacao"),
        "orgao": st.get("siglaOrgao"),
        "regime": st.get("regime"),
        "apreciacao": st.get("apreciacao"),
        "despacho": corta(st.get("despacho"), 700),
        "dataStatus": st.get("dataHora"),
        "urlTeor": det.get("urlInteiroTeor"),
        "autoriaPrincipal": principal,
        "autores": autores,
        "historico": historico,
    }


def main():
    agora = dt.datetime.now(dt.timezone.utc)
    anterior = {}
    if os.path.exists(SAIDA):
        with open(SAIDA, encoding="utf-8") as f:
            anterior = json.load(f)
    anteriores = {p["id"]: p for p in anterior.get("proposicoes", [])}
    completa = (
        os.environ.get("COMPLETA") == "1"
        or not anteriores
        or anterior.get("deputadoId") != DEPUTADO_ID
        or anterior.get("tipos") != TIPOS
        or (agora.weekday() == 6 and agora.hour < 3)   # domingo de madrugada: revisão completa
    )
    log(f"Deputado {DEPUTADO_ID} | tipos {TIPOS} | atualização {'COMPLETA' if completa else 'incremental'}")

    dep = (baixar(f"/deputados/{DEPUTADO_ID}") or {}).get("dados") or {}
    us = dep.get("ultimoStatus") or {}
    gab = us.get("gabinete") or {}
    deputado = {
        "id": DEPUTADO_ID,
        "nome": us.get("nomeEleitoral") or us.get("nome") or dep.get("nomeCivil"),
        "partido": us.get("siglaPartido"),
        "uf": us.get("siglaUf"),
        "situacao": us.get("situacao"),
        "condicao": us.get("condicaoEleitoral"),
        "foto": us.get("urlFoto"),
        "gabinete": gab.get("sala"),
        "telefone": gab.get("telefone"),
        "email": us.get("email") or gab.get("email"),
    }

    # 1) lista de proposições, ano a ano
    lista = {}
    for ano in range(ANO_INICIAL, agora.year + 1):
        itens = paginar("/proposicoes", {
            "idDeputadoAutor": DEPUTADO_ID, "siglaTipo": TIPOS, "ano": ano,
            "itens": 100, "ordem": "ASC", "ordenarPor": "id",
        })
        for p in itens:
            lista[p["id"]] = p
        if itens:
            log(f"  {ano}: {len(itens)} proposições")
    if not lista:
        sys.exit("Nenhuma proposição encontrada. Verifique DEPUTADO_ID e TIPOS.")

    # 2) quais precisam ser (re)consultadas
    if completa:
        alvo = list(lista)
    else:
        base = anterior.get("atualizadoEm") or anterior.get("geradoEm")
        try:
            desde = dt.datetime.fromisoformat(base.replace("Z", "+00:00")) - dt.timedelta(days=3)
        except Exception:
            desde = agora - dt.timedelta(days=10)
        movidas = {p["id"] for p in paginar("/proposicoes", {
            "idDeputadoAutor": DEPUTADO_ID, "siglaTipo": TIPOS,
            "dataInicio": desde.date().isoformat(), "dataFim": agora.date().isoformat(),
            "itens": 100, "ordem": "ASC", "ordenarPor": "id",
        })}
        alvo = [i for i in lista if i not in anteriores or i in movidas]
    log(f"Consultando detalhes de {len(alvo)} de {len(lista)} proposições...")

    partidos = mapa_de_partidos(agora.year)

    novos = {}
    with ThreadPoolExecutor(TRABALHADORES) as ex:
        for n, p in enumerate(ex.map(lambda i: montar(lista[i], partidos), alvo), 1):
            novos[p["id"]] = p
            if n % 50 == 0:
                log(f"  {n}/{len(alvo)}")

    proposicoes = [novos.get(i) or anteriores[i] for i in lista if (i in novos or i in anteriores)]
    proposicoes.sort(key=lambda p: (p.get("dataStatus") or "", p["id"]), reverse=True)

    conteudo = {"deputado": deputado, "proposicoes": proposicoes}
    antigo = {"deputado": anterior.get("deputado"), "proposicoes": anterior.get("proposicoes")}
    if conteudo == antigo:
        log("Nenhuma mudança desde a última atualização.")
        return

    saida = {
        "atualizadoEm": agora.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "deputadoId": DEPUTADO_ID,
        "tipos": TIPOS,
        "fonte": "API de Dados Abertos da Câmara dos Deputados (dadosabertos.camara.leg.br)",
        **conteudo,
    }
    os.makedirs(os.path.dirname(os.path.abspath(SAIDA)), exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, separators=(",", ":"))
    log(f"Pronto: {len(proposicoes)} proposições gravadas em {SAIDA}")


if __name__ == "__main__":
    main()
