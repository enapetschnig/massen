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
    # Decken-Aufbau
    "decke_auskragung": 1.05,          # (Bodenplatte+Loggia) × Faktor = Schalungs-Fläche
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
        self.menge = round(float(menge or 0), 2)
        self.formel = formel
        self.konfidenz = konfidenz

    def to_dict(self):
        return {
            "bauteil": self.bauteil,
            "material": self.material,
            "menge": self.menge,
            "einheit": self.einheit,
            "formel": self.formel,
            "konfidenz": self.konfidenz,
        }


# ────────────────────────────────────────────────────────────────────
# BAUTEIL-BERECHNUNGEN
# ────────────────────────────────────────────────────────────────────
def materialliste_bauteile(rooms, windows, baudaten, override=None, geschoss="EG",
                            tueren=None, gemessen=None):
    """Erzeugt eine flache Liste von MaterialPos über alle Bauteile.

    rooms:    gemergte Räume aus /api/projekt-massen
    windows:  erkannte Fenster (mit breite_m × hoehe_m)
    tueren:   erkannte Türen aus STUK/FPH-Cluster
    gemessen: optional {aussenumfang_m, bodenplatte_flaeche_m2, konfidenz, quelle}
              aus PASS-4-Bemaßung + Vision-Außenkontur. Wenn vorhanden,
              ersetzen diese Werte die Schätzformeln (sqrt × 1.55 etc).
              Konfidenz steigt entsprechend von 55-65% auf 85-95%.
    """
    tueren = tueren or []
    gemessen = gemessen or {}
    from massen_logic import kategorie_of

    def _kat(r):
        return kategorie_of(r.get("name") or r.get("bezeichnung") or "")

    innen = [r for r in rooms if _kat(r) == "Innenraum_warm"]
    loggia = [r for r in rooms if _kat(r) == "Loggia"]  # Terrasse, Balkon, Parkplatz

    f_sum_innen = sum(r.get("flaeche_m2") or 0 for r in innen)
    f_sum_loggia = sum(r.get("flaeche_m2") or 0 for r in loggia)
    u_sum_innen = sum(r.get("umfang_m") or 0 for r in innen)
    h_room = sum((r.get("hoehe_m") or 0) for r in innen if r.get("hoehe_m")) / max(
        1, sum(1 for r in innen if r.get("hoehe_m")))
    h = h_room if h_room > 0 else baudaten.get("geschosshoehe_m", 2.70)
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
        decke_m2 = round((bodenplatte_m2 + f_sum_loggia) * f("decke_auskragung", override), 2)
        geometrie_quelle = gemessen.get("quelle", "gemessen")
        geometrie_konfidenz = float(gemessen.get("konfidenz") or 0.85)
    else:
        bodenplatte_m2 = round(f_bp_base * bp_faktor, 2)
        # Auch im Schätz-Fall die Loggia für die Decke mitzählen
        decke_m2 = round((f_sum_innen + f_sum_loggia) * dk_faktor, 2)
        geometrie_quelle = f"Σ Raum-F × {bp_faktor:.2f}-Aufschlag"
        geometrie_konfidenz = 0.65

    if gemessen.get("aussenumfang_m"):
        aussenumfang_m = round(float(gemessen["aussenumfang_m"]), 2)
        umfang_quelle = gemessen.get("quelle", "gemessen")
        umfang_konfidenz = float(gemessen.get("konfidenz") or 0.85)
    else:
        aussenumfang_m = aussenumfang_schaetzung(
            bodenplatte_m2, aufschlag=f("aussenumfang_aufschlag", override))
        umfang_quelle = f"sqrt(BP)·4·{f('aussenumfang_aufschlag', override):.2f}-Aufschlag"
        umfang_konfidenz = 0.55

    aw_m2_aussen = round(aussenumfang_m * h, 2)
    iw_m2_innen_rohbau = max(0, round(u_sum_innen * h - aw_m2_aussen, 2))

    out = []

    # ═══ Frostschürze ═══
    # Die Frostschürze läuft als Graben AUSSEN um die Bodenplatte → etwas
    # größerer Umfang als die Gebäude-Außenkante (frostgraben_aufschlag).
    fg_umfang = round(aussenumfang_m * f("frostgraben_aufschlag", override), 2)
    fs_tiefe = f("frostschuerze_tiefe_m", override)
    fs_breite = f("frostschuerze_breite_m", override)
    fs_m3 = fg_umfang * fs_tiefe * fs_breite
    out.append(MaterialPos(
        "Frostschürze", "Lieferbeton C25/30, XC1, F52, GK 22", "m³",
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
        "Bodenplatte", "Lieferbeton C25/30, B2, GK 22, F52", "m³",
        bp_m3, f"{bodenplatte_m2}m² × {bopl_cm}cm Dicke",
        konfidenz=0.7))
    sauber_cm = f("sauberkeitsschicht_cm", override)
    out.append(MaterialPos(
        "Bodenplatte", "Lieferbeton C16/20 (Sauberkeitsschicht)", "m³",
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
        aussenumfang_m, f"Außenumfang {aussenumfang_m}m", konfidenz=0.65))
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
        round(aussenumfang_m * f("torstahl_stk_pro_m_randabschluss", override)),
        "Außenumfang × Stk-Dichte", konfidenz=0.4))

    # ═══ Mauerwerk EG — HLZ-Paletten pro Wandstärke ═══
    # Außenwand auf 50cm/38cm/25cm-aussen verteilen
    a50 = aw_m2_aussen * f("wand_anteil_50cm", override) / 100.0
    a38 = aw_m2_aussen * f("wand_anteil_38cm", override) / 100.0
    a25a = aw_m2_aussen * f("wand_anteil_25cm_aussen", override) / 100.0
    # Innenwand auf 25cm-innen/20cm/12cm
    i25 = iw_m2_innen_rohbau * f("wand_anteil_25cm_innen", override) / 100.0
    i20 = iw_m2_innen_rohbau * f("wand_anteil_20cm", override) / 100.0
    i12 = iw_m2_innen_rohbau * f("wand_anteil_12cm", override) / 100.0
    gesamt_m2_25 = a25a + i25

    def pal(m2, key):
        m2_pro_pal = f(key, override)
        return math.ceil(m2 / m2_pro_pal) if m2_pro_pal > 0 else 0

    out.append(MaterialPos(
        "Mauerwerk EG", "HLZ 50cm H.I. Plan", "Paletten",
        pal(a50, "hlz_50cm_m2_pro_palette"),
        f"{a50:.1f}m² Außenwand 50cm ÷ {f('hlz_50cm_m2_pro_palette', override)}m²/Pal", konfidenz=0.5))
    out.append(MaterialPos(
        "Mauerwerk EG", "HLZ 38cm H.I. Plan", "Paletten",
        pal(a38, "hlz_38cm_m2_pro_palette"),
        f"{a38:.1f}m² Außenwand 38cm", konfidenz=0.5))
    out.append(MaterialPos(
        "Mauerwerk EG", "HLZ 25cm Plan", "Paletten",
        pal(gesamt_m2_25, "hlz_25cm_m2_pro_palette"),
        f"{gesamt_m2_25:.1f}m² (Außen 25cm + Innen 25cm)", konfidenz=0.5))
    out.append(MaterialPos(
        "Mauerwerk EG", "HLZ 20cm Plan", "Paletten",
        pal(i20, "hlz_20cm_m2_pro_palette"),
        f"{i20:.1f}m² Innenwand 20cm", konfidenz=0.5))
    out.append(MaterialPos(
        "Mauerwerk EG", "HLZ 12cm Plan", "Paletten",
        pal(i12, "hlz_12cm_m2_pro_palette"),
        f"{i12:.1f}m² Innenwand 12cm", konfidenz=0.5))

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
    out.append(MaterialPos(
        "Mauerwerk EG", "Mauersperrbahn 25cm", "Rollen",
        math.ceil(aussenumfang_m / 25) or 1,
        f"Außenumfang {aussenumfang_m}m ÷ 25m/Rolle", konfidenz=0.65))

    # ═══ Öffnungen — Ziegelüberlagen + Rolladenkästen aus Vision-Fenster ═══
    fenster_breiten = []
    for w in (windows or []):
        bw = w.get("breite_m") or (w.get("breite_cm", 0) / 100.0 if w.get("breite_cm") else None)
        if bw:
            fenster_breiten.append(bw)

    rolladen_125 = sum(1 for b in fenster_breiten if 1.0 <= b <= 1.4)
    rolladen_180 = sum(1 for b in fenster_breiten if 1.4 < b <= 2.0)
    rolladen_215 = sum(1 for b in fenster_breiten if 2.0 < b <= 2.4)

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

    # Ziegelüberlagen aus den ERKANNTEN Türen (statt Pauschal).
    # Ziegelüberlage-Standard-Längen: 125cm (für Türöffnungen bis ~100cm),
    # 200cm (~150-180cm Öffnung), 250cm (~200-230cm Öffnung).
    if tueren:
        tuer_breiten = []
        for t in tueren:
            bw = t.get("breite_m") or (t.get("breite_cm", 0) / 100.0 if t.get("breite_cm") else None)
            if bw:
                tuer_breiten.append(bw)
        n_125 = sum(1 for b in tuer_breiten if b <= 1.10)        # 60-100cm Türen
        n_200 = sum(1 for b in tuer_breiten if 1.10 < b <= 1.80)  # 110-180cm
        n_250 = sum(1 for b in tuer_breiten if b > 1.80)         # Schiebe/Terrasse
        if n_125:
            out.append(MaterialPos(
                "Öffnungen", "Ziegelüberlage 12cm 125cm", "Stk",
                n_125, f"{n_125} Türen ≤110cm Breite", konfidenz=0.85))
        if n_200:
            out.append(MaterialPos(
                "Öffnungen", "Ziegelüberlage 12cm 200cm", "Stk",
                n_200, f"{n_200} Türen 110-180cm Breite", konfidenz=0.8))
        if n_250:
            out.append(MaterialPos(
                "Öffnungen", "Ziegelüberlage 12cm 250cm", "Stk",
                n_250, f"{n_250} Türen/Schiebe-Elemente >180cm", konfidenz=0.8))
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
        "Decke über EG", "Lieferbeton C25/30, XC1, GK 22, F52", "m³",
        decke_m3, f"{decke_m2}m² × {decke_cm}cm", konfidenz=0.7))
    out.append(MaterialPos(
        "Decke über EG", "Schaltafel 200/50", "m²",
        decke_m2, f"{decke_m2}m² Schalung", konfidenz=0.7))
    iso_korb_m = aussenumfang_m * f("iso_korb_anteil", override)
    out.append(MaterialPos(
        "Decke über EG", "ISO-Korb 8/25", "lfm",
        iso_korb_m, f"Außenumfang {aussenumfang_m}m × {f('iso_korb_anteil', override)}",
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
        aussenumfang_m, f"Außenumfang {aussenumfang_m}m", konfidenz=0.65))
    aq65_dk = f("aq65_m2_pro_matte", override)
    out.append(MaterialPos(
        "Decke über EG", "Baustahlgitter AQ 65", "Stk",
        math.ceil(decke_m2 / aq65_dk) if aq65_dk > 0 else 0,
        f"{decke_m2}m² ÷ {aq65_dk}m²/Matte", konfidenz=0.55))
    out.append(MaterialPos(
        "Decke über EG", "bitumin. Voranstrich", "Kanister",
        math.ceil(decke_m2 / 100 * f("voranstrich_kanister_pro_100m2", override)) or 1,
        f"{decke_m2}m² Decke", konfidenz=0.55))

    # ═══ Attika (nur bei Flachdach) ═══
    if f("attika_aktiv", override) or f("attika_anteil_aussen", override) > 0:
        att_h = f("attika_hoehe_m", override)
        attika_m2 = aussenumfang_m * att_h
        out.append(MaterialPos(
            "Attika", "XPS 6cm Oberfläche rau", "m²",
            attika_m2, f"Außenumfang {aussenumfang_m}m × {att_h}m Höhe", konfidenz=0.45))
        out.append(MaterialPos(
            "Attika", "Lieferbeton C25/30", "m³",
            attika_m2 * 0.15, f"{round(attika_m2,1)}m² × 0.15m Stärke", konfidenz=0.4))
        out.append(MaterialPos(
            "Attika", "Steckeisen 10mm a 1m gekröpft", "Stk",
            round(aussenumfang_m * 3), f"Außenumfang × 3 Stk/m", konfidenz=0.4))

    # ═══ Säulen / Stützen (nur wenn anzahl_saeulen gesetzt) ═══
    n_saeulen = int(f("anzahl_saeulen", override))
    if n_saeulen > 0:
        beton_pro = f("saeule_beton_m3_pro_stk", override)
        out.append(MaterialPos(
            "Säulen", "Lieferbeton C25/30 (Fundamente + Säulen)", "m³",
            n_saeulen * beton_pro, f"{n_saeulen} Säulen × {beton_pro}m³", konfidenz=0.45))
        out.append(MaterialPos(
            "Säulen", "Bügel geschlossen 18/18 12mm", "Stk",
            n_saeulen * 15, f"{n_saeulen} Säulen × 15 Bügel", konfidenz=0.4))
        out.append(MaterialPos(
            "Säulen", "Torstahl 14mm a 7m", "Stk",
            n_saeulen * 2, f"{n_saeulen} Säulen × 2 Stäbe", konfidenz=0.4))

    # ═══ Kamin (nur wenn anzahl_kamine gesetzt) ═══
    n_kamine = int(f("anzahl_kamine", override))
    if n_kamine > 0:
        out.append(MaterialPos(
            "Kamin", "Kamin DN16 mit Fertigfuß und Haube (Schiedel)", "Stk",
            n_kamine, f"{n_kamine} Kamin(e)", konfidenz=0.6))

    return out


def build_materialliste(rooms, windows, baudaten, override=None, geschoss="EG",
                         tueren=None, gemessen=None):
    """Wrapper: gibt strukturiertes Gewerk-Dict zurück.

    gemessen: optional dict mit gemessenen Werten aus PASS-4-Bemaßung +
              Vision-Außenkontur:
                {aussenumfang_m, bodenplatte_flaeche_m2, konfidenz, quelle}
              Wenn vorhanden, werden die Schätzformeln (sqrt-Bodenplatte,
              aussenumfang × 1.55) durch die gemessenen Werte ersetzt.
    """
    positionen = materialliste_bauteile(rooms, windows, baudaten, override, geschoss,
                                         tueren=tueren, gemessen=gemessen)
    # Gruppiere nach Bauteil
    by_bauteil = {}
    for p in positionen:
        by_bauteil.setdefault(p.bauteil, []).append(p.to_dict())

    return {
        "label": "Rohbau-Materialliste (Phase 1 — Faustformel-basiert)",
        "bauteile": by_bauteil,
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
