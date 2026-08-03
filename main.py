import os
import sys
import time
import threading
from nicegui import ui, app
import requests as _r

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(PROJECT_DIR, ".env")

# ── 日志初始化（最早执行）───────────────────────────────────────────────────────
from utils.logging_config import setup_logging
setup_logging()  # 配置控制台 + 文件日志（local_data/logs/）
logger = __import__("logging").getLogger(__name__)

# ── .env 加载 ─────────────────────────────
if os.path.exists(ENV_FILE):
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

# ── 页面 / 共享函数 导入 ─────────────────
from qconst import QDRANT_URL
from utils.state import STATE
from utils.ui_shared import (
    render_chunk_card, build_left_drawer, refresh_system_state,
    set_active_collection, EMBED_PRESETS, _status_tick, set_main_loop,
)
import kb_query
import watcher

from pages.ingest import page_ingest
from pages.search import page_search
from pages.hub    import page_hub
from pages.config import page_config
from pages.manage import page_manage
from pages.vocabulary import page_vocab

# ── .env 写入辅助 ────────────────────────
def _save_env(key: str, val: str):
    lines = []
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    found = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and stripped.split("=", 1)[0].strip() == key:
            lines[i] = f"{key}={val}\n"
            found = True
            break
    if not found:
        lines.append(f"{key}={val}\n")
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines)

# ── 启动回调 ─────────────────────────────
@app.on_startup
def startup():
    """启动回调：只做轻量操作，不阻塞事件循环。"""
    logger.info("startup 回调开始（事件循环线程）")
    set_main_loop()
    # 启动守望文件夹 v2
    try:
        watcher.start_watcher()
        logger.info("守望文件夹 v2 已启动")
    except Exception as e:
        logger.error(f"守望文件夹 v2 启动失败: {e}")
    logger.info(f"startup 回调完成 — STATE 已有 stats={STATE.get('stats')}")


@app.on_shutdown
def shutdown():
    """关闭回调：停止守望文件夹。"""
    logger.info("停止守望文件夹 v2…")
    try:
        watcher.stop_watcher()
    except Exception as e:
        logger.error(f"守望文件夹 v2 停止异常: {e}")

@app.get("/health")
def _health_check():
    """绕过 NiceGUI 路由，直接测试 FastAPI 层"""
    from fastapi.responses import JSONResponse
    return JSONResponse({
        "status": "ok",
        "qdrant_online": STATE["qdrant_online"],
        "stats": STATE.get("stats"),
        "pid": os.getpid(),
        "watcher": {
            "alive": watcher.is_watcher_alive(),
            "stats": watcher.get_watch_stats(),
        },
    })

@app.get("/reports/{filename}")
def _serve_report(filename: str):
    from fastapi.responses import FileResponse
    file_path = os.path.join(PROJECT_DIR, "local_data", "reports", filename)
    if os.path.exists(file_path):
        return FileResponse(file_path)
    from fastapi.responses import JSONResponse
    return JSONResponse({"error": "File not found"}, status_code=404)

def _enforce_single_instance() -> None:
    """单实例锁：防两个熔知同时跑抢收件箱/Ollama（轮2 被看门狗误杀的根因）。

    文件系统级原子创建(O_CREAT|O_EXCL)抢锁文件，谁先建谁赢；
    另一个实例拿到 EEXIST → 读锁里 PID，还活着就退出，已死(崩溃残留)就接管。
    仅主进程(__main__)执行；spawn 子进程(__mp_main__)跳过，避免误杀自己的 worker。
    """
    import atexit, subprocess
    lock_path = os.path.join(PROJECT_DIR, "local_data", ".citrinitas.lock")
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)

    def _pid_alive(pid: int) -> bool:
        # 优先用 Windows API 直接查进程句柄，绕开 tasklist 的 GBK 编码坑：
        # 中文 Windows 下 tasklist 输出 GBK，而 subprocess(text=True) 按 UTF-8 解码会
        # 抛 UnicodeDecodeError → 被 except 吞掉 → 误判"已死" → 错误接管锁 → 双实例放行。
        if sys.platform == "win32":
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if handle == 0:
                    return False
                try:
                    ec = ctypes.c_ulong()
                    # STILL_ACTIVE = 259：仅当进程仍在运行(退出码为 259)才算活着；
                    # 否则进程已终止但 PID 尚未被 OS 回收(强杀后的竞态窗口)→ 视为死亡，允许新实例接管。
                    if kernel32.GetExitCodeProcess(handle, ctypes.byref(ec)):
                        return ec.value == 259
                    return False
                finally:
                    kernel32.CloseHandle(handle)
            except Exception:
                pass
        # 兜底（非 Windows / ctypes 异常）：读原始字节再 errors=ignore 解码，
        # PID 是 ASCII 数字，任何编码下都能幸存匹配。
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True, timeout=10,
            ).stdout
            if isinstance(out, bytes):
                out = out.decode("utf-8", errors="ignore")
            return str(pid) in out
        except Exception:
            return False

    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError as e:
        if getattr(e, "errno", None) != 17:  # 17 = EEXIST
            raise
        try:
            with open(lock_path, "r", encoding="utf-8") as _lf:
                old_pid = int(_lf.read().strip())
        except (ValueError, OSError):
            old_pid = None
        if old_pid is not None and _pid_alive(old_pid):
            logger.critical(
                "已有另一个 Citrinitas 实例在运行（PID %s），退出避免双实例抢资源。", old_pid
            )
            sys.exit(1)
        # 残留死锁（旧进程已死）→ 接管
        try:
            os.remove(lock_path)
        except OSError:
            pass
        return _enforce_single_instance()
    with os.fdopen(fd, "w") as _lf:
        _lf.write(str(os.getpid()))

    def _release_lock() -> None:
        try:
            if os.path.exists(lock_path):
                os.remove(lock_path)
        except OSError:
            pass
    atexit.register(_release_lock)


