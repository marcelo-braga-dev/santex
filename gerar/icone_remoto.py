"""
Desenha o icone do programa remoto ("Painel de Producao") em
remoto/icone.ico a partir do LOGO DA SANTEX (painel/assets/logo.png): a
marca - o "S" preto dentro da elipse vermelha - sobre um quadrado branco
arredondado que ocupa todo o espaco do icone.

O logo original e pequeno (167 px de altura); para nao ficar borrado, a
marca e ampliada, separada em "preto" e "vermelho" e as bordas sao
alisadas antes de reduzir para cada tamanho (16 a 256 px).

Uso:  python gerar/icone_remoto.py      (precisa do Pillow)
"""

import os

from PIL import Image, ImageDraw, ImageFilter

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGO = os.path.join(RAIZ, "painel", "assets", "logo.png")
SAIDA = os.path.join(RAIZ, "remoto", "icone.ico")
PREVIA = os.path.join(RAIZ, "remoto", "icone.png")
TAMANHOS = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
SS = 1024  # desenha grande e reduz (bordas suaves)

# O "S" encosta no "a" no logo: ate a coluna 76 e tudo do S; de 77 a 80 so a
# ponta de cima (y < 64). A elipse vermelha passa por tras do "antex" no logo,
# entao e redesenhada inteira (crescente: grossa a esquerda, fina a direita).
S_ATE_X, PONTA_ATE_X, PONTA_ATE_Y = 76, 80, 64
PRETO = (28, 28, 30, 255)
VERMELHO = (140, 22, 26, 255)  # vinho do logo
FUNDO = (255, 255, 255, 255)
BORDA = (0, 0, 0, 30)
ESCALA = 14


def _letra_s():
    """O "S" do logo em alta resolucao (mascara L), com bordas lisas."""
    logo = Image.open(LOGO).convert("RGBA")
    px = logo.load()
    mascara = Image.new("L", logo.size, 0)
    m = mascara.load()
    for y in range(logo.height):
        for x in range(PONTA_ATE_X + 1):
            r, g, b, a = px[x, y]
            if r > g + 45 or not (x <= S_ATE_X or y < PONTA_ATE_Y):
                continue  # vermelho da elipse, ou o "a" ao lado
            # cobertura continua (0-255) pela escuridao do pixel: as bordas
            # antisserrilhadas do logo viram meio-termo, e o contorno fica liso
            m[x, y] = max(0, min(255, round((215 - max(r, g, b)) * 255 / 150 * a / 255)))
    mascara = mascara.crop(mascara.point(lambda v: 255 if v > 60 else 0).getbbox())
    grande = mascara.resize((mascara.width * ESCALA, mascara.height * ESCALA), Image.BICUBIC)
    lisa = grande.filter(ImageFilter.GaussianBlur(ESCALA * 0.55)).point(lambda v: 255 if v > 128 else 0)
    return lisa.filter(ImageFilter.GaussianBlur(1.2))  # borda final suave


def _marca():
    """S preto dentro da elipse vermelha (RGBA, alta resolucao)."""
    letra = _letra_s()
    lw, lh = letra.size
    larg, alt = round(lw * 1.95), round(lh * 1.16)
    marca = Image.new("RGBA", (larg, alt), (0, 0, 0, 0))
    # crescente: elipse externa menos a interna deslocada para a direita
    anel = Image.new("L", (larg, alt), 0)
    ImageDraw.Draw(anel).ellipse((0, 0, larg - 1, alt - 1), fill=255)
    esp = larg * 0.085
    ImageDraw.Draw(anel).ellipse((esp * 1.25, esp * 0.55, larg - 1 - esp * 0.25, alt - 1 - esp * 0.55), fill=0)
    marca.paste(Image.new("RGBA", marca.size, VERMELHO), (0, 0), anel)
    preta = Image.new("RGBA", letra.size, PRETO)
    marca.paste(preta, ((larg - lw) // 2 + round(larg * 0.02), (alt - lh) // 2), letra)
    return marca


_MARCA = None


def desenhar(tamanho):
    global _MARCA
    if _MARCA is None:
        _MARCA = _marca()
    n = SS
    margem = n * (0.02 if tamanho >= 32 else 0.0)
    raio = n * 0.22
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # quadrado branco arredondado (com um contorno bem leve para aparecer em fundos claros)
    d.rounded_rectangle((margem, margem, n - margem, n - margem), raio, fill=BORDA)
    contorno = n * (0.012 if tamanho >= 32 else 0.02)
    d.rounded_rectangle((margem + contorno, margem + contorno, n - margem - contorno, n - margem - contorno),
                        raio - contorno, fill=FUNDO)
    # marca centralizada, o maior possivel dentro do quadrado
    caber = n * (0.84 if tamanho >= 32 else 0.94)
    fator = min(caber / _MARCA.width, caber / _MARCA.height)
    marca = _MARCA.resize((round(_MARCA.width * fator), round(_MARCA.height * fator)), Image.LANCZOS)
    img.alpha_composite(marca, ((n - marca.width) // 2, (n - marca.height) // 2))
    return img.resize((tamanho, tamanho), Image.LANCZOS)


def main():
    imagens = [desenhar(t) for t in TAMANHOS]
    imagens[-1].save(SAIDA, format="ICO", sizes=[(t, t) for t in TAMANHOS], append_images=imagens[:-1])
    imagens[-1].save(PREVIA)
    print(f"Icone: {SAIDA}  (+ previa {PREVIA})")


if __name__ == "__main__":
    main()
