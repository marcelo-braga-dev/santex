<#
  Controla o monitor_serial.py para liberar a porta COM antes de gravar o
  firmware na Arduino IDE, e retomar a leitura em tempo real depois.

  Uso:
    .\controlar_porta_serial.ps1 parar       # libera a porta (rodar antes do upload)
    .\controlar_porta_serial.ps1 iniciar     # retoma a leitura (rodar depois do upload)
    .\controlar_porta_serial.ps1 reiniciar   # para e inicia de novo
    .\controlar_porta_serial.ps1 status      # mostra se esta rodando
#>

param(
    [Parameter(Position = 0)]
    [ValidateSet("iniciar", "parar", "reiniciar", "status")]
    [string]$Acao = "status"
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$logFile = Join-Path $scriptDir "monitor_serial.log"

function Get-ProcessoMonitor {
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*monitor_serial.py*" }
}

# O aplicativo do painel (ou controle_leitura_server.py) le a porta numa
# thread propria: pausa/retoma pela API local, que so aceita este PC.
function Chamar-Painel([string]$rota) {
    try {
        return Invoke-RestMethod -Method Post -Uri "http://localhost$rota" -TimeoutSec 20
    } catch {
        return $null
    }
}

function Parar-Monitor {
    $resposta = Chamar-Painel "/parar"
    if ($resposta -ne $null) {
        if ($resposta.rodando) {
            Write-Host "O painel ainda esta encerrando a leitura - rode de novo em alguns segundos." -ForegroundColor Yellow
            return
        }
        Write-Host "Leitura do painel pausada." -ForegroundColor Green
    }
    $procs = Get-ProcessoMonitor
    foreach ($p in $procs) {
        Write-Host "Encerrando monitor_serial.py avulso (PID $($p.ProcessId))..."
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
    if ($resposta -eq $null -and -not $procs) {
        Write-Host "Nenhuma leitura rodando - porta ja esta livre." -ForegroundColor Yellow
        return
    }
    Start-Sleep -Milliseconds 800
    Write-Host "Porta liberada. Pode gravar o firmware na Arduino IDE agora." -ForegroundColor Green
}

function Iniciar-Monitor {
    $resposta = Chamar-Painel "/iniciar"
    if ($resposta -ne $null) {
        if ($resposta.rodando) {
            Write-Host "Leitura do painel retomada." -ForegroundColor Green
        } else {
            Write-Host "O painel nao encontrou a placa na USB (ou a origem configurada e o Wi-Fi). Confira o cabo." -ForegroundColor Red
        }
        return
    }
    if (Get-ProcessoMonitor) {
        Write-Host "monitor_serial.py ja esta rodando." -ForegroundColor Yellow
        return
    }
    Write-Host "Iniciando monitor_serial.py (saida em $logFile)..."
    Start-Process -FilePath "python" `
        -ArgumentList "monitor_serial.py" `
        -WorkingDirectory $scriptDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $logFile `
        -RedirectStandardError "$logFile.err"
    Start-Sleep -Milliseconds 500
    if (Get-ProcessoMonitor) {
        Write-Host "Leitura reiniciada." -ForegroundColor Green
    } else {
        Write-Host "Nao foi possivel confirmar que o processo iniciou. Veja $logFile.err" -ForegroundColor Red
    }
}

function Mostrar-Status {
    $procs = Get-ProcessoMonitor
    if ($procs) {
        $pids = ($procs | ForEach-Object { $_.ProcessId }) -join ", "
        Write-Host "Leitura ATIVA (PID $pids)." -ForegroundColor Green
    } else {
        Write-Host "Leitura PARADA - porta livre." -ForegroundColor Yellow
    }
}

switch ($Acao) {
    "parar"     { Parar-Monitor }
    "iniciar"   { Iniciar-Monitor }
    "reiniciar" { Parar-Monitor; Start-Sleep -Milliseconds 500; Iniciar-Monitor }
    "status"    { Mostrar-Status }
}
