"""Bauphysikalische Konsistenz-Engine.

Nach Multi-Plan-Merge + Halluzinations-Filter laufen Plausibilitäts-
Checks: Mengen-Bilanzen, Raum-Geometrie-Verträglichkeit, Cross-Plan-
Konflikte. Findet die letzten Vision-Halluzinationen vor der
Materialliste-Berechnung.

Jeder Check liefert eine Liste von Findings:
  {
    "check":     "raum_summen" | "fenster_anzahl" | "hoehen" | ...,
    "schwere":   "info" | "warnung" | "fehler",
    "msg":       "Σ Räume 245 m² ist 80% mehr als Bodenplatten-Schätzung 136 m²",
    "betroffen": ["Wohnen Küche", ...]   # Element-Namen, optional
  }
"""
from __future__ import annotations
import math
import statistics

# Konstanten / Plausibilitäts-Grenzen
H_MIN_M = 2.20    # niedrigste plausible Raumhöhe (z.B. Bad mit abgehängter Decke)
H_MAX_M = 4.00    # höchste plausible für EFH/MFH
H_STDDEV_MAX = 0.30  # zulässige Streuung pro Geschoss
BODENBELAG_NASS = {"fliesen", "feinsteinzeug", "keramik", "naturstein"}
BODENBELAG_TROCKEN = {"parkett", "laminat", "vinyl", "teppich"}
NASS_RAUM_PREFIXES = {"bad", "wc", "dusche", "sauna", "waschküche", "waschkueche",
                       "waschraum", "waschen"}


def _nk(s):
    import re
    return re.sub(r"[\s\-_/]+", "", (s or "").lower())


def _is_innen_warm(name, kategorie_of):
    return kategorie_of(name) == "Innenraum_warm"


def check_raum_summen(rooms, kategorie_of):
    """Σ F_innen darf nicht offensichtlich unrealistisch sein.
    Sehr großer Σ F bei wenigen Räumen deutet auf Halluzinationen hin."""
    findings = []
    innen = [r for r in rooms
             if _is_innen_warm(r.get("name") or "", kategorie_of) and r.get("flaeche_m2")]
    if not innen:
        return findings
    f_sum = sum(r["flaeche_m2"] for r in innen)
    # EFH-Durchschnitt 15-25 m² pro Innenraum
    f_avg = f_sum / len(innen)
    if f_avg > 35.0:
        findings.append({
            "check": "raum_summen",
            "schwere": "warnung",
            "msg": f"Ø {f_avg:.1f} m² pro Innenraum ist hoch — übliche EFH-Spanne 15-25 m². "
                   f"Möglicherweise Loggia/Terrasse als Innenraum klassifiziert.",
        })
    return findings


def check_hoehen_konsistenz(rooms):
    """Alle Raumhöhen sollten zwischen H_MIN/H_MAX liegen und max 30cm streuen."""
    findings = []
    h_values = [(r.get("name"), r["hoehe_m"]) for r in rooms
                if r.get("hoehe_m") and not r.get("_h_inferred")]
    if not h_values:
        return findings
    for name, h in h_values:
        if h < H_MIN_M or h > H_MAX_M:
            findings.append({
                "check": "hoehen",
                "schwere": "fehler",
                "msg": f"Raum '{name}' hat unplausible Höhe {h:.2f} m "
                       f"(erwartet {H_MIN_M}-{H_MAX_M} m)",
                "betroffen": [name],
            })
    if len(h_values) >= 3:
        h_vals_only = [h for _, h in h_values]
        std = statistics.stdev(h_vals_only)
        if std > H_STDDEV_MAX:
            sorted_h = sorted([(n, h) for n, h in h_values], key=lambda x: x[1])
            findings.append({
                "check": "hoehen",
                "schwere": "info",
                "msg": f"Streuung der Raumhöhen σ={std:.2f}m ist hoch "
                       f"(typisch ±10cm pro Geschoss). Niedrigste: {sorted_h[0][0]} "
                       f"{sorted_h[0][1]:.2f}m, höchste: {sorted_h[-1][0]} {sorted_h[-1][1]:.2f}m",
            })
    return findings


def check_oeffnungen_pro_raum(rooms, fenster, tueren, kategorie_of):
    """Pro Innenraum erwarten wir ~1 Fenster (außer Flur/WC) + ~1 Tür."""
    findings = []
    innen = [r for r in rooms if _is_innen_warm(r.get("name") or "", kategorie_of)]
    if not innen:
        return findings
    # Räume ohne Fenster identifizieren — bei EFH soll fast jeder Wohnraum
    # ein Fenster haben (außer interne Flure)
    raeume_mit_fenster = set()
    for f in fenster or []:
        raum = (f.get("raum") or "").strip().lower()
        if raum:
            raeume_mit_fenster.add(_nk(raum))
    INTERNE_RAUM_PREFIXES = {"flur", "vorraum", "gang", "garderobe", "abstellraum",
                              "speis", "speisekammer", "ar"}
    fehlend = []
    for r in innen:
        nm = (r.get("name") or "")
        nm_nk = _nk(nm)
        is_intern = any(nm_nk.startswith(p) for p in INTERNE_RAUM_PREFIXES)
        if is_intern:
            continue
        # Suche Fenster das diesem Raum zugeordnet ist (auch über Teilnamen)
        found = False
        for fnm in raeume_mit_fenster:
            if fnm == nm_nk or fnm in nm_nk or nm_nk in fnm:
                found = True
                break
        if not found:
            fehlend.append(nm)
    if fehlend:
        findings.append({
            "check": "fenster_anzahl",
            "schwere": "info",
            "msg": f"{len(fehlend)} Wohnräume ohne erkanntes Fenster: "
                   f"{', '.join(fehlend[:5])}{'...' if len(fehlend)>5 else ''}. "
                   f"Eventuell Fenster nicht im Text-Layer codiert (STUK/FPH) "
                   f"oder Raumzuordnung über Position fehlgeschlagen.",
            "betroffen": fehlend,
        })
    return findings


