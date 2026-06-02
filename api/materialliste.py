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

    aw_m2_aussen = round(aussenumfang_m * h, 2)
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
    iw_m2_innen_rohbau = round(iw_laenge * h, 2)

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
    # Sauberkeitsschicht: Legende (byte-exakt in baudaten) > Override > Default
    sauber_cm = baudaten.get("sauberkeitsschicht_cm") or f("sauberkeitsschicht_cm", override)
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
        pos = []
        gesamt = 0.0
        for dd in sorted(m2_pro_dicke.keys(), reverse=True):
            m2 = m2_pro_dicke[dd]
            gesamt += m2
            cov = _coverage(dd)
            pos.append(MaterialPos(
                "Mauerwerk EG", f"HLZ {int(round(dd))}cm Plan", "Paletten",
                math.ceil(m2 / cov) if cov > 0 else 0,
                f"{' + '.join(formel_teile[dd])} ÷ {cov}m²/Pal", konfidenz=konf))
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
        a50 = aw_m2_aussen * f("wand_anteil_50cm", override) / 100.0
        a38 = aw_m2_aussen * f("wand_anteil_38cm", override) / 100.0
        a25a = aw_m2_aussen * f("wand_anteil_25cm_aussen", override) / 100.0
        i25 = iw_m2_innen_rohbau * f("wand_anteil_25cm_innen", override) / 100.0
        i20 = iw_m2_innen_rohbau * f("wand_anteil_20cm", override) / 100.0
        i12 = iw_m2_innen_rohbau * f("wand_anteil_12cm", override) / 100.0
        out.append(MaterialPos("Mauerwerk EG", "HLZ 50cm H.I. Plan", "Paletten",
            math.ceil(a50 / _coverage(50)), f"{a50:.1f}m² AW 50cm (Annahme)", konfidenz=0.5))
        out.append(MaterialPos("Mauerwerk EG", "HLZ 38cm H.I. Plan", "Paletten",
            math.ceil(a38 / _coverage(38)), f"{a38:.1f}m² AW 38cm (Annahme)", konfidenz=0.5))
        out.append(MaterialPos("Mauerwerk EG", "HLZ 25cm Plan", "Paletten",
            math.ceil((a25a + i25) / _coverage(25)), f"{a25a+i25:.1f}m² 25cm (Annahme)", konfidenz=0.5))
        out.append(MaterialPos("Mauerwerk EG", "HLZ 20cm Plan", "Paletten",
            math.ceil(i20 / _coverage(20)), f"{i20:.1f}m² IW 20cm (Annahme)", konfidenz=0.5))
        out.append(MaterialPos("Mauerwerk EG", "HLZ 12cm Plan", "Paletten",
            math.ceil(i12 / _coverage(12)), f"{i12:.1f}m² IW 12cm (Annahme)", konfidenz=0.5))
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
        n_125 = sum(1 for b in tuer_breiten if b <= 1.10) + n_ohne_breite  # ≤110cm + ohne Maß
        n_200 = sum(1 for b in tuer_breiten if 1.10 < b <= 1.80)  # 110-180cm
        n_250 = sum(1 for b in tuer_breiten if b > 1.80)         # Schiebe/Terrasse
        if n_125:
            _txt125 = (f"{n_125} Innentüren (≤110cm" + (f" + {n_ohne_breite} ohne Maß)" if n_ohne_breite else ")"))
            out.append(MaterialPos(
                "Öffnungen", "Ziegelüberlage 12cm 125cm", "Stk",
                n_125, _txt125, konfidenz=0.85 if not n_ohne_breite else 0.7))
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

    # ── Kennzahlen (immer-sichtbar in der Auswertung) — EXAKT dieselben Werte, die
    # die Mengen treiben, damit Anzeige und Materialliste garantiert konsistent sind.
    if kennzahlen_out is not None:
        kennzahlen_out.update({
            "geschosshoehe_m": round(h, 2),
            "aussenwand_flaeche_m2": round(aw_m2_aussen, 2),
            "innenwand_flaeche_m2": round(iw_m2_innen_rohbau, 2),
            "wandflaeche_gesamt_m2": round(aw_m2_aussen + iw_m2_innen_rohbau, 2),
            "decke_flaeche_m2": round(decke_m2, 2),
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
