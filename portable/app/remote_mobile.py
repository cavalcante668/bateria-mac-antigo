#!/usr/bin/env python3
import json
import re
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_STARTED = False
_LOCK = threading.Lock()
_GET = None
_DATA_DIR = None
_PUSH_STATE = {}

HTML = r"""<!doctype html>
<html lang="pt-BR"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#111318"><link rel="manifest" href="/manifest.webmanifest">
<title>Battery Guard</title>
<style>
:root{color-scheme:dark;--bg:#0d0f13;--card:#171a20;--line:#2a303a;--text:#f6f7f9;--muted:#9aa4b2;--ok:#63d297;--warn:#ffd166;--bad:#ff6b6b;--crit:#ff3b30}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text",sans-serif}main{max-width:760px;margin:auto;padding:calc(env(safe-area-inset-top) + 18px) 14px calc(env(safe-area-inset-bottom) + 24px)}header{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:14px}h1{font-size:24px;margin:0}.sub{font-size:12px;color:var(--muted)}.badge{border:1px solid var(--line);border-radius:999px;background:var(--card);padding:8px 10px;font-size:12px;white-space:nowrap}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.card{background:var(--card);border:1px solid var(--line);border-radius:17px;padding:14px;min-width:0}.wide{grid-column:1/-1}.label{font-size:12px;color:var(--muted);margin-bottom:7px}.value{font-size:25px;font-weight:750;letter-spacing:-.03em}.small{font-size:18px;font-weight:650}.row{display:flex;justify-content:space-between;gap:10px;border-bottom:1px solid var(--line);padding:8px 0;font-size:14px}.row:last-child{border-bottom:0}.row span:first-child{color:var(--muted)}.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}.crit{color:var(--crit)}.bar{height:8px;border-radius:20px;background:#242a33;overflow:hidden;margin-top:9px}.bar>div{height:100%;background:currentColor;width:0}.apps{display:grid;gap:4px}.app{display:flex;justify-content:space-between;gap:10px;padding:8px 0;border-bottom:1px solid var(--line)}.app:last-child{border-bottom:0}.appname{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.appmeta{font-size:11px;color:var(--muted);margin-top:2px}button{width:100%;padding:12px;border:1px solid var(--line);border-radius:13px;background:#20252e;color:var(--text);font-size:14px}.footer{text-align:center;font-size:11px;color:var(--muted);margin-top:14px;line-height:1.5}@media(min-width:650px){.grid{grid-template-columns:repeat(4,minmax(0,1fr))}.span2{grid-column:span 2}}
</style></head><body><main>
<header><div><h1>Battery Guard</h1><div class="sub" id="headline">Conectando…</div></div><div class="badge" id="online">● CONECTANDO</div></header>
<section class="grid">
<div class="card span2"><div class="label">Bateria</div><div class="value" id="percent">—</div><div class="bar"><div id="pbar"></div></div></div>
<div class="card span2"><div class="label">Risco elétrico</div><div class="value" id="risk">—</div><div class="sub" id="riskLabel">—</div></div>
<div class="card"><div class="label">C1</div><div class="small" id="c1">—</div></div>
<div class="card"><div class="label">Δ células</div><div class="small" id="delta">—</div></div>
<div class="card"><div class="label">Corrente</div><div class="small" id="amps">—</div></div>
<div class="card"><div class="label">Potência</div><div class="small" id="watts">—</div></div>
<div class="card wide"><div class="label">Estado elétrico</div><div class="row"><span>C1 projetada @2 A</span><strong id="proj">—</strong></div><div class="row"><span>Pico recente</span><strong id="peak">—</strong></div><div class="row"><span>Stress hold</span><strong id="hold">—</strong></div><div class="row"><span>Energia útil</span><strong id="useful">—</strong></div><div class="row"><span>Temperatura</span><strong id="temp">—</strong></div></div>
<div class="card wide"><div class="label">Mac</div><div class="row"><span>CPU</span><strong id="cpu">—</strong></div><div class="row"><span>RAM</span><strong id="ram">—</strong></div><div class="row"><span>Primeiro plano</span><strong id="fg">—</strong></div><div class="row"><span>Sem interação</span><strong id="idle">—</strong></div><div class="row"><span>Tampa</span><strong id="lid">—</strong></div></div>
<div class="card wide"><div class="label">Maior atividade</div><div class="apps" id="apps"><div class="sub">Aguardando telemetria…</div></div></div>
<div class="card wide"><button id="notify">Ativar alertas neste celular</button><div class="sub" style="margin-top:8px">Alertas do navegador funcionam enquanto o painel/PWA estiver ativo.</div></div>
</section><div class="footer"><div id="last">Nenhuma leitura recebida.</div><div>Acesso privado recomendado: Tailscale Serve.</div></div>
</main><script>
const $=x=>document.getElementById(x);let last=0,lastBand='';let es;
function n(v,d=0){return v==null?'—':Number(v).toFixed(d)}function mv(v){return v==null?'—':(Number(v)/1000).toFixed(3)+' V'}function ma(v){return v==null?'—':(Number(v)/1000).toFixed(2)+' A'}function w(v){return v==null?'—':Number(v).toFixed(1)+' W'}function sec(v){if(v==null)return'—';v=Number(v);if(v<60)return Math.round(v)+' s';if(v<3600)return Math.round(v/60)+' min';return(v/3600).toFixed(1)+' h'}
function cls(r){r=Number(r||0);return r>=90?'crit':r>=70?'bad':r>=25?'warn':'ok'}function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]))}
function phoneNotify(b){if(!('Notification'in window)||Notification.permission!=='granted')return;let r=Number(b.shutdown_risk||0),band=r>=90?'e':r>=70?'c':'';if(!band||band===lastBand)return;lastBand=band;try{new Notification(r>=90?'Battery Guard — emergência':'Battery Guard — risco crítico',{body:`${b.percent??'—'}% · C1 ${mv(b.c1)} · Δ ${b.delta??'—'} mV · risco ${r}/100`})}catch(e){}}
function render(x){let b=x.battery||{},s=x.system||{};last=Date.now();localStorage.setItem('bg_last',JSON.stringify({x,t:last}));$('online').textContent='● ONLINE';$('online').className='badge ok';$('headline').textContent=b.external?'Na fonte':'Na bateria';$('percent').textContent=b.percent==null?'—':b.percent+'%';$('pbar').style.width=Math.max(0,Math.min(100,Number(b.percent||0)))+'%';$('pbar').parentElement.style.color=Number(b.percent||0)<=20?'var(--bad)':'var(--ok)';$('risk').textContent=b.shutdown_risk==null?'—':b.shutdown_risk+'/100';$('risk').className='value '+cls(b.shutdown_risk);$('riskLabel').textContent=b.electrical_risk_level||b.shutdown_risk_label||b.status||'—';$('c1').textContent=mv(b.c1);$('delta').textContent=b.delta==null?'—':b.delta+' mV';$('amps').textContent=ma(b.instant_ma??b.current_ma);$('watts').textContent=w(b.instant_power_w??b.avg_power_w);$('proj').textContent=mv(b.c1_projected_2a_mv);$('peak').textContent=(b.recent_peak_ma==null?'—':ma(b.recent_peak_ma))+(b.recent_peak_power_w==null?'':' · '+w(b.recent_peak_power_w));$('hold').textContent=sec(b.stress_hold_remaining_s);$('useful').textContent=b.useful_energy_percent==null?'—':n(b.useful_energy_percent)+'%';$('temp').textContent=b.temperature==null?'—':n(b.temperature,1)+' °C';$('cpu').textContent=s.cpu_pct==null?'—':n(s.cpu_pct,1)+'%';$('ram').textContent=s.ram_used_pct==null?'—':n(s.ram_used_pct,1)+'%';$('fg').textContent=s.foreground_app||'—';$('idle').textContent=sec(x.presence&&x.presence.idle_seconds);$('lid').textContent=x.presence&&x.presence.clamshell_closed===true?'Fechada':x.presence&&x.presence.clamshell_closed===false?'Aberta':'—';let a=Array.isArray(s.apps)?s.apps.slice(0,6):[];$('apps').innerHTML=a.length?a.map(v=>`<div class="app"><div><div class="appname">${esc(v.app_name||'Processo')}</div><div class="appmeta">${n(v.cpu_pct,1)}% CPU · ${n(v.memory_pct,1)}% RAM</div></div><strong>${esc(v.impact_label||'')}</strong></div>`).join(''):'<div class="sub">Sem dados.</div>';phoneNotify(b)}
function connect(){if(es)es.close();es=new EventSource('/api/stream');es.onmessage=e=>{try{render(JSON.parse(e.data))}catch(_){}};es.onerror=()=>{$('online').textContent='● RECONECTANDO';$('online').className='badge warn'}}
$('notify').onclick=async()=>{if(!('Notification'in window)){ $('notify').textContent='Não suportado';return }let p=await Notification.requestPermission();$('notify').textContent=p==='granted'?'Alertas ativados':'Permissão não concedida'};
setInterval(()=>{let a=last?(Date.now()-last)/1000:null;$('last').textContent=a==null?'Nenhuma leitura recebida.':'Última atualização há '+sec(a)+'.';if(a!=null&&a>15){$('online').textContent='● OFFLINE / REPOUSO';$('online').className='badge bad'}},1000);
try{let z=JSON.parse(localStorage.getItem('bg_last')||'null');if(z&&z.x)render(z.x)}catch(_){}if('serviceWorker'in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>{});connect();
</script></body></html>"""

