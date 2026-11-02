"""Acompanha a fala dentro do roteiro, palavra por palavra.

O reconhecimento de voz erra ("Claude Code" vira "claudio coutinho"), então a
busca não exige palavras exatas: compara as últimas palavras ouvidas com uma
janela à frente do ponto atual e avança para o trecho mais parecido.
"""

import re
import unicodedata
from difflib import SequenceMatcher

NUMEROS = {
    "0": "zero", "1": "um", "2": "dois", "3": "tres", "4": "quatro", "5": "cinco", "6": "seis", "7": "sete",
    "8": "oito", "9": "nove", "10": "dez", "100": "cem", "1000": "mil",
}


def normalizar(palavra: str) -> str:
    p = unicodedata.normalize("NFKD", palavra.lower()).encode("ascii", "ignore").decode()
    p = re.sub(r"[^a-z0-9]", "", p)
    return NUMEROS.get(p, p)


def palavras(texto: str) -> list[str]:
    return texto.split()


def parecidas(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if len(a) <= 2 or len(b) <= 2:
        return 0.0
    r = SequenceMatcher(None, a, b).ratio()
    return r if r >= 0.72 else 0.0


class Acompanhador:
    def __init__(self, texto: str, olhar_a_frente: int = 30, ouvidas: int = 5):
        self.originais = palavras(texto)
        self.norm = [normalizar(p) for p in self.originais]
        self.pos = 0                 # índice da próxima palavra a ser dita
        self.frente = olhar_a_frente
        self.ouvidas = ouvidas
        self._frase_anterior: list[str] = []

    def reiniciar(self, pos: int = 0):
        self.pos = max(0, min(pos, len(self.norm)))
        self._frase_anterior = []

    def ouvir(self, frase: str) -> int:
        """Recebe o texto reconhecido da frase atual (parcial) e devolve a nova posição."""
        ditas = [n for n in (normalizar(p) for p in frase.split()) if n]
        if not ditas or ditas == self._frase_anterior:
            return self.pos
        self._frase_anterior = ditas
        cauda = ditas[-self.ouvidas:]

        melhor, melhor_fim = 0.0, None
        inicio = max(0, self.pos - 3)
        fim = min(len(self.norm), self.pos + self.frente)
        for fim_candidato in range(inicio + 1, fim + 1):
            # alinha a cauda ouvida terminando em fim_candidato (de trás para frente, com tolerância a uma palavra a mais ou a menos)
            pontos, i, j = 0.0, len(cauda) - 1, fim_candidato - 1
            while i >= 0 and j >= max(0, fim_candidato - len(cauda) - 2):
                s = parecidas(cauda[i], self.norm[j])
                if s:
                    pontos += s * (1.0 if len(self.norm[j]) > 3 else 0.6)
                    i -= 1; j -= 1
                elif i > 0 and parecidas(cauda[i - 1], self.norm[j]):
                    i -= 1                    # o reconhecedor inventou uma palavra
                else:
                    j -= 1                    # a pessoa pulou uma palavra
            # pequena preferência por não saltar muito à frente
            pontos -= (fim_candidato - self.pos) * 0.015
            if pontos > melhor:
                melhor, melhor_fim = pontos, fim_candidato

        # exige confiança: duas palavras boas, ou uma palavra longa logo à frente
        if melhor_fim is not None and (melhor >= 1.5 or (melhor >= 0.9 and melhor_fim - self.pos <= 2)):
            if melhor_fim > self.pos or self.pos - melhor_fim <= 2:
                self.pos = melhor_fim
        return self.pos

    @property
    def terminou(self) -> bool:
        return self.pos >= len(self.norm)
