"""Opus-Korrektur-Loop (S1).

Lässt die Opus-Schlussprüfung GESCHÄTZTE Mengen gegen den Plan nachjustieren —
mit harten Schutzregeln, damit byte-exakte und Legende-gebundene Werte NIEMALS
angetastet werden. Das ist der „+2-Stufen"-Sprung: die Materialliste validiert
sich gegen den Plan, statt dass Opus nur advisorisch meldet.

Reine, testbare Logik. Die Verdrahtung in den /api-Endpoint ist hinter dem
Env-Flag OPUS_NUDGE (Default AUS) gegated — solange aus, ist dieses Modul
vollständig dormant.

SCHUTZREGELN (eine Position ist nur korrigierbar, wenn ALLE gelten):
  1. Konfidenz < NUDGE_KONF_MAX — da die Konfidenz inzwischen byte-exakt vs.
     geschätzt sauber widerspiegelt, ist sie das einzige nötige Tor. Hohe
     Konfidenz = gemessen/Legende = tabu (Bodenplatte 0.95, gemessene Decke,
     Legende-HLZ bleiben unberührt). Niedrige = geschätzt = korrigierbar
     (Öffnungen, Säulen, Attika, Fallback-Decke).
  2. Beleg vorhanden — kein Beleg, keine Korrektur.
  3. Abweichung ≤ NUDGE_ABW_MAX — größere Sprünge werden NICHT angewandt,
     sondern nur zur manuellen Prüfung geflaggt (Opus-Halluzinations-Schutz).
Nach Anwendung: Konfidenz gedeckelt (geschätzt, nicht gemessen) + sichtbarer
„Opus-korrigiert (Beleg: …)"-Vermerk in der Formel + opus_korrigiert-Flag.
"""

NUDGE_KONF_MAX = 0.80      # nur Positionen mit Konfidenz < 0.80 sind korrigierbar
NUDGE_ABW_MAX = 0.25       # nur Korrekturen bis ±25% anwenden, sonst nur flaggen
NUDGE_KONF_NACH = 0.60     # nach Korrektur: Konfidenz gedeckelt (Opus-Schätzung)


def _eligible(positionen):
    """Nur ehrlich unsichere Positionen sind korrigierbar — byte-exakt = tabu."""
    return [p for p in positionen if (p.get("konfidenz") or 1.0) < NUDGE_KONF_MAX]


def _match_pos(positionen, material):
    """Zielposition: per Material-Stichwort eindeutig, sonst die einzige geschätzte."""
    elig = _eligible(positionen)
    if material:
        ml = material.lower()
        treffer = [p for p in elig if ml in (p.get("material") or "").lower()]
        return treffer[0] if len(treffer) == 1 else None
    return elig[0] if len(elig) == 1 else None


def opus_mengen_nudge(bauteile, korrekturen, *, konf_max=NUDGE_KONF_MAX,
                      abw_max=NUDGE_ABW_MAX, konf_nach=NUDGE_KONF_NACH):
    """Wendet Opus-Mengen-Korrekturen auf geschätzte Positionen an (in-place).

    bauteile:    {bauteil_name: [pos, ...]} aus materialliste_result["bauteile"];
                 jede pos ein dict mit menge/konfidenz/material/formel.
    korrekturen: [{bauteil, material?, soll_menge, beleg}] aus der Opus-Prüfung.

    Returns: (bauteile, log) — log dokumentiert JEDE Korrektur transparent
             (angewandt / geflaggt / abgelehnt + Grund), für Prüfliste & Herkunft.
    """
    log = []
    for k in (korrekturen or []):
        k = k or {}
        bt = k.get("bauteil")
        beleg = (k.get("beleg") or "").strip()
        material = k.get("material")
        soll_raw = k.get("soll_menge")

        if not bt or bt not in bauteile:
            log.append({"bauteil": bt, "status": "abgelehnt", "grund": "Bauteil nicht in Liste"})
            continue
        if not beleg:
            log.append({"bauteil": bt, "status": "abgelehnt", "grund": "kein Beleg"})
            continue
        try:
            soll = float(soll_raw)
        except (TypeError, ValueError):
            log.append({"bauteil": bt, "status": "abgelehnt", "grund": "Soll keine Zahl"})
            continue
        if soll <= 0:
            log.append({"bauteil": bt, "status": "abgelehnt", "grund": "Soll ≤ 0"})
            continue

        pos = _match_pos(bauteile[bt], material)
        if pos is None:
            log.append({"bauteil": bt, "material": material, "status": "abgelehnt",
                        "grund": "keine eindeutige GESCHÄTZTE Zielposition (byte-exakt ist tabu)"})
            continue

        alt = float(pos.get("menge") or 0)
        if alt <= 0:
            log.append({"bauteil": bt, "material": pos.get("material"), "status": "abgelehnt",
                        "grund": "Ist-Menge 0 — keine Skalierungsbasis"})
            continue

        abw = abs(soll - alt) / alt
        if abw > abw_max:
            log.append({"bauteil": bt, "material": pos.get("material"), "status": "geflaggt",
                        "alt": round(alt, 2), "soll": round(soll, 2), "abw": round(abw, 4),
                        "beleg": beleg,
                        "grund": f"Abweichung {abw*100:.0f}% > {abw_max*100:.0f}% — nicht angewandt, manuell prüfen"})
            continue

        # ── anwenden ──
        pos["menge"] = round(soll, 2)
        pos["konfidenz"] = round(min(float(pos.get("konfidenz") or konf_nach), konf_nach), 2)
        _f = pos.get("formel") or ""
        pos["formel"] = (_f + f" · Opus-korrigiert {round(alt, 2)}→{round(soll, 2)} (Beleg: {beleg})").strip(" ·")
        pos["opus_korrigiert"] = True
        log.append({"bauteil": bt, "material": pos.get("material"), "status": "angewandt",
                    "alt": round(alt, 2), "neu": round(soll, 2), "abw": round(abw, 4), "beleg": beleg})

    return bauteile, log