MANIFEST = {"name":"Battery Guard","short_name":"Battery Guard","start_url":"/mobile","display":"standalone","background_color":"#0d0f13","theme_color":"#111318","icons":[{"src":"/icon.svg","sizes":"any","type":"image/svg+xml","purpose":"any maskable"}]}
SW = r"""const C="bg-mobile-v1",S=["/mobile","/manifest.webmanifest","/icon.svg"];self.addEventListener("install",e=>e.waitUntil(caches.open(C).then(c=>c.addAll(S)).then(()=>self.skipWaiting())));self.addEventListener("activate",e=>e.waitUntil(self.clients.claim()));self.addEventListener("fetch",e=>{const u=new URL(e.request.url);if(u.pathname.startsWith("/api/"))return;e.respondWith(fetch(e.request).catch(()=>caches.match(e.request).then(r=>r||caches.match("/mobile"))))});"""
ICON = r"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"><rect width="256" height="256" rx="56" fill="#111318"/><rect x="43" y="71" width="155" height="114" rx="19" fill="none" stroke="#f5f7fa" stroke-width="15"/><rect x="204" y="105" width="16" height="46" rx="7" fill="#f5f7fa"/><path d="M83 139h31l14-36 20 57 13-27h20" fill="none" stroke="#63d297" stroke-width="13" stroke-linecap="round" stroke-linejoin="round"/></svg>"""

def presence():
    out={"idle_seconds":None,"clamshell_closed":None}
    try:
        t=subprocess.check_output(["ioreg","-c","IOHIDSystem"],text=True,stderr=subprocess.DEVNULL,timeout=2)
        m=re.search(r'"HIDIdleTime"\s*=\s*(\d+)',t)
        if m: out["idle_seconds"]=round(int(m.group(1))/1_000_000_000,1)
    except Exception: pass
    try:
        t=subprocess.check_output(["ioreg","-r","-k","AppleClamshellState","-d","4"],text=True,stderr=subprocess.DEVNULL,timeout=2)
        if '"AppleClamshellState" = Yes' in t: out["clamshell_closed"]=True
        elif '"AppleClamshellState" = No' in t: out["clamshell_closed"]=False
    except Exception: pass
    return out

def snapshot():
    try: d=_GET() or {}
    except Exception: d={}
    if not isinstance(d,dict): d={}
    d["server_time"]=time.time(); d["presence"]=presence(); return d

def jb(x): return json.dumps(x,ensure_ascii=False,separators=(",",":")).encode()

class H(BaseHTTPRequestHandler):
    protocol_version="HTTP/1.1"
    def log_message(self,*a): return
    def sendb(self,code,body,ctype="text/plain; charset=utf-8",cache="no-store"):
        if isinstance(body,str): body=body.encode()
        self.send_response(code); self.send_header("Content-Type",ctype); self.send_header("Content-Length",str(len(body))); self.send_header("Cache-Control",cache); self.send_header("X-Content-Type-Options","nosniff"); self.send_header("X-Frame-Options","DENY"); self.send_header("Referrer-Policy","no-referrer"); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        p=self.path.split("?",1)[0]
        if p=="/": self.send_response(302); self.send_header("Location","/mobile"); self.send_header("Content-Length","0"); self.end_headers(); return
        if p=="/mobile": return self.sendb(200,HTML,"text/html; charset=utf-8","no-cache")
        if p=="/manifest.webmanifest": return self.sendb(200,jb(MANIFEST),"application/manifest+json; charset=utf-8","public, max-age=300")
        if p=="/sw.js": return self.sendb(200,SW,"application/javascript; charset=utf-8","no-cache")
        if p=="/icon.svg": return self.sendb(200,ICON,"image/svg+xml; charset=utf-8","public, max-age=86400")
        if p=="/api/current": return self.sendb(200,jb(snapshot()),"application/json; charset=utf-8")
        if p=="/api/health":
            x=snapshot(); b=x.get("battery") or {}; return self.sendb(200,jb({"ok":True,"server_time":x.get("server_time"),"status":b.get("status"),"electrical_risk_level":b.get("electrical_risk_level"),"battery_percent":b.get("percent")}),"application/json; charset=utf-8")
        if p=="/api/stream":
            self.send_response(200); self.send_header("Content-Type","text/event-stream; charset=utf-8"); self.send_header("Cache-Control","no-cache"); self.send_header("Connection","keep-alive"); self.end_headers()
            try:
                while True:
                    frame=("data: "+jb(snapshot()).decode()+"\n\n").encode(); self.wfile.write(frame); self.wfile.flush(); time.sleep(1)
            except (BrokenPipeError,ConnectionResetError,OSError): return
        return self.sendb(404,"Not found\n")

class S(ThreadingHTTPServer):
    daemon_threads=True; allow_reuse_address=True

def _load_remote_config():
    if _DATA_DIR is None: return {}
    try:
        return json.loads((_DATA_DIR / "remote_dashboard.json").read_text(encoding="utf-8"))
    except Exception:
        return {}

def _push(kind,title,body,priority=3,cooldown=900):
    cfg=_load_remote_config()
    if not cfg.get("push_enabled"): return False
    topic=cfg.get("ntfy_topic")
    server=(cfg.get("ntfy_server") or "https://ntfy.sh").rstrip("/")
    if not topic: return False
    now=time.time(); last=_PUSH_STATE.get(kind,0)
    if now-last<cooldown: return False
    try:
        req=urllib.request.Request(
            server+"/"+topic,
            data=body.encode("utf-8"),
            method="POST",
            headers={
                "Title": title,
                "Priority": str(priority),
                "Tags": "battery",
                "Content-Type": "text/plain; charset=utf-8",
            },
        )
        with urllib.request.urlopen(req,timeout=8) as r: r.read(1)
        _PUSH_STATE[kind]=now
        return True
    except Exception:
        return False

def _alert_loop():
    while True:
        try:
            x=snapshot(); b=x.get("battery") or {}; pr=x.get("presence") or {}
            if not b.get("external"):
                risk=int(b.get("shutdown_risk") or 0)
                pct=b.get("percent")
                c1=b.get("c1")
                delta=b.get("delta")
                power=b.get("instant_power_w")
                if power is None: power=b.get("avg_power_w")
                idle=float(pr.get("idle_seconds") or 0)
                def summary():
                    parts=[]
                    if pct is not None: parts.append(f"Bateria {pct}%")
                    if c1 is not None: parts.append(f"C1 {int(c1)} mV")
                    if delta is not None: parts.append(f"Δ {int(delta)} mV")
                    if power is not None: parts.append(f"{float(power):.1f} W")
                    if risk: parts.append(f"risco {risk}/100")
                    return " · ".join(parts)
                if risk>=90:
                    _push("emergency","Battery Guard — emergência elétrica",summary(),5,300)
                elif risk>=70:
                    _push("critical","Battery Guard — risco crítico",summary(),4,900)
                elif pct is not None and float(pct)<=20:
                    _push("low","Battery Guard — bateria fraca",summary(),4,1200)
                elif idle>=600 and power is not None and abs(float(power))>=12:
                    _push("away","Battery Guard — Mac drenando sem uso",summary()+f" · sem interação há {int(idle/60)} min",4,900)
        except Exception:
            pass
        time.sleep(10)

def start_remote_server(get_snapshot,port=8766,data_dir=None):
    global _STARTED,_GET,_DATA_DIR
    with _LOCK:
        if _STARTED: return False
        _GET=get_snapshot
        _DATA_DIR=Path(data_dir) if data_dir else None
        server=S(("127.0.0.1",int(port)),H)
        threading.Thread(target=server.serve_forever,name="battery-guard-remote",daemon=True).start()
        threading.Thread(target=_alert_loop,name="battery-guard-remote-alerts",daemon=True).start()
        _STARTED=True
        return True
