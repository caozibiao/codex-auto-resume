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
STATE_FILE = ROOT / "status.json"
LOG_DIR = ROOT / "logs"
PORT = int(os.environ.get("CODEX_RESUME_PORT", "8765"))
COMPLETE_MARKER = "AUTORETRY_COMPLETE"
PROMPT = (
    "请从上次中断处继续执行原任务，完成所有剩余工作并进行必要验证。"
    "如果仍受额度限制、网络故障或有任何工作未完成，请说明阻碍后结束本次尝试，服务稍后会重试。"
    "只有原任务全部完成且验证通过时，才在最终回复最后单独输出一行 AUTORETRY_COMPLETE；"
    "未完成时绝对不要输出该标记。"
)
LOG_DIR.mkdir(parents=True, exist_ok=True)


def load_config():
    raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    if "tasks" not in raw:  # v1 single-session migration
        raw["tasks"] = [{
            "id": raw.pop("session_id"), "name": "Imported v1 task",
            "workspace": raw.pop("workspace"), "interval_seconds": raw.pop("interval_seconds", 3600),
            "enabled": True,
        }]
    raw.setdefault("default_workspace", str(Path.home()))
    raw.setdefault("default_interval_seconds", 3600)
    return raw


config = load_config()
config_lock = threading.RLock()
state_lock = threading.RLock()
run_lock = threading.Lock()
wake = threading.Event()


def blank_task_state():
    return {"running": False, "completed": False, "attempts": 0, "last_attempt": None,
            "next_attempt": time.time(), "last_exit_code": None, "last_message": "等待首次尝试"}


def load_state():
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        value = {"tasks": {}}
    value.setdefault("tasks", {})
    for task in config["tasks"]:
        value["tasks"].setdefault(task["id"], blank_task_state())
        value["tasks"][task["id"]]["running"] = False
    return value


state = load_state()


def atomic_json(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def save_config():
    atomic_json(CONFIG_FILE, config)


def save_state():
    atomic_json(STATE_FILE, state)


def task_config(session_id):
    with config_lock:
        return next((dict(x) for x in config["tasks"] if x["id"] == session_id), None)


def update_task_state(session_id, **changes):
    with state_lock:
        state["tasks"].setdefault(session_id, blank_task_state()).update(changes)
        save_state()


def task_log_path(session_id):
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_")
    return LOG_DIR / f"{safe}.log"


def append_log(session_id, text):
    with task_log_path(session_id).open("a", encoding="utf-8") as handle:
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        handle.write(f"\n[{stamp}] {text}\n")


def read_log(session_id):
    try:
        return task_log_path(session_id).read_text(encoding="utf-8")[-30000:]
    except Exception:
        return ""


def move_task_log(old_id, new_id):
    old_path, new_path = task_log_path(old_id), task_log_path(new_id)
    if old_path == new_path or not old_path.exists():
        return
    if new_path.exists():
        old_text = old_path.read_text(encoding="utf-8")
        with new_path.open("a", encoding="utf-8") as handle:
            handle.write(old_text)
        old_path.unlink()
    else:
        old_path.replace(new_path)


def attempt(session_id):
    if not run_lock.acquire(blocking=False):
        return
    try:
        task = task_config(session_id)
        if not task or not task.get("enabled"):
            return
        with state_lock:
            item = state["tasks"].setdefault(session_id, blank_task_state())
            if item.get("completed"):
                return
            item.update(running=True, attempts=item["attempts"] + 1,
                        last_attempt=datetime.now().astimezone().isoformat(timespec="seconds"),
                        last_message="正在尝试恢复")
            save_state()
        interval = int(task.get("interval_seconds", 3600))
        command = [config["codex_bin"], "--ask-for-approval", "never", "exec", "--cd", task["workspace"],
                   "--sandbox", "workspace-write", "--skip-git-repo-check", "resume", session_id, PROMPT]
        try:
            result = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=55 * 60)
            output = result.stdout or "(没有输出)"
            append_log(session_id, output)
            if result.returncode == 0 and COMPLETE_MARKER in output:
                with config_lock:
                    live = next((x for x in config["tasks"] if x["id"] == session_id), None)
                    if live: live["enabled"] = False
                    save_config()
                update_task_state(session_id, running=False, completed=True, next_attempt=None,
                                  last_exit_code=0, last_message="任务已完成，自动重试已停止")
            else:
                update_task_state(session_id, running=False, next_attempt=time.time() + interval,
                                  last_exit_code=result.returncode,
                                  last_message=f"尚未确认完成，{interval // 60} 分钟后重试")
        except subprocess.TimeoutExpired:
            append_log(session_id, "执行超时")
            update_task_state(session_id, running=False, next_attempt=time.time() + interval,
                              last_exit_code=124, last_message=f"执行超时，{interval // 60} 分钟后重试")
        except Exception as exc:
            append_log(session_id, f"启动失败：{exc}")
            update_task_state(session_id, running=False, next_attempt=time.time() + interval,
                              last_exit_code=127, last_message=f"启动失败，{interval // 60} 分钟后重试")
    finally:
        run_lock.release()


