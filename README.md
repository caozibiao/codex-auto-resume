# Codex Auto Resume / Codex 自动续跑

A tiny macOS and Windows service that periodically resumes an unfinished Codex session. It includes a local web dashboard for status, logs, retry, pause, and resume controls.

一个轻量的 macOS / Windows 本地服务：定时恢复尚未完成的 Codex 会话，并提供网页控制台查看状态、日志、立即重试、暂停和恢复。

## The problem / 它解决什么问题

Long Codex tasks can stop after the five-hour usage allowance is exhausted. The allowance may recover later, but the interrupted task does not necessarily continue by itself. Codex Auto Resume keeps the original session ID and periodically asks that same session to continue from where it stopped.

Codex 长任务可能因为 5 小时额度耗尽而中断。额度恢复后，原任务不一定会自行继续。本工具保存原会话 ID，定时唤醒同一会话，从中断位置继续工作。

> This tool does not scrape account pages or bypass usage limits. It waits and retries through the normal Codex CLI after allowance becomes available.
>
> 本工具不会抓取账户页面，也不会绕过额度限制；它只会等待额度正常恢复后，通过 Codex CLI 重新尝试。

## Features / 功能

- Periodically resumes one specified Codex session / 定时恢复指定 Codex 会话
- Local dashboard at `http://127.0.0.1:8765` / 本地网页控制台
- Configurable retry interval / 可设置重试间隔
- Starts automatically after login on macOS and Windows / 登录系统后自动启动
- Stops only after explicit completion confirmation / 仅在任务明确完成后停止
- Uses the `workspace-write` sandbox / 使用 `workspace-write` 沙箱
- Uninstaller included / 附带卸载程序
- Settings can be changed from the dashboard without reinstalling / 可在页面修改配置，无需重新安装

## Requirements / 系统要求

- macOS or Windows 10/11
- ChatGPT/Codex desktop app installed and signed in
- Python 3; the installer also tries to locate the Python bundled with Codex
- The Mac must be powered on, signed in, and online for retries to run

## Quick Start: macOS / macOS 快速安装

1. Download this repository as a ZIP and extract it.
2. Right-click `install.command` and choose **Open**.
3. Enter the Codex session ID.
4. Enter the original task workspace. You can drag the folder into Terminal.
5. Enter a retry interval in minutes, or press Return to use 60 minutes.
6. The dashboard opens automatically at <http://127.0.0.1:8765>.

中文步骤：

1. 下载仓库 ZIP 并解压。
2. 右键点击 `install.command`，选择“打开”。
3. 输入 Codex 会话 ID。
4. 输入原任务所在目录；可以把文件夹直接拖进终端。
5. 输入重试间隔，直接回车默认为 60 分钟。
6. 安装完成后会自动打开 <http://127.0.0.1:8765>。

## Quick Start: Windows / Windows 快速安装

1. Download this repository as a ZIP and extract it.
2. Double-click `install-windows.bat`.
3. Enter the Codex session ID, original task folder, and retry interval.
4. The installer registers a Windows Scheduled Task and opens <http://127.0.0.1:8765>.

中文步骤：下载并解压 ZIP，双击 `install-windows.bat`，依次输入会话 ID、原任务目录和重试间隔。安装器会创建 Windows 计划任务，并自动打开控制页面。

Windows requires Python 3 in `PATH`. If Python is missing, install it from [python.org](https://www.python.org/downloads/windows/) and enable **Add Python to PATH** during installation.

## How completion works / 完成判断

Every retry asks Codex to continue the original task. Codex must output the following marker only after the task is genuinely complete and verified:

```text
AUTORETRY_COMPLETE
```

If the marker is absent—because of a usage limit, network problem, deployment failure, or unfinished work—the service schedules another retry.

只有当原任务确实完成并验证通过时，Codex 才会返回上述标记。额度不足、网络故障、部署失败或任务仍未完成时，服务会继续定时重试。

## Dashboard / 控制页面

The dashboard shows:

- Current state and session ID
- Previous and next attempt times
- Attempt count and logs
- Retry now, pause/resume, and reset controls
- Edit session ID, workspace, and retry interval without reinstalling

The server listens only on `127.0.0.1`; it is not directly exposed to the LAN or internet.

## Uninstall / 卸载

- macOS: right-click `uninstall.command`, choose **Open**, and confirm.
- Windows: double-click `uninstall-windows.bat`.

Both uninstallers stop the service and remove its program, configuration, state, and logs.

## Security notes / 安全说明

- The dashboard is local-only.
- Codex runs with the `workspace-write` sandbox.
- The tool does not use `--dangerously-bypass-approvals-and-sandbox`.
- Unattended runs cannot complete actions that require interactive approval; review the dashboard logs when necessary.

## Troubleshooting / 常见问题

### The page does not open / 页面打不开

Confirm the computer is logged in, then reopen `http://127.0.0.1:8765`. If another program uses port 8765, stop that program or launch the service with a different `CODEX_RESUME_PORT` environment value.

### It keeps retrying although Codex produced a response / 已有回复但仍在重试

A response is not the same as task completion. The service stops only when Codex confirms that all work is complete and outputs `AUTORETRY_COMPLETE`.

### The task needs approval / 任务需要人工授权

For safety, unattended runs use `--ask-for-approval never`. Complete approval-sensitive steps manually, then click **Retry now**.

### The computer was asleep / 电脑休眠了

Retries run only while the computer is awake and the user is logged in. After wake or the next login, the service continues from its saved state.

### The session or folder changed / 会话或目录填错了

Open the dashboard, edit the session ID or task directory in **Settings**, save, and click **Retry now**. Reinstallation is not required.

## License

[MIT](LICENSE)
