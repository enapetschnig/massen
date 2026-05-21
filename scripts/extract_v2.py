#!/usr/bin/env python3
"""Extract v2 — verbesserte Plan-Auswertung mit Text-Layer.

Verbesserungen gegenüber v1:
- Raumnamen nur mit Schriftgröße >= 9 (echte Labels statt Annotations)
- Strikteres nearest-neighbor für Name→U:-Zuordnung
- Loggia/Stiegenhaus separat klassifiziert (für getrennte Putz-Berechnung)
- Exakte Fenster-Abzüge aus AL-Werten (statt 2.5 m² Pauschale)
- Verschiedene Innenputz-Szenarien zum Cross-Check

Lokal nutzbar: python3 scripts/extract_v2.py <plan.pdf>
"""
import fitz, re, json, sys
from collections import defaultdict, Counter
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────
# Raumname-Kategorisierung
# ──────────────────────────────────────────────────────────────────────────
RAUM_TYPEN = {
    'Innenraum_warm': ['Wohnküche', 'Wohnen', 'Zimmer', 'Schlafzimmer', 'Kinderzimmer',
                       'Küche', 'Esszimmer', 'Vorraum', 'Diele', 'Flur', 'Garderobe',
                       'Bad', 'WC', 'Abstellraum', 'Speis'],
    'Loggia':         ['Loggia'],
    'Stiegenhaus':    ['Stiegenhaus', 'STGH', 'Stiege'],
    'Nebenraum_kalt': ['Tiefgarage', 'Keller', 'Lift'],
    'Sonderraum':     ['KiGa', 'Gruppen', 'Speisesaal', 'Sanitär', 'Putzraum', 'Eingang'],
}
NAME_TO_KAT = {n: k for k, ns in RAUM_TYPEN.items() for n in ns}
ALL_NAMES = list(NAME_TO_KAT.keys())

MIN_RAUMNAME_SIZE = 9.0  # echte Raumlabels haben size>=10, Annotations <8

# ──────────────────────────────────────────────────────────────────────────
# Pipeline
# ──────────────────────────────────────────────────────────────────────────
def extract_spans(page):
    spans = []
    td = page.get_text("dict")
    for block in td.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                t = (span.get("text") or "").strip()
                if t:
                    bb = span.get("bbox")
                    spans.append({
                        'text': t, 'bbox': bb,
                        'size': round(span.get("size", 0), 1),
                        'cx': (bb[0]+bb[2])/2, 'cy': (bb[1]+bb[3])/2,
                    })
    return spans


def find_anchors(spans, pattern, group=1):
    """Findet Spans die Pattern matchen, extrahiert numerischen Wert."""
    out = []
    for s in spans:
        m = re.search(pattern, s['text'])
        if m:
            try:
                v = float(m.group(group).replace(',', '.'))
                out.append({**s, 'value': v})
            except (ValueError, IndexError):
                pass
    return out


def find_nearest(target, candidates, max_d=80, max_dy=30):
    """Findet nearest candidate, mit harten Limits."""
    best, best_d = None, max_d + 1
    for c in candidates:
        dx, dy = abs(c['cx']-target['cx']), abs(c['cy']-target['cy'])
        if dy > max_dy:
            continue
        d = dx + dy
        if d < best_d:
            best_d = d
            best = c
    return best, best_d


def find_room_name(u_anchor, spans, max_radius=200, prefer_above=True):
    """Sucht den nächsten gültigen Raumname-Span um den U:-Anker."""
    candidates = []
    for s in spans:
        if s['size'] < MIN_RAUMNAME_SIZE:
            continue
        for name in ALL_NAMES:
            if s['text'] == name or s['text'].startswith(name + ' '):
                dx = abs(s['cx']-u_anchor['cx'])
                dy = u_anchor['cy'] - s['cy']  # positiv = Name liegt über Anker
                if abs(dx) > max_radius or abs(dy) > max_radius:
                    continue
                score = abs(dx) + abs(dy)
                if prefer_above and dy > 0:
                    score *= 0.7  # Bonus für Name oberhalb des U:
                candidates.append((score, name, s))
                break
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0])
    return candidates[0][1]


def cluster_rooms(spans):
    """Findet alle Räume anhand U:-Anker + nearest H: + nearest Raumname."""
    u_anchors = find_anchors(spans, r'U\s*[:=]?\s*(\d+[,.]\d+)\s*m\b')
    h_anchors = find_anchors(spans, r'H\s*[:=]?\s*(\d+[,.]\d+)\s*m\b')

    rooms = []
    for u in u_anchors:
        h, _ = find_nearest(u, h_anchors, max_d=50, max_dy=20)
        name = find_room_name(u, spans)
        kat = NAME_TO_KAT.get(name) if name else None
        rooms.append({
            'cx': u['cx'], 'cy': u['cy'],
            'umfang': u['value'],
            'hoehe': h['value'] if h else None,
            'name': name, 'kategorie': kat,
        })
    return rooms


