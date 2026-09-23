#!/usr/bin/env python3
import json, re, subprocess, threading, time, urllib.request
from pathlib import Path
_STARTED=False
_LOCK=threading.Lock()

def _presence():
    try:
        t=subprocess.check_output(["ioreg","-c","IOHIDSystem"],text=True,stderr=subprocess.DEVNULL,timeout=2)
        m=re.search(r'"HIDIdleTime"\s*=\s*(\d+)',t)
        return {"idle_seconds": round(int(m.group(1))/1_000_000_000,1) if m else None}
    except Exception:
        return {"idle_seconds":None}

def _log(data_dir,msg):
    try:
        p=Path(data_dir)/"logs"/"cloud-relay.log";p.parent.mkdir(parents=True,exist_ok=True)
        with p.open("a",encoding="utf-8") as f:f.write(time.strftime("%Y-%m-%d %H:%M:%S")+" "+msg+"\n")
    except Exception: pass

def _loop(get_snapshot,data_dir):
    cfgp=Path(data_dir)/"cloud_relay.json";delay=3.0;last=None
    while True:
        try:
            cfg=json.loads(cfgp.read_text(encoding="utf-8"));base=cfg["url"].rstrip("/");token=cfg["device_token"];interval=max(2.0,float(cfg.get("interval_s",3)))
            snap=get_snapshot() or {};snap["presence"]=_presence();snap["device_sent_at"]=time.time()
            data=json.dumps(snap,ensure_ascii=False,separators=(",",":")).encode()
            req=urllib.request.Request(base+"/api/device",data=data,method="POST",headers={"Authorization":"Bearer "+token,"Content-Type":"application/json","User-Agent":"BatteryGuard/0.4"})
            with urllib.request.urlopen(req,timeout=6) as r:
                if not 200<=r.status<300: raise RuntimeError("HTTP "+str(r.status))
            if last is not None:_log(data_dir,"cloud relay recovered");last=None
            delay=interval;time.sleep(interval)
        except Exception as e:
            msg=f"{type(e).__name__}: {e}"
            if msg!=last:_log(data_dir,"cloud relay error: "+msg);last=msg
            time.sleep(min(60,delay));delay=min(60,max(5,delay*2))

def start_cloud_relay(get_snapshot,data_dir):
    global _STARTED
    with _LOCK:
        if _STARTED:return False
        if not (Path(data_dir)/"cloud_relay.json").exists():return False
        threading.Thread(target=_loop,args=(get_snapshot,data_dir),daemon=True,name="battery-guard-cloud-relay").start()
        _STARTED=True
        return True
