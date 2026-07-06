"""Rohbau-Materialliste (Phase 1) — Faustformel-basierte Mengen-Schätzung.

Im Gegensatz zur ÖNORM-Putz/Estrich/Maler-LV (massen_logic.py) listet
dieses Modul Material-Mengen nach Bauteil-Bereichen auf:
  - Frostschürze
  - Bodenplatte
  - Mauerwerk EG (HLZ-Paletten pro Wandstärke)
  - Decke über EG
  - Attika
  - Säulen
  - Öffnungen (Ziegelüberlagen, Rolladenkästen)

WICHTIG — Phase 1 = grobe Schätzung:
  • Außenkontur wird aus Σ Raumfläche × Aufschlag geschätzt
    (echter Polygon-Build kommt in Phase 2 mit Vektor-Geometrie)
  • Wandstärken-Verteilung kann der User parametrisieren
  • Alle Faustformeln sind als Konstanten unten dokumentiert
"""
from __future__ import annotations
import math

# ────────────────────────────────────────────────────────────────────
# FAUSTFORMEL-KONSTANTEN (alle als optionaler Override im Request)
# ────────────────────────────────────────────────────────────────────
DEFAULTS = {
    # Bodenplatte / Decke aus Σ Raumfläche
    # Decke ist meist GRÖßER als Σ Innenraum_warm, weil überdachte Außen-
    # bereiche (Terrasse, Parkplatz) ebenfalls unter der EG-Decke liegen.
    # → bei der Decke ALLE Räume zählen (inkl. Loggia/Parkplatz/Terrasse),
    # bei der Bodenplatte nur Innen + Vorräume + überdachte Bereiche.
    # Bodenplatte = Footprint des Hauses (OHNE überdachte Außenbereiche,
    #   die meist eigenständige Fundamente haben).
    # Decke EG = inkl. überdachte Außenbereiche (sie liegen UNTER der Decke).
    "bodenplatte_aufschlag": 1.15,     # Σ F_innen × Faktor (Aufschlag für Außenwand-Bereich)
    "decke_aufschlag": 1.10,           # Σ F_innen+loggia × Faktor
    "include_loggia_decke": 1,          # 1 = Terrasse/Parkplatz für Decke mitzählen
    "include_loggia_bodenplatte": 0,    # 0 = Terrasse/Parkplatz NICHT für Bodenplatte
    "sauberkeitsschicht_cm": 5.0,      # C16/20 Untergrund unter Bodenplatte
    "frostschuerze_tiefe_m": 0.80,     # Tiefe ab OK Erdreich
    "frostschuerze_breite_m": 0.30,    # Breite der Frostschürze
    "frostgraben_aufschlag": 1.15,     # Frostschürze/Sockel läuft ~15% weiter als
                                       # die Bodenplatten-Außenkante (Graben außen herum)
    "aussenumfang_aufschlag": 1.55,     # Faktor für Vor-/Rücksprünge (rechteckiger
                                       # Bau ≈1.0, EFH mit Vor-/Auskragung 1.3-1.7,
                                       # L-Form/Versatz 1.5-1.7)
    # Mauerwerk-Wandstärken-Verteilung (Summe sollte 100 sein) — Außenwände
    "wand_anteil_50cm": 85.0,          # % der Außenwand-m² in 50cm Stärke (Haupt-Tragwand)
    "wand_anteil_38cm": 10.0,          # Stiegenhaus/Brandwand-Bereich
    "wand_anteil_25cm_aussen": 5.0,    # kleine Außenwand-Anteile (Garage etc.)
    # Innenwand-Verteilung (Anteile vom Innenwand-m²)
    "wand_anteil_25cm_innen": 25.0,    # tragend
    "wand_anteil_20cm": 30.0,
    "wand_anteil_12cm": 45.0,
    # Mauerwerks-Verschnitt: bestellte Ziegel-Paletten liegen über der NETTO-Wandfläche
    # (Schnittreste an Öffnungen/Ecken, Bruch, Fugengeometrie) — ~5% ist Polier-Standard.
    # Greift NUR auf die Paletten-Menge, nicht auf Mauermörtel/Voranstrich/EKV (rohes m²).
    "hlz_verschnitt": 1.05,
    "innenwand_aufschlag": 1.0,        # Nutzer-Korrektur für kurze/unbemaßte Trennwände,
                                       # die die Geometrie nicht voll erfasst (1.0 = neutral)
    # Decken-Aufbau
    "decke_auskragung": 1.05,          # (Bodenplatte+Loggia) × Faktor = Schalungs-Fläche
    "loggia_decke_aufschlag": 1.15,    # überdachte Loggia/Terrasse-Decke spannt über
                                       # Auflager/Dachüberstand → ~15% mehr als die lichte
                                       # Raumfläche (das Wand-Band hat der Footprint schon)
    "ekv_decke_aufschlag": 1.35,       # Dachabdichtung läuft über ALLES inkl Terrassen-
                                       # dach + Aufkantungen → größer als Schalung
    "iso_korb_anteil": 0.80,           # ISO-Korb (Thermo-Trennung) läuft entlang der
                                       # auskragenden Decken-/Balkonanschlüsse — typisch
                                       # ~80% des Außenumfangs (nicht ganz, nicht nur Balkon)
    "attika_anteil_aussen": 0.0,       # m² Attika-Aufbau, default 0 (User setzt)
    # Attika (Flachdach-Abschluss) — default aktiv via Außenumfang
    "attika_hoehe_m": 0.50,            # Aufkantungs-Höhe für XPS/Beton-Menge
    "attika_aktiv": 0,                 # 0 = aus (Satteldach), 1 = Flachdach mit Attika
    # Säulen / Stützen
    "anzahl_saeulen": 0,               # default 0 — User/Vision setzt
    "saeule_beton_m3_pro_stk": 0.5,    # inkl Fundament
    # Kamin
    "anzahl_kamine": 0,                # default 0
    # Bewehrungs-Matten (Baustahlgitter)
    "aq65_m2_pro_matte": 5.0,          # AQ65 effektiv ~5 m²/Matte (Doppellage oben+unten
                                       # + Überlappung) — kalibriert gg. Polier-Praxis
    "pe_folie_m2_pro_rolle": 50.0,     # 1 Rolle PE-Folie ~50 m²
    "xps_frostschuerze_tiefe_m": 1.05, # XPS-Sockeldämmung läuft höher als Beton-Schürze (0.8m)
    # HLZ-Paletten pro m² Wand (richtwert Wienerberger/Bramac, je nach Geometrie)
    "hlz_50cm_m2_pro_palette": 3.0,    # 1 Palette = ~3 m² Wand 50cm
    "hlz_38cm_m2_pro_palette": 4.5,
    "hlz_25cm_m2_pro_palette": 6.5,
    "hlz_20cm_m2_pro_palette": 8.0,
    "hlz_12cm_m2_pro_palette": 12.0,
    # Stück pro Palette je HLZ-Stärke (Polier-Angaben Angerer; 20er interpoliert).
    # Rein für die Stück-Anzeige neben den Paletten — der Polier bestellt/zählt in Stück.
    # Calibrierbar pro Firma (wie die m²/Palette-Deckung).
    "hlz_50cm_stk_pro_palette": 40,
    "hlz_38cm_stk_pro_palette": 45,
    "hlz_25cm_stk_pro_palette": 55,
    "hlz_20cm_stk_pro_palette": 60,   # interpoliert (Polier gab 25er=55, 12er=70)
    "hlz_12cm_stk_pro_palette": 70,
    # Mörtel / Voranstrich
    # Üblich: bei Plansteinen reicht 1 Palette pro ~150-200 m² Wand
    "mauermoertel_paletten_pro_100m2": 0.6,
    "voranstrich_kanister_pro_100m2": 1.0,
    # Bewehrung
    "torstahl_stk_pro_m_randabschluss": 0.25,
    "steckeisen_stk_pro_m_frostschuerze": 1.7,
    # EKV-Bahnen
    "ekv_aufschlag": 1.0,              # m² Bahn = m² Bauteil × Faktor
    "ekv_mauerwerk_h_anteil": 0.95,    # m² Außenwand × Faktor = Mauerwerk-Bahn
                                       # (Materialliste: m² ≈ Außenfläche fast voll)
}


def f(name, override):
    """Override-Resolver."""
    if override and name in override:
        try:
            return float(override[name])
        except (TypeError, ValueError):
            pass
    return DEFAULTS[name]


# ────────────────────────────────────────────────────────────────────
# Geometrie-Schätzungen (Phase-1-Heuristik)
# ────────────────────────────────────────────────────────────────────
def aussenumfang_schaetzung(bodenplatte_m2: float, aufschlag: float = 1.40) -> float:
    """Außenumfang aus Bodenplatten-Fläche.
    Annahme: ein Rechteck mit Seitenverhältnis 1:1.3 (typisches Haus),
    plus Aufschlag für Vor-/Rücksprünge (typisch 1.3-1.5 für EFH).
    """
    if bodenplatte_m2 <= 0:
        return 0.0
    b = math.sqrt(bodenplatte_m2 / 1.3)
    a = b * 1.3
    rechteck_umfang = 2 * (a + b)
    return round(rechteck_umfang * aufschlag, 2)


