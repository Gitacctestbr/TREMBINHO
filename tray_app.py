"""Trembinho — Controlador da Bandeja do Sistema (System Tray)

Roda silenciosamente na área de notificação do Windows ("mostrar ícones ocultos").
Liga/desliga o bot do Telegram (testar_ponte.py) sem abrir prompt de comando.
Sempre usa o Python do venv local — nunca o Python do sistema — para garantir
que todas as dependências (dotenv, ollama, notion_client, etc.) estão presentes.
"""
import os
import sys
import subprocess
import threading
import winreg
from datetime import datetime
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

# ---------------------------------------------------------------------------
# Caminhos — sempre apontam para o venv local, não para sys.executable
# ---------------------------------------------------------------------------
PASTA_RAIZ = Path(__file__).resolve().parent
SCRIPT_BOT = PASTA_RAIZ / "listener_main.py"
SCRIPT_MAIN = PASTA_RAIZ / "main.py"
ESTE_SCRIPT = Path(__file__).resolve()
NOME_REGISTRO = "TrembinhoBot"
LOG_FILE = PASTA_RAIZ / "trembinho_bot.log"

VENV_PYTHON = PASTA_RAIZ / "venv" / "Scripts" / "python.exe"
VENV_PYTHONW = PASTA_RAIZ / "venv" / "Scripts" / "pythonw.exe"


def _resolver_python(janela: bool) -> str:
    """Devolve sempre um Python do venv. Se o venv não existir, cai para sys.executable
    como último recurso (e loga aviso)."""
    alvo = VENV_PYTHON if janela else VENV_PYTHONW
    if alvo.exists():
        return str(alvo)
    _log(f"AVISO: venv não encontrado em {alvo}. Usando sys.executable como fallback.")
    return sys.executable


# ---------------------------------------------------------------------------
# Estado global do processo bot
# ---------------------------------------------------------------------------
_processo_bot = None
_lock = threading.Lock()


def bot_ativo() -> bool:
    with _lock:
        return _processo_bot is not None and _processo_bot.poll() is None


