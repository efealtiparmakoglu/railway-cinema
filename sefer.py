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
    if refs is not None:
        refs["_teget"] = X


def duman_havuzu(refs, adet=16):
    """Duman kürelerini trenden kopar (dünya uzayında yaşayacaklar)."""
    havuz = []
    for p in refs["duman"]:
        p.parent = None
        havuz.append(p)
    refs["duman"] = havuz
    return havuz


def gece_kur(refs, gece_cfg):
    """Gece seferi: on far spot'u + ateş kutusu parıltısı + sinyal lambası."""
    kok = refs["kok"]

    # on far: spot, lokomotif burnunda, +X ileriye
    spot_data = bpy.data.lights.new("OnFar", "SPOT")
    spot_data.energy = gece_cfg.get("far_guc", 6000)
    spot_data.spot_size = math.radians(38)
    spot_data.spot_blend = 0.35
    spot_data.color = (1.0, 0.9, 0.72)
    spot_data.shadow_soft_size = 0.08
    spot = bpy.data.objects.new("OnFar", spot_data)
    bpy.context.collection.objects.link(spot)
    spot.parent = kok
    spot.location = (6.05, 0, 2.30)
    hedef = Vector((60, 0, 0.2))
    spot.rotation_euler = (hedef - Vector(spot.location)
                           ).to_track_quat("-Z", "Y").to_euler()
    # far lambasi gozu (emissive kucuk disk)
    m_far = bpy.data.materials.new("FarGozu")
    m_far.use_nodes = True
    nt = m_far.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (1.0, 0.93, 0.75, 1)
    em.inputs["Strength"].default_value = 14.0
    outn = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs["Emission"], outn.inputs["Surface"])
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.10, segments=20, ring_count=14,
                                         location=(6.28, 0, 2.30))
    goz = bpy.context.active_object
    goz.name = "FarGozu"
    bpy.ops.object.shade_smooth()
    goz.data.materials.append(m_far)
    goz.parent = kok

    # ates kutusu pariltisi: kabin alti turuncu emissive + point
    m_ates = bpy.data.materials.new("AtesKutusu")
    m_ates.use_nodes = True
    nt2 = m_ates.node_tree
    nt2.nodes.clear()
    em2 = nt2.nodes.new("ShaderNodeEmission")
    em2.inputs["Color"].default_value = (1.0, 0.32, 0.05, 1)
    em2.inputs["Strength"].default_value = 14.0
    out2 = nt2.nodes.new("ShaderNodeOutputMaterial")
    nt2.links.new(em2.outputs["Emission"], out2.inputs["Surface"])
    bpy.ops.mesh.primitive_cube_add(size=1, location=(-1.2, 0, 1.35))
    ates = bpy.context.active_object
    ates.name = "AtesKutusuPariltisi"
    ates.scale = (0.5, 1.1, 0.5)
    ates.data.materials.append(m_ates)
    ates.parent = kok
    p_data = bpy.data.lights.new("AtesNokta", "POINT")
    p_data.energy = 45
    p_data.color = (1.0, 0.38, 0.08)
    p_data.shadow_soft_size = 0.3
    p_nokta = bpy.data.objects.new("AtesNokta", p_data)
    bpy.context.collection.objects.link(p_nokta)
    p_nokta.parent = kok
    p_nokta.location = (-1.2, 0, 1.2)


