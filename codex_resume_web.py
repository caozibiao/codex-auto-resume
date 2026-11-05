#!/usr/bin/env python3
import json
import os
import subprocess
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "config.json"
config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
STATE_FILE = ROOT / "status.json"
ATTEMPT_LOG = ROOT / "attempts.log"
PORT = int(os.environ.get("CODEX_RESUME_PORT", "8765"))
COMPLETE_MARKER = "AUTORETRY_COMPLETE"
PROMPT = (
    "请从上次中断处继续执行原任务，完成所有剩余工作并进行必要验证。"
    "如果仍受额度限制、网络故障或有任何工作未完成，请说明阻碍后结束本次尝试，服务稍后会重试。"
    "只有原任务全部完成且验证通过时，才在最终回复最后单独输出一行 AUTORETRY_COMPLETE；"
    "未完成时绝对不要输出该标记。"
)

state_lock = threading.Lock()
config_lock = threading.Lock()
run_lock = threading.Lock()
wake = threading.Event()


def fresh_state():
    return {"enabled": True, "running": False, "completed": False, "attempts": 0,
            "last_attempt": None, "next_attempt": time.time(), "last_exit_code": None,
            "last_message": "服务已启动，等待首次尝试"}


def load_state():
    try:
        result = fresh_state()
        result.update(json.loads(STATE_FILE.read_text(encoding="utf-8")))
        result["running"] = False
        return result
    except Exception:
        return fresh_state()


state = load_state()


def save():
    temp = STATE_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(STATE_FILE)


def update(**changes):
    with state_lock:
        state.update(changes)
        save()


def save_config():
    temp = CONFIG_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(CONFIG_FILE)


def log(text):
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    with ATTEMPT_LOG.open("a", encoding="utf-8") as f:
        f.write(f"\n[{stamp}] {text}\n")


def attempt():
    if not run_lock.acquire(blocking=False):
        return
    try:
        with state_lock:
            if not state["enabled"] or state["completed"]:
                return
            state.update(running=True, attempts=state["attempts"] + 1,
                         last_attempt=datetime.now().astimezone().isoformat(timespec="seconds"),
                         last_message="正在尝试恢复任务")
            save()
        with config_lock:
            active = dict(config)
        interval = int(active.get("interval_seconds", 3600))
        command = [active["codex_bin"], "--ask-for-approval", "never", "exec", "--cd", active["workspace"],
                   "--sandbox", "workspace-write", "--skip-git-repo-check",
                   "resume", active["session_id"], PROMPT]
        try:
            result = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=55 * 60)
            output = result.stdout or "(没有输出)"
            log(output)
            if result.returncode == 0 and COMPLETE_MARKER in output:
                update(running=False, enabled=False, completed=True, next_attempt=None,
                       last_exit_code=0, last_message="任务已完成，自动重试已停止")
            else:
                update(running=False, next_attempt=time.time() + interval,
                       last_exit_code=result.returncode,
                       last_message=f"任务未确认完成，将在 {interval // 60} 分钟后重试")
        except subprocess.TimeoutExpired:
            log("执行超时")
            update(running=False, next_attempt=time.time() + interval, last_exit_code=124,
                   last_message=f"执行超时，将在 {interval // 60} 分钟后重试")
        except Exception as exc:
            log(f"启动失败：{exc}")
            update(running=False, next_attempt=time.time() + interval, last_exit_code=127,
                   last_message=f"启动失败，将在 {interval // 60} 分钟后重试")
    finally:
        run_lock.release()


def scheduler():
    while True:
        with state_lock:
            due = state["enabled"] and not state["completed"] and (
                state["next_attempt"] is None or state["next_attempt"] <= time.time())
        if due:
            attempt()
        wake.wait(5)
        wake.clear()