# ────────────────────────────────────────────────────────────────────
# Material-Position (Buchform mit Material-Einheit)
# ────────────────────────────────────────────────────────────────────
class MaterialPos:
    def __init__(self, bauteil: str, material: str, einheit: str,
                 menge: float, formel: str = "", konfidenz: float = 0.6):
        self.bauteil = bauteil
        self.material = material
        self.einheit = einheit
        # Menge nie negativ/NaN/inf (Fuzz-Test: negative/absurde Baudaten sollen
        # keine unsinnige Bestellmenge erzeugen). Eine Materialmenge ist ≥ 0.
        try:
            _m = float(menge or 0)
            _m = 0.0 if _m != _m or _m in (float("inf"), float("-inf")) else max(0.0, _m)
        except (TypeError, ValueError):
            _m = 0.0
        self.menge = round(_m, 2)
        self.formel = formel
        self.konfidenz = konfidenz
        self.plan_ref = None   # {"layer": "waende|oeffnungen|konturen", …}

    def to_dict(self):
        return {
            "bauteil": self.bauteil,
            "material": self.material,
            "menge": self.menge,
            "einheit": self.einheit,
            "formel": self.formel,
            "konfidenz": self.konfidenz,
            **({"plan_ref": self.plan_ref} if self.plan_ref else {}),
        }


# ────────────────────────────────────────────────────────────────────
# BAUTEIL-BERECHNUNGEN
# ────────────────────────────────────────────────────────────────────
def _stb_bauteile(rooms, baudaten, override, gemessen, kennzahlen_out,
                  K_GEO, K_UMF):
    """STB-/Tiefgaragen-Materialliste (Sektor-Weiche): Beton m³ + Schalung m²
    + Bewehrung t + Bodenbeschichtung statt HLZ-EFH-Positionen. Kalkulanten-
    Bedarf lt. B 2211/LB-HB LG07: Beton je Bauteil, Schalung horizontal/
    vertikal getrennt, Bewehrung über kg/m³-Kennwert (firmen-kalibrierbar)."""
    bd = baudaten or {}
    gemessen = gemessen or {}
    f_alle = sum(r.get("flaeche_m2") or 0 for r in rooms)
    u_alle = sum(r.get("umfang_m") or 0 for r in rooms)
    _hs = [r.get("hoehe_m") for r in rooms if r.get("hoehe_m")]
    h = float(bd.get("geschosshoehe_m") or (sum(_hs) / len(_hs) if _hs else 2.75))
    decke_cm = float(bd.get("decke_cm") or 25)
    bp_cm = float(bd.get("bodenplatte_cm") or 30)
    wand_cm = float(bd.get("stb_wand_cm") or 25)
    kg_m3 = float(bd.get("bewehrung_kg_m3") or 90.0)   # Kalibrier-Moat-Parameter
    umfang = float(gemessen.get("aussenumfang_m") or 0)
    if not umfang and f_alle:
        umfang = round((f_alle ** 0.5) * 4 * 1.15, 2)
    # Grundfläche brutto: Σ lichte Flächen + Wand-Band (5%)
    gf = round(f_alle * 1.05, 2)
    f_garage = sum(r.get("flaeche_m2") or 0 for r in rooms
                   if "garage" in str(r.get("name") or "").lower())
    out = []
    out.append(MaterialPos("Bodenplatte", "Beton C25/30", "m³",
                           gf * bp_cm / 100.0,
                           f"{gf}m² × {bp_cm:.0f}cm (ΣF {f_alle:.0f}m² × 1,05 Wand-Band)",
                           konfidenz=K_GEO))
    out.append(MaterialPos("Bodenplatte", "Sauberkeitsschicht C16/20 5cm", "m³",
                           gf * 0.05, f"{gf}m² × 5cm", konfidenz=round(K_GEO * 0.9, 2)))
    out.append(MaterialPos("Bodenplatte", "Bewehrung (Kennwert)", "t",
                           gf * bp_cm / 100.0 * kg_m3 / 1000.0,
                           f"{gf * bp_cm / 100.0:.1f}m³ × {kg_m3:.0f}kg/m³",
                           konfidenz=0.5))
    wand_m2 = round(umfang * h, 2)
    out.append(MaterialPos("Wände (STB)", f"Beton C25/30 Wand {wand_cm:.0f}cm", "m³",
                           wand_m2 * wand_cm / 100.0,
                           f"Umfang {umfang}m × h {h:.2f}m × {wand_cm:.0f}cm",
                           konfidenz=K_UMF))
    out.append(MaterialPos("Wände (STB)", "Schalung vertikal (2-seitig)", "m²",
                           wand_m2 * 2, f"{wand_m2}m² × 2 Seiten", konfidenz=K_UMF))
    out.append(MaterialPos("Wände (STB)", "Bewehrung (Kennwert)", "t",
                           wand_m2 * wand_cm / 100.0 * kg_m3 / 1000.0,
                           f"{wand_m2 * wand_cm / 100.0:.1f}m³ × {kg_m3:.0f}kg/m³",
                           konfidenz=0.5))
    out.append(MaterialPos("Decke", "Beton C25/30", "m³",
                           gf * decke_cm / 100.0, f"{gf}m² × {decke_cm:.0f}cm",
                           konfidenz=K_GEO))
    out.append(MaterialPos("Decke", "Schalung horizontal", "m²",
                           gf, f"= Grundfläche {gf}m²", konfidenz=K_GEO))
    out.append(MaterialPos("Decke", "Bewehrung (Kennwert)", "t",
                           gf * decke_cm / 100.0 * kg_m3 / 1000.0,
                           f"{gf * decke_cm / 100.0:.1f}m³ × {kg_m3:.0f}kg/m³",
                           konfidenz=0.5))
    if f_garage:
        out.append(MaterialPos("Bodenaufbau", "Bodenbeschichtung (OS 8)", "m²",
                               f_garage, f"Σ Garagen-Fläche {f_garage:.1f}m²",
                               konfidenz=round(K_GEO * 0.95, 2)))
    if kennzahlen_out is not None:
        kennzahlen_out.update({
            "sektor": "STB/Tiefgarage",
            "geschosshoehe_m": round(h, 2),
            "grundflaeche_brutto_m2": gf,
            "wandflaeche_m2": wand_m2,
            "aussenumfang_m": round(umfang, 2),
            "bewehrung_kg_m3": kg_m3,
        })
    return out


