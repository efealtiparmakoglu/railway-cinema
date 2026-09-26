#!/usr/bin/env python3
# Blender icinde: blender --background --python sefer.py -- --scene scenes/gecit.json [--gif 48]
"""railway-cinema — iki evrenin birleşimi: rail-cinema'nın sonsuz hattı
üzerinde train-cinema'nın fonksiyonel lokomotifi sefere çıkar.

Fizik: tekerler KAYSIZ yuvarlanır — theta = (v*t + s0) / TEKER_R.
Virajda tren süpereleyisyonla birlikte yatar (hat cervevesiyle ayni roll).
"""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys

import bpy
from mathutils import Matrix, Vector

BURASI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BURASI)
sys.path.insert(0, os.path.join(BURASI, "..", "rail-cinema"))
sys.path.insert(0, os.path.join(BURASI, "..", "train-cinema"))

from patika import Parca, Patika  # noqa: E402
import ray  # noqa: E402
import tren  # noqa: E402
from mekanik import TEKER_R  # noqa: E402


# ---------------------------------------------------------------- sahne (ayni aile)

def gunes_vektoru(el_rad, az_rad):
    return Vector((math.cos(el_rad) * math.sin(az_rad),
                   -math.cos(el_rad) * math.cos(az_rad),
                   math.sin(el_rad)))


def temiz():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def kamera_kur(konum, hedef, lens=50):
    cam = bpy.data.cameras.new("Cam")
    cam.lens = lens
    co = bpy.data.objects.new("kamera", cam)
    bpy.context.collection.objects.link(co)
    co.location = konum
    yon = Vector(hedef) - Vector(konum)
    co.rotation_euler = yon.to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = co
    return co


def govcem_diski(cfg, cam_konum):
    d = cfg["sun"].get("disk")
    if not d:
        return
    el = math.radians(cfg["sun"]["elevation_deg"])
    az = math.radians(cfg["sun"]["azimuth_deg"])
    merkez = gunes_vektoru(el, az) * d.get("distance", 500)
    bpy.ops.mesh.primitive_circle_add(vertices=96, radius=d.get("radius", 4.0),
                                      fill_type="NGON", location=merkez)
    disk = bpy.context.active_object
    disk.name = "govcem_diski"
    yon = Vector(cam_konum) - merkez
    disk.rotation_euler = yon.to_track_quat("Z", "Y").to_euler()
    m = bpy.data.materials.new("DiskMat")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    renk = list(d.get("color", (1.0, 0.5, 0.2)))
    if len(renk) == 3:
        renk.append(1.0)
    em.inputs["Color"].default_value = renk
    em.inputs["Strength"].default_value = d.get("strength", 6.0)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    disk.data.materials.append(m)


def sahne_kur(cfg):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.compute_device_type = "METAL"
        prefs.get_devices()
        for dv in prefs.devices:
            dv.use = True
        sc.cycles.device = "GPU"
    except Exception as e:
        print("  [uyari] GPU:", e)
    sc.cycles.samples = cfg["render"].get("samples", 128)
    sc.cycles.use_denoising = True
    sc.render.resolution_x = cfg["render"].get("width", 1600)
    sc.render.resolution_y = cfg["render"].get("height", 900)
    sc.view_settings.view_transform = "Filmic"
    sc.view_settings.exposure = cfg["render"].get("exposure", 0.0)
    look = cfg["render"].get("look")
    if look:
        try:
            sc.view_settings.look = look
        except Exception:
            pass

    dunya = bpy.data.worlds.new("Gokyuzu")
    sc.world = dunya
    dunya.use_nodes = True
    nt = dunya.node_tree
    nt.nodes.clear()
    sky = nt.nodes.new("ShaderNodeTexSky")
    sky.sky_type = "HOSEK_WILKIE"
    sun_elev = math.radians(cfg["sun"]["elevation_deg"])
    sun_azim = math.radians(cfg["sun"]["azimuth_deg"])
    sky.sun_elevation = sun_elev
    skycfg = cfg.get("sky", {})
    try:
        sky.turbidity = skycfg.get("turbidity", 3.0)
    except Exception:
        pass
    sky.sun_rotation = sun_azim + math.radians(skycfg.get("az_offset", 0))
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = skycfg.get("strength", 1.0)
    out = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])

    sun_data = bpy.data.lights.new("gunes", "SUN")
    sun_data.energy = cfg["sun"].get("strength", 4.0)
    sun_data.angle = math.radians(1.2)
    sun_data.color = tuple(cfg["sun"].get("color", (1.0, 0.85, 0.7)))
    sun_obj = bpy.data.objects.new("gunes_isigi", sun_data)
    bpy.context.collection.objects.link(sun_obj)
    sun_obj.rotation_euler = gunes_vektoru(sun_elev, sun_azim).to_track_quat(
        "Z", "Y").to_euler()
    return sc


