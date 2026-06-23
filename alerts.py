#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Alerta de ruptura — Cervejaria Tabuas.

Le o model.json (gerado pelo generate.py), olha os grupos CRITICOS (ruptura ja /
em <= 2 semanas — o mesmo vermelho da dash) e envia email SO quando algo novo
fica critico ou piora em relacao ao ultimo envio. Estado guardado em alert_state.json.

Variaveis de ambiente (no GitHub: Secrets):
  GMAIL_USER          -> email remetente (ex: compras.cervejariatabuas@gmail.com)
  GMAIL_APP_PASSWORD  -> senha de app de 16 digitos do Gmail
  ALERT_RECIPIENTS    -> destinatarios separados por virgula

Rodar local sem enviar (so mostra o que sairia):
  python alerts.py --dry-run
"""
import os, sys, json, smtplib, datetime
from email.message import EmailMessage

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_JSON = os.path.join(HERE, "model.json")
STATE_JSON = os.path.join(HERE, "alert_state.json")
SUBJECT = "🍺🚨 Alerta Tabuas: tem chopp ameaçando acabar"


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def piorou(atual, ant):
    """True se o grupo piorou: estoque caiu, ruptura chegou mais cedo, ou virou zerada."""
    if atual["stock"] < ant.get("stock", 10**9):
        return True
    a_fn, b_fn = atual.get("first_neg"), ant.get("first_neg")
    if a_fn is not None and b_fn is not None and a_fn < b_fn:
        return True
    if atual["zerada"] and not ant.get("zerada", False):
        return True
    return False


def linha_grupo(gd):
    status = "zerada" if gd["zerada"] else f"rompe na {gd['rompe_label']}"
    envase = f"Próximo envase na {gd['envase_label']}" if gd["envase_label"] else "sem envase previsto no horizonte"
    return gd["nome"], f"{gd['stock']} L, {status}. {envase}."


def compor_email(model, criticos):
    dash = model["dash_url"]
    linhas = [linha_grupo(model["grupos"][g]) for g in criticos]

    txt = (
        "Oi, time! 👋 Aqui é o robô de plantão do S&OP.\n\n"
        "Não é trote: tem chopp querendo zerar nos próximos dias, e achei melhor "
        "avisar antes que vire vexame de torneira seca. 😬\n\n"
        "Em estado de alerta agora:\n"
        + "".join(f"🔴 {nome} — {resto}\n" for nome, resto in linhas)
        + "\nTradução pra ação: antecipar envase ou acionar chopp convidado — "
        "antes que alguém peça e a gente tenha que olhar pro chão.\n\n"
        f"Projeção completa na dash 👉 {dash}\n\n"
        "P.S.: esse email só pinga quando algo novo fica crítico (ou piora). "
        "Caixa quieta = chopp fluindo. 🍻\n\n"
        "— Robô S&OP, a serviço da Talita\n"
    )

    itens = "".join(
        f'<li style="margin:4px 0"><span style="color:#A32D2D">🔴</span> '
        f'<strong>{nome}</strong> — {resto}</li>'
        for nome, resto in linhas
    )
    html = f"""<div style="font-family:-apple-system,Segoe UI,sans-serif;color:#1C2B1E;max-width:560px;line-height:1.55">
  <p>Oi, time! 👋 Aqui é o robô de plantão do S&OP.</p>
  <p>Não é trote: tem chopp querendo zerar nos próximos dias, e achei melhor avisar antes que vire vexame de torneira seca. 😬</p>
  <p style="margin-bottom:4px"><strong>Em estado de alerta agora:</strong></p>
  <ul style="margin-top:0;padding-left:18px;list-style:none">{itens}</ul>
  <p>Tradução pra ação: antecipar envase ou acionar chopp convidado — antes que alguém peça e a gente tenha que olhar pro chão.</p>
  <p>Projeção completa na dash 👉 <a href="{dash}" style="color:#1A3C2A">{dash}</a></p>
  <p style="font-size:12px;color:#888;font-style:italic">P.S.: esse email só pinga quando algo novo fica crítico (ou piora). Caixa quieta = chopp fluindo. 🍻</p>
  <p style="color:#666">— Robô S&OP, a serviço da Talita</p>
</div>"""
    return txt, html


def enviar(txt, html, dry):
    user = os.environ.get("GMAIL_USER")
    pwd = os.environ.get("GMAIL_APP_PASSWORD")
    dest = [e.strip() for e in os.environ.get("ALERT_RECIPIENTS", "").split(",") if e.strip()]

    if dry or not (user and pwd and dest):
        print("=== [DRY-RUN] email NAO enviado (faltam credenciais ou --dry-run) ===")
        print("Para:", dest or "(ALERT_RECIPIENTS vazio)")
        print("Assunto:", SUBJECT)
        print("-" * 60)
        print(txt)
        return

    msg = EmailMessage()
    msg["Subject"] = SUBJECT
    msg["From"] = user
    msg["To"] = ", ".join(dest)
    msg.set_content(txt)
    msg.add_alternative(html, subtype="html")
    with smtplib.SMTP("smtp.gmail.com", 587) as s:
        s.starttls()
        s.login(user, pwd)
        s.send_message(msg)
    print(f"[ok] email enviado para {len(dest)} destinatario(s).")


def main():
    dry = "--dry-run" in sys.argv
    model = load_json(MODEL_JSON, None)
    if not model:
        print("[erro] model.json nao encontrado — rode o generate.py antes.")
        sys.exit(1)

    grupos = model["grupos"]
    criticos = [g for g in grupos if grupos[g]["sev"] == "critico"]
    estado_ant = load_json(STATE_JSON, {})

    # quem e novo (nao estava critico) ou piorou
    novos_ou_pior = [
        g for g in criticos
        if g not in estado_ant or piorou(grupos[g], estado_ant[g])
    ]

    # estado a gravar = assinatura dos criticos atuais (recuperados somem)
    estado_novo = {
        g: {"stock": grupos[g]["stock"], "first_neg": grupos[g]["first_neg"],
            "zerada": grupos[g]["zerada"]}
        for g in criticos
    }

    if novos_ou_pior:
        print(f"[!] disparo de alerta — novo/pior: {novos_ou_pior} | todos criticos: {criticos}")
        txt, html = compor_email(model, criticos)
        enviar(txt, html, dry)   # se o envio falhar, levanta erro AQUI e o estado NAO e gravado
    else:
        print(f"[ok] sem novidade critica (criticos atuais: {criticos or 'nenhum'}). Nenhum email.")

    # so chega aqui se enviou com sucesso (ou nao precisou enviar)
    with open(STATE_JSON, "w", encoding="utf-8") as f:
        json.dump(estado_novo, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
