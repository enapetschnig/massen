"""Guard: deterministischer Geometrie-Umfang (nachzeichnen.geometrie_umfang).

Sichert den Umfang-Hebel für Pläne OHNE U-Stempel (Polierpläne). Am Angerer
byte-exakt validiert: mittlerer |Fehler| 3,6 %. Diese Tests nageln die reinen
Formel-Invarianten fest, damit die Genauigkeit nicht wegregressiert.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import nachzeichnen as nz  # noqa: E402


def _approx(a, b, tol=0.05):
    return abs(a - b) <= tol * max(1.0, abs(b))


def test_isoperimetrisch_quadrat_exakt():
    # Quadrat F=16 → Seite 4 → U=16 (aspect 1)
    assert _approx(nz.isoperimetrischer_umfang(16, 1.0), 16.0, 0.001)


def test_isoperimetrisch_waechst_mit_seitenverhaeltnis():
    u1 = nz.isoperimetrischer_umfang(20, 1.0)
    u2 = nz.isoperimetrischer_umfang(20, 3.0)
    assert u2 > u1  # länglicher Raum → mehr Umfang bei gleicher Fläche
    assert nz.isoperimetrischer_umfang(0) is None


def test_rechteck_umfang_exakt():
    # 4m × 3m Rechteck (ptm=10 → 1m=10pt): F=12, U=14
    rect = [(0, 0), (40, 0), (40, 30), (0, 30)]
    r = nz.geometrie_umfang(rect, 12.0, 10.0)
    assert r is not None
    assert _approx(r["u_m"], 14.0, 0.02)
    assert _approx(r["a_poly_m2"], 12.0, 0.02)


def test_rdp_entfernt_kollineare_und_zacken():
    # Kollinearer Mittelpunkt (20,0) muss verschwinden
    poly = [(0, 0), (20, 0), (40, 0), (40, 20), (0, 20)]
    vereinfacht = nz._rdp(poly, 1.0)
    assert (20, 0) not in vereinfacht
    assert len(vereinfacht) < len(poly)


def test_zackiges_polygon_wird_nicht_massiv_ueberschaetzt():
    # 5m × 5m Raum (F=25, echter U=20), aber mit Säge-Zacken an der Oberkante.
    # Roher Polygon-Umfang wäre stark überhöht; das geom. Mittel mit der BBox-
    # Isoperimetrie (hier ~20) muss den Umfang nahe der Wahrheit halten.
    ptm = 10.0  # 1m = 10pt
    pts = [(0, 0), (50, 0), (50, 50)]
    x = 50
    while x > 0:  # gezackte Oberkante
        pts.append((x, 45))
        pts.append((x - 5, 50))
        x -= 10
    pts.append((0, 50))
    r = nz.geometrie_umfang(pts, 25.0, ptm)
    assert r is not None
    # roher Polygon-Umfang deutlich über 20 (Zacken), Blend muss näher an 20 sein
    assert r["u_poly_m"] >= r["u_m"]        # Blend zügelt die Überschätzung
    assert 18.0 <= r["u_m"] <= 26.0         # nahe am wahren U=20


def test_degenerierte_eingaben():
    assert nz.geometrie_umfang(None, 10, 10) is None
    assert nz.geometrie_umfang([(0, 0), (1, 1)], 10, 10) is None  # <3 Punkte
    assert nz.geometrie_umfang([(0, 0), (10, 0), (10, 10)], 10, 0) is None  # ptm=0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    fehler = 0
    for fn in fns:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
        except AssertionError as e:
            fehler += 1
            print(f"  ✗ {fn.__name__}: {e!r}")
    print(f"\n{len(fns) - fehler}/{len(fns)} grün")
    sys.exit(1 if fehler else 0)
