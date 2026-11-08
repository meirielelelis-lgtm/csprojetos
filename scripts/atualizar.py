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
    """id do deputado -> {legislatura: (partido, uf)}. Se a Câmara falhar, devolve o que conseguiu."""
    mapa = {}
    for leg in range(legislatura_do_ano(max(ANO_INICIAL, 2019)), legislatura_do_ano(ano_final) + 1):
        try:
            for d in paginar("/deputados", {"idLegislatura": leg, "itens": 100, "ordem": "ASC", "ordenarPor": "nome"}):
                mapa.setdefault(d["id"], {})[leg] = (d.get("siglaPartido") or "", d.get("siglaUf") or "")
        except Exception as e:
            log(f"  aviso: não consegui a lista de partidos da legislatura {leg} ({e})")
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


def montar_basico(item, det):
    st = det.get("statusProposicao") or {}
    return {
        "id": item["id"],
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
    }


def montar_autores_historico(p, partidos_fn, anterior):
    pid = p["id"]
    autores_api = (baixar(f"/proposicoes/{pid}/autores") or {}).get("dados") or []
    autores_api = sorted(autores_api, key=lambda a: (a.get("ordemAssinatura") or 9999))
    antigos = {a.get("id"): a for a in (anterior or {}).get("autores", []) if a.get("id")}
    autores = []
    for a in autores_api:
        dep_id = id_da_uri(a.get("uri")) if "deputados" in str(a.get("uri")) else None
        partido, uf = partido_de(partidos_fn(), dep_id, p.get("ano") or 2019) if dep_id else ("", "")
        if dep_id and not partido and dep_id in antigos:
            partido, uf = antigos[dep_id].get("partido", ""), antigos[dep_id].get("uf", "")
        autores.append({"id": dep_id, "nome": a.get("nome"), "tipo": a.get("tipo"), "partido": partido, "uf": uf})

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
        "autoriaPrincipal": bool(autores) and autores[0].get("id") == DEPUTADO_ID,
        "autores": autores,
        "historico": historico,
    }


def iso(t):
    return t.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def gravar_verificacao(agora, ok, msg, total=None, mudou=False):
    """Arquivo pequeno que diz à página quando o robô conferiu pela última vez (não vai para o histórico)."""
    caminho = os.path.join(os.path.dirname(os.path.abspath(SAIDA)), "verificacao.json")
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump({"verificadoEm": iso(agora), "ok": ok, "mensagem": msg, "total": total, "mudou": mudou}, f, ensure_ascii=False)