# ── 主入口 ───────────────────────────────
if __name__ in {"__main__", "__mp_main__"}:
    if __name__ == "__main__":
        _enforce_single_instance()
    print(f"[启动] 检查 Qdrant: {QDRANT_URL}/collections")
    _qdrant_ok = False
    for _attempt in range(3):
        try:
            _test = _r.get(f"{QDRANT_URL}/collections", timeout=5)
            if _test.status_code == 200:
                logger.info("✅ Qdrant 连接正常")
                _qdrant_ok = True
                break
            else:
                logger.warning(f"Qdrant 返回异常状态码: {_test.status_code}")
        except Exception as _e:
            logger.warning(f"Qdrant 连接失败 (尝试 {_attempt+1}/3): {_e}")
        if not _qdrant_ok and _attempt < 2:
            logger.info("等待 5 秒后重试...")
            import time
            time.sleep(5)

    if not _qdrant_ok:
        # 尝试通过 qdrant_helper.ps1 启动 Qdrant（真正启动，不只是检测）
        import subprocess
        _ps = os.path.join(PROJECT_DIR, "scripts", "qdrant_helper.ps1")
        logger.info("尝试启动 Qdrant...")
        try:
            _r = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", _ps, "-Action", "start", "-ProjectDir", PROJECT_DIR,
                 "-MaxRetries", "30", "-RetryDelay", "2"],
                capture_output=True, text=True, timeout=80
            )
            if _r.returncode == 0:
                logger.info("✅ Qdrant 已启动")
                _qdrant_ok = True
            else:
                logger.error(f"Qdrant 启动失败，返回码: {_r.returncode}")
                if _r.stdout:
                    logger.debug(f"Qdrant 启动输出: {_r.stdout[-500:]}")
        except Exception as _e2:
            logger.error(f"自动启动 Qdrant 失败: {_e2}")

    if not _qdrant_ok:
        logger.critical("无法连接到 Qdrant，Citrinitas 不能启动。")
        logger.critical("  请确保 Qdrant 正在运行：")
        logger.critical("    1. 手动检查：打开 http://127.0.0.1:6333 看是否响应")
        logger.critical("    2. 或重新运行 run.bat（它会自动启动 Qdrant）")
        sys.exit(1)

    # 在事件循环启动前刷新状态（阻塞主线程没问题，此时事件循环还没启动）
    logger.info("刷新系统状态（ui.run 前）...")
    refresh_system_state()
    logger.info(f"状态刷新完成 — stats={STATE.get('stats')}")

    logger.info("Citrinitas 服务启动成功！")
    logger.info("  📍 Web UI:  http://127.0.0.1:8080")
    logger.info("  📍 Qdrant:  http://127.0.0.1:6333")

    # 浏览器自动开启：仅「非受总管监管」的手动启动才开（OM_AUTO_OPEN_BROWSER != "0"）。
    # 受总管监管时后台静默运行，改用托盘「打开界面」手动打开，避免重启时无限弹窗。
    _auto_open = os.environ.get("OM_AUTO_OPEN_BROWSER", "1") != "0"

    # 备用浏览器开启（NiceGUI 的 webbrowser.open 在 Windows 下可能静默失败）
    def _fallback_browser():
        for i in range(30):
            time.sleep(0.5)
            try:
                _r.get("http://127.0.0.1:8080", timeout=1)
                os.startfile("http://127.0.0.1:8080")
                logger.info("浏览器已自动打开")
                break
            except Exception:
                continue
    if _auto_open:
        threading.Thread(target=_fallback_browser, daemon=True).start()

    ui.run(
        title="Citrinitas · 熔知",
        host="0.0.0.0",
        port=8080,
        reload=False,
        show=False,   # 浏览器由上方 _fallback_browser 兜底打开（os.startfile 更可靠）；
                      # 此处若再 show=True 会与兜底双开两个网页（用户 2026-08-02 反馈修复）
        storage_secret=os.environ.get("STORAGE_SECRET", "citrinitas-dev-secret-change-me"),
    )
