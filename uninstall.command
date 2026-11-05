#!/bin/zsh
set -e
LABEL="com.codex.resume.web"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
INSTALL_DIR="$HOME/Library/Application Support/CodexResume"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
[[ -f "$PLIST" ]] && /bin/rm "$PLIST"
[[ -d "$INSTALL_DIR" ]] && /bin/rm -R "$INSTALL_DIR"
print "Codex 自动续跑服务已卸载。"
read "?按回车关闭…"
