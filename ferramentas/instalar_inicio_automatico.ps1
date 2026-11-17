<#
  Faz o Painel de Producao abrir sozinho quando o Windows inicia (atalho na
  pasta "Inicializar" do usuario) - para o notebook que fica como servidor
  permanente do painel.

  Uso (PowerShell, na pasta ferramentas):
    .\instalar_inicio_automatico.ps1 "C:\Caminho\PainelProducaoSantex.exe"   # instala
    .\instalar_inicio_automatico.ps1 -Remover                                 # remove

  Sem caminho, usa ..\app\dist\PainelProducaoSantex.exe.
#>
param(
    [Parameter(Position = 0)]
    [string]$Executavel = "",
    [switch]$Remover
)

$pastaInicio = [Environment]::GetFolderPath("Startup")
$atalho = Join-Path $pastaInicio "Painel de Producao.lnk"

if ($Remover) {
    if (Test-Path $atalho) {
        Remove-Item $atalho -Confirm:$false
        Write-Host "Inicio automatico removido." -ForegroundColor Green
    } else {
        Write-Host "Inicio automatico nao estava instalado." -ForegroundColor Yellow
    }
    return
}

if (-not $Executavel) {
    $Executavel = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "..\app\dist\PainelProducaoSantex.exe"
}
if (-not (Test-Path $Executavel)) {
    Write-Host "Executavel nao encontrado: $Executavel" -ForegroundColor Red
    Write-Host "Informe o caminho: .\instalar_inicio_automatico.ps1 `"C:\...\PainelProducaoSantex.exe`""
    exit 1
}
$Executavel = (Resolve-Path $Executavel).Path

$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($atalho)
$lnk.TargetPath = $Executavel
$lnk.WorkingDirectory = Split-Path -Parent $Executavel
$lnk.Description = "Painel de Producao (abre com o Windows)"
$lnk.Save()
Write-Host "Pronto: o painel abre sozinho quando este usuario entrar no Windows." -ForegroundColor Green
Write-Host "Atalho: $atalho"
Write-Host ""
Write-Host "Lembre tambem de: (1) desativar a suspensao do notebook na tomada, se ele"
Write-Host "for o servidor do painel; (2) manter 'Acertar a hora automaticamente' ligado"
Write-Host "no Windows - e o PC que acerta o relogio do controlador."