def scheduler():
    while True:
        due = []
        with config_lock, state_lock:
            for task in config["tasks"]:
                item = state["tasks"].setdefault(task["id"], blank_task_state())
                if task.get("enabled") and not item.get("completed") and not item.get("running"):
                    if item.get("next_attempt") is None or item["next_attempt"] <= time.time():
                        due.append(task["id"])
        for session_id in due:
            attempt(session_id)
        wake.wait(5)
        wake.clear()


def discover_sessions():
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    index = home / "session_index.jsonl"
    found = {}
    try:
        for line in index.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("id"):
                found[row["id"]] = {"id": row["id"], "name": row.get("thread_name") or row["id"],
                                        "updated_at": row.get("updated_at")}
    except Exception:
        return []
    return sorted(found.values(), key=lambda x: x.get("updated_at") or "", reverse=True)[:500]


def merged_tasks():
    result = []
    with config_lock, state_lock:
        for task in config["tasks"]:
            item = dict(task)
            item.update(state["tasks"].setdefault(task["id"], blank_task_state()))
            item["interval_minutes"] = int(task.get("interval_seconds", 3600)) // 60
            result.append(item)
    return result


PAGE = r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Codex Auto Resume</title><style>
:root{color-scheme:dark;--bg:#0b1020;--card:#151c30;--line:#2a3552;--muted:#9aa7c4;--green:#35d07f;--blue:#69a7ff;--red:#ff7280}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 20% 0,#17264a 0,transparent 40%),var(--bg);color:#eef2ff;font:15px/1.5 system-ui}main{max-width:1050px;margin:38px auto;padding:20px}.head,.row{display:flex;justify-content:space-between;align-items:center;gap:14px}.card{margin-top:16px;padding:18px;border:1px solid var(--line);border-radius:16px;background:#151c30e8}.task{background:#0d1427;border-radius:12px;padding:15px;margin-top:12px}.meta{color:var(--muted);font-size:12px;word-break:break-all}.pill{padding:6px 10px;border-radius:99px;background:#25304d;color:var(--muted)}.pill.on{color:var(--green)}button{border:0;border-radius:9px;padding:9px 13px;background:var(--blue);color:#07101f;font-weight:650;cursor:pointer}button.alt{background:#293550;color:white}button.red{background:#49242d;color:#ffb7be}input{width:100%;padding:9px;margin-top:5px}.grid{display:grid;grid-template-columns:2fr 1fr;gap:10px}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}pre{max-height:260px;overflow:auto;white-space:pre-wrap;background:#080d19;padding:13px;border-radius:10px;font:12px/1.5 monospace}.hidden{display:none}@media(max-width:650px){.head,.row{align-items:flex-start;flex-direction:column}.grid{grid-template-columns:1fr}}</style></head><body><main>
<div class="head"><div><h1 style="margin:0">Codex 自动续跑</h1><div class="meta">一个、多个，或导入本机所有会话；只有启用的任务会自动执行</div></div><button onclick="discover()">导入本机会话</button></div>
<section class="card"><div class="row"><b>任务列表</b><div class="actions" style="margin:0"><button class="alt" onclick="toggleAll(true)">全部启用</button><button class="alt" onclick="toggleAll(false)">全部暂停</button><button onclick="showAdd()">＋ 添加会话</button></div></div><div id="tasks"></div></section>
<section id="formCard" class="card hidden"><b id="formTitle">添加会话</b><div class="grid" style="margin-top:10px"><label>名称<input id="nameInput"></label><label>间隔（分钟）<input id="minutesInput" type="number" min="1" max="1440" value="60"></label><label style="grid-column:1/-1">会话 ID<input id="idInput"></label><label style="grid-column:1/-1">任务目录<input id="workspaceInput"></label></div><div class="actions"><button onclick="saveTask()">保存</button><button class="alt" onclick="hideForm()">取消</button></div></section>
<section id="logCard" class="card hidden"><div class="row"><b id="logTitle">日志</b><button class="alt" onclick="logCard.classList.add('hidden')">关闭</button></div><pre id="logText"></pre></section>
</main><script>
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const fmt=x=>x?new Date(x*1000).toLocaleString():'—';let current=null,cache=[];
async function api(data){const r=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const o=await r.json();if(!r.ok)alert(o.error||'操作失败');return o}
async function refresh(){const s=await(await fetch('/api/status')).json();cache=s.tasks;tasks.innerHTML=s.tasks.length?s.tasks.map(t=>`<div class="task"><div class="row"><div><b>${esc(t.name||t.id)}</b><div class="meta">${esc(t.id)} · ${esc(t.workspace)}</div></div><span class="pill ${t.running||t.enabled?'on':''}">${t.running?'运行中':t.completed?'已完成':t.enabled?'等待中':'已暂停'}</span></div><div class="meta" style="margin-top:8px">${esc(t.last_message)} · 尝试 ${t.attempts} 次 · 下次 ${fmt(t.next_attempt)}</div><div class="actions"><button onclick="act('retry','${t.id}')">立即重试</button><button class="alt" onclick="act('toggle','${t.id}')">${t.enabled?'暂停':'启用'}</button><button class="alt" onclick="editTask('${t.id}')">设置</button><button class="alt" onclick="showLog('${t.id}')">日志</button><button class="red" onclick="removeTask('${t.id}')">删除</button></div></div>`).join(''):'<div class="meta" style="margin-top:15px">暂无任务，点击“添加会话”或“导入本机会话”。</div>'}
async function act(action,id){await api({action,id});refresh()}async function toggleAll(enabled){await api({action:'toggle_all',enabled});refresh()}function showAdd(){current=null;formTitle.textContent='添加会话';nameInput.value='';idInput.value='';workspaceInput.value='';minutesInput.value=60;formCard.classList.remove('hidden')}function editTask(id){current=id;const t=cache.find(x=>x.id===id);formTitle.textContent='编辑会话';nameInput.value=t.name||'';idInput.value=t.id;workspaceInput.value=t.workspace;minutesInput.value=t.interval_minutes;formCard.classList.remove('hidden')}function hideForm(){formCard.classList.add('hidden')}async function saveTask(){const newId=idInput.value.trim();const o=await api({action:current?'edit':'add',id:current||newId,new_id:newId,name:nameInput.value.trim(),workspace:workspaceInput.value.trim(),interval_minutes:Number(minutesInput.value)});if(o.ok){hideForm();refresh()}}async function removeTask(id){if(confirm('删除这个自动续跑任务？不会删除原 Codex 会话。')){await api({action:'remove',id});refresh()}}async function showLog(id){const s=await(await fetch('/api/log?id='+encodeURIComponent(id))).json();logTitle.textContent='日志 · '+id;logText.textContent=s.log||'暂无日志';logCard.classList.remove('hidden')}async function discover(){const o=await api({action:'import_all'});alert(`已导入 ${o.imported} 个新会话。为安全起见，新导入任务默认暂停。`);refresh()}refresh();setInterval(refresh,4000);
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, value, content_type="application/json"):
        body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status); self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            return self.reply(200, PAGE.encode(), "text/html; charset=utf-8")
        if parsed.path == "/api/status":
            return self.reply(200, {"tasks": merged_tasks()})
        if parsed.path == "/api/log":
            from urllib.parse import parse_qs
            session_id = parse_qs(parsed.query).get("id", [""])[0]
            return self.reply(200, {"log": read_log(session_id)})
        self.reply(404, {"error": "not found"})

    def do_POST(self):
        if urlparse(self.path).path != "/api/action": return self.reply(404, {"error": "not found"})
        if self.headers.get("Origin") not in (None, f"http://127.0.0.1:{PORT}"):
            return self.reply(403, {"error": "forbidden"})
        try:
            size = min(int(self.headers.get("Content-Length", 0)), 100000)
            payload = json.loads(self.rfile.read(size)); action = payload.get("action"); session_id = payload.get("id")
            if action in ("add", "edit"):
                new_id = str(payload.get("new_id") or session_id or "").strip()
                name = str(payload.get("name") or new_id).strip(); workspace = str(payload.get("workspace", "")).strip()
                minutes = int(payload.get("interval_minutes", 0))
                if len(new_id) < 8: raise ValueError("会话 ID 无效")
                if not os.path.isdir(workspace): raise ValueError("任务目录不存在")
                if minutes < 1 or minutes > 1440: raise ValueError("重试间隔应为 1–1440 分钟")
                with config_lock, state_lock:
                    existing = next((x for x in config["tasks"] if x["id"] == session_id), None)
                    duplicate = next((x for x in config["tasks"] if x["id"] == new_id and x is not existing), None)
                    if action == "add" and (existing or duplicate): raise ValueError("该会话已经存在")
                    if action == "edit" and not existing: raise ValueError("原会话不存在，请刷新页面后重试")
                    if duplicate: raise ValueError("新的会话 ID 已经存在")
                    if action == "edit" and session_id != new_id:
                        old_state = state["tasks"].get(session_id, blank_task_state())
                        if old_state.get("running"):
                            raise ValueError("任务正在运行，请等待本次执行结束后再修改会话 ID")
                        existing["id"] = new_id
                        state["tasks"].pop(session_id, None)
                        state["tasks"][new_id] = old_state
                        move_task_log(session_id, new_id)
                    if existing: existing.update(name=name, workspace=workspace, interval_seconds=minutes * 60)
                    else: config["tasks"].append({"id": new_id, "name": name, "workspace": workspace,
                                                   "interval_seconds": minutes * 60, "enabled": False})
                    save_config()
                    state["tasks"].setdefault(new_id, blank_task_state()).update(
                        completed=False, next_attempt=time.time() + minutes * 60)
                    save_state()
            elif action == "remove":
                with config_lock:
                    config["tasks"] = [x for x in config["tasks"] if x["id"] != session_id]; save_config()
                with state_lock: state["tasks"].pop(session_id, None); save_state()
            elif action == "toggle":
                with config_lock:
                    task = next(x for x in config["tasks"] if x["id"] == session_id)
                    task["enabled"] = not task.get("enabled"); save_config()
                if task["enabled"]: update_task_state(session_id, completed=False, next_attempt=time.time())
            elif action == "retry":
                with config_lock:
                    task = next(x for x in config["tasks"] if x["id"] == session_id); task["enabled"] = True; save_config()
                update_task_state(session_id, completed=False, next_attempt=time.time())
            elif action == "toggle_all":
                enabled = bool(payload.get("enabled"))
                with config_lock:
                    for task in config["tasks"]: task["enabled"] = enabled
                    save_config()
                if enabled:
                    for task in config["tasks"]: update_task_state(task["id"], completed=False, next_attempt=time.time())
            elif action == "import_all":
                known = {x["id"] for x in config["tasks"]}; imported = 0
                with config_lock:
                    for found in discover_sessions():
                        if found["id"] not in known:
                            config["tasks"].append({"id": found["id"], "name": found["name"],
                              "workspace": config["default_workspace"], "interval_seconds": config["default_interval_seconds"],
                              "enabled": False}); known.add(found["id"]); imported += 1
                    save_config()
                for task in config["tasks"]: update_task_state(task["id"])
                wake.set(); return self.reply(200, {"ok": True, "imported": imported})
            else: raise ValueError("unknown action")
            wake.set(); self.reply(200, {"ok": True})
        except Exception as exc:
            self.reply(400, {"error": str(exc)})

    def log_message(self, *_): pass


threading.Thread(target=scheduler, daemon=True).start()
print(f"Codex Auto Resume: http://127.0.0.1:{PORT}", flush=True)
ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
