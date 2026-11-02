"""Atalhos do Windows: Menu Iniciar, Área de Trabalho e inicialização automática."""

import os
import subprocess
import sys

PASTA_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICONE = os.path.join(PASTA_APP, "teleprompter.ico")
NOME = "Teleprompter BR.lnk"


def _pastas() -> dict[str, str]:
    appdata = os.environ["APPDATA"]
    return {
        "menu": os.path.join(appdata, r"Microsoft\Windows\Start Menu\Programs"),
        "inicio": os.path.join(appdata, r"Microsoft\Windows\Start Menu\Programs\Startup"),
        "area": os.path.join(os.path.expanduser("~"), "Desktop"),
    }


def _pythonw() -> str:
    return os.path.join(os.path.dirname(sys.executable), "pythonw.exe")


def icone(tamanho=64):
    from PIL import Image, ImageDraw
    e = max(4, tamanho // 16)
    img = Image.new("RGBA", (64 * e, 64 * e), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([4 * e, 4 * e, 60 * e, 60 * e], radius=16 * e, fill=(13, 15, 18, 255))
    for i, (w, cor) in enumerate([(40, (92, 98, 109)), (30, (255, 138, 61)), (36, (242, 244, 247))]):
        d.rounded_rectangle([12 * e, (18 + i * 11) * e, (12 + w) * e, (24 + i * 11) * e], radius=3 * e, fill=cor)
    return img.resize((tamanho, tamanho), Image.LANCZOS)


def criar_icone():
    img = icone()
    img.save(ICONE, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64)])


def criar(onde: str):
    destino = os.path.join(_pastas()[onde], NOME)
    script = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:DESTINO);"
        "$s.TargetPath=$env:ALVO;$s.Arguments='-m teleprompter';$s.WorkingDirectory=$env:PASTA;"
        "$s.IconLocation=$env:ICONE;$s.Description='Teleprompter BR: o texto acompanha a sua voz';$s.Save()"
    )
    env = {**os.environ, "DESTINO": destino, "ALVO": _pythonw(), "PASTA": PASTA_APP, "ICONE": ICONE}
    subprocess.run(["powershell", "-NoProfile", "-Command", script], env=env, check=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def existe(onde: str) -> bool:
    return os.path.exists(os.path.join(_pastas()[onde], NOME))


def remover(onde: str):
    caminho = os.path.join(_pastas()[onde], NOME)
    if os.path.exists(caminho):
        os.remove(caminho)


if __name__ == "__main__":
    criar_icone()
    criar("menu")
    criar("area")
    print("   Atalhos criados no Menu Iniciar e na Area de Trabalho.")
