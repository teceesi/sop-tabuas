#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gerador da dash S&OP — Cervejaria Tabuas.

Modos:
  python generate.py --mock     -> usa dados embutidos já validados (nao acessa a planilha)
  python generate.py            -> le a planilha ao vivo via API gviz/tq (modo de producao)

Saida: index.html (na mesma pasta). O GitHub Actions commita esse arquivo e o
GitHub Pages republica sozinho.

OBS sobre o modo ao vivo: o parser se localiza pelos cabecalhos da aba
'POSICAO DE ESTOQUE CHOPE SEMANAL'. Se a estrutura da aba mudar muito, ele
levanta erro e grava debug_grid.json com o que leu, pra ajuste rapido.
"""
import sys, json, re, datetime, urllib.request, urllib.parse

# ============================ CONFIG ============================
SHEET_ID   = "1IASI5pc9jTY9DLs_AzEgmVpJo-tLT5KBw-rQIlufbSE"
POSICAO_TAB = "POSIÇÃO DE ESTOQUE CHOPE SEMANAL"
GROUPS     = ["trevo", "capim", "estaca", "NEIPA", "escura", "sour", "outras"]
HORIZON    = 20          # quantas semanas projetar pra frente
WEEK_OFFSET = 0          # ajuste fino se a numeracao da planilha diferir da semana ISO
TZ_LABEL   = "America/Sao_Paulo"
MESES = ["jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"]
# ===============================================================


# -------- utilidades de data/semana --------
def hoje():
    return datetime.date.today()

def semana_atual():
    return hoje().isocalendar()[1] + WEEK_OFFSET

def data_da_semana(ano, semana):
    """Segunda-feira da semana ISO."""
    return datetime.date.fromisocalendar(ano, semana - WEEK_OFFSET, 1)

def fmt_data(d):
    return f"{d.day:02d}/{MESES[d.month-1]}"

def fmt_l(n):
    return f"{round(n):,}".replace(",", ".")


# ======================= CARGA DE DADOS =======================
# Cada loader devolve um dicionario "raw" com:
#   cur_week : int
#   real_stock : {grupo: litros}             estoque liquido real na semana corrente
#   plan_ent   : {grupo: {semana: litros}}   entradas (envases) planejadas
#   plan_sai   : {grupo: {semana: litros}}   saidas planejadas
#   real_sai   : {grupo: {semana: litros}}   saidas realizadas (S18..cur)
#   plan_sai_total : {semana: litros}        saida planejada total (p/ grafico real x plan)

def load_mock():
    cur = 25
    real_stock = {"trevo":855,"capim":1719,"estaca":0,"NEIPA":458,"escura":30,"sour":344,"outras":270}
    # pares (entrada, saida) planejados por semana a partir da S18
    PLAN_PAIRS = {
     "trevo":[0,493,600,509,600,509,800,509,600,509,600,488,0,488,570,988,570,488,570,501,570,507,570,507,570,507,570,521,570,555,570,555,570,555,570,555,570,618,570,629,570,629,570,629,570,651,570,668,570,668,570,668,570,579,570,48,570,48],
     "capim":[1000,277,0,281,1000,281,0,281,0,281,1000,270,0,270,1000,770,0,270,0,277,0,280,1000,280,0,280,0,288,1000,307,0,307,1000,307,0,307,0,345,1000,352,0,352,0,352,1000,362,0,370,0,370,1000,370,0,321,0,24,1000,24],
     "estaca":[600,398,0,399,0,399,850,399,0,399,850,388,0,388,920,388,930,437,0,398,0,402,930,402,0,402,0,412,0,437,920,437,920,437,0,437,0,493,0,503,0,503,0,503,0,510,0,516,0,516,0,516,0,447,0,29,0,29],
     "NEIPA":[0,217,0,215,0,215,750,215,0,215,0,208,500,208,0,208,0,235,0,214,738,216,0,216,530,216,0,221,0,235,700,235,0,235,0,235,0,268,0,273,0,273,0,273,0,276,0,278,0,278,0,278,0,240,0,11,0,11],
     "escura":[0,68,0,68,0,68,0,68,20,68,262,65,0,65,20,65,0,75,550,68,160,68,0,68,0,68,0,70,0,75,0,75,0,75,160,75,0,83,0,84,0,84,160,84,0,87,0,90,160,90,0,90,0,78,160,6,0,6],
     "sour":[600,115,0,115,0,115,0,115,850,115,0,111,0,111,0,111,0,126,0,114,950,116,0,116,0,116,0,119,0,126,0,126,0,126,0,126,0,142,0,145,0,145,0,145,0,148,0,150,0,150,0,150,0,130,0,8,0,8],
     "outras":[0,227,0,225,250,225,600,225,250,225,0,218,560,218,0,218,800,246,0,224,0,226,0,226,0,226,1050,232,0,246,500,246,0,246,0,246,500,279,0,284,0,284,500,284,0,288,0,291,500,291,0,291,0,251,500,12,0,12],
    }
    REAL_SAIDA_PAIRS = {  # saida realizada por semana S18..S25 (gruposData)
     "trevo":[1,507,400,500,296,543,241,405],"estaca":[4,158,11,640,219,709,126,330],
     "capim":[26,230,496,370,55,209,195,250],"NEIPA":[11,312,284,386,186,134,295,299],
     "sour":[9,252,194,56,317,206,91,50],"escura":[2,4,2,0,31,138,100,0],
     "outras":[2,188,163,313,176,100,420,80],
    }
    plan_ent, plan_sai = {}, {}
    for g, arr in PLAN_PAIRS.items():
        plan_ent[g], plan_sai[g] = {}, {}
        for w in range(18, 18 + len(arr)//2):
            i = 2*(w-18)
            plan_ent[g][w] = arr[i]; plan_sai[g][w] = arr[i+1]
    real_sai = {g: {18+i: v for i, v in enumerate(arr)} for g, arr in REAL_SAIDA_PAIRS.items()}
    plan_sai_total = {w: v for w, v in zip(range(18,36),
        [776,1812,1812,1812,1812,1748,1748,2748,1748,499,1296,1815,1815,1815,1296,566,1983,1983])}
    return dict(cur_week=cur, real_stock=real_stock, plan_ent=plan_ent, plan_sai=plan_sai,
                real_sai=real_sai, plan_sai_total=plan_sai_total)


def _gviz_grid(sheet_name):
    """Le uma aba publica via gviz/tq e devolve uma matriz (lista de listas) de valores."""
    url = (f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?"
           + urllib.parse.urlencode({"tqx": "out:json", "sheet": sheet_name}))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
    m = re.search(r"setResponse\((.*)\);?\s*$", raw, re.S)
    if not m:
        raise RuntimeError("Resposta gviz inesperada (a aba precisa estar publica/compartilhada por link).")
    table = json.loads(m.group(1))["table"]
    grid = []
    for r in table["rows"]:
        row = []
        for c in (r.get("c") or []):
            row.append(None if c is None else c.get("v"))
        grid.append(row)
    return grid

def _num(x):
    if x is None: return None
    if isinstance(x, (int, float)): return x
    s = str(x).strip().replace(".", "").replace(",", ".")
    try: return float(s)
    except ValueError: return None

def load_live():
    grid = _gviz_grid(POSICAO_TAB)
    # localizar blocos: cada grupo aparece em 3 blocos (estoque, real e/s, plan e/s),
    # sempre na ordem trevo..outras. Detectamos pelo reinicio da sequencia.
    blocks, cur, seen = [], [], set()
    for ri, row in enumerate(grid):
        first = (str(row[0]).strip().lower() if row and row[0] is not None else "")
        match = next((g for g in GROUPS if g.lower() == first), None)
        if match:
            if match.lower() in seen:           # reiniciou -> novo bloco
                blocks.append(cur); cur, seen = [], set()
            cur.append((ri, match, row)); seen.add(match.lower())
    if cur: blocks.append(cur)
    if len(blocks) < 3:
        with open("debug_grid.json", "w") as f: json.dump(grid, f, ensure_ascii=False, indent=1)
        raise RuntimeError(f"Esperava 3 blocos (estoque, real e/s, plan e/s), achei {len(blocks)}. "
                           "Veja debug_grid.json e ajuste o parser.")
    blk_stock, blk_real_es, blk_plan_es = blocks[0], blocks[1], blocks[2]

    def header_weeks(block_first_ri):
        """Acha a linha de cabecalho (numeros de semana) logo acima do bloco e
        devolve lista [(col, semana)] na ordem das colunas."""
        for ri in range(block_first_ri-1, max(block_first_ri-6, -1), -1):
            row = grid[ri]
            wks = [(ci, int(v)) for ci, v in enumerate(row)
                   if isinstance(_num(v), float) and 10 <= _num(v) <= 53 and float(v).is_integer()]
            if len(wks) >= 6:
                return wks
        return []

    def pair_cols(weeks):
        """De [(col,sem),(col,sem)...] com semanas duplicadas (a,a,b,b..) -> {sem:(col1,col2)}."""
        out = {}
        i = 0
        while i < len(weeks):
            col, w = weeks[i]
            if i+1 < len(weeks) and weeks[i+1][1] == w:
                out[w] = (col, weeks[i+1][0]); i += 2
            else:
                out[w] = (col, col); i += 1
        return out

    cur_week = semana_atual()
    # --- estoque real na semana corrente (2a coluna do par = 'real') ---
    cols_stock = pair_cols(header_weeks(blk_stock[0][0]))
    real_stock = {}
    for _, g, row in blk_stock:
        c = cols_stock.get(cur_week)
        real_stock[g] = round(_num(row[c[1]]) or 0)
    # --- plan entrada/saida (1o=entrada, 2o=saida) ---
    cols_pes = pair_cols(header_weeks(blk_plan_es[0][0]))
    plan_ent, plan_sai = {}, {}
    for _, g, row in blk_plan_es:
        plan_ent[g], plan_sai[g] = {}, {}
        for w, (ce, cs) in cols_pes.items():
            plan_ent[g][w] = round(_num(row[ce]) or 0)
            plan_sai[g][w] = round(_num(row[cs]) or 0)
    # --- saida realizada por grupo (2o do par no bloco real e/s) ---
    cols_res = pair_cols(header_weeks(blk_real_es[0][0]))
    real_sai = {}
    for _, g, row in blk_real_es:
        real_sai[g] = {}
        for w, (ce, cs) in cols_res.items():
            if w <= cur_week:
                real_sai[g][w] = round(_num(row[cs]) or 0)
    plan_sai_total = {w: sum(plan_sai[g].get(w, 0) for g in GROUPS) for w in cols_pes}
    return dict(cur_week=cur_week, real_stock=real_stock, plan_ent=plan_ent, plan_sai=plan_sai,
                real_sai=real_sai, plan_sai_total=plan_sai_total)


# ========================== CALCULO ==========================
def build_model(raw):
    cur = raw["cur_week"]; ano = hoje().year
    proj_weeks = list(range(cur+1, cur+1+HORIZON))
    m = {"cur_week": cur, "ano": ano, "proj_weeks": proj_weeks, "groups": {}}
    for g in GROUPS:
        s = raw["real_stock"].get(g, 0); proj = []
        for w in proj_weeks:
            s = s + raw["plan_ent"][g].get(w, 0) - raw["plan_sai"][g].get(w, 0)
            proj.append(round(s))
        first_neg = next((proj_weeks[i] for i, v in enumerate(proj) if v < 0), None)
        # proximo envase = 1a semana futura com entrada planejada > 0
        nxt = next(((w, raw["plan_ent"][g][w]) for w in proj_weeks if raw["plan_ent"][g].get(w, 0) > 0), None)
        cur_stock = raw["real_stock"].get(g, 0)
        if cur_stock <= 0:
            sev = "critico"
        elif first_neg is not None and first_neg <= cur + 2:
            sev = "critico"
        elif first_neg is not None:
            sev = "atencao"
        else:
            sev = "ok"
        m["groups"][g] = dict(stock=cur_stock, proj=proj, first_neg=first_neg, sev=sev,
                              next_env=nxt,
                              ent_next=raw["plan_ent"][g].get(cur+1, 0),
                              sai_next=raw["plan_sai"][g].get(cur+1, 0),
                              saldo_next=proj[0])
    m["total_stock"] = sum(raw["real_stock"].get(g, 0) for g in GROUPS)
    # saidas realizadas
    weeks_real = sorted({w for g in GROUPS for w in raw["real_sai"].get(g, {})})
    weeks_real = [w for w in weeks_real if w <= cur]
    m["weeks_real"] = weeks_real
    m["gruposData"] = {g: [round(raw["real_sai"][g].get(w, 0)) for w in weeks_real] for g in GROUPS}
    m["saida_real_total"] = [round(sum(raw["real_sai"][g].get(w, 0) for g in GROUPS)) for w in weeks_real]
    last7 = m["saida_real_total"][-7:] if len(m["saida_real_total"]) >= 2 else m["saida_real_total"]
    m["media_saida"] = round(sum(m["saida_real_total"][1:][-6:]) / max(len(m["saida_real_total"][1:][-6:]), 1)) if len(m["saida_real_total"])>1 else 0
    m["total_saido"] = sum(m["saida_real_total"])
    # grafico real x plan: ate cur+10
    all_w = list(range(18, cur+11))
    m["all_sems"] = all_w
    real_map = {w: t for w, t in zip(weeks_real, m["saida_real_total"])}
    m["saida_real_chart"] = [real_map.get(w) for w in all_w]
    m["saida_plan_chart"] = [round(raw["plan_sai_total"].get(w, 0)) for w in all_w]
    return m


# ========================== RENDER ==========================
NAMES = {"trevo":"Trevo","capim":"Capim","estaca":"Estaca","NEIPA":"NEIPA",
         "escura":"Escura","sour":"Sour","outras":"Outras"}
CORES = {"trevo":"#2C5F2D","estaca":"#1B6CA8","capim":"#D4820A","NEIPA":"#7B5EA7",
         "sour":"#D85A30","escura":"#6B4C3B","outras":"#888"}

def env_label(gd, ano):
    if not gd["next_env"]: return "sem envase no horizonte"
    w, l = gd["next_env"]; d = data_da_semana(ano, w)
    return f"S{w} · {fmt_data(d)} · {fmt_l(l)} L"

def render(m):
    cur = m["cur_week"]; ano = m["ano"]; nxt = cur+1
    cur_date = fmt_data(data_da_semana(ano, cur)) if False else fmt_data(datetime.date.today())
    end = m["proj_weeks"][-1]
    crit = [g for g in GROUPS if m["groups"][g]["sev"] == "critico"]
    aten = [g for g in GROUPS if m["groups"][g]["sev"] == "atencao"]
    oks  = [g for g in GROUPS if m["groups"][g]["sev"] == "ok"]

    # ---- subtitle + badge ----
    sub = f"Saídas realizadas S18–S{cur} · Previsão S{nxt}–S{end} · Estoque real atualizado S{cur} ({cur_date})"
    if crit:
        badge = f'<span class="badge b-danger">⚠ Ação imediata — {", ".join(NAMES[g] for g in crit)}</span>'
    elif aten:
        badge = f'<span class="badge b-warn">⚠ Atenção — {", ".join(NAMES[g] for g in aten)}</span>'
    else:
        badge = '<span class="badge b-ok">✅ Sem riscos no horizonte</span>'

    # ---- alerts ----
    alerts = []
    if crit:
        desc = " · ".join(
            (f"{NAMES[g]} zerada (0 L)" if m['groups'][g]['stock'] <= 0
             else f"{NAMES[g]} em {fmt_l(m['groups'][g]['stock'])} L (rompe S{m['groups'][g]['first_neg']})")
            for g in crit)
        alerts.append(f'''    <div class="alert alert-danger">
      <span style="font-size:18px;flex-shrink:0">🚨</span>
      <span><strong>Ação imediata — esta semana (S{cur}, {cur_date}):</strong> {desc}. Decisão hoje: antecipar envase ou acionar chope convidado.</span>
    </div>''')
    if aten:
        desc = " · ".join(f"{NAMES[g]} (S{m['groups'][g]['first_neg']})" for g in aten)
        alerts.append(f'''    <div class="alert alert-warn">
      <span style="font-size:18px;flex-shrink:0">⚠️</span>
      <span><strong>Atenção (vãos / 2º semestre):</strong> {desc}. Conferir timing dos envases e planejar envases extras.</span>
    </div>''')
    alerts.append(f'''    <div class="alert alert-ok">
      <span style="font-size:18px;flex-shrink:0">✅</span>
      <span><strong>Sem risco:</strong> {", ".join(NAMES[g] for g in oks) if oks else "—"}. Estoque real total de chope na S{cur}: <strong>{fmt_l(m["total_stock"])} L</strong>.</span>
    </div>''')

    # ---- risk cards (ordem: critico, atencao, ok) ----
    cards = []
    ordered = crit + aten + oks
    for idx, g in enumerate(ordered):
        gd = m["groups"][g]; cls = gd["sev"]
        icon = "🚨" if cls == "critico" else ("⚠️" if cls == "atencao" else "✅")
        if cls == "critico" and gd["stock"] <= 0:
            rs = f"Estoque zerado · próx. envase {env_label(gd, ano)}"
            rw = f'<div class="rw" style="color:#A32D2D">Ruptura atual · S{cur}</div>'
        elif cls == "critico":
            d = data_da_semana(ano, gd["first_neg"])
            rs = f"Envase só {env_label(gd, ano)}"
            rw = f'<div class="rw" style="color:#A32D2D">Falta S{gd["first_neg"]} · {fmt_data(d)}</div>'
        elif cls == "atencao":
            d = data_da_semana(ano, gd["first_neg"])
            rs = f"Próx. envase {env_label(gd, ano)}"
            rw = f'<div class="rw" style="color:#854F0B">Risco S{gd["first_neg"]} · {fmt_data(d)}</div>'
        else:
            rs = f"Envases garantidos · próx. {env_label(gd, ano)}"
            rw = f'<div class="rw" style="color:#3B6D11">OK até S{end} · cobertura folgada</div>'
        span = ' style="grid-column:span 2"' if idx == len(ordered)-1 and len(ordered) % 4 == 3 else ''
        cards.append(f'''    <div class="rcard {cls}"{span}>
      <div class="rg">{icon} {NAMES[g]}</div>
      <div class="re">{fmt_l(gd["stock"])} L</div>
      <div class="rs">{rs}</div>
      {rw}
    </div>''')

    # ---- mcards ----
    crit_names = " · ".join(NAMES[g] for g in crit) if crit else "nenhum"
    mcards = f'''    <div class="mcard">
      <div class="mcard-top" style="background:#2C5F2D;"></div>
      <div class="lbl">Estoque total atual</div>
      <div class="val" style="color:#2C5F2D">{fmt_l(m["total_stock"])} L</div>
      <div class="sub">Chope · posição real S{cur}</div>
    </div>
    <div class="mcard">
      <div class="mcard-top" style="background:#1B6CA8;"></div>
      <div class="lbl">Média real saída</div>
      <div class="val" style="color:#1B6CA8">{fmt_l(m["media_saida"])} L</div>
      <div class="sub">últimas semanas realizadas</div>
    </div>
    <div class="mcard">
      <div class="mcard-top" style="background:#D4820A;"></div>
      <div class="lbl">Total saído S18–S{cur}</div>
      <div class="val" style="color:#D4820A">{fmt_l(m["total_saido"])} L</div>
      <div class="sub">Chope · todos os canais</div>
    </div>
    <div class="mcard">
      <div class="mcard-top" style="background:#A32D2D;"></div>
      <div class="lbl">Grupos em risco imediato</div>
      <div class="val" style="color:#A32D2D">{len(crit)} grupo{"s" if len(crit)!=1 else ""}</div>
      <div class="sub">{crit_names}</div>
    </div>'''

    # ---- risk table ----
    rows = []
    badge_cls = {"critico":"b-danger","atencao":"b-warn","ok":"b-ok"}
    for g in ordered:
        gd = m["groups"][g]; bg = ' style="background:#FCEEED"' if gd["sev"]=="critico" else (' style="background:#FEF3CD"' if gd["sev"]=="atencao" else "")
        saldo = gd["saldo_next"]; saldo_s = f'<td style="color:#A32D2D;font-weight:600">{fmt_l(saldo)}</td>' if saldo<0 else f'<td>{fmt_l(saldo)}</td>'
        stock_s = f'<td style="color:#A32D2D;font-weight:600">{fmt_l(gd["stock"])}</td>' if gd["stock"]<=0 else f'<td>{fmt_l(gd["stock"])}</td>'
        if gd["sev"]=="critico" and gd["stock"]<=0: risco = '<span class="badge b-danger">Ruptura atual</span>'
        elif gd["sev"]=="critico": risco = f'<span class="badge b-danger">Falta S{gd["first_neg"]}</span>'
        elif gd["sev"]=="atencao": risco = f'<span class="badge b-warn">Risco S{gd["first_neg"]}</span>'
        else: risco = f'<span class="badge b-ok">OK até S{end}</span>'
        ent = gd["ent_next"] or "—"; ent = fmt_l(ent) if isinstance(ent,(int,float)) else ent
        rows.append(f'''          <tr{bg}>
            <td><strong>{NAMES[g]}</strong></td>{stock_s}<td>{ent}</td><td>{fmt_l(gd["sai_next"])}</td>
            {saldo_s}
            <td>{env_label(gd, ano)}</td>
            <td>{risco}</td>
          </tr>''')

    # ---- decisions ----
    dec = []
    if crit:
        dec.append(f'''      <div style="background:#A32D2D;border-radius:8px;padding:10px 14px;display:flex;gap:12px;align-items:center;">
        <span style="background:#fff;color:#A32D2D;font-size:11px;font-weight:600;padding:3px 10px;border-radius:4px;white-space:nowrap;">🚨 URGENTE</span>
        <span style="color:#fff;font-size:13px;">{", ".join(NAMES[g] for g in crit)}: antecipar envase ou acionar chope convidado imediatamente</span>
      </div>''')
    if aten:
        dec.append(f'''      <div style="background:#2C5F2D;border-radius:8px;padding:10px 14px;display:flex;gap:12px;align-items:center;">
        <span style="background:#D4820A;color:#fff;font-size:11px;font-weight:600;padding:3px 10px;border-radius:4px;white-space:nowrap;">D1</span>
        <span style="color:#C8E6C9;font-size:13px;">{", ".join(NAMES[g] for g in aten)}: planejar envases adicionais / conferir timing (riscos a partir de S{min(m['groups'][g]['first_neg'] for g in aten)})</span>
      </div>''')
    dec.append(f'''      <div style="background:#2C5F2D;border-radius:8px;padding:10px 14px;display:flex;gap:12px;align-items:center;">
        <span style="background:#7B5EA7;color:#fff;font-size:11px;font-weight:600;padding:3px 10px;border-radius:4px;white-space:nowrap;">D2</span>
        <span style="color:#C8E6C9;font-size:13px;">Confirmar demanda das próximas semanas e aprovar orçamento de contingência</span>
      </div>''')

    # ---- tabela head saidas ----
    head = "".join(f"<th>S{w}</th>" for w in m["weeks_real"])
    real_head = f"<th>Grupo</th>{head}<th>Total</th>"

    repl = {
        "{{SUBTITLE}}": sub, "{{BADGE}}": badge, "{{ALERTS}}": "\n".join(alerts),
        "{{RISK_CARDS}}": "\n".join(cards), "{{MCARDS}}": mcards,
        "{{CUR_WEEK}}": str(cur), "{{NEXT_WEEK}}": str(nxt), "{{CUR_DATE}}": cur_date,
        "{{PROJ_TITLE}}": f"S{nxt} a S{end}", "{{RISK_TABLE_ROWS}}": "\n".join(rows),
        "{{REAL_TABLE_HEAD}}": real_head, "{{DECISIONS}}": "\n".join(dec),
        "{{GENERATED_AT}}": datetime.datetime.now().strftime("%d/%m/%Y %H:%M") + " (S"+str(cur)+")",
        "{{SEMS_REAL}}": json.dumps([f"S{w}" for w in m["weeks_real"]]),
        "{{GRUPOS_DATA}}": json.dumps(m["gruposData"]),
        "{{SEMS_PROJ}}": json.dumps(m["proj_weeks"]),
        "{{EST_PROJ}}": json.dumps({g: m["groups"][g]["proj"] for g in GROUPS}),
        "{{ALL_SEMS}}": json.dumps(m["all_sems"]),
        "{{SAIDA_REAL}}": json.dumps(m["saida_real_chart"]),
        "{{SAIDA_PLAN}}": json.dumps(m["saida_plan_chart"]),
    }
    tpl = open(TEMPLATE, encoding="utf-8").read()
    for k, v in repl.items():
        tpl = tpl.replace(k, v)
    return tpl


DASH_URL = "https://teceesi.github.io/sop-tabuas/"

def dump_model(m, path):
    """Escreve model.json — a ponte que o alerts.py lê pra decidir/compor o email."""
    ano = m["ano"]
    grupos = {}
    for g in GROUPS:
        gd = m["groups"][g]
        zerada = gd["stock"] <= 0
        rompe_label = None
        if not zerada and gd["first_neg"] is not None:
            rompe_label = f"S{gd['first_neg']} ({fmt_data(data_da_semana(ano, gd['first_neg']))})"
        if gd["next_env"]:
            w, _ = gd["next_env"]
            envase_label = f"S{w} ({fmt_data(data_da_semana(ano, w))})"
        else:
            envase_label = None
        grupos[g] = dict(nome=NAMES[g], stock=gd["stock"], sev=gd["sev"],
                         zerada=zerada, first_neg=gd["first_neg"],
                         rompe_label=rompe_label, envase_label=envase_label)
    out = dict(cur_week=m["cur_week"], ano=ano, total_stock=m["total_stock"],
               gerado_em=datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
               dash_url=DASH_URL, grupos=grupos)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)


import os
TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template.html")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
MODEL_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model.json")

if __name__ == "__main__":
    mock = "--mock" in sys.argv
    raw = load_mock() if mock else load_live()
    model = build_model(raw)
    html = render(model)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    dump_model(model, MODEL_JSON)
    print(f"[ok] index.html + model.json gerados ({'MOCK' if mock else 'LIVE'}) — semana S{model['cur_week']}, "
          f"total {fmt_l(model['total_stock'])} L, "
          f"criticos: {[g for g in GROUPS if model['groups'][g]['sev']=='critico']}")