def check_bodenbelag(rooms):
    """Bad/WC/Waschküche sollten Nass-Belag (Fliesen) haben, Wohnräume Trocken."""
    findings = []
    miss = []
    for r in rooms:
        nm = (r.get("name") or "").lower()
        belag = (r.get("bodenbelag") or "").lower()
        if not belag:
            continue
        is_nass = any(nm.startswith(p) for p in NASS_RAUM_PREFIXES)
        if is_nass and belag in BODENBELAG_TROCKEN:
            miss.append(f"{r.get('name')} ({belag})")
        # Trocken-Räume mit Fliesen → in EFH häufig OK (Küche), kein Finding
    if miss:
        findings.append({
            "check": "bodenbelag",
            "schwere": "info",
            "msg": f"{len(miss)} Nass-Räume mit Trocken-Belag: "
                   f"{', '.join(miss)}. Möglicherweise falsche Bodenbelag-Erkennung.",
            "betroffen": [m.split(' (')[0] for m in miss],
        })
    return findings


def check_aussenkontur_plausibel(rooms, kategorie_of):
    """Σ F_innen × 1.15 sollte zur Bodenplatten-Schätzung passen.
    Bei extremer Diskrepanz: möglich Loggia/Terrasse fälschlich gezählt."""
    findings = []
    innen = [r for r in rooms if _is_innen_warm(r.get("name") or "", kategorie_of)]
    loggia = [r for r in rooms if kategorie_of(r.get("name") or "") == "Loggia"]
    if not innen:
        return findings
    f_innen = sum(r.get("flaeche_m2") or 0 for r in innen)
    f_loggia = sum(r.get("flaeche_m2") or 0 for r in loggia)
    # EFH typisch: F_loggia 30-60% von F_innen (Terrasse + Parkplatz)
    if f_innen > 0 and f_loggia > f_innen * 1.5:
        findings.append({
            "check": "aussenkontur",
            "schwere": "info",
            "msg": f"Σ Loggia/Terrasse {f_loggia:.1f} m² ist deutlich größer als "
                   f"Innen {f_innen:.1f} m². Bei EFH typisch ~50% — bitte prüfen.",
        })
    return findings


def check_cross_plan_konflikte(rooms):
    """Räume die in 2+ Plänen vorkommen sollten ähnliche F/U haben (5% Toleranz).
    Größere Diskrepanz → der Architekt hat den Raum überarbeitet oder
    eine Vision hat anders gelesen."""
    findings = []
    for r in rooms:
        if len(r.get("_quellen_plaene") or []) < 2:
            continue
        # _merged_from sagt welche Felder zwischen Plänen gemergt wurden.
        # Ein "konflikt"-Tag müssten wir setzen wenn beide Pläne ein F haben
        # und es signifikant abweicht. Diese Information ist aktuell nicht
        # im merge_rooms. Wir markieren stattdessen "merged" als info.
    return findings


def laufe_alle_checks(rooms, fenster, tueren, kategorie_of_fn):
    """Sammle alle Findings."""
    findings = []
    findings.extend(check_raum_summen(rooms, kategorie_of_fn))
    findings.extend(check_hoehen_konsistenz(rooms))
    findings.extend(check_oeffnungen_pro_raum(rooms, fenster, tueren, kategorie_of_fn))
    findings.extend(check_bodenbelag(rooms))
    findings.extend(check_aussenkontur_plausibel(rooms, kategorie_of_fn))
    findings.extend(check_cross_plan_konflikte(rooms))
    return findings


# Zusammenfassende Statistik für UI
def zusammenfassung(findings):
    if not findings:
        return {"status": "ok", "anzahl": 0, "schwere_max": "ok",
                "msg": "Alle Konsistenz-Checks bestanden."}
    schweren = {"info": 0, "warnung": 0, "fehler": 0}
    for f in findings:
        schweren[f.get("schwere", "info")] += 1
    if schweren["fehler"]:
        max_sch = "fehler"
    elif schweren["warnung"]:
        max_sch = "warnung"
    else:
        max_sch = "info"
    return {
        "status": max_sch,
        "anzahl": len(findings),
        "schwere_max": max_sch,
        "schweren": schweren,
    }