# ---------------------------------------------------------------------------
# Log seguro (não depende de stdout — funciona mesmo via pythonw.exe)
# ---------------------------------------------------------------------------
def _log(msg: str):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[TRAY {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Ícones (gerados uma vez em memória)
# ---------------------------------------------------------------------------
def _criar_icone(ativo: bool) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cor = (34, 197, 94, 255) if ativo else (107, 114, 128, 255)
    d.ellipse([2, 2, 62, 62], fill=cor)
    d.rectangle([17, 15, 47, 24], fill="white")
    d.rectangle([28, 24, 36, 50], fill="white")
    return img


ICONE_ATIVO = _criar_icone(True)
ICONE_INATIVO = _criar_icone(False)


# ---------------------------------------------------------------------------
# Sincroniza ícone + tooltip com o estado real
# ---------------------------------------------------------------------------
def _sincronizar_icone(icon: pystray.Icon):
    ativo = bot_ativo()
    icon.icon = ICONE_ATIVO if ativo else ICONE_INATIVO
    icon.title = f"Trembinho — {'Ativo ✔' if ativo else 'Inativo'}"
    icon.update_menu()


# ---------------------------------------------------------------------------
# Ações dos botões do menu
# ---------------------------------------------------------------------------
def ligar_bot(icon: pystray.Icon, item=None):
    global _processo_bot
    if bot_ativo():
        return
    python_exe = _resolver_python(janela=False)  # bot roda silencioso
    with _lock:
        # Redireciona stdout/stderr do bot para o arquivo de log.
        # Sem isso, pythonw.exe herda handles nulos e qualquer print() mata o processo.
        log_f = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
        # Força UTF-8 no subprocess pra emojis (🎯 etc.) não estourarem no cp1252 do Windows.
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        _processo_bot = subprocess.Popen(
            [python_exe, str(SCRIPT_BOT)],
            cwd=str(PASTA_RAIZ),
            stdout=log_f,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
            env=env,
        )
        log_f.close()  # Popen duplicou o handle internamente; podemos fechar nossa cópia
    _log(f"Bot iniciado (PID={_processo_bot.pid}) via {python_exe}")
    if icon is not None:
        _sincronizar_icone(icon)


def desligar_bot(icon: pystray.Icon, item=None):
    global _processo_bot
    with _lock:
        proc = _processo_bot
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    with _lock:
        _processo_bot = None
    _log("Bot encerrado.")
    if icon is not None:
        _sincronizar_icone(icon)


def abrir_terminal(icon: pystray.Icon, item=None):
    """Abre main.py em uma nova janela de terminal visível (mesmo efeito do atalho)."""
    python_exe = _resolver_python(janela=True)
    subprocess.Popen(
        ["cmd.exe", "/k", f'"{python_exe}" "{SCRIPT_MAIN}"'],
        cwd=str(PASTA_RAIZ),
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
    _log("Terminal interativo aberto pelo menu da bandeja.")


def sair_app(icon: pystray.Icon, item=None):
    desligar_bot(icon, item)
    icon.stop()


# ---------------------------------------------------------------------------
# Menu dinâmico (enabled muda conforme o estado)
# ---------------------------------------------------------------------------
def _status_label(item) -> str:
    return "● Bot: Ativo" if bot_ativo() else "○ Bot: Inativo"


MENU = pystray.Menu(
    pystray.MenuItem("Ligar Bot",    ligar_bot,    enabled=lambda i: not bot_ativo()),
    pystray.MenuItem("Desligar Bot", desligar_bot, enabled=lambda i: bot_ativo()),
    pystray.Menu.SEPARATOR,
    pystray.MenuItem("Abrir terminal interativo", abrir_terminal),
    pystray.Menu.SEPARATOR,
    pystray.MenuItem(_status_label, None, enabled=False),
    pystray.Menu.SEPARATOR,
    pystray.MenuItem("Sair", sair_app),
)


# ---------------------------------------------------------------------------
# Auto-inicialização no Windows (registro HKCU\Run) — sempre via venv pythonw
# ---------------------------------------------------------------------------
def _registrar_startup():
    exe = _resolver_python(janela=False)  # pythonw do venv = sem janela
    comando = f'"{exe}" "{ESTE_SCRIPT}"'
    try:
        chave = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
        winreg.SetValueEx(chave, NOME_REGISTRO, 0, winreg.REG_SZ, comando)
        winreg.CloseKey(chave)
        _log(f"Startup registrado: {comando}")
    except Exception as e:
        _log(f"Aviso: não foi possível registrar startup automático: {e}")


# ---------------------------------------------------------------------------
# Atalho na área de trabalho — abre main.py em terminal VISÍVEL (cmd.exe)
# ---------------------------------------------------------------------------
def _criar_atalho_desktop():
    """Cria/atualiza o atalho 'Trembinho DESK.lnk' na área de trabalho.
    O atalho abre cmd.exe rodando 'venv\\python.exe main.py' na pasta do projeto,
    deixando o terminal aberto após o programa encerrar (cmd /k)."""
    desktop = Path.home() / "Desktop"
    atalho = desktop / "Trembinho DESK.lnk"
    python_exe = _resolver_python(janela=True)

    # cmd /k mantém a janela aberta depois que o python sair (pra ver mensagens finais)
    target = r"C:\Windows\System32\cmd.exe"
    arguments = f'/k ""{python_exe}" "{SCRIPT_MAIN}""'

    ps = (
        f'$s=(New-Object -comObject WScript.Shell).CreateShortcut("{atalho}");'
        f'$s.TargetPath="{target}";'
        f'$s.Arguments=\'{arguments}\';'
        f'$s.WorkingDirectory="{PASTA_RAIZ}";'
        f'$s.IconLocation="{python_exe},0";'
        f'$s.Description="Trembinho — Terminal Interativo";'
        f'$s.Save()'
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True,
    )
    if atalho.exists():
        _log(f"Atalho de terminal criado/atualizado em: {atalho}")
    else:
        erro = result.stderr.decode(errors="replace")
        _log(f"Aviso: atalho não foi criado. Erro: {erro}")


def _criar_atalho_tray():
    """Cria/atualiza o atalho 'Trembinho TELEGRAM.lnk' na área de trabalho.
    O atalho roda tray_app.py 100% silenciosamente via pythonw.exe (sem janela, sem console)."""
    desktop = Path.home() / "Desktop"
    atalho = desktop / "Trembinho TELEGRAM.lnk"
    python_exe = _resolver_python(janela=False)  # pythonw = sem janela

    target = python_exe
    arguments = f'"{ESTE_SCRIPT}"'

    ps = (
        f'$s=(New-Object -comObject WScript.Shell).CreateShortcut("{atalho}");'
        f'$s.TargetPath="{target}";'
        f'$s.Arguments=\'{arguments}\';'
        f'$s.WorkingDirectory="{PASTA_RAIZ}";'
        f'$s.IconLocation="{python_exe},0";'
        f'$s.Description="Trembinho — Bandeja (Bot Telegram)";'
        f'$s.Save()'
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True,
    )
    if atalho.exists():
        _log(f"Atalho de bandeja criado/atualizado em: {atalho}")
    else:
        erro = result.stderr.decode(errors="replace")
        _log(f"Aviso: atalho de bandeja não foi criado. Erro: {erro}")


# ---------------------------------------------------------------------------
# Monitor de processo (detecta se o bot caiu sozinho)
# ---------------------------------------------------------------------------
def _monitor(icon: pystray.Icon, stop: threading.Event):
    while not stop.is_set():
        _sincronizar_icone(icon)
        stop.wait(5)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    _log("=" * 60)
    _log(f"Tray iniciando. sys.executable={sys.executable}")
    _log(f"venv pythonw esperado: {VENV_PYTHONW} (existe={VENV_PYTHONW.exists()})")

    _registrar_startup()
    _criar_atalho_desktop()
    _criar_atalho_tray()

    icon = pystray.Icon(
        "trembinho",
        ICONE_INATIVO,
        "Trembinho — Inativo",
        menu=MENU,
    )

    stop_event = threading.Event()
    threading.Thread(target=_monitor, args=(icon, stop_event), daemon=True).start()

    def ao_iniciar(icon):
        """Chamado pelo pystray após o ícone aparecer na bandeja."""
        icon.visible = True
        _log("Tray pronto. Iniciando bot automaticamente...")
        ligar_bot(icon)

    try:
        icon.run(setup=ao_iniciar)
    finally:
        stop_event.set()


if __name__ == "__main__":
    main()
