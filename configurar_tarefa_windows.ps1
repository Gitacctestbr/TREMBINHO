# ============================================================
# TREMBINHO - Configuracao do Task Scheduler (Passo 6)
# ============================================================
# Execute UMA VEZ no PowerShell:
#
#   cd C:\Users\DESKTOP\Desktop\trembinho
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\configurar_tarefa_windows.ps1
# ============================================================

$RaizProjeto = "C:\Users\DESKTOP\Desktop\trembinho"
$PythonVenv  = "$RaizProjeto\venv\Scripts\python.exe"
$ScriptBot   = "$RaizProjeto\listener_main.py"
$Launcher    = "$RaizProjeto\iniciar_bot.bat"
$NomeTarefa  = "TrembinhoBot"

# ------------------------------------------------------------
# Passo 1 - Valida ambiente
# ------------------------------------------------------------
if (-not (Test-Path $PythonVenv)) {
    Write-Host "ERRO: Python do venv nao encontrado: $PythonVenv" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $ScriptBot)) {
    Write-Host "ERRO: listener_main.py nao encontrado: $ScriptBot" -ForegroundColor Red
    exit 1
}

# ------------------------------------------------------------
# Passo 2 - Cria iniciar_bot.bat
# ------------------------------------------------------------
$linhas = @(
    '@echo off',
    "cd /d `"$RaizProjeto`"",
    "`"$PythonVenv`" `"$ScriptBot`""
)
$linhas | Set-Content -Path $Launcher -Encoding ASCII
Write-Host "OK: Launcher criado -> $Launcher" -ForegroundColor Green

# ------------------------------------------------------------
# Passo 3 - Remove tarefa anterior se existir
# ------------------------------------------------------------
$existe = Get-ScheduledTask -TaskName $NomeTarefa -ErrorAction SilentlyContinue
if ($existe) {
    Unregister-ScheduledTask -TaskName $NomeTarefa -Confirm:$false
    Write-Host "INFO: Tarefa anterior removida." -ForegroundColor Yellow
}

# ------------------------------------------------------------
# Passo 4 - Registra a tarefa
# ------------------------------------------------------------
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$Launcher`"" `
    -WorkingDirectory $RaizProjeto

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit 0 `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName $NomeTarefa `
    -Trigger $trigger `
    -Action $action `
    -Settings $settings `
    -Principal $principal `
    -Description "Trembinho SDR Bot - inicia no login e reinicia em crash." `
    -Force | Out-Null

Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "  TREMBINHO BOT registrado com sucesso!" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Tarefa   : $NomeTarefa"
Write-Host "Disparo  : login do Windows ($env:USERNAME)"
Write-Host "Reinicio : 3x com intervalo de 1 min em caso de falha"
Write-Host ""
Write-Host "Comandos uteis:" -ForegroundColor Yellow
Write-Host "  Iniciar agora : Start-ScheduledTask -TaskName '$NomeTarefa'"
Write-Host "  Parar         : Stop-ScheduledTask  -TaskName '$NomeTarefa'"
Write-Host "  Ver status    : Get-ScheduledTask   -TaskName '$NomeTarefa'"
Write-Host "  Remover       : Unregister-ScheduledTask -TaskName '$NomeTarefa'"
Write-Host ""
$logPath = "$RaizProjeto\trembinho_bot.log"
Write-Host "Log do bot: $logPath"