def find_windows(spans):
    """Sammelt Fenster: FE_-Marker + zugehörige AL-Werte (Breite/Höhe)."""
    fe_markers = [s for s in spans if re.match(r'^FE[_]?\d+', s['text'])]
    al_spans = []
    for s in spans:
        m = re.match(r'^AL(\d{2,3})', s['text'])
        if m:
            al_spans.append({**s, 'al_cm': int(m.group(1))})

    # Pro Fenster: nächste 2 AL-Werte → erste = Breite, zweite = Höhe
    windows = []
    used_al = set()
    for fe in fe_markers:
        nearby = []
        for al in al_spans:
            if id(al) in used_al:
                continue
            dx = abs(al['cx']-fe['cx'])
            dy = abs(al['cy']-fe['cy'])
            if dx > 100 or dy > 80:
                continue
            nearby.append((dx+dy, al))
        nearby.sort(key=lambda x: x[0])
        my_al = nearby[:2]
        for _, al in my_al:
            used_al.add(id(al))
        if len(my_al) == 2:
            vals = sorted([al['al_cm'] for _, al in my_al])
            breite_cm, hoehe_cm = vals[0], vals[1]
        elif len(my_al) == 1:
            breite_cm = my_al[0][1]['al_cm']
            hoehe_cm = 200  # heuristisch
        else:
            breite_cm, hoehe_cm = 120, 200
        windows.append({
            'cx': fe['cx'], 'cy': fe['cy'],
            'code': fe['text'],
            'breite_m': breite_cm / 100.0,
            'hoehe_m': hoehe_cm / 100.0,
            'flaeche_m2': (breite_cm * hoehe_cm) / 10000.0,
        })
    return windows


def assign_haus(cx, bereiche):
    for h, (x0, x1) in bereiche.items():
        if x0 <= cx < x1:
            return h
    return None


