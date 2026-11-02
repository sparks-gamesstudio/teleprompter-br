"""Teleprompter BR: janela flutuante que acompanha a sua voz, palavra por palavra."""

import ctypes
import json
import os
import threading
import time
import tkinter as tk
from tkinter import filedialog, font as tkfont

from .acompanhar import Acompanhador

PASTA = os.environ.get("TELE_PASTA") or os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "teleprompter-br")
CONFIG = os.path.join(PASTA, "config.json")
ROTEIRO = os.path.join(PASTA, "roteiro.txt")

FUNDO = "#0D0F12"
BARRA = "#16191F"
DITO = "#5C626D"
FUTURO = "#F2F4F7"
DESTAQUE = "#FF8A3D"
SUAVE = "#8B93A1"

MODOS = {"voz": "Segue a voz", "rolagem": "Rolagem fixa", "fala": "Rola enquanto fala"}

ROTEIRO_EXEMPLO = (
    "Bem-vindo ao Teleprompter BR!\n\n"
    "Aperte a barra de espaço e comece a ler este texto em voz alta. "
    "A palavra em laranja é a próxima que você vai dizer, e o texto sobe sozinho acompanhando a sua voz. "
    "Pode errar, parar para respirar ou pular uma palavra: ele se encontra de novo.\n\n"
    "Para colocar o seu roteiro, aperte E ou clique em Editar. "
    "Se ele se perder, clique na palavra em que você está."
)


