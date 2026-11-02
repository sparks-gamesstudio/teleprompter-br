"""Microfone + reconhecimento offline (Vosk) numa thread separada."""

import json
import os
import queue
import ssl
import threading
import urllib.request
import zipfile

import numpy as np

URL_MODELO = "https://alphacephei.com/vosk/models/vosk-model-small-pt-0.3.zip"
NOME_MODELO = "vosk-model-small-pt-0.3"
TAXA = 16000


def baixar_modelo(pasta: str, progresso=lambda f: None) -> str:
    destino = os.path.join(pasta, NOME_MODELO)
    if os.path.isdir(destino):
        return destino
    os.makedirs(pasta, exist_ok=True)
    zip_tmp = destino + ".zip.parcial"
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = None
    with urllib.request.urlopen(URL_MODELO, context=ctx, timeout=60) as r, open(zip_tmp, "wb") as f:
        total = int(r.headers.get("Content-Length", 0)) or 1
        lido = 0
        while bloco := r.read(1 << 16):
            f.write(bloco)
            lido += len(bloco)
            progresso(lido / total)
    with zipfile.ZipFile(zip_tmp) as z:
        z.extractall(pasta)
    os.remove(zip_tmp)
    return destino


class Ouvido:
    """Escuta o microfone e entrega (texto_parcial, frase_terminou) para quem quiser."""

    def __init__(self, caminho_modelo: str, ao_ouvir, microfone=None):
        from vosk import KaldiRecognizer, Model, SetLogLevel
        SetLogLevel(-1)
        self.reconhecedor = KaldiRecognizer(Model(caminho_modelo), TAXA)
        self.ao_ouvir = ao_ouvir
        self.microfone = microfone
        self.fila: queue.Queue = queue.Queue()
        self.nivel = 0.0
        self.ligado = False
        self._fluxo = None
        threading.Thread(target=self._trabalhar, daemon=True).start()

    def _callback(self, dados, quadros, tempo, status):
        if self.ligado:
            self.fila.put(bytes(dados))
        amostras = np.frombuffer(dados, dtype=np.int16).astype(np.float32) / 32768
        self.nivel = min(1.0, float(np.sqrt(np.mean(amostras ** 2))) * 10)

    def _trabalhar(self):
        while True:
            dados = self.fila.get()
            if dados is None:
                continue
            if self.reconhecedor.AcceptWaveform(dados):
                self.ao_ouvir(json.loads(self.reconhecedor.Result()).get("text", ""), True)
            else:
                self.ao_ouvir(json.loads(self.reconhecedor.PartialResult()).get("partial", ""), False)

    def abrir(self):
        import sounddevice as sd
        self._fluxo = sd.RawInputStream(samplerate=TAXA, blocksize=1600, dtype="int16", channels=1,
                                        device=self.microfone, callback=self._callback)
        self._fluxo.start()

    def alimentar(self, dados: bytes):
        """Para testes: manda áudio de um arquivo em vez do microfone."""
        amostras = np.frombuffer(dados, dtype=np.int16).astype(np.float32) / 32768
        self.nivel = min(1.0, float(np.sqrt(np.mean(amostras ** 2))) * 10) if len(amostras) else 0
        if self.ligado:
            self.fila.put(dados)

    def fechar(self):
        if self._fluxo:
            self._fluxo.stop()
            self._fluxo.close()