def zemin_kur(cfg):
    z = cfg.get("zemin", {})
    m = bpy.data.materials.new("Zemin")
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    renk = z.get("color", (0.06, 0.065, 0.04))
    b.inputs["Base Color"].default_value = (*renk, 1)
    b.inputs["Roughness"].default_value = z.get("roughness", 0.95)
    bpy.ops.mesh.primitive_plane_add(size=z.get("boyut", 2400), location=(0, 0, -0.86))
    o = bpy.context.active_object
    o.name = "Zemin"
    o.data.materials.append(m)
    if z.get("tepeler"):
        import random
        rng = random.Random(z.get("tepe_tohum", 5))
        mt = bpy.data.materials.new("Tepe")
        mt.use_nodes = True
        bt = mt.node_tree.nodes["Principled BSDF"]
        rt = z.get("tepe_renk", (0.045, 0.05, 0.05))
        bt.inputs["Base Color"].default_value = (*rt, 1)
        bt.inputs["Roughness"].default_value = 0.95
        for i in range(z.get("tepe_adet", 8)):
            aci = rng.uniform(0, 2 * math.pi)
            mesafe = rng.uniform(500, 1100)
            bpy.ops.mesh.primitive_uv_sphere_add(
                radius=rng.uniform(60, 130), segments=24, ring_count=14,
                location=(math.cos(aci) * mesafe, math.sin(aci) * mesafe, -60))
            t = bpy.context.active_object
            t.name = f"Tepe{i}"
            t.scale = (rng.uniform(1.8, 3.4), rng.uniform(1.2, 2.2),
                       rng.uniform(0.55, 0.85))
            t.data.materials.append(mt)


# ---------------------------------------------------------------- tren yerlesimi

def trene_koku_ver(kok, refs, s, patika_obj):
    """Treni patikaya oturt: konum + yaw + cant roll (matrix dogrudan)."""
    konum, teget, sag, cant, _ = patika_obj.cerceve(s)
    r = cant
    X = Vector((teget[0], teget[1], 0.0))
    Y = Vector((sag[0] * math.cos(r), sag[1] * math.cos(r), math.sin(r)))
    Z = Vector((-sag[0] * math.sin(r), -sag[1] * math.sin(r), math.cos(r)))
    M = Matrix((
        (X.x, Y.x, Z.x, konum[0]),
        (X.y, Y.y, Z.y, konum[1]),
        (X.z, Y.z, Z.z, -0.012 + 0.001),
        (0.0, 0.0, 0.0, 1.0),
    ))
    kok.matrix_world = M
    refs["_teget"] = X


def duman_havuzu(refs, adet=16):
    """Duman kürelerini trenden kopar (dünya uzayında yaşayacaklar)."""
    havuz = []
    for p in refs["duman"]:
        p.parent = None
        havuz.append(p)
    refs["duman"] = havuz
    return havuz


def duman_guncelle(havuz, kaynak_dunya, t, ruzgar=(-1.6, 0.35)):
    n = len(havuz)
    periyot = 0.42
    for i, p in enumerate(havuz):
        faz = ((t / periyot + i / n) % 1.0)
        yas = faz * 2.8
        p.location = (kaynak_dunya.x + ruzgar[0] * yas + 0.35 * math.sin(yas * 2 + i),
                      kaynak_dunya.y + ruzgar[1] * yas + 0.3 * math.cos(yas * 1.7 + i * 2),
                      kaynak_dunya.z + 1.8 * yas)
        olcek = 0.28 + 1.5 * yas
        p.scale = (olcek, olcek, olcek * 0.8)
        m = p.data.materials[0]
        b = m.node_tree.nodes.get("Principled BSDF")
        if b and "Alpha" in b.inputs:
            b.inputs["Alpha"].default_value = max(0.03, 0.5 * (1.0 - faz))
        p.visible_shadow = False


# ---------------------------------------------------------------- ana

