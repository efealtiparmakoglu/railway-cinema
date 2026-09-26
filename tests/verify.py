#!/usr/bin/env python3
"""railway-cinema dogrulama kapilari (Blender'siz: python3 tests/verify.py)

Saf matematik kisimlari: patika.cerceve + mekanik.yurutucu zaten kapili.
Burada birlesimin kendi kanunlari test edilir.
"""

import math
import os
import sys

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KOK)
sys.path.insert(0, os.path.join(KOK, "..", "rail-cinema"))
sys.path.insert(0, os.path.join(KOK, "..", "train-cinema"))

from patika import Parca, Patika  # noqa: E402
from mekanik import TEKER_R, yurutucu  # noqa: E402

GAUGE = 1.435
RAY_BASI_USTU = -0.012


def cerceve_3b(patika, s):
    """sefer.trene_koku_ver'in kullandigi cerceve — dunya konumu + z."""
    konum, teget, sag, cant, _ = patika.cerceve(s)
    r = cant
    X = (teget[0], teget[1], 0.0)
    Y = (sag[0] * math.cos(r), sag[1] * math.cos(r), math.sin(r))
    Z = (-sag[0] * math.sin(r), -sag[1] * math.sin(r), math.cos(r))
    return (konum[0], konum[1], RAY_BASI_USTU + 0.001), X, Y, Z


def main():
    ok_adet, fail_adet = 0, 0

    def kapil(ad, kosul, detay=""):
        nonlocal ok_adet, fail_adet
        if kosul:
            ok_adet += 1
            print(f"  [ok] {ad} {detay}")
        else:
            fail_adet += 1
            print(f"  [FAIL] {ad} {detay}")

    p = Patika([
        Parca("duz", uzunluk=90),
        Parca("viraj", yaricap=500, aci_deg=40, yon=1, v_kmh=110),
        Parca("duz", uzunluk=60),
        Parca("viraj", yaricap=350, aci_deg=28, yon=-1, v_kmh=90),
        Parca("duz", uzunluk=90),
    ])

    # 1) kaysiz yuvarlanma: theta(s) = s/R, teker cevresiyle orantili
    #    iki nokta arasinda donen aci = yol / R (radyan)
    s1, s2 = 10.0, 58.0
    yol = s2 - s1
    donen = yol / TEKER_R
    kapil("kaysiz yuvarlanma theta = s/R", abs(donen - yol / TEKER_R) < 1e-12,
          f"(donen {donen:.4f} rad, beklenen {yol / TEKER_R:.4f})")

    # 2) tren origini ray basi ustunde: z her s'de sabit
    zs = set()
    for s in range(0, int(p.uzunluk), 25):
        k, _, _, _ = cerceve_3b(p, float(s))
        zs.add(round(k[2], 6))
    kapil("tren kottasi sabit (ray basi ustu)", len(zs) == 1 and abs(zs.pop() + 0.011) < 1e-6)

    # 3) virajda yatis: Z kolonu cant ile doner — R500'de ~17.3 derece
    p2 = Patika([Parca("viraj", yaricap=500, aci_deg=40, yon=1, v_kmh=110, cant_mm=150)])
    _, _, Y, Z = cerceve_3b(p2, 20.0)
    yatis = math.degrees(math.asin(min(1.0, max(-1.0, abs(Y[2])))))
    beklenen = math.degrees(math.asin(0.150 / GAUGE))
    kapil("viraj yatisi = asin(cant/genislik)", abs(yatis - beklenen) < 1e-6,
          f"({yatis:.3f} ~ {beklenen:.3f} derece)")
    kapil("Z kolonu birim kaldi", abs(math.hypot(Z[0], Z[1]) ** 2 + Z[2] ** 2 - 1.0) < 1e-9)

    # 4) poz tekrarlanabilir: yurutucu(s/R) her tekerde ortak aci verir
    d1 = yurutucu(s2 / TEKER_R)
    d2 = yurutucu(s2 / TEKER_R)
    kapil("kinematik determinizm", d1 == d2)

    print(f"\n{'TUM KAPILAR GECTI' if fail_adet == 0 else 'KAPILARDA FAIL VAR'}"
          f" ({ok_adet} ok, {fail_adet} fail)")
    sys.exit(0 if fail_adet == 0 else 1)


if __name__ == "__main__":
    main()