def carregar_config() -> dict:
    padrao = {"modo": "voz", "tamanho": 40, "velocidade": 140, "geometria": None, "transparencia": 1.0}
    try:
        padrao.update(json.load(open(CONFIG, encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return padrao


class Teleprompter:
    def __init__(self, ouvido_fabrica=None):
        os.makedirs(PASTA, exist_ok=True)
        self.cfg = carregar_config()
        self.janela = j = tk.Tk()
        j.title("Teleprompter BR")
        j.configure(bg=FUNDO)
        j.attributes("-topmost", True)
        j.attributes("-alpha", self.cfg["transparencia"])
        larg = j.winfo_screenwidth()
        j.geometry(self.cfg["geometria"] or f"1000x340+{(larg - 1000) // 2}+8")
        j.minsize(480, 200)

        self._barra()
        self.tela = tk.Canvas(j, bg=FUNDO, highlightthickness=0)
        self.tela.pack(fill="both", expand=True)
        self.tela.bind("<Configure>", lambda e: self._diagramar())
        self.tela.bind("<Button-1>", self._clique)
        self.tela.bind("<MouseWheel>", lambda e: self._rolar_manual(-e.delta / 120))

        for tecla, acao in {
            "<space>": self.alternar, "<Home>": self.reiniciar, "<e>": self.editar, "<E>": self.editar,
            "<Up>": lambda: self._velocidade(10), "<Down>": lambda: self._velocidade(-10),
            "<Control-plus>": lambda: self._tamanho(4), "<Control-equal>": lambda: self._tamanho(4),
            "<Control-minus>": lambda: self._tamanho(-4), "<m>": self._proximo_modo, "<M>": self._proximo_modo,
            "<Escape>": self.fechar,
        }.items():
            j.bind(tecla, lambda e, a=acao: a())
        j.protocol("WM_DELETE_WINDOW", self.fechar)

        texto = open(ROTEIRO, encoding="utf-8").read() if os.path.exists(ROTEIRO) else ROTEIRO_EXEMPLO
        self.definir_texto(texto)
        self.rodando = False
        self.deslocamento = 0.0       # rolagem atual, em pixels
        self.alvo = 0.0
        self._ultimo = time.time()
        self.ouvido = None
        self._ouvido_fabrica = ouvido_fabrica
        threading.Thread(target=self._preparar_voz, daemon=True).start()
        self._quadro()

    # ---------- barra superior ----------
    def _barra(self):
        b = tk.Frame(self.janela, bg=BARRA, height=38)
        b.pack(fill="x")
        b.pack_propagate(False)
        estilo = dict(bg=BARRA, fg=FUTURO, activebackground="#232833", activeforeground=FUTURO, bd=0, relief="flat",
                      font=("Segoe UI Semibold", 10), padx=12, cursor="hand2")
        self.bt_play = tk.Button(b, text="▶  Começar", command=self.alternar, **estilo)
        self.bt_play.pack(side="left", padx=(6, 0))
        tk.Button(b, text="⟲", command=self.reiniciar, **estilo).pack(side="left")
        self.bt_modo = tk.Button(b, text="", command=self._proximo_modo, **estilo)
        self.bt_modo.pack(side="left")
        tk.Button(b, text="✎ Editar", command=self.editar, **estilo).pack(side="left")
        tk.Button(b, text="A−", command=lambda: self._tamanho(-4), **estilo).pack(side="left")
        tk.Button(b, text="A+", command=lambda: self._tamanho(4), **estilo).pack(side="left")
        self.status = tk.Label(b, text="", bg=BARRA, fg=SUAVE, font=("Segoe UI", 9))
        self.status.pack(side="right", padx=10)
        self.mic = tk.Canvas(b, width=64, height=14, bg=BARRA, highlightthickness=0)
        self.mic.pack(side="right")
        self._atualizar_botoes()

    def _atualizar_botoes(self):
        self.bt_play.config(text="⏸  Pausar" if getattr(self, "rodando", False) else "▶  Começar")
        extra = f" · {self.cfg['velocidade']} ppm" if self.cfg["modo"] != "voz" else ""
        self.bt_modo.config(text=f"◎ {MODOS[self.cfg['modo']]}{extra}")

    # ---------- texto ----------
    def definir_texto(self, texto: str):
        self.texto = texto.strip() or ROTEIRO_EXEMPLO
        self.acomp = Acompanhador(self.texto)
        self._paragrafos = [p.split() for p in self.texto.split("\n")]
        self.pos_continua = 0.0  # para os modos sem voz
        self._diagramar()

    def _diagramar(self):
        """Calcula a posição de cada palavra (quebra de linha própria, para rolar suave)."""
        w = max(200, self.tela.winfo_width())
        self.fonte = tkfont.Font(family="Segoe UI Semibold", size=-int(self.cfg["tamanho"]))
        margem, espaco = 48, self.fonte.measure(" ")
        altura = int(self.cfg["tamanho"] * 1.45)
        self.caixas, x, y = [], margem, 0
        for par in self._paragrafos:
            if not par:
                y += altura // 2
                continue
            for p in par:
                larg = self.fonte.measure(p)
                if x + larg > w - margem and x > margem:
                    x, y = margem, y + altura
                self.caixas.append((p, x, y, larg))
                x += larg + espaco
            x, y = margem, y + altura
        self.altura_linha = altura

    # ---------- voz ----------
    def _preparar_voz(self):
        if self._ouvido_fabrica:
            self.ouvido = self._ouvido_fabrica(self._ao_ouvir)
            self._msg("Pronto. Aperte espaço e comece a falar.")
            return
        from . import voz
        try:
            self._msg("Baixando o modelo de voz em português (50 MB, só na 1ª vez)…")
            caminho = voz.baixar_modelo(PASTA, lambda f: self._msg(f"Baixando o modelo de voz… {f:.0%}"))
            self._msg("Carregando o reconhecimento de voz…")
            self.ouvido = voz.Ouvido(caminho, self._ao_ouvir)
            self.ouvido.abrir()
            self._msg("Pronto. Aperte espaço e comece a falar.")
        except Exception as e:
            self._msg(f"Sem voz ({str(e)[:60]}). Use o modo Rolagem fixa.")

    def _ao_ouvir(self, texto: str, terminou: bool):
        if self.rodando and self.cfg["modo"] == "voz":
            self.acomp.ouvir(texto)
        if terminou:
            self.acomp._frase_anterior = []

    def _msg(self, texto: str):
        self.janela.after(0, lambda: self.status.config(text=texto))

    # ---------- controles ----------
    def alternar(self):
        self.rodando = not self.rodando
        if self.ouvido:
            self.ouvido.ligado = self.rodando
        self._msg("Ouvindo…" if self.rodando and self.cfg["modo"] == "voz" else ("Rolando…" if self.rodando else "Pausado"))
        self._atualizar_botoes()

    def reiniciar(self):
        self.acomp.reiniciar(0)
        self.pos_continua = 0.0
        self.deslocamento = self.alvo = 0.0

    def _proximo_modo(self):
        ordem = list(MODOS)
        self.cfg["modo"] = ordem[(ordem.index(self.cfg["modo"]) + 1) % len(ordem)]
        self.pos_continua = float(self.acomp.pos)
        self._atualizar_botoes()
        self._salvar()

    def _velocidade(self, d):
        self.cfg["velocidade"] = max(60, min(260, self.cfg["velocidade"] + d))
        self._atualizar_botoes()
        self._salvar()

    def _tamanho(self, d):
        self.cfg["tamanho"] = max(20, min(96, self.cfg["tamanho"] + d))
        self._diagramar()
        self._salvar()

    def _rolar_manual(self, linhas):
        indice = self._indice_atual() + int(linhas * 6)
        self._ir_para(indice)

    def _clique(self, e):
        y = e.y + self.deslocamento - self._linha_leitura()
        mais_perto = min(range(len(self.caixas)), key=lambda i: abs(self.caixas[i][2] + self.altura_linha / 2 - y) * 4 + abs(self.caixas[i][1] + self.caixas[i][3] / 2 - e.x), default=0)
        self._ir_para(mais_perto)

    def _ir_para(self, indice):
        indice = max(0, min(indice, len(self.caixas)))
        self.acomp.reiniciar(indice)
        self.pos_continua = float(indice)

    def _indice_atual(self) -> int:
        return self.acomp.pos if self.cfg["modo"] == "voz" else int(self.pos_continua)

    def editar(self):
        ed = tk.Toplevel(self.janela, bg=FUNDO)
        ed.title("Seu roteiro")
        ed.attributes("-topmost", True)
        ed.geometry("720x520")
        caixa = tk.Text(ed, wrap="word", font=("Segoe UI", 13), bg="#15181E", fg=FUTURO, insertbackground=FUTURO, bd=0, padx=18, pady=14, undo=True)
        caixa.insert("1.0", self.texto)
        rodape = tk.Frame(ed, bg=FUNDO)
        rodape.pack(side="bottom", fill="x", pady=10, padx=12)
        caixa.pack(fill="both", expand=True, padx=12, pady=(12, 0))

        def abrir():
            arq = filedialog.askopenfilename(parent=ed, filetypes=[("Texto", "*.txt *.md"), ("Todos", "*.*")])
            if arq:
                caixa.delete("1.0", "end")
                caixa.insert("1.0", open(arq, encoding="utf-8", errors="replace").read())

        def usar():
            texto = caixa.get("1.0", "end")
            with open(ROTEIRO, "w", encoding="utf-8") as f:
                f.write(texto)
            self.definir_texto(texto)
            self.reiniciar()
            ed.destroy()

        estilo = dict(bd=0, relief="flat", font=("Segoe UI Semibold", 10), padx=16, pady=8, cursor="hand2")
        tk.Button(rodape, text="Usar este roteiro", command=usar, bg=DESTAQUE, fg="#1A1005", activebackground="#FFA266", **estilo).pack(side="right")
        tk.Button(rodape, text="Abrir arquivo .txt…", command=abrir, bg="#232833", fg=FUTURO, activebackground="#2D3340", activeforeground=FUTURO, **estilo).pack(side="right", padx=8)
        tk.Label(rodape, text="Dica: frases curtas e um parágrafo por ideia ficam mais fáceis de ler.", bg=FUNDO, fg=SUAVE, font=("Segoe UI", 9)).pack(side="left")
        caixa.focus_set()

    def _salvar(self):
        try:
            self.cfg["geometria"] = self.janela.geometry()
            json.dump(self.cfg, open(CONFIG, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        except OSError:
            pass

    def fechar(self):
        self._salvar()
        if self.ouvido:
            self.ouvido.fechar()
        self.janela.destroy()

    # ---------- desenho ----------
    def _linha_leitura(self) -> float:
        # a linha atual fica no primeiro terço: perto da câmera, com o que vem depois visível
        return max(self.altura_linha * 0.6, self.tela.winfo_height() * 0.28)

    def _quadro(self):
        agora = time.time()
        dt, self._ultimo = min(0.1, agora - self._ultimo), agora
        modo = self.cfg["modo"]
        if self.rodando and modo != "voz":
            falando = self.ouvido is not None and self.ouvido.nivel > 0.08
            if modo == "rolagem" or falando:
                self.pos_continua = min(len(self.caixas), self.pos_continua + self.cfg["velocidade"] / 60 * dt)
        indice = self._indice_atual()

        if self.caixas:
            ref = self.caixas[min(indice, len(self.caixas) - 1)][2]
            self.alvo = ref
        self.deslocamento += (self.alvo - self.deslocamento) * min(1, dt * 6)

        c = self.tela
        c.delete("all")
        topo = self._linha_leitura() - self.deslocamento
        h = c.winfo_height()
        for i, (p, x, y, larg) in enumerate(self.caixas):
            yy = topo + y
            if yy < -self.altura_linha or yy > h:
                continue
            if i == indice:
                c.create_rectangle(x - 6, yy + 2, x + larg + 6, yy + self.altura_linha - 4, fill=DESTAQUE, outline="")
                cor = "#1A1005"
            else:
                cor = DITO if i < indice else FUTURO
            c.create_text(x, yy + self.altura_linha / 2, text=p, anchor="w", fill=cor, font=self.fonte)
        # faixa de leitura e degradê nas bordas
        ly = self._linha_leitura()
        c.create_polygon(10, ly + 6, 22, ly + self.altura_linha / 2, 10, ly + self.altura_linha - 6, fill=DESTAQUE, outline="")
        if self.acomp.terminou and modo == "voz" or (modo != "voz" and self.pos_continua >= len(self.caixas)):
            c.create_text(c.winfo_width() / 2, h - 30, text="Fim do roteiro · aperte ⟲ para voltar ao começo", fill=SUAVE, font=("Segoe UI", 11))

        # medidor do microfone
        self.mic.delete("all")
        n = self.ouvido.nivel if self.ouvido and self.rodando else 0
        for k in range(8):
            ativo = n * 8 > k
            self.mic.create_rectangle(k * 8, 3, k * 8 + 5, 11, fill=(DESTAQUE if ativo else "#2A2F38"), outline="")
        self.janela.after(16, self._quadro)

    def rodar(self):
        self.janela.mainloop()


def principal():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    Teleprompter().rodar()
