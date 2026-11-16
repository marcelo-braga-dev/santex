@echo off
REM Gera o executavel standalone do Painel de Producao (PainelProducaoSantex.exe).
REM Duplo clique neste arquivo: instala as dependencias e roda o build_exe.py.

cd /d "%~dp0"

echo ============================================================
echo  Painel de Producao - gerando executavel
echo ============================================================
echo.

echo [1/2] Instalando dependencias (pywebview, pyinstaller, pyserial)...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERRO ao instalar as dependencias. Verifique se o Python esta instalado
    echo e disponivel no PATH ^(comando "python" precisa funcionar no terminal^).
    pause
    exit /b 1
)

echo.
echo [2/2] Gerando o executavel ^(pode levar alguns minutos^)...
python build_exe.py
if errorlevel 1 (
    echo.
    echo ERRO ao gerar o executavel. Veja a mensagem do PyInstaller acima.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Pronto! Executavel gerado em: dist\PainelProducaoSantex.exe
echo ============================================================
pause