def main():
    agora = dt.datetime.now(dt.timezone.utc)
    anterior = {}
    if os.path.exists(SAIDA):
        with open(SAIDA, encoding="utf-8") as f:
            anterior = json.load(f)
    anteriores = {p["id"]: p for p in anterior.get("proposicoes", [])}
    ultima_completa = anterior.get("revisaoCompletaEm") or anterior.get("atualizadoEm") or "2000-01-01T00:00:00Z"
    try:
        dias_desde_completa = (agora - dt.datetime.fromisoformat(ultima_completa.replace("Z", "+00:00"))).days
    except ValueError:
        dias_desde_completa = 99
    completa = (
        os.environ.get("COMPLETA") == "1"
        or not anteriores
        or anterior.get("deputadoId") != DEPUTADO_ID
        or anterior.get("tipos") != TIPOS
        or dias_desde_completa >= 7          # uma vez por semana revisa autores e histórico de tudo
    )
    log(f"Deputado {DEPUTADO_ID} | tipos {TIPOS} | revisão {'COMPLETA' if completa else 'rápida'}")
    avisos = 0

    # 0) dados do deputado (se falhar, mantém os anteriores)
    try:
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
    except Exception as e:
        log(f"  aviso: não consegui os dados do deputado ({e}); mantendo os anteriores")
        deputado = anterior.get("deputado") or {"id": DEPUTADO_ID}
        avisos += 1

    # 1) lista de proposições, ano a ano (se um ano falhar, mantém o que já se sabia daquele ano)
    lista = {}
    for ano in range(ANO_INICIAL, agora.year + 1):
        try:
            itens = paginar("/proposicoes", {
                "idDeputadoAutor": DEPUTADO_ID, "siglaTipo": TIPOS, "ano": ano,
                "itens": 100, "ordem": "ASC", "ordenarPor": "id",
            })
        except Exception as e:
            itens = [{"id": p["id"], "siglaTipo": p["tipo"], "numero": p["numero"], "ano": p["ano"], "ementa": p["ementa"]}
                     for p in anteriores.values() if p.get("ano") == ano]
            log(f"  aviso: falha ao listar {ano} ({e}); mantendo {len(itens)} proposições já conhecidas")
            avisos += 1
        for p in itens:
            lista[p["id"]] = p
    if not lista:
        gravar_verificacao(agora, False, "A Câmara não respondeu.")
        sys.exit("Nenhuma proposição encontrada. Verifique DEPUTADO_ID e TIPOS, ou se a Câmara está fora do ar.")

    # 2) situação atual de cada proposição (1 consulta por proposição)
    def situacao(i):
        try:
            det = (baixar(f"/proposicoes/{i}", tentativas=4) or {}).get("dados")
            return i, (montar_basico(lista[i], det) if det else None)
        except Exception as e:
            log(f"  aviso: falha em {i} ({e}); mantendo dados anteriores")
            return i, None

    log(f"Conferindo a situação de {len(lista)} proposições...")
    basicos = {}
    with ThreadPoolExecutor(TRABALHADORES) as ex:
        for i, b in ex.map(situacao, list(lista)):
            if b:
                basicos[i] = b
            else:
                avisos += 1

    # 3) autores e histórico só para as novas ou que se mexeram (ou todas, na revisão semanal)
    precisa = [i for i, b in basicos.items()
               if completa or i not in anteriores
               or anteriores[i].get("dataStatus") != b.get("dataStatus")
               or anteriores[i].get("situacao") != b.get("situacao")]
    log(f"Buscando autores e histórico de {len(precisa)} proposições...")
    cache = {}
    def partidos_fn():
        if "m" not in cache:
            cache["m"] = mapa_de_partidos(agora.year)
        return cache["m"]
    if precisa:
        partidos_fn()  # carrega antes das threads

    def extras(i):
        try:
            return i, montar_autores_historico(basicos[i], partidos_fn, anteriores.get(i))
        except Exception as e:
            log(f"  aviso: falha nos autores/histórico de {i} ({e})")
            return i, None

    novos_extras = {}
    with ThreadPoolExecutor(TRABALHADORES) as ex:
        for i, x in ex.map(extras, precisa):
            if x:
                novos_extras[i] = x
            else:
                avisos += 1

    # 4) junta tudo
    proposicoes = []
    for i in lista:
        ant = anteriores.get(i)
        if i in basicos:
            p = dict(basicos[i])
            ex_ = novos_extras.get(i) or ({k: ant.get(k) for k in ("autoriaPrincipal", "autores", "historico")} if ant else None)
            if ex_ is None:
                ex_ = {"autoriaPrincipal": True, "autores": [], "historico": []}
            p.update(ex_)
            proposicoes.append(p)
        elif ant:
            proposicoes.append(ant)
    proposicoes.sort(key=lambda p: (p.get("dataStatus") or "", p["id"]), reverse=True)

    conteudo = {"deputado": deputado, "proposicoes": proposicoes}
    antigo = {"deputado": anterior.get("deputado"), "proposicoes": anterior.get("proposicoes")}
    mudou = conteudo != antigo
    msg = "Conferido com sucesso." if not avisos else f"Conferido, mas a Câmara falhou em {avisos} consulta(s); esses itens mantêm os dados anteriores."
    gravar_verificacao(agora, avisos <= 5, msg, len(proposicoes), mudou)

    if not mudou and not completa:
        log("Nenhuma mudança desde a última atualização.")
        return

    saida = {
        "atualizadoEm": iso(agora) if mudou else anterior.get("atualizadoEm", iso(agora)),
        "revisaoCompletaEm": iso(agora) if completa and not avisos else anterior.get("revisaoCompletaEm"),
        "deputadoId": DEPUTADO_ID,
        "tipos": TIPOS,
        "fonte": "API de Dados Abertos da Câmara dos Deputados (dadosabertos.camara.leg.br)",
        **conteudo,
    }
    os.makedirs(os.path.dirname(os.path.abspath(SAIDA)), exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, separators=(",", ":"))
    log(f"Pronto: {len(proposicoes)} proposições gravadas ({'com mudanças' if mudou else 'revisão semanal sem mudanças'}).")


if __name__ == "__main__":
    main()
