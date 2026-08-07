#!/usr/bin/env python3
"""SCOREBOARD — alle Kern-Metriken der App in einem Lauf (Doktrin: Messwert statt
Behauptung). Vor/nach JEDER Änderung laufen lassen; keine Zahl darf fallen.

Lauf: massenermittlung/venv/bin/python3 scripts/test_alles.py [--schnell]
  --schnell: nur die Guards (ohne Korpus/Raumverifikation, ~10s statt ~2min)
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, "massenermittlung", "venv", "bin", "python3")

GUARDS = [
    ("Polier-Liste (rote Linie)", "test_materialliste_angerer.py", "13/13 Positionen"),
    ("ÖNORM-Öffnungslogik", "test_massen_logic.py", "B 2204 §5.5.1.3"),
    ("Öffnungs-Codes", "test_oeffnungen_codes.py", "STUK/FPH/STUK-only"),
    ("Verschnitt", "test_verschnitt.py", "nur HLZ, nur aufwärts"),
    ("Farb-Legende", "test_farben.py", "Neubau/Bestand/Abbruch + Boilerplate-Gate"),
    ("Nachzeichnen-Backend", "test_nachzeichnen.py", "Bild+Wände+graceful-fail"),
    ("Korrektur-Override", "test_nachzeichnen_override.py", "bounded, kein Kollateral"),
    ("Aufmaßblatt", "test_aufmassblatt.py", "PDF mit Plan+Einzeichnungen"),
    ("Kalibrier-Mechanik", "test_kalibrierung.py", "dormant, aber intakt"),
    ("Dach-Sektor (byte-exakt)", "test_dach_positionen.py", "Σ=Gesamt + Sparren + Velux"),
    ("Edge-Case-Robustheit", "test_edgecases.py", "leer/Scan/rotiert — nie crashen"),
    ("Mengen-Engine-Fuzz", "test_materialliste_fuzz.py", "None/Strings/negativ — nie crashen/negativ"),
    ("Aufmaß-Kreuztabelle", "test_aufmass_matrix.py", "Räume × Positionen, Abzüge raumscharf"),
    ("Aufmaßregeln (ÖNORM-Deckung)", "test_aufmassregeln.py", "Positionen mit Menge"),
    ("Eigene Positionen (Regel-Pflicht)", "test_eigene_positionen.py", "Aufmaßregeln"),
    ("Vision-Antwort-Parser", "test_json_parser.py", "Vision-Parser"),
    ("LV-Import (A 2063)", "test_lv_import.py", "LV-Import"),
    ("ÖNORM-Nachweis (Rechenweg)", "mess_oenorm_nachweis.py", "Regeln nachgewiesen"),
    ("Gewerke-Breite (Sektoren)", "mess_gewerke_breite.py", "Gewerke liefern Mengen"),
    ("Textfleck-Anker (Scan-Lage)", "test_textanker.py", "Textfleck-Anker"),
    ("Workflow-Schritte", "test_workflow_schritte.py", "Pflicht-Bereiche"),
    ("Gleichnamige Räume (MFH)", "test_namens_kollision.py", "eigene Zahlen"),
    ("Klick-Handler (Im Plan zeigen)", "test_klick_handler.py", "Inline-Handler"),
    ("Außenumfang plausibel", "test_umfang_plausibel.py", "richtig bewertet"),
    ("Quellen-Konflikt (Text schlägt Vision)", "test_quellen_konflikt.py", "Konfliktfälle"),
    ("Umriss begradigen", "test_umriss_begradigen.py", "Zickzack wird begradigt"),
    ("Umriss auf Wand (Kennzahl)", "test_umriss_auf_wand.py", "misst Wandnaehe, ist kein Beweis"),
    # Lag unregistriert im Ordner und lief damit NIE mit — von der
    # Verwaisten-Pruefung dieser Suite gefunden (2026-08-06).
    ("Umfassung je Bauteil", "test_raumumfassung.py", "Raeume zerlegt"),
    ("Raumname aus dem Stempel", "test_raumname_buendig.py", "Stempel-Formen"),
    ("Freifläche ist kein Raum", "test_aussenanlage.py", "richtig eingeordnet"),
    ("Plan-Varianten (gebaute Pläne)", "test_planvarianten.py", "Planarten"),
    ("Sektoren der Baubranche", "test_sektoren.py", "Bauarten"),
    ("Sanierung + Scan (gebaut)", "test_sanierung_und_scan.py", "Sanierungsplan"),
    ("Trockenbau-Hinweis (LG 39)", "test_trockenbau_hinweis.py", "Kennzeichnung erkannt"),
    ("Schichtaufbau Holzbau/WDVS", "test_schicht_aufbau.py", "Gesamtspanne"),
    ("RBL-Öffnungen (Rohbaulichte)", "test_rbl_oeffnungen.py", "vollständige Öffnungsmaße"),
    ("Öffnungen ohne Maß", "test_oeffnungen_hinweis.py", "kein stiller Nulldurchgang"),
    ("Schnitt-Koten (Maßstab/Höhen)", "test_schnitt_koten.py", "kein Blatt behauptet Höhen"),
    ("Höhen-Vorrang (Messung vor Schätzung)", "test_hoehen_vorrang.py", "Physik-Sperren"),
    ("Messung vor Schätzung (3 Audit-Fixes)", "test_messung_vor_schaetzung.py", "festgenagelt"),
    ("Nachvollziehbarkeit (Menge → Plan)", "test_nachvollziehbarkeit.py", "am Plan zeigbar"),
    ("Stempel-Schreibweisen", "mess_stempel_konventionen.py", "BEKANNTE Schreibweisen"),
    # ── NACHGETRAGEN 2026-07-30 ────────────────────────────────────────
    # Diese 22 Waechter existierten, wurden vom Scoreboard aber NIE
    # ausgefuehrt. Es meldete "ALLE METRIKEN GRÜN", waehrend ein Drittel der
    # Pruefungen gar nicht lief — und genau darauf stuetzt sich jede Aussage
    # dieses Projekts. Beim Nachtragen fiel ein echter Fehler heraus
    # (test_oeffnungen_dedup: Symbol-Cap bei Konfidenz 0,4 loeschte
    # byte-exakte Tueren) und fuenf Waechter waren wegen PEP-604-Annotationen
    # unter Python 3.9 ueberhaupt nicht startbar.
    ("Öffnungs-Dedup (Symbol-Cap)", "test_oeffnungen_dedup.py", "Dedup robust"),
    ("ONLV-Export (A 2063 XSD)", "test_onlv_export.py", "onlv.xsd"),
    ("Maßketten byte-exakt", "test_massketten.py", "byte-exakt"),
    ("Maßketten Rohbau", "test_massketten_rohbau.py", "GESAMT"),
    ("Geometrie-Umfang", "test_geometrie_umfang.py", "grün"),
    ("Geometrie-Präzision", "test_geometrie_precision.py", "korrekt"),
    ("Generalisierung", "test_generalisierung.py", "bestanden"),
    ("Schnitt-/Ansichtslesung", "test_schnitt.py", "korrekt verarbeitet"),
    ("Türbögen (Geometrie)", "test_tuerboegen.py", "ABDECKUNG"),
    ("Vorwand-Abzug", "test_vorwand.py", "Vorwand"),
    ("Fundamentkante", "test_fundamentkante.py", "korrekt geroutet"),
    ("Legende-Verteilung", "test_legende_verteilung.py", "unveraendert"),
    ("Materialklasse (Gewerk aus Aufbau)", "test_materialklasse.py", "korrekt zugeordnet"),
    ("Inventar-Crosscheck", "test_inventar_check.py", "Crosscheck"),
    ("Ensemble/Reconciliation", "test_ensemble.py", "deterministisch"),
    ("Opus-Konsum", "test_opus_konsum.py", "additiv"),
    ("Opus-Korrektur-Loop", "test_opus_nudge.py", "byte-exakt tabu"),
    ("Opus projektweit", "test_opus_projekt.py", "projekt-weit"),
    ("Rückspeisung (Schatten)", "test_rueckspeisung_schatten.py", "HLZ"),
    ("Sektoren synchron (UI/Engine)", "test_sektoren_sync.py", "synchron"),
    ("Vektor gegen Polier-Liste", "test_vektor_angerer.py", "Paletten"),
    ("Echter Green-Count", "test_echter_greencount.py", "Roh-Status"),
]
LANGSAM = [
    ("Umriss-Treue am Plan", "mess_umriss_treue.py", "ABDECKUNG"),
    # Belegt die WIDERLEGUNG der Beweisregel am echten Korpus: sobald der
    # Fehltreffer-Anteil hier faellt, waere sie neu zu bewerten.
    ("Umriss auf Wand (Gegenprobe)", "mess_umriss_auf_wand.py", "GEGENPROBE"),
    ("Geometrie-Umfang Risiko", "mess_geometrie_umfang_risiko.py", "FEHLERQUOTE"),
    ("Tür-Dichtung (Ausgangslinie)", "mess_tuer_dichtung.py", "KORPUS"),
    ("Plan-Korpus BREIT (alle Pläne)", "mess_plankorpus_breit.py", "MIT RÄUMEN"),
    ("Plan-Korpus-Abdeckung", "test_korpus.py", "ABDECKUNG:"),
    ("Raum-Verifikation", "test_raumverifikation.py", "ERGEBNIS:"),
    ("Rohbau-Raumcheck", "test_rohbau_raumcheck.py", "ROHBAU-verifiziert"),
    ("Räumlicher Beweis (IoU)", "exp_rohbau_iou_v3.py", "RÄUMLICH bewiesen"),
    ("Räume richtig markiert", "mess_raum_markierung.py", "KENNZAHL"),
    ("Plan-Typ-Abdeckung", "mess_plantypen.py", "wie erwartet behandelt"),
]


# Skripte, die BEWUSST nicht im Scoreboard laufen — mit Grund, damit die
# Liste nicht zur Ausrede wird.
NICHT_IM_SCOREBOARD = {
    "test_alles.py": "das Scoreboard selbst",
    "mess_raumnamen.py": "Vorher/Nachher-Diff, braucht einen Vergleichsstand",
    "mess_scan_anker.py": "braucht den gitignorierten Scan-Korpus (~80 MB)",
    "mess_scan_raeume.py": "braucht den gitignorierten Scan-Korpus (~80 MB)",
    "mess_scan_verschiebung.py": "braucht den gitignorierten Scan-Korpus (~80 MB)",
    "test_multiple_plans.py": "meldet Befunde, bricht aber nicht ab — "
                              "als Waechter untauglich, bis er zusichert",
}


def selbstpruefung():
    """Läuft JEDER Wächter, den es gibt — oder nur die, an die wir uns erinnern?

    Am 30.07.2026 lagen 22 Wächter im Ordner, die das Scoreboard nie aufrief.
    Es meldete trotzdem "ALLE METRIKEN GRÜN". Beim Nachtragen fiel sofort ein
    echter Fehler heraus (Symbol-Cap löschte byte-exakte Türen), und fünf
    Wächter waren wegen PEP-604-Annotationen unter Python 3.9 überhaupt nicht
    startbar. Ein Wächter, der nicht läuft, ist schlimmer als keiner: er
    erzeugt Sicherheit, die es nicht gibt.
    """
    hier = os.path.dirname(os.path.abspath(__file__))
    quelle = open(os.path.abspath(__file__), encoding="utf-8").read()
    verwaist = []
    for b in sorted(os.listdir(hier)):
        if not (b.startswith("test_") or b.startswith("mess_")):
            continue
        if not b.endswith(".py") or b in NICHT_IM_SCOREBOARD:
            continue
        if f'"{b}"' not in quelle:
            verwaist.append(b)
    return verwaist


def lauf(skript):
    r = subprocess.run([PY, os.path.join(ROOT, "scripts", skript)],
                       capture_output=True, text=True, timeout=1500)
    return r.returncode == 0, r.stdout


def run():
    schnell = "--schnell" in sys.argv
    print("=" * 72)
    print("SCOREBOARD — Kern-Metriken (Messwert statt Behauptung)")
    print("=" * 72)
    alle_ok = True
    verwaist = selbstpruefung()
    if verwaist:
        print(f"  ✗ {len(verwaist)} Wächter liegen im Ordner, laufen hier aber "
              f"NICHT: {verwaist}")
        print("     (eintragen oder mit Grund in NICHT_IM_SCOREBOARD stellen)")
        alle_ok = False
    else:
        print(f"  ✓ Selbstprüfung: jeder Wächter im Ordner läuft "
              f"({len(GUARDS)} schnell + {len(LANGSAM)} langsam, "
              f"{len(NICHT_IM_SCOREBOARD)} begründete Ausnahmen)")
    for name, skript, was in GUARDS:
        try:
            ok, _ = lauf(skript)
        except Exception:
            ok = False
        alle_ok &= ok
        print(f"  {'✓' if ok else '✗'} {name:<28} {was}")
    if not schnell:
        print("-" * 72)
        for name, skript, marker in LANGSAM:
            try:
                ok, out = lauf(skript)
                zeile = next((l for l in out.splitlines() if marker in l), "?")
            except Exception:
                ok, zeile = False, "CRASH"
            alle_ok &= ok
            print(f"  {'✓' if ok else '✗'} {name:<28} {zeile.strip()[:70]}")
    print("=" * 72)
    print("ALLE METRIKEN GRÜN — keine Regression." if alle_ok
          else "MINDESTENS EINE METRIK ROT — NICHT mergen/pushen.")
    return 0 if alle_ok else 1


if __name__ == "__main__":
    sys.exit(run())