def materialliste_bauteile(rooms, windows, baudaten, override=None, geschoss="EG",
                            tueren=None, gemessen=None, wand_verteilung=None, legende=None,
                            kennzahlen_out=None):
    """Erzeugt eine flache Liste von MaterialPos über alle Bauteile.

    rooms:    gemergte Räume aus /api/projekt-massen
    windows:  erkannte Fenster (mit breite_m × hoehe_m)
    tueren:   erkannte Türen aus STUK/FPH-Cluster
    gemessen: optional {aussenumfang_m, bodenplatte_flaeche_m2, konfidenz, quelle}
              aus PASS-4-Bemaßung + Vision-Außenkontur. Wenn vorhanden,
              ersetzen diese Werte die Schätzformeln (sqrt × 1.55 etc).
              Konfidenz steigt entsprechend von 55-65% auf 85-95%.
    """
    # DEFENSIVE EINGANGS-NORMALISIERUNG (Fuzz-Test der Mengen-Engine: baudaten=
    # None → AttributeError, Zahl-Strings '50' → TypeError beim Rechnen, negative
    # Baudaten → negative Mengen). Das Kernprodukt darf NIE crashen, egal was
    # Vision/Text/Merge liefert. Zahl-Strings → float; echte Strings (dach_typ,
    # wandmaterial) + _quellen bleiben; None/nicht-dict → {}.
    def _mknum(v):
        if isinstance(v, str):
            try:
                return float(v.replace(",", "."))
            except ValueError:
                return v
        return v
    baudaten = {k: _mknum(v) for k, v in baudaten.items()} \
        if isinstance(baudaten, dict) else {}
    _rn = []
    for r in (rooms or []):
        if isinstance(r, dict):
            _rn.append({k: (_mknum(v) if k in ("flaeche_m2", "umfang_m", "hoehe_m")
                            else v) for k, v in r.items()})
    rooms = _rn
    tueren = tueren or []
    gemessen = gemessen or {}
    legende = legende or {}
    from massen_logic import kategorie_of

    def _kat(r):
        return kategorie_of(r.get("name") or r.get("bezeichnung") or "")

    # ── Konfidenz aus der DATENQUELLE ableiten (statt Phase-1-Pauschale) ──
    # Ein Wert ist so verlässlich wie seine Eingangsdaten:
    #   K_GEO  = Qualität der gemessenen Geometrie (Polygon-Build/Vision)
    #   K_LEG  = Qualität der Legende (byte-exakt aus Plan-Text)
    #   K_BEIDE= braucht Geometrie UND Legende (z.B. HLZ: Fläche × Wandstärke)
    #   K_FORM = reine Faustformel/Annahme (Dichten, Pauschalen) → niedrig
    K_GEO = round(min(0.96, float((gemessen or {}).get("konfidenz") or 0.0) or 0.62), 2)
    K_LEG = round(min(0.97, float((legende or {}).get("konfidenz") or 0.0) or 0.0), 2)
    # UMFANG separat: Frostschürze/Randabschluss/Außenwand hängen am Außenumfang,
    # der bei L-Form von Vision unterschätzt wird → eigene, ehrlich niedrigere
    # Konfidenz wenn der Umfang nicht validiert/verdächtig ist. Fläche bleibt hoch.
    K_UMF = round(min(0.96, float((gemessen or {}).get("umfang_konfidenz")
                                  or (gemessen or {}).get("konfidenz") or 0.62)), 2)
    # Σ-F-verankerte + Legende-gelesene Werte sind faktisch byte-exakt → bis 0.96
    K_BEIDE = round(min(K_GEO, K_LEG) if K_LEG else K_GEO * 0.9, 2)
    K_FORM = 0.5   # reine Faustformel ohne direkte Messung — bleibt ehrlich niedrig

    # ── SEKTOR-WEICHE STB/Tiefgarage (Baubetriebe-Audit: 'Tiefgarage' =
    # Nebenraum_kalt → 555,9 m² = 77% des Velden-TG fielen aus Bodenplatte/
    # Decke/Wänden, und für den STAHLBETON-Bau wurden HLZ-Paletten
    # vorgeschlagen). Signal: ein Garage-Raum ≥100 m² (TG-Halle; EFH-Garagen
    # sind <50 m²) ODER kalt-dominiert (>60% von ΣF). Dann Beton/Schalung/
    # Bewehrung statt HLZ — die EFH-Polier-Linie bleibt byte-identisch. ──
    _f_alle = sum(r.get("flaeche_m2") or 0 for r in rooms)
    _f_kalt = sum(r.get("flaeche_m2") or 0 for r in rooms
                  if _kat(r) in ("Nebenraum_kalt", "Loggia"))
    _tg_halle = any((r.get("flaeche_m2") or 0) >= 100.0
                    and "garage" in str(r.get("name") or r.get("bezeichnung") or "").lower()
                    for r in rooms)
    if rooms and (_tg_halle or (_f_alle > 0 and _f_kalt / _f_alle > 0.60
                                and _f_alle >= 200.0)):
        return _stb_bauteile(rooms, baudaten, override, gemessen,
                             kennzahlen_out, K_GEO, K_UMF)

    innen = [r for r in rooms if _kat(r) == "Innenraum_warm"]
    loggia = [r for r in rooms if _kat(r) == "Loggia"]  # Terrasse, Balkon, Parkplatz

    f_sum_innen = sum(r.get("flaeche_m2") or 0 for r in innen)
    f_sum_loggia = sum(r.get("flaeche_m2") or 0 for r in loggia)
    u_sum_innen = sum(r.get("umfang_m") or 0 for r in innen)
    # KONSISTENZ: EINE Geschoss-Höhe überall. Die kanonische baudaten-Geschoss-Höhe
    # (median/Schnitt/Opus, doppelcheck-bestätigt — derselbe Wert wie im Geo-Kasten)
    # treibt die geschoss-weite Wandfläche UND wird in den Kennzahlen gezeigt. Sonst
    # weicht die angezeigte Höhe (Geo-Kasten) vom Wandflächen-Treiber (Raum-Schnitt)
    # ab → genau der 2,95-vs-2,89-Widerspruch. Raum-Höhen-Schnitt nur als Fallback.
    h_room = sum((r.get("hoehe_m") or 0) for r in innen if r.get("hoehe_m")) / max(
        1, sum(1 for r in innen if r.get("hoehe_m")))
    h = baudaten.get("geschosshoehe_m") or (h_room if h_room > 0 else 2.70)
    aw_cm = baudaten.get("aussenwand_cm", 50)
    iw_cm = baudaten.get("innenwand_tragend_cm", 25)
    decke_cm = baudaten.get("decke_cm", 22)
    bopl_cm = baudaten.get("bodenplatte_cm", 25)

    # Bodenplatte / Decke — überdachte Außenbereiche optional mitzählen
    bp_inkl_loggia = bool(f("include_loggia_bodenplatte", override))
    dk_inkl_loggia = bool(f("include_loggia_decke", override))
    f_bp_base = f_sum_innen + (f_sum_loggia if bp_inkl_loggia else 0)
    f_dk_base = f_sum_innen + (f_sum_loggia if dk_inkl_loggia else 0)
    bp_faktor = f("bodenplatte_aufschlag", override)
    dk_faktor = f("decke_aufschlag", override)

    # GEMESSEN ÜBERSTEUERT GESCHÄTZT:
    # Wenn PASS-4-Bemaßung oder Vision-Polygon eine echte Bodenplatten-
    # Fläche / einen echten Außenumfang liefert → nutzen statt Schätzung.
    # Die Quelle wird transparent im "geometrie_quelle" hinterlegt.
    if gemessen.get("bodenplatte_flaeche_m2"):
        bodenplatte_m2 = round(float(gemessen["bodenplatte_flaeche_m2"]), 2)
        # Decke liegt ÜBER Innenräumen + überdachten Außenbereichen (Terrasse,
        # Parkplatz, Loggia). Diese sind im Bodenplatten-Footprint NICHT
        # enthalten (eigene Fundamente), aber die EG-Decke kragt darüber.
        # Decke = Bodenplatte + überdachte Loggia + Auskragungs-Aufschlag.
        decke_m2 = round((bodenplatte_m2 + f_sum_loggia * f("loggia_decke_aufschlag", override))
                         * f("decke_auskragung", override), 2)
        geometrie_quelle = gemessen.get("quelle", "gemessen")
        geometrie_konfidenz = float(gemessen.get("konfidenz") or 0.85)
    else:
        bodenplatte_m2 = round(f_bp_base * bp_faktor, 2)
        # KONSTANZ + GENAUIGKEIT: dieselbe Decken-Formel wie im gemessen-Zweig —
        # Footprint-Basis (bodenplatte_m2, schon inkl. Wand-Band) + Loggia ×
        # Auskragung. Vorher nahm der Fallback die LICHTE Σ-Raumfläche × anderem
        # Faktor → unterschätzte die Rohbau-Decke um die Wand-Querschnitte und
        # flackerte mit dem gemessen-vorhanden/-nicht-vorhanden-Zustand.
        decke_m2 = round((bodenplatte_m2 + f_sum_loggia * f("loggia_decke_aufschlag", override))
                         * f("decke_auskragung", override), 2)
        geometrie_quelle = f"Σ Raum-F × {bp_faktor:.2f}-Aufschlag"
        geometrie_konfidenz = 0.65

    # ÖNORM-Audit (LV-Planmaß-Entkopplung): die LV-Abrechnungsmenge der Decke
    # darf die BESTELL-Aufschläge (decke_auskragung 1,05 / loggia 1,15) nicht
    # enthalten — Norm verlangt Planmaß ab Außenkante. Bestell-Position behält
    # decke_m2 (mit Reserve), die LV bekommt das aufschlagfreie Planmaß.
    decke_planmass_m2 = round(bodenplatte_m2 + f_sum_loggia, 2)

    if gemessen.get("aussenumfang_m"):
        aussenumfang_m = round(float(gemessen["aussenumfang_m"]), 2)
        umfang_quelle = gemessen.get("quelle", "gemessen")
        umfang_konfidenz = float(gemessen.get("konfidenz") or 0.85)
    else:
        aussenumfang_m = aussenumfang_schaetzung(
            bodenplatte_m2, aufschlag=f("aussenumfang_aufschlag", override))
        umfang_quelle = f"sqrt(BP)·4·{f('aussenumfang_aufschlag', override):.2f}-Aufschlag"
        umfang_konfidenz = 0.55

    # ── Fundamentplatten-Außenkante (Linie B aus Vision-Außenkontur) ──
    # Frostschürze, Randabschluss & Sockelabdichtung laufen AUSSEN um die
    # durchgehende Bodenplatte — also auch unter fest angebauten überdachten
    # Bereichen (Loggia, überdachte Terrasse) weiter. Das MAUERWERK dagegen
    # folgt nur der gemauerten Hülle (aussenumfang_m). Fehlt Linie B → = Hülle
    # (Verhalten exakt wie bisher, kein Regressions-Effekt).
    fundament_umfang_m = round(float(gemessen.get("fundament_umfang_m") or aussenumfang_m), 2)
    _fund_groesser = fundament_umfang_m > aussenumfang_m + 0.05

    # MAUERWERKSHÖHE (ÖNORM-Audit-Experiment): Mauerwerk reicht real nur bis
    # UK Decke — das ~20cm-Band darüber ist Beton/Deckenrost (h × Umfang war
    # ~+7% HLZ). Messlauf gegen die Polier-Ground-Truth entscheidet.
    h_mw = max(2.0, h - decke_cm / 100.0)
    aw_m2_aussen = round(aussenumfang_m * h_mw, 2)
    # Innenwand-Fläche OHNE Doppelzählung: Σ Raum-Umfang zählt jede Innenwand
    # von BEIDEN angrenzenden Räumen (2×), die Außenwand-Innenseite 1×. Also:
    #   Σ U_innen = Außenumfang + 2 × Innenwand-Länge
    #   → Innenwand-Länge = (Σ U_innen − Außenumfang) / 2
    # (ein Bautechniker sieht jede Wand genau einmal — kein Doppelzählen).
    # BEZUGSRAHMEN: aussenumfang_m ist die AUSSENkante der Hülle, u_sum_innen aber
    # lichte Innenmaße. Vor der Subtraktion die Hülle auf die Innenkante bringen
    # (konservativ 4 Ecken × 2 Wandstärken — echtes EFH hat mehr konvexe Ecken,
    # also unterkorrigiert der Fix eher), sonst wird die Innenwand-Länge
    # systematisch zu kurz (HLZ 12 war dadurch -14%).
    aussen_innenkante = max(0.0, aussenumfang_m - 4 * 2 * aw_cm / 100.0)
    iw_laenge = max(0.0, (u_sum_innen - aussen_innenkante) / 2.0)
    # Innenwand-Aufschlag: kurze/unbemaßte Trennwände erfasst die (ΣU−Außenkante)/2-
    # Geometrie nicht voll → der Polier kann hier hochkorrigieren (Default 1.0 = neutral,
    # kein Effekt auf Bestandsläufe). Skaliert HLZ-Innen + Mörtel + Innenwand-Kennzahl.
    iw_m2_innen_rohbau = round(iw_laenge * h_mw * f("innenwand_aufschlag", override), 2)

    # ÖNORM-Audit (Bestell-Öffnungsabzug): GROSSE Öffnungen (> Schwelle, z.B.
    # Hebeschiebetür 6,9 m²) aus der Bestell-Wandfläche abziehen — kleine bleiben
    # übermessen (Verschnittreserve). Dieselbe oeffnung_netto-Regel wie die LV,
    # damit beide Ansichten dieselbe Wand zeigen. Firmen-Override:
    # bestell_oeffnung_schwelle (Default = Rohbau-Schwelle 4,0).
    abzug_aw_m2, abzug_iw_m2 = 0.0, 0.0
    try:
        from massen_logic import oeffnung_netto, _wand_cm_of, _schwelle_fuer
        _bs = float((baudaten or {}).get("bestell_oeffnung_schwelle")
                    or _schwelle_fuer(baudaten or {}, "rohbau"))
        for _o, _art in ([(o, "fenster") for o in (windows or [])]
                         + [(o, "tuer") for o in (tueren or [])]):
            _o2 = dict(_o)
            _o2["_art"] = _art
            _n = oeffnung_netto(_o2.get("breite_m") or 0, _o2.get("hoehe_m") or 0,
                                _wand_cm_of(_o2, baudaten), _o2.get("fph_m", 0), _bs)
            if not _n["abzug"]:
                continue
            _wt = (_o2.get("wand_typ") or "").lower()
            _ist_aw = _wt.startswith("a") if _wt else (_art == "fenster")
            if _ist_aw:
                abzug_aw_m2 += _n["abzug"]
            else:
                abzug_iw_m2 += _n["abzug"]
    except Exception:
        abzug_aw_m2, abzug_iw_m2 = 0.0, 0.0
    # BRUTTO merken (VOR dem Öffnungsabzug): die Gewerke-LV-Positionen (Rohbau
    # Außenwand-Ansichtsfläche, Außenputz) ziehen die Öffnungen SELBST ab — sie
    # brauchen daher die BRUTTO-Basis, sonst würden sie doppelt abziehen. Die
    # Bestell-Materialliste dagegen nutzt weiterhin die netto-Wandfläche.
    aw_m2_brutto = aw_m2_aussen
    iw_m2_brutto = iw_m2_innen_rohbau
    aw_m2_aussen = round(max(0.0, aw_m2_aussen - abzug_aw_m2), 2)
    iw_m2_innen_rohbau = round(max(0.0, iw_m2_innen_rohbau - abzug_iw_m2), 2)

    out = []

    # ═══ Frostschürze ═══
    # Die Frostschürze läuft als Graben AUSSEN um die Bodenplatte → etwas
    # größerer Umfang als die Bodenplatten-Außenkante (frostgraben_aufschlag).
    # Basis = Fundamentkante (Linie B), nicht die gemauerte Hülle.
    fg_umfang = round(fundament_umfang_m * f("frostgraben_aufschlag", override), 2)
    fs_tiefe = f("frostschuerze_tiefe_m", override)
    fs_breite = f("frostschuerze_breite_m", override)
    fs_m3 = fg_umfang * fs_tiefe * fs_breite
    out.append(MaterialPos(
        "Frostschürze", "Beton C25/30, XC1, F52, GK 22", "m³",
        fs_m3, f"Frostgraben-Umfang {fg_umfang}m × {fs_tiefe}m × {fs_breite}m",
        konfidenz=0.55))
    xps_tiefe = f("xps_frostschuerze_tiefe_m", override)
    out.append(MaterialPos(
        "Frostschürze", "XPS-SF G30 140mm", "m²",
        fg_umfang * xps_tiefe,
        f"Frostgraben-Umfang {fg_umfang}m × Sockeldämm-Höhe {xps_tiefe}m",
        konfidenz=0.55))
    out.append(MaterialPos(
        "Frostschürze", "2k Bitumen Spachtelmasse (5mm)", "m²",
        fg_umfang * xps_tiefe,
        "Außenkante Frostschürze als Sockelabdichtung",
        konfidenz=0.5))
    out.append(MaterialPos(
        "Frostschürze", "Noppenfolie 1m", "lfm",
        fg_umfang, f"Frostgraben-Umfang {fg_umfang}m", konfidenz=0.6))
    out.append(MaterialPos(
        "Frostschürze", "Steckeisen 10mm a 1m gekröpft", "Stk",
        round(fg_umfang * f("steckeisen_stk_pro_m_frostschuerze", override)),
        "Frostgraben-Umfang × Stk-Dichte", konfidenz=0.5))

    # ═══ Bodenplatte ═══
    bp_m3 = bodenplatte_m2 * (bopl_cm / 100.0)
    out.append(MaterialPos(
        "Bodenplatte", "Beton C25/30, B2, GK 22, F52", "m³",
        bp_m3, f"{bodenplatte_m2}m² × {bopl_cm}cm Dicke",
        konfidenz=0.7))
    # Sauberkeitsschicht: Legende (byte-exakt in baudaten) > Override > Default
    sauber_cm = baudaten.get("sauberkeitsschicht_cm") or f("sauberkeitsschicht_cm", override)
    out.append(MaterialPos(
        "Bodenplatte", "Beton C16/20 (Sauberkeitsschicht)", "m³",
        bodenplatte_m2 * (sauber_cm / 100.0),
        f"{bodenplatte_m2}m² × {sauber_cm}cm",
        konfidenz=0.5))
    ekv_f = f("ekv_aufschlag", override)
    out.append(MaterialPos(
        "Bodenplatte", "EKV-5 Bitumendichtbahn", "m²",
        bodenplatte_m2 * ekv_f, f"{bodenplatte_m2}m² × {ekv_f}",
        konfidenz=0.65))
    out.append(MaterialPos(
        "Bodenplatte", "XPS-SF G30 120mm", "m²",
        bodenplatte_m2, f"{bodenplatte_m2}m²", konfidenz=0.7))
    out.append(MaterialPos(
        "Bodenplatte", "Randabschlusskorb 16cm", "lfm",
        fundament_umfang_m,
        f"Bodenplatten-Außenkante {fundament_umfang_m}m" +
        (" (inkl. angebauter überdachter Fläche)" if _fund_groesser else ""),
        konfidenz=0.65))
    aq65_bp = f("aq65_m2_pro_matte", override)
    out.append(MaterialPos(
        "Bodenplatte", "Baustahlgitter AQ 65", "Stk",
        math.ceil(bodenplatte_m2 / aq65_bp) if aq65_bp > 0 else 0,
        f"{bodenplatte_m2}m² ÷ {aq65_bp}m²/Matte", konfidenz=0.6))
    pe_roll = f("pe_folie_m2_pro_rolle", override)
    out.append(MaterialPos(
        "Bodenplatte", "PE-Folie", "Rollen",
        math.ceil(bodenplatte_m2 / pe_roll) if pe_roll > 0 else 0,
        f"{bodenplatte_m2}m² ÷ {pe_roll}m²/Rolle", konfidenz=0.6))
    out.append(MaterialPos(
        "Bodenplatte", "Torstahl 12mm (Schürzen-Bewehrung)", "Stk",
        round(fundament_umfang_m * f("torstahl_stk_pro_m_randabschluss", override)),
        "Bodenplatten-Außenkante × Stk-Dichte", konfidenz=0.4))

    # ═══ Mauerwerk EG — HLZ-Paletten pro Wandstärke ═══
    # Paletten-Deckung pro m² Wand: bekannte Stärke aus DEFAULTS, sonst
    # generische Formel 150/Dicke_cm (50→3.0, 25→6.0, 12→12.5 — passt zur Tabelle).
    def _coverage(dicke_cm):
        key = f"hlz_{int(round(dicke_cm))}cm_m2_pro_palette"
        if key in DEFAULTS or (override and key in override):
            return f(key, override)
        return round(150.0 / dicke_cm, 2) if dicke_cm > 0 else 6.0

    def _hlz_positionen(verteilung_aussen, verteilung_innen, konf):
        """verteilung_*: {dicke_cm: anteil_pct}. Erzeugt HLZ-Positionen."""
        # Außen + Innen je Dicke zusammenfassen (gleiche Dicke = gleiche Palette)
        m2_pro_dicke = {}
        formel_teile = {}
        for d, pct in (verteilung_aussen or {}).items():
            dd = float(d)
            m2 = aw_m2_aussen * pct / 100.0
            m2_pro_dicke[dd] = m2_pro_dicke.get(dd, 0) + m2
            formel_teile.setdefault(dd, []).append(f"AW {m2:.1f}m²")
        for d, pct in (verteilung_innen or {}).items():
            dd = float(d)
            m2 = iw_m2_innen_rohbau * pct / 100.0
            m2_pro_dicke[dd] = m2_pro_dicke.get(dd, 0) + m2
            formel_teile.setdefault(dd, []).append(f"IW {m2:.1f}m²")
        versch = f("hlz_verschnitt", override)
        pos = []
        gesamt = 0.0
        for dd in sorted(m2_pro_dicke.keys(), reverse=True):
            m2 = m2_pro_dicke[dd]
            gesamt += m2
            cov = _coverage(dd)
            paletten = math.ceil(m2 * versch / cov) if cov > 0 else 0
            formel = f"{' + '.join(formel_teile[dd])} ÷ {cov}m²/Pal × {versch} Verschnitt"
            # Stück-Anzeige (der Polier bestellt/zählt in Stück): Paletten × Stk/Palette
            stk_key = f"hlz_{int(round(dd))}cm_stk_pro_palette"
            if (stk_key in DEFAULTS or (override and stk_key in override)) and paletten:
                stk = int(round(paletten * f(stk_key, override)))
                formel += f"  ·  ≈ {stk} Stück ({int(round(f(stk_key, override)))}/Pal)"
            pos.append(MaterialPos(
                "Mauerwerk EG", f"HLZ {int(round(dd))}cm Plan", "Paletten",
                paletten, formel, konfidenz=konf))
        return pos, gesamt

    # Verteilungs-Quelle in Reihenfolge: EXPLIZIT gesetzte Anteile (User-Override
    # ODER firmenspezifische Kalibrierung) > Legende-Verteilung (aus Code-Vorkommen,
    # empirisch unzuverlässig weil Codes selten je Wand stehen) > Default. So
    # schlägt der manuelle Innenwand-Regler / die gelernte Verteilung die wackeligen
    # Legende-Counts, ohne die byte-exakten Wandstärken anzutasten.
    _WAND_ANTEIL_KEYS = ("wand_anteil_50cm", "wand_anteil_38cm", "wand_anteil_25cm_aussen",
                         "wand_anteil_25cm_innen", "wand_anteil_20cm", "wand_anteil_12cm")
    _explizite_verteilung = bool(override and any(k in override for k in _WAND_ANTEIL_KEYS))
    # SELBST-SCHUTZ gegen „erfundene" Wandstärken (z.B. HLZ 38cm, das die Legende gar
    # nicht kennt): kennt die byte-exakte Legende explizite Wandtypen, bestimmt SIE die
    # Stärken — direkt hier abgeleitet (Vorkommen je Code → Anteil), damit keine
    # upstream-Vision-Verteilung eine fremde Stärke einschmuggelt. User-Override/
    # Kalibrierung (explizite Anteile) schlagen weiterhin alles.
    _leg_wt = (legende or {}).get("wand_typen") or {}
    if _leg_wt and not _explizite_verteilung:
        _leg_counts = (legende or {}).get("wand_counts") or {}
        _la, _li = {}, {}
        _sa = sum((_leg_counts.get(k) or 1) for k, v in _leg_wt.items() if v.get("art") == "aussen")
        _si = sum((_leg_counts.get(k) or 1) for k, v in _leg_wt.items() if v.get("art") == "innen")
        for _code, _v in _leg_wt.items():
            _c = _leg_counts.get(_code) or 1
            _dk = _v.get("dicke_cm")
            if _dk and _v.get("art") == "aussen" and _sa:
                _la[_dk] = _la.get(_dk, 0) + _c / _sa * 100.0
            elif _dk and _v.get("art") == "innen" and _si:
                _li[_dk] = _li.get(_dk, 0) + _c / _si * 100.0
        # Legende kennt evtl. nur EINE Wandklasse (nur aussen ODER nur innen) — dann
        # würde die ANDERE Wandfläche (aw_m2_aussen bzw. iw_m2_innen_rohbau) im
        # Legende-Zweig stillschweigend fallengelassen. Fehlende Klasse aus der
        # Standard-Verteilung nachfüllen, damit KEINE Wand-m² verloren geht.
        if _la and not _li:
            _li = {25: f("wand_anteil_25cm_innen", override),
                   20: f("wand_anteil_20cm", override),
                   12: f("wand_anteil_12cm", override)}
        elif _li and not _la:
            _la = {50: f("wand_anteil_50cm", override),
                   38: f("wand_anteil_38cm", override),
                   25: f("wand_anteil_25cm_aussen", override)}
        if _la or _li:
            wand_verteilung = {"aussen": _la, "innen": _li}
    if (wand_verteilung and (wand_verteilung.get("aussen") or wand_verteilung.get("innen"))
            and not _explizite_verteilung):
        # LEGENDE-basiert: echte Wandstärken + Verteilung aus dem Plan gelesen
        hlz_pos, gesamt_wand_m2 = _hlz_positionen(
            wand_verteilung.get("aussen"), wand_verteilung.get("innen"), konf=0.75)
        out.extend(hlz_pos)
    else:
        # Fallback: hartcodierte Standard-Verteilung (kein Legende-Fund)
        versch = f("hlz_verschnitt", override)
        a50 = aw_m2_aussen * f("wand_anteil_50cm", override) / 100.0
        a38 = aw_m2_aussen * f("wand_anteil_38cm", override) / 100.0
        a25a = aw_m2_aussen * f("wand_anteil_25cm_aussen", override) / 100.0
        i25 = iw_m2_innen_rohbau * f("wand_anteil_25cm_innen", override) / 100.0
        i20 = iw_m2_innen_rohbau * f("wand_anteil_20cm", override) / 100.0
        i12 = iw_m2_innen_rohbau * f("wand_anteil_12cm", override) / 100.0
        out.append(MaterialPos("Mauerwerk EG", "HLZ 50cm H.I. Plan", "Paletten",
            math.ceil(a50 * versch / _coverage(50)), f"{a50:.1f}m² AW 50cm (Annahme) × {versch} Verschnitt", konfidenz=0.5))
        out.append(MaterialPos("Mauerwerk EG", "HLZ 38cm H.I. Plan", "Paletten",
            math.ceil(a38 * versch / _coverage(38)), f"{a38:.1f}m² AW 38cm (Annahme) × {versch} Verschnitt", konfidenz=0.5))
        out.append(MaterialPos("Mauerwerk EG", "HLZ 25cm Plan", "Paletten",
            math.ceil((a25a + i25) * versch / _coverage(25)), f"{a25a+i25:.1f}m² 25cm (Annahme) × {versch} Verschnitt", konfidenz=0.5))
        out.append(MaterialPos("Mauerwerk EG", "HLZ 20cm Plan", "Paletten",
            math.ceil(i20 * versch / _coverage(20)), f"{i20:.1f}m² IW 20cm (Annahme) × {versch} Verschnitt", konfidenz=0.5))
        out.append(MaterialPos("Mauerwerk EG", "HLZ 12cm Plan", "Paletten",
            math.ceil(i12 * versch / _coverage(12)), f"{i12:.1f}m² IW 12cm (Annahme) × {versch} Verschnitt", konfidenz=0.5))
        gesamt_wand_m2 = a50 + a38 + a25a + i25 + i20 + i12
    out.append(MaterialPos(
        "Mauerwerk EG", "Mauermörtel", "Paletten",
        gesamt_wand_m2 / 100 * f("mauermoertel_paletten_pro_100m2", override),
        f"{gesamt_wand_m2:.0f}m² Wand", konfidenz=0.6))
    out.append(MaterialPos(
        "Mauerwerk EG", "bitumin. Voranstrich", "Kanister",
        math.ceil(aw_m2_aussen / 100 * f("voranstrich_kanister_pro_100m2", override)) or 1,
        f"{aw_m2_aussen}m² Außenwand × {f('voranstrich_kanister_pro_100m2', override)} Kan/100m²",
        konfidenz=0.55))
    ekv_mw_h = f("ekv_mauerwerk_h_anteil", override)
    out.append(MaterialPos(
        "Mauerwerk EG", "EKV-5 (Außenwand)", "m²",
        aw_m2_aussen * ekv_mw_h,
        f"{aw_m2_aussen}m² Außenwand × {ekv_mw_h}", konfidenz=0.65))
    # Mauersperrbahn (Horizontalsperre) läuft unter ALLEN Außenwänden inkl. der
    # Wände an angebauten überdachten Bereichen → Fundament-/Gebäudekante, nicht
    # nur die beheizte Hülle.
    out.append(MaterialPos(
        "Mauerwerk EG", "Mauersperrbahn 25cm", "Rollen",
        math.ceil(fundament_umfang_m / 25) or 1,
        f"Gebäude-Außenkante {fundament_umfang_m}m ÷ 25m/Rolle", konfidenz=0.65))

    # ═══ Öffnungen — Ziegelüberlagen + Rolladenkästen ═══
    # KONSTANZ: Breiten bevorzugt aus dem byte-exakten STUK/FPH-Text-Layer (über jede
    # Re-Analyse identisch). Nur wenn KEINE Text-Öffnung eine Breite liefert, auf
    # Vision-Breiten zurückfallen — die wackeln zwischen Läufen um Bucket-Grenzen und
    # ließen die Rolladen-/Sturz-Anzahl springen.
    def _breite_of(o):
        return o.get("breite_m") or (o.get("breite_cm", 0) / 100.0 if o.get("breite_cm") else None)
    def _ist_text(o):
        q = (o.get("quelle") or "").lower()
        return "stuk" in q or "fph" in q or "text" in q
    def _breiten_quelle(items):
        text_items = [o for o in (items or []) if _ist_text(o) and _breite_of(o)]
        return text_items if text_items else (items or [])
    fenster_breiten = [b for b in (_breite_of(w) for w in _breiten_quelle(windows)) if b]

    rolladen_125 = sum(1 for b in fenster_breiten if 1.0 <= b <= 1.4)
    rolladen_180 = sum(1 for b in fenster_breiten if 1.4 < b <= 2.0)
    rolladen_215 = sum(1 for b in fenster_breiten if 2.0 < b <= 2.4)
    rolladen_245 = sum(1 for b in fenster_breiten if b > 2.4)   # breite Schiebe-Elemente

    if rolladen_125:
        out.append(MaterialPos(
            "Öffnungen", "Rolladenkasten (Lavatherm) 124cm", "Stk",
            rolladen_125, f"{rolladen_125} Fenster mit 1.0–1.4m Breite", konfidenz=0.7))
    if rolladen_180:
        out.append(MaterialPos(
            "Öffnungen", "Rolladenkasten (Lavatherm) 184cm", "Stk",
            rolladen_180, f"{rolladen_180} Fenster mit 1.4–2.0m Breite", konfidenz=0.7))
    if rolladen_215:
        out.append(MaterialPos(
            "Öffnungen", "Rolladenkasten (Lavatherm) 214cm", "Stk",
            rolladen_215, f"{rolladen_215} Fenster mit 2.0–2.4m Breite", konfidenz=0.7))
    if rolladen_245:
        out.append(MaterialPos(
            "Öffnungen", "Rolladenkasten (Lavatherm) 244cm", "Stk",
            rolladen_245, f"{rolladen_245} Fenster/Schiebe-Element >2.4m Breite", konfidenz=0.6))

    # Ziegelüberlagen aus den ERKANNTEN Türen (statt Pauschal).
    # Ziegelüberlage-Standard-Längen: 125cm (für Türöffnungen bis ~100cm),
    # 200cm (~150-180cm Öffnung), 250cm (~200-230cm Öffnung).
    oeffnung_unscharf = False   # ≥1 Tür ohne lesbares Breitenmaß → Sturz geschätzt
    if tueren:
        tuer_breiten = [b for b in (_breite_of(t) for t in _breiten_quelle(tueren)) if b]
        # Jede ERKANNTE Tür braucht einen Sturz — eine ohne lesbare Breite zählt als
        # Standard-Innentür (125cm) statt herauszufallen (sonst „9 Türen, nur 7 Stürze").
        n_ohne_breite = max(0, len(tueren) - len(tuer_breiten))
        oeffnung_unscharf = n_ohne_breite > 0
        # NORMBASIERT (LB-HB LG08: Überlagen = 'jeweilige Rohbaulichte,
        # zusätzlich 2 × 15 cm für die Auflager'): benötigt = lichte + 0,30m,
        # dann die KLEINSTE Standardlänge ≥ benötigt (Sortiment konfigurierbar).
        # Vorher rutschte z.B. eine 1,00m-Tür in den 125er (benötigt 1,30!).
        _sortiment = [float(x) for x in
                      (baudaten or {}).get("ueberlagen_sortiment_cm")
                      or (125, 150, 200, 250, 300)]
        _sortiment.sort()
        stk = {}
        for b in tuer_breiten:
            ben = b * 100.0 + 30.0
            l_cm = next((L for L in _sortiment if L >= ben), _sortiment[-1])
            stk[l_cm] = stk.get(l_cm, 0) + 1
        if n_ohne_breite:   # Standard-Innentür 88er → benötigt 118 → 125er
            stk[_sortiment[0]] = stk.get(_sortiment[0], 0) + n_ohne_breite
        for l_cm in sorted(stk):
            _txt = (f"{stk[l_cm]}× lichte+2×15cm Auflager ≤ {l_cm:.0f}cm"
                    + (f" (inkl. {n_ohne_breite} ohne Maß)"
                       if n_ohne_breite and l_cm == _sortiment[0] else ""))
            out.append(MaterialPos(
                "Öffnungen", f"Ziegelüberlage 12cm {l_cm:.0f}cm", "Stk",
                stk[l_cm], _txt,
                konfidenz=0.85 if not (n_ohne_breite and l_cm == _sortiment[0]) else 0.7))
        # FENSTER ohne Rolladenkasten brauchen ebenfalls einen Sturz (jede
        # Öffnung hat Sturz ODER Kasten — nie keins; Audit-Befund: Fenster
        # <1,0m Breite bekamen bisher gar nichts)
        _f_sturz = {}
        for w in (windows or []):
            b = w.get("breite_m") or 0
            if not b or b >= 1.0:      # ≥1,0m → Rolladenkasten-Block oben
                continue
            ben = b * 100.0 + 30.0
            l_cm = next((L for L in _sortiment if L >= ben), _sortiment[-1])
            _f_sturz[l_cm] = _f_sturz.get(l_cm, 0) + 1
        for l_cm in sorted(_f_sturz):
            out.append(MaterialPos(
                "Öffnungen", f"Ziegelüberlage 12cm {l_cm:.0f}cm (Fenster)", "Stk",
                _f_sturz[l_cm], f"{_f_sturz[l_cm]}× Fenster <1,0m ohne Rolladenkasten",
                konfidenz=0.75))
    else:
        # Fallback: Pauschal-Annahme wenn STUK/FPH-Erkennung leer war
        n_tueren = max(0, len(rooms) - 1)
        out.append(MaterialPos(
            "Öffnungen", "Ziegelüberlage 12cm 125cm", "Stk",
            n_tueren, f"{n_tueren} Innentüren (Pauschal: 1 pro Raum)", konfidenz=0.45))
        out.append(MaterialPos(
            "Öffnungen", "Ziegelüberlage 12cm 200cm", "Stk",
            2, "Pauschal 2 Außenöffnungen", konfidenz=0.4))

    # ═══ Decke über EG ═══
    decke_m3 = decke_m2 * (decke_cm / 100.0)
    out.append(MaterialPos(
        "Decke über EG", "Beton C25/30, XC1, GK 22, F52", "m³",
        decke_m3, f"{decke_m2}m² × {decke_cm}cm", konfidenz=0.7))
    out.append(MaterialPos(
        "Decke über EG", "Schaltafel 200/50", "m²",
        decke_m2, f"{decke_m2}m² Schalung", konfidenz=0.7))
    # Decken-Rand-Umfang: die Decke ist die Dachplatte über der GANZEN Boden-
    # platte inkl. angebauter überdachter Bereiche → ihr Rand folgt der
    # Fundamentplatten-Außenkante (Linie B), nicht der gemauerten Hülle, und
    # skaliert zusätzlich mit der Wurzel des Flächenverhältnisses (Auskragung).
    _rand_basis = fundament_umfang_m if _fund_groesser else aussenumfang_m
    if bodenplatte_m2 > 0:
        decke_umfang = round(_rand_basis * (decke_m2 / bodenplatte_m2) ** 0.5, 2)
    else:
        decke_umfang = _rand_basis
    # ISO-Korb (Thermo-Trennung) sitzt an der Decken-Auskragung zu überdachter
    # Terrasse/Balkon → folgt der Gebäude-/Fundamentkante, nicht der Hülle.
    iso_korb_m = round(fundament_umfang_m * f("iso_korb_anteil", override), 2)
    out.append(MaterialPos(
        "Decke über EG", "ISO-Korb 8/25", "lfm",
        iso_korb_m, f"Gebäude-Außenkante {fundament_umfang_m}m × {f('iso_korb_anteil', override)}",
        konfidenz=0.5))
    # EKV-Decke = Dachabdichtung, läuft über ALLES inkl Terrassendach + Auf-
    # kantungen → größer als die Schalungsfläche (eigener Aufschlag).
    ekv_dk = f("ekv_decke_aufschlag", override)
    out.append(MaterialPos(
        "Decke über EG", "EKV-5 Dachabdichtung", "m²",
        decke_m2 * ekv_dk, f"{decke_m2}m² × {ekv_dk} (inkl Aufkantung/Terrassendach)",
        konfidenz=0.6))
    out.append(MaterialPos(
        "Decke über EG", "Randabschlusskorb 16cm", "lfm",
        decke_umfang, f"Decken-Rand {decke_umfang}m (Bodenplatte-Umfang × √Flächenverhältnis)",
        konfidenz=0.6))
    aq65_dk = f("aq65_m2_pro_matte", override)
    out.append(MaterialPos(
        "Decke über EG", "Baustahlgitter AQ 65", "Stk",
        math.ceil(decke_m2 / aq65_dk) if aq65_dk > 0 else 0,
        f"{decke_m2}m² ÷ {aq65_dk}m²/Matte", konfidenz=0.55))
    out.append(MaterialPos(
        "Decke über EG", "bitumin. Voranstrich", "Kanister",
        math.ceil(decke_m2 / 100 * f("voranstrich_kanister_pro_100m2", override)) or 1,
        f"{decke_m2}m² Decke", konfidenz=0.55))

    # ═══ Giebel (Sattel-/Pultdach) — ÖNORM-Audit P1: fehlte komplett ═══
    # LB-HB LG08 kennt die Giebelwand explizit ('Az schräger Abschluss z.B.
    # bei Giebelwänden'). Giebelfläche = Giebelseite × Firstüberhöhung / 2 ×
    # Anzahl (Sattel 2, Pult 1). Giebelseite = kürzere Rechteck-Seite aus
    # U/A (2(b+t)=U, b·t=A); Firstüberhöhung = Gebäudehöhe − Traufe
    # (Geschosshöhe + Decke). Nur wenn ALLE Quellen da sind — sonst keine
    # Position (kein Schaden, additiv; eigene Zeile statt still in die
    # Paletten, damit der Polier sie am Plan/Schnitt prüfen kann).
    _dt = str((baudaten or {}).get("dach_typ") or "").lower()
    _gh_ges = (baudaten or {}).get("gebaeudehoehe_m")
    if _dt in ("sattel", "satteldach", "pult", "pultdach") and _gh_ges             and aussenumfang_m > 0 and bodenplatte_m2 > 0:
        _traufe = h + decke_cm / 100.0
        _ueber = float(_gh_ges) - _traufe
        _disc = aussenumfang_m * aussenumfang_m / 16.0 - bodenplatte_m2
        if 0.5 <= _ueber <= 6.0 and _disc > 0:
            _seite_kurz = aussenumfang_m / 4.0 - _disc ** 0.5
            _n_giebel = 2 if _dt.startswith("sattel") else 1
            _giebel_m2 = round(_seite_kurz * _ueber / 2.0 * _n_giebel, 2)
            if _giebel_m2 >= 2.0:
                out.append(MaterialPos(
                    "Mauerwerk EG", f"HLZ {aw_cm:.0f}cm Giebel", "m²",
                    _giebel_m2,
                    f"{_n_giebel}× Giebel {_seite_kurz:.2f}m × "
                    f"(First {float(_gh_ges):.2f} − Traufe {_traufe:.2f})/2",
                    konfidenz=0.55))

    # ═══ Attika (nur bei Flachdach) ═══
    if f("attika_aktiv", override) or f("attika_anteil_aussen", override) > 0:
        att_h = f("attika_hoehe_m", override)
        attika_m2 = aussenumfang_m * att_h
        out.append(MaterialPos(
            "Attika", "XPS 6cm Oberfläche rau", "m²",
            attika_m2, f"Außenumfang {aussenumfang_m}m × {att_h}m Höhe", konfidenz=0.45))
        out.append(MaterialPos(
            "Attika", "Beton C25/30", "m³",
            attika_m2 * 0.15, f"{round(attika_m2,1)}m² × 0.15m Stärke", konfidenz=0.4))
        out.append(MaterialPos(
            "Attika", "Steckeisen 10mm a 1m gekröpft", "Stk",
            round(aussenumfang_m * 3), f"Außenumfang × 3 Stk/m", konfidenz=0.4))

    # ═══ Säulen / Stützen (nur wenn anzahl_saeulen gesetzt) ═══
    n_saeulen = int(f("anzahl_saeulen", override))
    if n_saeulen > 0:
        beton_pro = f("saeule_beton_m3_pro_stk", override)
        out.append(MaterialPos(
            "Säulen", "Beton C25/30 (Fundamente + Säulen)", "m³",
            n_saeulen * beton_pro, f"{n_saeulen} Säulen × {beton_pro}m³", konfidenz=0.45))
        out.append(MaterialPos(
            "Säulen", "Bügel geschlossen 18/18 12mm", "Stk",
            n_saeulen * 15, f"{n_saeulen} Säulen × 15 Bügel", konfidenz=0.4))
        out.append(MaterialPos(
            "Säulen", "Torstahl 14mm a 7m", "Stk",
            n_saeulen * 2, f"{n_saeulen} Säulen × 2 Stäbe", konfidenz=0.4))

    # ═══ Kamin — Anzahl aus Legende-Textzählung ODER Override ═══
    n_kamine = int(f("anzahl_kamine", override)) or int(legende.get("kamin_anzahl") or 0)
    if n_kamine > 0:
        kq = "Plan-Text gezählt" if legende.get("kamin_anzahl") and not (override or {}).get("anzahl_kamine") else "Annahme"
        out.append(MaterialPos(
            "Kamin", "Kamin DN16 mit Fertigfuß und Haube (Schiedel)", "Stk",
            n_kamine, f"{n_kamine} Kamin(e) ({kq})", konfidenz=0.6))

    # ═══ Infrastruktur — Sickerschacht aus Legende-Textzählung ═══
    n_sicker = int(legende.get("sickerschacht_anzahl") or 0)
    if n_sicker > 0:
        out.append(MaterialPos(
            "Infrastruktur", "Sickerschacht DN 2500 mit Konus + Betondeckel", "Stk",
            n_sicker, f"{n_sicker}× im Plan-Text gezählt", konfidenz=0.6))

    # ═══ Bodenaufbau pro Raum — byte-exakte Schichtdicken aus Legende ═══
    # (wie ein Mensch: liest Estrich/Schüttung/Belag-Dicke aus B-Code-Aufbau
    #  und multipliziert mit der Raumfläche). Eigene Sektion, stört die
    #  Rohbau-Mengen nicht.
    estrich_cm = legende.get("estrich_cm")
    schuettung_cm = legende.get("schuettung_cm")
    belag_cm = legende.get("belag_cm")
    trittschall_cm = legende.get("trittschall_cm")
    if f_sum_innen > 0 and (estrich_cm or schuettung_cm or belag_cm):
        if estrich_cm:
            out.append(MaterialPos(
                "Bodenaufbau", "Estrich (Volumen)", "m³",
                round(f_sum_innen * estrich_cm / 100.0, 2),
                f"Σ Innenfläche {f_sum_innen:.1f}m² × {estrich_cm}cm (Legende)", konfidenz=0.8))
        out.append(MaterialPos(
            "Bodenaufbau", "Estrich-Fläche", "m²",
            round(f_sum_innen, 2), f"Σ Innenfläche {f_sum_innen:.1f}m²", konfidenz=0.9))
        if schuettung_cm:
            out.append(MaterialPos(
                "Bodenaufbau", "Schüttung (Volumen)", "m³",
                round(f_sum_innen * schuettung_cm / 100.0, 2),
                f"Σ Innenfläche × {schuettung_cm}cm (Legende)", konfidenz=0.75))
        if trittschall_cm:
            out.append(MaterialPos(
                "Bodenaufbau", "Trittschalldämmung", "m²",
                round(f_sum_innen, 2), f"Σ Innenfläche × {trittschall_cm}cm (Legende)", konfidenz=0.75))
        out.append(MaterialPos(
            "Bodenaufbau", "Randdämmstreifen", "lfm",
            round(u_sum_innen, 2), f"Σ Innenraum-Umfang {u_sum_innen:.1f}m", konfidenz=0.8))
        # Bodenbelag pro Material (aus Raum-bodenbelag aggregiert)
        belag_map = {}
        for r in innen:
            bel = (r.get("bodenbelag") or "").strip()
            if bel and bel.lower() not in ("nicht erkennbar", "?", ""):
                belag_map[bel] = belag_map.get(bel, 0) + (r.get("flaeche_m2") or 0)
        for bel, m2 in sorted(belag_map.items()):
            out.append(MaterialPos(
                "Bodenaufbau", f"Bodenbelag {bel}", "m²",
                round(m2, 2), f"Σ Räume mit {bel}", konfidenz=0.85))

    # ── Konfidenz zentral aus der Datenquelle setzen (ehrlich) ──
    # Hoch wo byte-exakt gemessen (Geometrie) oder aus Legende gelesen,
    # niedrig wo reine Faustformel. K_GEO/K_LEG kommen aus den echten
    # Mess-/Lese-Konfidenzen dieses Plans → spiegelt die Qualität wider.
    # Reine Dichte-Faustformeln (kein direkter Messbezug) → ehrlich niedrig
    DICHTE_FORMEL = ("steckeisen", "torstahl", "bügel", "abstandhalter")
    # Aus byte-exakter Fläche × Produkt-Deckung (Matte/Rolle) → mittel-hoch
    FLAECHEN_PRODUKT = ("aq 65", "pe-folie")
    # Direkt am Außen-/Fundament-UMFANG hängend → K_UMF (sinkt bei L-Form-Verdacht)
    PERIMETER_MAT = ("randabschluss", "mauersperrbahn")
    for p in out:
        b, mat = p.bauteil, p.material.lower()
        formel = (p.formel or "").lower()
        # umfang-getrieben? (Frostgraben/Außenkante/Außenumfang/Außenwand in der Formel)
        umf = any(s in formel for s in ("umfang", "außenkante", "außenwand", "frostgraben", "aussenkante", "aussenwand"))
        if any(k in mat for k in DICHTE_FORMEL):
            p.konfidenz = K_FORM                       # reine Bewehrungs-Dichte
        elif any(k in mat for k in FLAECHEN_PRODUKT):
            p.konfidenz = round(min(K_GEO, 0.72), 2)   # Fläche byte-exakt × Produkt-Norm
        elif any(k in mat for k in PERIMETER_MAT):
            p.konfidenz = K_UMF                         # läuft am Umfang → Umfang-Konfidenz
        elif b == "Bodenaufbau" or "sauberkeit" in mat:
            p.konfidenz = K_BEIDE if K_LEG else round(K_GEO * 0.85, 2)
        elif b == "Mauerwerk EG" and "hlz" in mat:
            # BEIDE HLZ-Sorten hängen am Außenumfang und erben dessen Unsicherheit:
            # Außenwand = Umfang×H direkt; Innenwand-Länge = (ΣU_innen − Außenumfang)/2
            # → ein zu kompakt gelesener Umfang bläht die Innenwand-Länge auf. Darum
            # KEINE Schein-Sicherheit: min(K_BEIDE, K_UMF) für beide (sinkt bei L-Form).
            p.konfidenz = round(min(K_BEIDE, K_UMF), 2)
        elif b == "Öffnungen":
            # Öffnungen werden in PROD nachweislich UNTERERFASST: gelesen werden nur
            # annotierte STUK/FPH-Maße — reine Symbol-Fenster/-Türen ohne Bemaßung
            # fehlen. Darum ehrlicher Cap (raus aus dem grünen „verlässlich"-Tier),
            # zusätzlich gesenkt wenn Türen ohne lesbares Maß (Sturz nur geschätzt).
            # Der Pauschal-Fallback (schon 0.40-0.45) bleibt via min() unberührt.
            p.konfidenz = round(min(p.konfidenz, 0.55 if oeffnung_unscharf else 0.62), 2)
        elif b in ("Attika", "Säulen"):
            p.konfidenz = round(K_GEO * 0.6, 2)         # parametrische Schätzung
        elif b in ("Kamin", "Infrastruktur"):
            p.konfidenz = 0.7                           # Text-Zählung
        elif b == "Frostschürze":
            p.konfidenz = K_UMF if "noppenfolie" in mat else round(K_UMF * 0.9, 2)
        elif b == "Bodenplatte":
            # Footprint-Fläche byte-exakt gemessen → volle Geometrie-Konfidenz.
            p.konfidenz = K_UMF if umf else K_GEO
        elif b == "Decke über EG":
            if umf:
                p.konfidenz = K_UMF                     # Rand/Umfang-getrieben
            else:
                # Decke = byte-exakter Footprint × Auskragungs-/Loggia-FAKTOR
                # (kalibrierte Schätzung) → ehrlich etwas unter der reinen
                # Footprint-Sicherheit der Bodenplatte.
                p.konfidenz = round(K_GEO * (0.85 if ("iso-korb" in mat or "voranstrich" in mat) else 0.92), 2)
        elif b == "Mauerwerk EG":
            p.konfidenz = round(min(K_GEO, K_UMF + 0.05), 2) if umf else round(K_GEO * 0.88, 2)

    # ── plan_ref-TAGGING (Nachvollziehbarkeits-Audit P2): jede Position
    # referenziert ihre Plan-Ebene STRUKTURELL (Frontend-Kopplung lief bisher
    # über einen HLZ-Material-Regex — Konturen/Öffnungen hatten gar keine).
    import re as _re
    for p in out:
        _mat = (p.material or "").lower()
        _frm = (p.formel or "").lower()
        _m_hlz = _re.search(r"hlz\s*(\d+)", _mat)
        if _m_hlz:
            p.plan_ref = {"layer": "waende", "snap_cm": int(_m_hlz.group(1))}
        elif "überlage" in _mat or "rolladen" in _mat or "rollladen" in _mat:
            p.plan_ref = {"layer": "oeffnungen"}
        elif ("umfang" in _frm or "außenkante" in _frm or "frostgraben" in _frm
              or "gebäude-außen" in _frm):
            p.plan_ref = {"layer": "konturen"}

    # ── Kennzahlen (immer-sichtbar in der Auswertung) — EXAKT dieselben Werte, die
    # die Mengen treiben, damit Anzeige und Materialliste garantiert konsistent sind.
    if kennzahlen_out is not None:
        kennzahlen_out.update({
            "geschosshoehe_m": round(h, 2),
            "aussenwand_flaeche_m2": round(aw_m2_aussen, 2),
            "innenwand_flaeche_m2": round(iw_m2_innen_rohbau, 2),
            # BRUTTO (vor Öffnungsabzug) — Basis für die Gewerke-LV, die selbst abziehen
            "aussenwand_flaeche_brutto_m2": round(aw_m2_brutto, 2),
            "innenwand_flaeche_brutto_m2": round(iw_m2_brutto, 2),
            "wandflaeche_gesamt_m2": round(aw_m2_aussen + iw_m2_innen_rohbau, 2),
            "decke_flaeche_m2": round(decke_m2, 2),
            "decke_planmass_m2": decke_planmass_m2,
            "bodenplatte_flaeche_m2": round(bodenplatte_m2, 2),
            "aussenumfang_m": round(aussenumfang_m, 2),
            "fundament_umfang_m": round(fundament_umfang_m, 2),
        })

    return out


