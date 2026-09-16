#!/usr/bin/env python3
"""AmneziaWG control service for Ubuntu Touch.

Brings tunnels up and down on request from the GUI. Binds to 127.0.0.1 only and
exposes nothing outwards. The set of actions is deliberately narrow: show
status, bring up, bring down, import a configuration, delete one. Arbitrary
commands cannot be run.
"""
import json
import os
import re
import subprocess
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CONF_DIR = "/etc/amnezia/amneziawg"
AWG = "/usr/local/bin/awg"
AWG_QUICK = "/usr/local/bin/awg-quick"
AWG_IMPORT = "/usr/local/bin/awg-import"
PORT = 8099

# A tunnel name is a network interface name, hence the restrictions.
NAME_RE = re.compile(r"^[A-Za-z0-9_=+.-]{1,15}$")

UI = r"""<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>AmneziaWG</title>
<style>
  :root { --bg:#f7f7f7; --card:#fff; --line:#e3e3e3; --text:#1a1a1a;
          --muted:#6b6b6b; --on:#0e8a3e; --off:#9a9a9a; --accent:#e95420; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#111; --card:#1c1c1c; --line:#2e2e2e; --text:#f1f1f1;
            --muted:#9a9a9a; --on:#35c46a; }
  }
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  body { margin:0; padding:16px; background:var(--bg); color:var(--text);
         font:16px/1.45 Ubuntu, system-ui, sans-serif; }
  h1 { font-size:20px; margin:4px 0 16px; font-weight:600; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px;
          padding:14px; margin-bottom:12px; }
  .row { display:flex; align-items:center; gap:12px; }
  .name { font-weight:600; font-size:17px; flex:1; word-break:break-all; }
  .dot { width:10px; height:10px; border-radius:50%; background:var(--off); flex:none; }
  .dot.on { background:var(--on); }
  .info { color:var(--muted); font-size:13px; margin-top:8px; white-space:pre-wrap;
          word-break:break-all; }
  button { font:inherit; border:0; border-radius:9px; padding:11px 18px;
           background:var(--accent); color:#fff; font-weight:600; }
  button.sec { background:transparent; color:var(--muted); border:1px solid var(--line); }
  button:disabled { opacity:.5; }
  textarea { width:100%; min-height:90px; border:1px solid var(--line); border-radius:9px;
             padding:10px; font:14px monospace; background:var(--bg); color:var(--text); }
  input[type=text] { width:100%; border:1px solid var(--line); border-radius:9px;
             padding:10px; font:inherit; background:var(--bg); color:var(--text); }
  .muted { color:var(--muted); font-size:14px; }
  .err { color:#c0392b; white-space:pre-wrap; font-size:14px; margin-top:8px; }
  .sp { height:8px; }
</style></head><body>
<h1>AmneziaWG</h1>
<div id="list"></div>

<div class="card">
  <div class="name">Добавить настройку</div>
  <div class="muted" style="margin:6px 0 10px">
    Вставьте ссылку <code>vpn://…</code> из приложения AmneziaVPN
    или содержимое файла <code>.conf</code>.
  </div>
  <textarea id="conf" placeholder="vpn://…"></textarea>
  <div class="sp"></div>
  <input type="text" id="cname" placeholder="имя туннеля (необязательно)">
  <div class="sp"></div>
  <button onclick="imp()">Добавить</button>
  <div class="err" id="imperr"></div>
</div>

<script>
async function api(path, opts) {
  const r = await fetch(path, opts || {});
  const t = await r.text();
  try { return JSON.parse(t); } catch (e) { return {error: t}; }
}
function esc(s){ return (s||'').replace(/[<>&]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;'}[c])); }

async function refresh() {
  const d = await api('/api/status');
  const el = document.getElementById('list');
  if (d.error) { el.innerHTML = '<div class="card err">' + esc(d.error) + '</div>'; return; }
  if (!d.tunnels.length) {
    el.innerHTML = '<div class="card muted">Пока нет ни одной настройки.</div>';
    return;
  }
  el.innerHTML = d.tunnels.map(t => `
    <div class="card">
      <div class="row">
        <span class="dot ${t.up ? 'on' : ''}"></span>
        <span class="name">${esc(t.name)}</span>
        <button onclick="toggle('${esc(t.name)}', ${t.up})">${t.up ? 'Отключить' : 'Подключить'}</button>
      </div>
      ${t.info ? '<div class="info">' + esc(t.info) + '</div>' : ''}
      ${t.up ? '' : '<div class="sp"></div><button class="sec" onclick="del(\'' + esc(t.name) + '\')">Удалить</button>'}
    </div>`).join('');
}

async function toggle(name, up) {
  document.querySelectorAll('button').forEach(b => b.disabled = true);
  const d = await api('/api/' + (up ? 'down' : 'up') + '?name=' + encodeURIComponent(name), {method:'POST'});
  if (d.error) alert(d.error);
  await refresh();
  document.querySelectorAll('button').forEach(b => b.disabled = false);
}

async function del(name) {
  if (!confirm('Удалить настройку «' + name + '»?')) return;
  await api('/api/delete?name=' + encodeURIComponent(name), {method:'POST'});
  refresh();
}

async function imp() {
  document.getElementById('imperr').textContent = '';
  const body = document.getElementById('conf').value.trim();
  if (!body) return;
  const name = document.getElementById('cname').value.trim();
  const d = await api('/api/import?name=' + encodeURIComponent(name),
                      {method:'POST', body: body});
  if (d.error) { document.getElementById('imperr').textContent = d.error; return; }
  document.getElementById('conf').value = '';
  document.getElementById('cname').value = '';
  refresh();
}

refresh();
setInterval(refresh, 4000);
</script>
</body></html>
"""