PAGE = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Codex 自动续跑</title><style>
:root{color-scheme:dark;--bg:#0b1020;--card:#151c30;--line:#2a3552;--muted:#9aa7c4;--green:#35d07f;--blue:#69a7ff}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#eef2ff;font:15px/1.55 system-ui}main{max-width:850px;margin:45px auto;padding:20px}.head{display:flex;justify-content:space-between;align-items:center;gap:16px}.pill{padding:7px 12px;border-radius:99px;background:#24304b}.pill.on{color:var(--green)}.card{margin-top:18px;padding:21px;border:1px solid var(--line);border-radius:16px;background:var(--card)}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.item{background:#0d1427;padding:14px;border-radius:10px}.label{font-size:11px;color:var(--muted);letter-spacing:.08em}.value{margin-top:5px;word-break:break-all}.actions{display:flex;gap:10px;margin-top:16px;flex-wrap:wrap}button{border:0;border-radius:9px;padding:10px 15px;background:var(--blue);color:#07101f;font-weight:650;cursor:pointer}button.alt{background:#293550;color:white}pre{max-height:350px;overflow:auto;white-space:pre-wrap;background:#080d19;padding:15px;border-radius:10px;color:#cbd5ec;font:12px/1.5 monospace}@media(max-width:600px){.grid{grid-template-columns:1fr}}
</style></head><body><main><div class="head"><div><h1>Codex 自动续跑</h1><div style="color:var(--muted)">5 小时额度恢复后，自动继续未完成任务</div></div><div id="badge" class="pill">读取中</div></div><section class="card"><div class="grid"><div class="item"><div class="label">会话 ID</div><div id="sid" class="value"></div></div><div class="item"><div class="label">状态</div><div id="msg" class="value"></div></div><div class="item"><div class="label">上次尝试</div><div id="last" class="value">—</div></div><div class="item"><div class="label">下次尝试</div><div id="next" class="value">—</div></div><div class="item"><div class="label">尝试次数</div><div id="count" class="value">0</div></div><div class="item"><div class="label">重试间隔</div><div id="interval" class="value"></div></div></div><div class="actions"><button onclick="act('retry')">立即重试</button><button class="alt" id="toggle" onclick="act('toggle')">暂停</button><button class="alt" onclick="act('reset')">重置完成状态</button></div></section><section class="card"><div class="label">设置（修改后无需重新安装）</div><div class="grid" style="margin-top:10px"><label class="item"><span class="label">会话 ID</span><input id="sessionInput" style="width:100%;margin-top:7px;padding:9px" /></label><label class="item"><span class="label">重试间隔（分钟）</span><input id="intervalInput" type="number" min="1" max="1440" style="width:100%;margin-top:7px;padding:9px" /></label><label class="item" style="grid-column:1/-1"><span class="label">任务目录</span><input id="workspaceInput" style="width:100%;margin-top:7px;padding:9px" /></label></div><div class="actions"><button onclick="saveSettings()">保存设置</button></div></section><section class="card"><div class="label">运行日志</div><pre id="log">暂无日志</pre></section></main><script>
const fmt=x=>x?new Date(x*1000).toLocaleString():'—';async function refresh(){const s=await(await fetch('/api/status')).json();sid.textContent=s.session_id;msg.textContent=s.last_message;last.textContent=s.last_attempt||'—';next.textContent=fmt(s.next_attempt);count.textContent=s.attempts;interval.textContent=s.interval_minutes+' 分钟';log.textContent=s.log||'暂无日志';badge.textContent=s.running?'运行中':s.completed?'已完成':s.enabled?'轮询中':'已暂停';badge.className='pill '+(s.enabled||s.completed?'on':'');toggle.textContent=s.enabled?'暂停':'恢复';if(document.activeElement!==sessionInput)sessionInput.value=s.session_id;if(document.activeElement!==workspaceInput)workspaceInput.value=s.workspace;if(document.activeElement!==intervalInput)intervalInput.value=s.interval_minutes}async function request(data){const r=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const out=await r.json();if(!r.ok)alert(out.error||'操作失败');return out}async function act(action){await request({action});refresh()}async function saveSettings(){const out=await request({action:'settings',session_id:sessionInput.value.trim(),workspace:workspaceInput.value.trim(),interval_minutes:Number(intervalInput.value)});if(out.ok){alert('设置已保存');refresh()}}refresh();setInterval(refresh,3000);
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urlparse(self.path).path == "/":
            return self.reply(200, PAGE.encode(), "text/html; charset=utf-8")
        if urlparse(self.path).path == "/api/status":
            with state_lock:
                data = dict(state)
            with config_lock:
                active = dict(config)
            data.update(session_id=active["session_id"], workspace=active["workspace"],
                        interval_minutes=int(active.get("interval_seconds", 3600)) // 60)
            try: data["log"] = ATTEMPT_LOG.read_text(encoding="utf-8")[-30000:]
            except Exception: data["log"] = ""
            return self.reply(200, json.dumps(data, ensure_ascii=False).encode(), "application/json")
        self.reply(404, b"not found", "text/plain")

    def do_POST(self):
        if urlparse(self.path).path != "/api/action":
            return self.reply(404, b"not found", "text/plain")
        if self.headers.get("Origin") not in (None, f"http://127.0.0.1:{PORT}"):
            return self.reply(403, b"forbidden", "text/plain")
        try:
            size = min(int(self.headers.get("Content-Length", 0)), 1024)
            payload = json.loads(self.rfile.read(size))
            action = payload.get("action")
            if action == "retry":
                update(enabled=True, completed=False, next_attempt=time.time(), last_message="已安排立即重试")
            elif action == "toggle":
                with state_lock: enabled = not state["enabled"]
                update(enabled=enabled, next_attempt=time.time() if enabled else None,
                       last_message="轮询已恢复" if enabled else "轮询已暂停")
            elif action == "reset":
                update(enabled=True, completed=False, next_attempt=time.time(), last_message="已重置，即将重试")
            elif action == "settings":
                session_id = str(payload.get("session_id", "")).strip()
                workspace = str(payload.get("workspace", "")).strip()
                minutes = int(payload.get("interval_minutes", 0))
                if not session_id or len(session_id) < 8:
                    raise ValueError("会话 ID 无效")
                if not os.path.isdir(workspace):
                    raise ValueError("任务目录不存在")
                if minutes < 1 or minutes > 1440:
                    raise ValueError("重试间隔必须在 1 到 1440 分钟之间")
                with config_lock:
                    config.update(session_id=session_id, workspace=workspace,
                                  interval_seconds=minutes * 60)
                    save_config()
                update(enabled=True, completed=False, next_attempt=time.time() + minutes * 60,
                       last_message="设置已保存")
            else: raise ValueError("unknown action")
            wake.set()
            self.reply(200, b'{"ok":true}', "application/json")
        except Exception as exc:
            self.reply(400, json.dumps({"error": str(exc)}).encode(), "application/json")

    def log_message(self, *_): pass


threading.Thread(target=scheduler, daemon=True).start()
print(f"Codex Resume: http://127.0.0.1:{PORT}", flush=True)
ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
