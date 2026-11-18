<#
  Monta o pacote do acesso remoto para a VPS: distribuir\painel-nuvem-<versao>.tar.gz

  Leva so o que o servidor da VPS precisa (servidor, ferramentas, painel,
  vps/, guia) + o CLAUDE.md para o Claude Code rodar a instalacao la.
  Nunca leva segredos da fabrica (.env, segredos_app.json, segredos.h),
  bancos, backups nem o .exe.

  Uso (PowerShell, na raiz do projeto):
    .\gerar\pacote_vps.ps1   (ou gerar\gerar.bat, opcao 3)

  Depois, para a VPS (troque usuario@IP):
    scp distribuir\painel-nuvem-<versao>.tar.gz usuario@IP:~
    ssh usuario@IP "tar -xzf painel-nuvem-<versao>.tar.gz"   # cria ~/painel-nuvem
#>
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $raiz

$versao = (Select-String -Path "app\servidor.py" -Pattern '^APP_VERSAO = "([^"]+)"').Matches[0].Groups[1].Value
$saida = Join-Path $raiz "distribuir"
$temp = Join-Path ([System.IO.Path]::GetTempPath()) ("painel-nuvem-" + [guid]::NewGuid().ToString("N"))
$pacote = Join-Path $temp "painel-nuvem"

$arquivos = @(
    "app\servidor.py", "app\caminhos.py", "app\anuncio_rede.py",
    "ferramentas\banco_dados.py", "ferramentas\backup_banco.py", "ferramentas\monitor_serial.py",
    "ferramentas\monitor_wifi.py", "ferramentas\nuvem.py",
    "ferramentas\controle_leitura_server.py",
    "painel\index.html",
    "vps\instalar.sh", "vps\painel-nuvem.service", "vps\Caddyfile", "vps\painel-nuvem.env.exemplo",
    "docs\nuvem-vps.md"
)

try {
    foreach ($a in $arquivos) {
        $destino = Join-Path $pacote $a
        New-Item -ItemType Directory -Force (Split-Path -Parent $destino) | Out-Null
        Copy-Item $a $destino
    }
    Copy-Item "painel\assets" (Join-Path $pacote "painel\assets") -Recurse
    if (Test-Path "vps\app-remoto") { Copy-Item "vps\app-remoto" (Join-Path $pacote "vps\app-remoto") -Recurse }
    Copy-Item "vps\CLAUDE_VPS.md" (Join-Path $pacote "CLAUDE.md")

    # Linux: quebra de linha LF nos arquivos de texto (bash/systemd falham com CRLF)
    Get-ChildItem $pacote -Recurse -File -Include *.sh, *.service, Caddyfile, *.py, *.md, *.exemplo | Where-Object { $_.FullName -notlike "*app-remoto*" } | ForEach-Object {
        $texto = [System.IO.File]::ReadAllText($_.FullName)
        [System.IO.File]::WriteAllText($_.FullName, $texto.Replace("`r`n", "`n"), (New-Object System.Text.UTF8Encoding($false)))
    }

    # Nenhum segredo da fabrica pode ir junto
    $proibidos = Get-ChildItem $pacote -Recurse -File | Where-Object { $_.Name -in @(".env", "segredos_app.json", "segredos.h", "build_info.json", "painel.db") }
    if ($proibidos) { throw "Pacote recusado - contem segredo/dado: $($proibidos.Name -join ', ')" }
    if (Test-Path ".env") {
        $valores = Get-Content ".env" | Where-Object { $_ -match '^(\w*(SENHA|CHAVE)\w*)=(.{6,})$' } | ForEach-Object { ($_ -split '=', 2)[1].Trim('"', "'") }
        foreach ($f in Get-ChildItem $pacote -Recurse -File) {
            $conteudo = [System.IO.File]::ReadAllText($f.FullName)
            foreach ($v in $valores) { if ($conteudo.Contains($v)) { throw "Pacote recusado - um valor do .env apareceu em $($f.Name)" } }
        }
    }

    New-Item -ItemType Directory -Force $saida | Out-Null
    $arquivoTar = Join-Path $saida "painel-nuvem-$versao.tar.gz"
    if (Test-Path $arquivoTar) { Remove-Item $arquivoTar -Confirm:$false }
    # o tar do proprio Windows (o do Git le "C:" como um computador remoto)
    $tar = Join-Path $env:SystemRoot "System32\tar.exe"
    & $tar -czf $arquivoTar -C $temp "painel-nuvem"
    if ($LASTEXITCODE -ne 0) { throw "tar falhou" }

    $tamanho = [math]::Round((Get-Item $arquivoTar).Length / 1KB)
    Write-Host "Pacote: $arquivoTar ($tamanho KB, versao $versao)" -ForegroundColor Green
    Write-Host "Para a VPS:  scp `"$arquivoTar`" usuario@IP:~   e la:  tar -xzf painel-nuvem-$versao.tar.gz"
    Write-Host "Depois, na VPS:  cd ~/painel-nuvem && claude   (o CLAUDE.md guia a instalacao)"
}
finally {
    if (Test-Path $temp) { Remove-Item $temp -Recurse -Force -Confirm:$false }
}