def run(args, stdin=None):
    try:
        p = subprocess.run(args, capture_output=True, text=True, input=stdin, timeout=60)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return 1, str(e)


def tunnels():
    out = []
    try:
        names = sorted(f[:-5] for f in os.listdir(CONF_DIR) if f.endswith(".conf"))
    except OSError:
        names = []
    code, shown = run([AWG, "show", "interfaces"])
    active = shown.split() if code == 0 else []
    for n in names:
        item = {"name": n, "up": n in active, "info": ""}
        if item["up"]:
            c, txt = run([AWG, "show", n])
            if c == 0:
                keep = []
                for line in txt.splitlines():
                    s = line.strip()
                    if s.startswith(("endpoint:", "latest handshake:", "transfer:")):
                        keep.append(s)
                item["info"] = "\n".join(keep)
        out.append(item)
    return out


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _name(self):
        q = urllib.parse.urlparse(self.path).query
        name = urllib.parse.parse_qs(q).get("name", [""])[0]
        return name if NAME_RE.match(name) else None

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, UI, "text/html; charset=utf-8")
        elif path == "/api/status":
            self._send(200, json.dumps({"tunnels": tunnels()}, ensure_ascii=False))
        else:
            self._send(404, json.dumps({"error": "no such endpoint"}))

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/api/up", "/api/down"):
            name = self._name()
            if not name:
                return self._send(400, json.dumps({"error": "invalid name"}))
            action = "up" if path.endswith("up") else "down"
            code, txt = run([AWG_QUICK, action, name])
            if code != 0:
                return self._send(500, json.dumps({"error": txt.strip()}, ensure_ascii=False))
            return self._send(200, json.dumps({"ok": True}))

        if path == "/api/delete":
            name = self._name()
            if not name:
                return self._send(400, json.dumps({"error": "invalid name"}))
            run([AWG_QUICK, "down", name])
            try:
                os.remove(os.path.join(CONF_DIR, name + ".conf"))
            except OSError as e:
                return self._send(500, json.dumps({"error": str(e)}, ensure_ascii=False))
            return self._send(200, json.dumps({"ok": True}))

        if path == "/api/import":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8", "replace")
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            name = q.get("name", [""])[0]
            args = [AWG_IMPORT, "/dev/stdin"]
            if name:
                if not NAME_RE.match(name):
                    return self._send(400, json.dumps({"error": "invalid name"}))
                args.append(name)
            code, txt = run(args, stdin=body)
            if code != 0:
                return self._send(400, json.dumps({"error": txt.strip()}, ensure_ascii=False))
            return self._send(200, json.dumps({"ok": True}))

        self._send(404, json.dumps({"error": "no such endpoint"}))


def main():
    if os.geteuid() != 0:
        print("this service must run as root", file=sys.stderr)
        sys.exit(1)
    os.makedirs(CONF_DIR, mode=0o700, exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    srv.serve_forever()


if __name__ == "__main__":
    main()
