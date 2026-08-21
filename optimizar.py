#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Saca las imagenes incrustadas en base64 del HTML y las deja como archivos
sueltos, para que la pagina se vea al instante en vez de esperar a que baje
un HTML de 13 MB.

Uso:
    python optimizar.py                      # usa el la-taquera_N.html mas nuevo de Descargas
    python optimizar.py ruta/al/archivo.html # usa el archivo que le digas

Deja:
    index.html   ligero, con rutas a los archivos
    frames/      los fotogramas del video comercial (f000.jpg, f001.jpg, ...)
    img/         el resto de imagenes de la pagina
"""

import base64
import glob
import os
import re
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
DESCARGAS = os.path.join(os.path.expanduser("~"), "Downloads")

EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
}


def origen():
    """El HTML de entrada: el que pasen por argumento, o el mas nuevo de Descargas."""
    if len(sys.argv) > 1:
        return os.path.abspath(sys.argv[1])
    candidatos = glob.glob(os.path.join(DESCARGAS, "la-taquera*.html"))
    if not candidatos:
        sys.exit("No encontre ningun la-taquera*.html en %s" % DESCARGAS)
    return max(candidatos, key=os.path.getmtime)


def limpiar(carpeta):
    os.makedirs(carpeta, exist_ok=True)
    for f in os.listdir(carpeta):
        os.remove(os.path.join(carpeta, f))


def guardar(carpeta, nombre, mime, datos_b64):
    ruta = os.path.join(carpeta, nombre + EXT.get(mime, ".bin"))
    with open(ruta, "wb") as fh:
        fh.write(base64.b64decode(datos_b64))
    return os.path.getsize(ruta)


def main():
    entrada = origen()
    html = open(entrada, "r", encoding="utf-8").read()
    peso_antes = len(html.encode("utf-8"))
    print("Entrada: %s (%.1f MB)" % (entrada, peso_antes / 1048576))

    dir_frames = os.path.join(AQUI, "frames")
    dir_img = os.path.join(AQUI, "img")
    limpiar(dir_frames)
    limpiar(dir_img)

    # --- 1. Los fotogramas del showcase: const FRAMES = ["data:...", ...]; ---
    m = re.search(r"const\s+FRAMES\s*=\s*\[(.*?)\]\s*;", html, re.S)
    if not m:
        sys.exit("No encontre el array FRAMES en el HTML.")

    uris = re.findall(r"data:(image/[a-z+]+);base64,([A-Za-z0-9+/=]+)", m.group(1))
    if not uris:
        sys.exit("El array FRAMES no traia imagenes en base64.")

    bytes_frames = 0
    for i, (mime, datos) in enumerate(uris):
        bytes_frames += guardar(dir_frames, "f%03d" % i, mime, datos)

    ext_frame = EXT.get(uris[0][0], ".bin")
    nuevo_array = (
        "const FRAMES = Array.from({length: %d}, function(_, i){\n"
        "    return 'frames/f' + String(i).padStart(3, '0') + '%s';\n"
        "  });" % (len(uris), ext_frame)
    )
    html = html[: m.start()] + nuevo_array + html[m.end() :]
    print("Fotogramas: %d archivos, %.1f MB en frames/" % (len(uris), bytes_frames / 1048576))

    # --- 2. El resto de imagenes incrustadas (hero, chips, fondos...) ---
    contador = [0]
    bytes_img = [0]

    def reemplazar(match):
        mime, datos = match.group(1), match.group(2)
        # las muy pequenas (iconos) se quedan dentro: un archivo aparte costaria mas
        if len(datos) < 8000:
            return match.group(0)
        nombre = "i%03d" % contador[0]
        bytes_img[0] += guardar(dir_img, nombre, mime, datos)
        contador[0] += 1
        return "img/" + nombre + EXT.get(mime, ".bin")

    html = re.sub(r"data:(image/[a-z+]+);base64,([A-Za-z0-9+/=]+)", reemplazar, html)
    print("Otras imagenes: %d archivos, %.1f MB en img/" % (contador[0], bytes_img[0] / 1048576))

    # --- 3. Escribir el HTML ligero ---
    salida = os.path.join(AQUI, "index.html")
    with open(salida, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(html)

    peso_despues = os.path.getsize(salida)
    print(
        "\nindex.html: %.1f MB -> %.0f KB  (%.1f%% menos)"
        % (
            peso_antes / 1048576,
            peso_despues / 1024,
            100 - (peso_despues * 100.0 / peso_antes),
        )
    )


if __name__ == "__main__":
    main()