def main(pdf_path):
    doc = fitz.open(pdf_path)
    page = doc[0]
    pw, ph = page.rect.width, page.rect.height

    print(f"\n{'='*72}\n  {Path(pdf_path).name}\n{'='*72}")
    print(f"Plan-Größe: {pw:.0f} × {ph:.0f} pt")

    spans = extract_spans(page)
    print(f"Text-Spans: {len(spans)}")

    rooms = cluster_rooms(spans)
    windows = find_windows(spans)

    print(f"\nGefunden: {len(rooms)} Räume, {len(windows)} Fenster")

    # Haus-Bereiche (für diesen Plan manuell, später aus Schnittmarker)
    HAUS_BEREICHE = {'C': (0, 1800), 'D': (1800, 3700), 'E': (3700, 5500)}
    for r in rooms:
        r['haus'] = assign_haus(r['cx'], HAUS_BEREICHE)
    for w in windows:
        w['haus'] = assign_haus(w['cx'], HAUS_BEREICHE)

    # Aggregation pro Haus × Kategorie
    print(f"\n{'─'*72}\nRäume pro Haus × Kategorie:\n{'─'*72}")
    print(f"{'Haus':>5} | {'Kategorie':18} | {'#':>3} | {'ΣU [m]':>8} | {'ΣU×H [m²]':>10} | Namen")
    print('─'*100)
    per_kat = defaultdict(lambda: defaultdict(lambda: {'n':0,'u':0.0,'uh':0.0,'names':Counter()}))
    for r in rooms:
        if r['haus'] is None or r['kategorie'] is None:
            continue
        d = per_kat[r['haus']][r['kategorie']]
        d['n'] += 1
        if r['umfang']:
            d['u'] += r['umfang']
        if r['umfang'] and r['hoehe']:
            d['uh'] += r['umfang'] * r['hoehe']
        if r['name']:
            d['names'][r['name']] += 1
    for h in sorted(per_kat.keys()):
        for kat in ['Innenraum_warm','Loggia','Stiegenhaus','Nebenraum_kalt','Sonderraum']:
            d = per_kat[h].get(kat)
            if not d or d['n'] == 0:
                continue
            print(f"{h:>5} | {kat:18} | {d['n']:>3} | {d['u']:>8.2f} | {d['uh']:>10.2f} | {dict(d['names'])}")

    # Fenster pro Haus mit ECHTEN Flächen
    print(f"\n{'─'*72}\nFenster pro Haus (mit echten Flächen aus AL-Werten):\n{'─'*72}")
    per_haus_fe = defaultdict(lambda: {'n':0,'sum_flaeche':0.0,'sum_breite':0.0,'flaechen':[]})
    for w in windows:
        if w['haus'] is None: continue
        d = per_haus_fe[w['haus']]
        d['n'] += 1
        d['sum_flaeche'] += w['flaeche_m2']
        d['sum_breite'] += w['breite_m']
        d['flaechen'].append(w['flaeche_m2'])
    for h in sorted(per_haus_fe.keys()):
        d = per_haus_fe[h]
        print(f"  Haus {h}: {d['n']} Fenster, Σ Fläche={d['sum_flaeche']:.2f} m², "
              f"Σ Breite={d['sum_breite']:.2f} m, Avg {d['sum_flaeche']/max(d['n'],1):.2f} m²")

    # ─────────────────────────────────────────────────────────────────
    # Innenputz-Berechnung: mehrere Szenarien
    # ─────────────────────────────────────────────────────────────────
    print(f"\n{'='*72}\nINNENPUTZ-SZENARIEN (Wandfläche EG)\n{'='*72}")

    EXCEL_SOLL = {
        'C': 388.89,  # alle Geschosse? unklar
        'D': 503.31,  # EG eindeutig
    }
    EXCEL_QUELLE = {
        'C': '"Innenputz Wände" ohne Geschoss-Marker',
        'D': '"Innenputz Wände" Erdgeschoss',
    }

    for h in ['C', 'D']:
        if h not in per_kat:
            continue
        innen = per_kat[h].get('Innenraum_warm', {'n':0,'uh':0.0,'u':0.0})
        loggia = per_kat[h].get('Loggia', {'n':0,'uh':0.0,'u':0.0})
        sth = per_kat[h].get('Stiegenhaus', {'n':0,'uh':0.0,'u':0.0})
        fe = per_haus_fe.get(h, {'n':0,'sum_flaeche':0.0})

        n_raeume = innen['n']
        # Türen: heuristisch 1.5 pro Innenraum (1 Eingangstür + manchmal Verbindungstür)
        n_tueren = round(n_raeume * 1.5)
        tuer_flaeche = n_tueren * 2.1 * 0.9  # 2.10×0.90 m je Tür

        excel = EXCEL_SOLL[h]

        print(f"\n══ Haus {h} ══ Excel-Soll EG: {excel:.2f} m²  ({EXCEL_QUELLE[h]})")
        print(f"{'Szenario':70} {'Wert [m²]':>10} {'Δ':>10} {'Δ%':>7}")
        print('─'*100)

        szenarien = [
            ('S1: alle Räume Σ U×H (roh)',
             innen['uh'] + loggia['uh'] + sth['uh']),
            ('S2: Innenräume + Loggia + STH − Fenster (echt) − Türen (heuristisch)',
             innen['uh'] + loggia['uh'] + sth['uh'] - fe['sum_flaeche'] - tuer_flaeche),
            ('S3: Innenräume + STH − Fenster − Türen (Loggien als außen ausgeschlossen)',
             innen['uh'] + sth['uh'] - fe['sum_flaeche'] - tuer_flaeche),
            ('S4: Nur Innenräume − Fenster − Türen (STH als Sondergewerk)',
             innen['uh'] - fe['sum_flaeche'] - tuer_flaeche),
            ('S5: Innenräume + STH (mit Fenstern, ohne Türen — falls Excel Türen nicht abzieht)',
             innen['uh'] + sth['uh'] - fe['sum_flaeche']),
            ('S6: Innenräume + 1/4 Loggien (nur Wohnungs-Seite) + STH − Fenster − Türen',
             innen['uh'] + loggia['uh']*0.25 + sth['uh'] - fe['sum_flaeche'] - tuer_flaeche),
        ]
        for name, wert in szenarien:
            d = wert - excel
            pct = d/excel*100
            flag = '  ✓' if abs(pct) < 3 else ('  ~' if abs(pct) < 8 else '')
            print(f"  {name:68} {wert:>10.2f} {d:>+10.2f} {pct:>+6.1f}%{flag}")

    # Speichere Ergebnisse
    result = {
        'plan': str(Path(pdf_path).name),
        'plan_size_pt': [pw, ph],
        'haus_bereiche': HAUS_BEREICHE,
        'rooms': rooms,
        'windows': windows,
        'aggregat': {h: {kat: {'n':d['n'],'u':d['u'],'uh':d['uh'],'names':dict(d['names'])}
                          for kat, d in v.items()}
                     for h, v in per_kat.items()},
        'windows_per_haus': {h: {'n':d['n'],'sum_flaeche':d['sum_flaeche'],'sum_breite':d['sum_breite']}
                              for h,d in per_haus_fe.items()},
    }
    out = Path('/tmp/extract_v2_result.json')
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    print(f"\nGespeichert: {out}")
    doc.close()


if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else '/Users/christophnapetschnig/Downloads/AU_WM_01 Erdgeschoss_INDEX E (3).pdf'
    main(path)
