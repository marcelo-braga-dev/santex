@echo off
REM Gera os entregaveis do projeto na pasta distribuir\ (fora do git):
REM   PainelProducaoSantex-versao.exe  - computador da fabrica (tem a chave: NAO distribuir)
REM   Painel de Producao.exe    - computadores de fora (sem chave: pode copiar; tambem vai para a VPS)
REM   painel-nuvem-<versao>.tar.gz - pacote da VPS (alternativa ao git pull)
REM Duplo clique e escolha. Precisa do Python no PATH e do .env na raiz.

cd /d "%~dp0.."

echo ============================================================
echo  Painel de Producao - gerar entregaveis  (saida: distribuir\)
echo ============================================================
echo   1) Aplicativo da fabrica   (PainelProducaoSantex-versao.exe)
echo   2) Programa remoto         (Painel de Producao.exe - tambem publicado no painel da VPS)
echo   3) Pacote da VPS           (painel-nuvem-versao.tar.gz)
echo   4) Tudo
echo.
set /p OPCAO="Opcao [4]: "
if "%OPCAO%"=="" set OPCAO=4

echo.
echo Instalando dependencias (pywebview, pyinstaller, pyserial, zeroconf)...
python -m pip install -q -r app\requirements.txt
if errorlevel 1 goto erro

if "%OPCAO%"=="1" goto fabrica
if "%OPCAO%"=="2" goto remoto
if "%OPCAO%"=="3" goto vps

:fabrica
echo.
echo == Aplicativo da fabrica: chaves a partir do .env
python ferramentas\gerar_segredos.py
if errorlevel 1 goto erro
python gerar\exe_fabrica.py
if errorlevel 1 goto erro
if "%OPCAO%"=="1" goto fim

:remoto
echo.
echo == Programa remoto
python gerar\exe_remoto.py
if errorlevel 1 goto erro
if "%OPCAO%"=="2" goto fim

:vps
echo.
echo == Pacote da VPS
powershell -NoProfile -ExecutionPolicy Bypass -File gerar\pacote_vps.ps1
if errorlevel 1 goto erro

:fim
echo.
echo ============================================================
echo  Pronto! Veja a pasta distribuir\
echo ============================================================
pause
exit /b 0

:erro
echo.
echo ERRO - veja a mensagem acima. (Python no PATH? .env na raiz? copie .env.exemplo)
pause
exit /b 1