def build_materialliste(rooms, windows, baudaten, override=None, geschoss="EG",
                         tueren=None, gemessen=None, wand_verteilung=None, legende=None,
                         kalibrierung=None):
    """Wrapper: gibt strukturiertes Gewerk-Dict zurück.

    gemessen: optional dict mit gemessenen Werten aus PASS-4-Bemaßung +
              Vision-Außenkontur:
                {aussenumfang_m, bodenplatte_flaeche_m2, konfidenz, quelle}
              Wenn vorhanden, werden die Schätzformeln (sqrt-Bodenplatte,
              aussenumfang × 1.55) durch die gemessenen Werte ersetzt.
    kalibrierung: optional dict {faktor_key: wert} aus der firmenspezifischen +
              globalen Selbst-Kalibrierung. Auflösungs-Reihenfolge der Faktoren:
              USER-Override > Kalibrierung > Default. Umgesetzt durch Merge UNTER
              override — die byte-exakten Werte (Flächen/Maße) bleiben unangetastet,
              nur die parametrischen Aufschläge werden firmen-genauer.
    """
    if kalibrierung:
        override = {**kalibrierung, **(override or {})}
    kennzahlen = {}
    positionen = materialliste_bauteile(rooms, windows, baudaten, override, geschoss,
                                         tueren=tueren, gemessen=gemessen,
                                         wand_verteilung=wand_verteilung, legende=legende,
                                         kennzahlen_out=kennzahlen)
    # Gruppiere nach Bauteil
    by_bauteil = {}
    for p in positionen:
        by_bauteil.setdefault(p.bauteil, []).append(p.to_dict())

    return {
        "label": "Rohbau-Materialliste (Phase 1 — Faustformel-basiert)",
        "bauteile": by_bauteil,
        "kennzahlen": kennzahlen,
        "annahmen": {
            "bodenplatte_aufschlag": f("bodenplatte_aufschlag", override),
            "decke_aufschlag": f("decke_aufschlag", override),
            "wand_verteilung": {
                "50cm_aussen": f("wand_anteil_50cm", override),
                "38cm_aussen": f("wand_anteil_38cm", override),
                "25cm_aussen": f("wand_anteil_25cm_aussen", override),
                "25cm_innen": f("wand_anteil_25cm_innen", override),
                "20cm_innen": f("wand_anteil_20cm", override),
                "12cm_innen": f("wand_anteil_12cm", override),
            },
            "hinweis": ("Phase 1: Bauteilmengen aus Σ Raumfläche × Aufschlägen "
                        "geschätzt. Phase 2 (Vektor-Geometrie) wird Außenkontur "
                        "präzise lesen statt zu schätzen."),
        },
    }