def sinyal_kur(patika_obj, s, taraf=1):
    """Hat kenari sinyali: gri direk + kirmizi emissive goz."""
    konum, teget, sag, cant = ray.cerceve(patika_obj, s)
    yan = taraf * 3.1
    mx, my = konum.x + sag.x * yan, konum.y + sag.y * yan
    m_govde = bpy.data.materials.new("SinyalGovde")
    m_govde.use_nodes = True
    b = m_govde.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.12, 0.12, 0.13, 1)
    bpy.ops.mesh.primitive_cylinder_add(radius=0.09, depth=3.6,
                                        location=(mx, my, 1.8), vertices=16)
    direk = bpy.context.active_object
    direk.name = "SinyalDirek"
    direk.data.materials.append(m_govde)
    m_goz = bpy.data.materials.new("SinyalGoz")
    m_goz.use_nodes = True
    nt = m_goz.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (1.0, 0.05, 0.03, 1)
    em.inputs["Strength"].default_value = 30.0
    outn = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs["Emission"], outn.inputs["Surface"])
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.14, segments=20, ring_count=14,
                                         location=(mx, my, 3.72))
    goz = bpy.context.active_object
    goz.name = "SinyalGoz"
    bpy.ops.object.shade_smooth()
    goz.data.materials.append(m_goz)
    p_data = bpy.data.lights.new("SinyalIsik", "POINT")
    p_data.energy = 12
    p_data.color = (1.0, 0.1, 0.05)
    p_nokta = bpy.data.objects.new("SinyalIsik", p_data)
    bpy.context.collection.objects.link(p_nokta)
    p_nokta.location = (mx, my, 3.72)


def duman_guncelle(havuz, kaynak_dunya, t, ruzgar=(-1.6, 0.35)):
    adet = len(havuz)
    periyot = 0.42
    for i, p in enumerate(havuz):
        faz = ((t / periyot + i / adet) % 1.0)
        yas = faz * 2.8
        p.location = (kaynak_dunya.x + ruzgar[0] * yas + 0.35 * math.sin(yas * 2 + i),
                      kaynak_dunya.y + ruzgar[1] * yas + 0.3 * math.cos(yas * 1.7 + i * 2),
                      kaynak_dunya.z + 1.8 * yas)
        olcek = 0.28 + 1.5 * yas
        p.scale = (olcek, olcek, olcek * 0.8)
        m = p.data.materials[0]
        if m.use_nodes:
            for dugum in m.node_tree.nodes:
                if dugum.type == "VOLUME_PRINCIPLED":
                    dugum.inputs["Density"].default_value = \
                        0.8 * (1.0 - faz) ** 1.5
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

    # ---------------- cok arac: loko+tender + vagon dizisi
    # her aracin kendi koku var; offset = kuyrugun s0'dan geriye uzakligi
    LOKO_ON = 6.2
    LOKO_KUYRUK = -10.3  # tender sonu
    araclar = [{"kok": refs["kok"], "teker_refs": refs["tekerler"],
                "tip": "loko", "offset": -LOKO_ON}]
    on_son = LOKO_KUYRUK
    for i, vspec in enumerate(sefer.get("vagonlar", [])):
        vkok, vteker, vboy = tren.vagon_kur(f"Vagon{i}",
                                            vspec.get("tip", "yolcu"),
                                            vspec.get("boy", 8.6))
        offset = on_son - 0.5 - vboy / 2 - vboy / 2  # kuyruk - vagon merkezi
        offset = on_son - 0.5 - vboy / 2
        araclar.append({"kok": vkok, "teker_refs": vteker,
                        "tip": "vagon", "offset": offset})
        on_son = offset - vboy / 2
    for arac in araclar:
        arac["s"] = s0 + arac["offset"]
        trene_koku_ver(arac["kok"], None, arac["s"], patika_obj)
    print(f"  [tren] {len(araclar)} arac, uzunluk {LOKO_ON - on_son:.1f} m")
    havuz = duman_havuzu(refs)

    gece = sefer.get("gece")
    if gece:
        gece_kur(refs, gece)
        if gece.get("sinyal_s") is not None:
            sinyal_kur(patika_obj, gece["sinyal_s"],
                       gece.get("sinyal_taraf", 1))

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
        for arac in araclar:
            if arac["tip"] == "loko":
                tren.poz(refs, arac["s"] / TEKER_R)
            else:
                tren.vagon_pozu(arac["teker_refs"], arac["s"])
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
        for arac in araclar:
            arac_s = s + arac["offset"]
            trene_koku_ver(arac["kok"], None, arac_s, patika_obj)
            if arac["tip"] == "loko":
                tren.poz(refs, arac_s / TEKER_R)
            else:
                tren.vagon_pozu(arac["teker_refs"], arac_s)
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