def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", required=True)
    ap.add_argument("--gif", type=int, default=0)
    ap.add_argument("--fps", type=int, default=12)
    a = ap.parse_args(args)

    cfg = json.load(open(a.scene, encoding="utf-8"))
    if os.environ.get("HIZLI") == "1":
        cfg["render"] = {**cfg.get("render", {}), "width": 800, "height": 450,
                         "samples": 32}
        cfg["output"] = "/tmp/onizleme_sefer_" + os.path.basename(a.scene).replace(".json", ".png")
        print("  [HIZLI] onizleme ->", cfg["output"])
    if a.gif:
        cfg["render"] = {**cfg.get("render", {}), "width": 1280, "height": 720,
                         "samples": 48}

    temiz()
    sc = sahne_kur(cfg)
    zemin_kur(cfg)

    parcalar = [Parca(p["tip"], uzunluk=p.get("uzunluk", 0),
                      yaricap=p.get("yaricap", 0), aci_deg=p.get("aci_deg", 0),
                      yon=p.get("yon", 1), v_kmh=p.get("v_kmh", 0),
                      cant_mm=p.get("cant_mm"))
                for p in cfg["patika"]["segments"]]
    patika_obj = Patika(parcalar)
    print(f"  [patika] uzunluk={patika_obj.uzunluk:.1f} m")

    kok_hat = bpy.data.objects.new("Hat", None)
    bpy.context.collection.objects.link(kok_hat)
    ray.hat_kur(patika_obj, cfg.get("hat", {}), kok_hat)

    refs = tren.kur()

    sefer = cfg["sefer"]
    s0 = sefer.get("s", 60.0)
    v = sefer.get("hiz", 9.0)
    trene_koku_ver(refs["kok"], refs, s0, patika_obj)
    havuz = duman_havuzu(refs)

    cam_cfg = cfg["camera"]
    cam_obj = kamera_kur((0, 0, 10), (0, 10, 0), cam_cfg.get("lens", 40))
    if a.gif:
        out = os.path.splitext(cfg["output"])[0] + ".gif"
    else:
        out = cfg["output"]
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    def kamera_takip(s_tren):
        mod = cam_cfg.get("mode", "sabit")
        if mod == "sabit":
            cam_obj.location = Vector(cam_cfg["position"])
            hedef = Vector(cam_cfg["look_at"])
        elif mod == "kacak":  # yandan sabit nokta, tren onden gecer
            konum, _, sag, _ = ray.cerceve(patika_obj, s_tren + cam_cfg.get("bakis_s", 0))
            cam_obj.location = konum + sag * cam_cfg.get("yanal", 10.0) + \
                Vector((0, 0, cam_cfg.get("yukseklik", 2.6)))
            hedef = konum + Vector((0, 0, cam_cfg.get("bak_yukseklik", 1.8)))
        else:  # "kovala" — arkadan takip
            kpos, _, ksag, _ = ray.cerceve(patika_obj, s_tren - cam_cfg.get("geri", 16.0))
            cam_obj.location = kpos + ksag * cam_cfg.get("yanal", 8.0) + \
                Vector((0, 0, cam_cfg.get("yukseklik", 2.8)))
            onu, _, _, _ = ray.cerceve(patika_obj, s_tren + 6.0)
            hedef = onu + Vector((0, 0, 1.8))
        yon = hedef - cam_obj.location
        cam_obj.rotation_euler = yon.to_track_quat("-Z", "Y").to_euler()

    ilk_pos, ilk_hedef = (None, None)
    if cam_cfg.get("mode") == "sabit":
        kamera_takip(s0)
        ilk_pos = cam_cfg["position"]
    else:
        kamera_takip(s0)
        ilk_pos = tuple(cam_obj.location)
    govcem_diski(cfg, ilk_pos)

    if not a.gif:
        tren.poz(refs, sefer.get("theta", 0.8))
        duman_guncelle(havuz, refs["kok"].matrix_world @ Vector((5.15, 0, 4.35)),
                       sefer.get("duman_t", 1.3))
        sc.render.filepath = out
        bpy.ops.render.render(write_still=True)
        print(f"== BİTTİ -> {out}")
        return

    tmp = out + ".frames"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    for f in range(a.gif):
        t = f / a.fps
        s = s0 + v * t
        trene_koku_ver(refs["kok"], refs, s, patika_obj)
        # kaysız yuvarlanma: teker acisi = gidilen yol / teker yaricapi
        tren.poz(refs, s / TEKER_R)
        kaynak = refs["kok"].matrix_world @ Vector((5.15, 0, 4.35))
        duman_guncelle(havuz, kaynak, t + sefer.get("duman_t", 0.0))
        kamera_takip(s)
        sc.render.filepath = f"{tmp}/f{f:05d}.png"
        bpy.ops.render.render(write_still=True)
        print(f"  kare {f + 1}/{a.gif} s={s:.1f}")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(a.fps),
                    "-i", f"{tmp}/f%05d.png",
                    "-vf", "palettegen=max_colors=256:stats_mode=diff",
                    f"{tmp}/pal.png"], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(a.fps),
                    "-i", f"{tmp}/f%05d.png", "-i", f"{tmp}/pal.png",
                    "-lavfi", "paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle",
                    "-loop", "0", out], check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"== BİTTİ -> {out}")


if __name__ == "__main__":
    main()
