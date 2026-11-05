#!/bin/zsh
set -e

BASE_DIR="${0:A:h}"
INSTALL_DIR="$HOME/Library/Application Support/CodexResume"
PLIST="$HOME/Library/LaunchAgents/com.codex.resume.web.plist"
LABEL="com.codex.resume.web"

print "\nCodex 自动续跑安装器\n"
read "SESSION_ID?请输入 Codex 会话 ID："
if [[ -z "$SESSION_ID" ]]; then
  print "会话 ID 不能为空。"
  read "?按回车退出…"
  exit 1
fi

read "WORKSPACE?请输入原任务目录（可把文件夹拖进窗口，默认 $HOME）："
WORKSPACE="${WORKSPACE:-$HOME}"
WORKSPACE="${WORKSPACE#\'}"; WORKSPACE="${WORKSPACE%\'}"

read "MINUTES?每隔多少分钟重试？（默认 60）："
MINUTES="${MINUTES:-60}"
if ! [[ "$MINUTES" == <-> ]] || (( MINUTES < 1 )); then
  print "重试分钟数必须是正整数。"
  read "?按回车退出…"
  exit 1
fi

CODEX_BIN="/Applications/ChatGPT.app/Contents/Resources/codex"
if [[ ! -x "$CODEX_BIN" ]]; then
  CODEX_BIN="$(command -v codex 2>/dev/null || true)"
fi
if [[ -z "$CODEX_BIN" || ! -x "$CODEX_BIN" ]]; then
  print "没有找到 Codex。请先安装并登录 ChatGPT/Codex 桌面版。"
  read "?按回车退出…"
  exit 1
fi

PYTHON_BIN="$(command -v python3 2>/dev/null || true)"
if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(find "$HOME/.cache/codex-runtimes" -path '*/python/bin/python3' -type f 2>/dev/null | head -n 1)"
fi
if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
  print "没有找到 Python 3。请先安装 Python 3 后重试。"
  read "?按回车退出…"
  exit 1
fi

mkdir -p "$INSTALL_DIR" "$HOME/Library/LaunchAgents"
/bin/cp "$BASE_DIR/codex_resume_web.py" "$INSTALL_DIR/codex_resume_web.py"

"$PYTHON_BIN" - "$INSTALL_DIR/config.json" "$SESSION_ID" "$WORKSPACE" "$MINUTES" "$CODEX_BIN" <<'PY'
import json, sys
path, session, workspace, minutes, codex = sys.argv[1:]
with open(path, "w", encoding="utf-8") as f:
    json.dump({"session_id": session, "workspace": workspace,
               "interval_seconds": int(minutes) * 60, "codex_bin": codex},
              f, ensure_ascii=False, indent=2)
PY

"$PYTHON_BIN" - "$PLIST" "$PYTHON_BIN" "$INSTALL_DIR/codex_resume_web.py" "$INSTALL_DIR" <<'PY'
import plistlib, sys
path, python, app, workdir = sys.argv[1:]
value = {
  "Label": "com.codex.resume.web",
  "ProgramArguments": [python, app],
  "WorkingDirectory": workdir,
  "RunAtLoad": True,
  "KeepAlive": True,
  "StandardOutPath": workdir + "/service.log",
  "StandardErrorPath": workdir + "/service-error.log",
  "ProcessType": "Background",
}
with open(path, "wb") as f: plistlib.dump(value, f)
PY

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
sleep 1
open "http://127.0.0.1:8765"
print "\n安装完成！控制页面：http://127.0.0.1:8765"
read "?按回车关闭安装器…"
