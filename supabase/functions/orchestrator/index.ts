import { serve } from "https://deno.land/std@0.168.0/http/server.ts"
import { createClient } from "https://esm.sh/@supabase/supabase-js@2"

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
}

const MODEL = "claude-sonnet-4-20250514"

function parseJson(raw: string): any {
  try { return JSON.parse(raw) } catch {}
  const m = raw.match(/```(?:json)?\s*([\s\S]*?)```/)
  if (m) try { return JSON.parse(m[1]) } catch {}
  const m2 = raw.match(/\{[\s\S]*\}/)
  if (m2) try { return JSON.parse(m2[0]) } catch {}
  throw new Error("JSON parse failed")
}

async function callClaude(apiKey: string, system: string, content: any[], maxTok = 16384): Promise<any> {
  const r = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-api-key": apiKey, "anthropic-version": "2023-06-01" },
    body: JSON.stringify({ model: MODEL, max_tokens: maxTok, system, messages: [{ role: "user", content }] }),
  })
  if (!r.ok) throw new Error("Claude " + r.status)
  const j = await r.json()
  return parseJson(j.content?.[0]?.text || "{}")
}

/*
 * Step-based orchestrator with DUAL VISION SCAN.
 *   step=1 → Deep Vision Scan (Pass A overview + Pass B verification) + geometry fixes
 *   step=2 → Kalkulation (ÖNORM mass calculation)
 *   step=3 → Kritik (quality check + finalize)
 */
serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders })

  try {
    const { plan_id, step = 1, gewerk = "allgemein" } = await req.json()
    if (!plan_id) throw new Error("plan_id fehlt")

    const sb = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!)
    const { data: cfg } = await sb.from("app_config").select("value").eq("key", "ANTHROPIC_API_KEY").single()
    if (!cfg?.value) throw new Error("API Key fehlt")

    const { data: plan } = await sb.from("plaene").select("*").eq("id", plan_id).single()
    if (!plan) throw new Error("Plan nicht gefunden")

    // ========== STEP 1: Deep Vision Scan (dual pass) ==========
    if (step === 1) {
      // Clean old results
      await sb.from("massen").delete().eq("plan_id", plan_id)
      await sb.from("elemente").delete().eq("plan_id", plan_id)
      await sb.from("plaene").update({ verarbeitet: false, agent_log: { start: new Date().toISOString() } }).eq("id", plan_id)

      const { data: u } = await sb.storage.from("plaene").createSignedUrl(plan.storage_path, 3600)
      if (!u?.signedUrl) throw new Error("PDF URL fehlt")
      const pdfSource = { type: "document", source: { type: "url", url: u.signedUrl } }

      // ---- PASS A: Overview scan ----
      const passA = await callClaude(cfg.value,
        `Du bist ein Senior-Bauingenieur mit 30 Jahren Erfahrung in der Analyse österreichischer Baupläne. Du analysierst diesen Plan wie ein Profi.

SYSTEMATISCHE ANALYSE:
1. PLANKOPF: Finde Maßstab, Geschoss, Planungsbüro, Plannummer, Index
2. RAUMAUFTEILUNG: Zähle JEDEN Raum. Gehe den Plan systematisch durch - Zeile für Zeile, von oben nach unten, von links nach rechts. Vergiss KEINEN Raum.
3. Typische Räume in Wohnbauten: Vorraum, Flur, Gang, Wohnzimmer, Wohnküche, Küche, Essbereich, Schlafzimmer, Kinderzimmer, Gästezimmer, Arbeitszimmer, Bad, WC, Dusche/WC, Abstellraum, Garderobe, Schrankraum, Loggia, Balkon, Terrasse, Keller, Technikraum, Waschküche, Speis
4. Lies für JEDEN Raum: Name, Fläche m², Umfang m, Höhe m, Bodenbelag
5. FENSTER: Suche ALLE Fensterbezeichnungen (FE_, F_ etc.) - auch rotiert an Wänden
6. TÜREN: Suche ALLE Türsymbole (Viertelkreis) und T-Bezeichnungen
7. WANDSTÄRKEN: Messe/lies die verschiedenen Wandstärken
8. POSITION: Gib für JEDES Element die ungefähre Position als [x%, y%, w%, h%] an

QUALITÄTSKONTROLLE - Prüfe dich selbst:
- Summe aller Raumflächen sollte die Gesamtfläche des Geschosses ergeben
- Jeder Raum sollte mindestens 1 Tür haben
- Fenster sollten an Außenwänden sein
- Umfang sollte zur Fläche passen (U ≈ 4 × √Fläche für quadratischen Raum)

Antworte NUR mit validem JSON, KEIN Markdown.`,
        [
          pdfSource,
          { type: "text", text: `Analysiere diesen Bauplan VOLLSTÄNDIG.

JSON-Format:
{
  "massstab": "1:100",
  "geschoss": "EG",
  "raumhoehe_global_m": 2.60,
  "wandstaerken_mm": [300, 200, 120],
  "plankopf": { "planungsbuero": "", "plannummer": "", "index": "" },
  "raeume": [
    {
      "name": "Wohnküche",
      "bodenbelag": "Parkett",
      "flaeche_m2": 26.37,
      "umfang_m": 20.66,
      "hoehe_m": 2.42,
      "wandflaeche_m2": 50.0,
      "position_pct": [10, 20, 35, 40],
      "konfidenz": 0.95
    }
  ],
  "fenster": [
    {
      "bezeichnung": "FE_31",
      "raum": "Wohnküche",
      "rph_mm": 1010,
      "fph_mm": 480,
      "al_breite_mm": 1510,
      "al_hoehe_mm": 1510,
      "rb_breite_mm": 1760,
      "rb_hoehe_mm": 1760,
      "flaeche_m2": 2.28,
      "position_pct": [5, 35, 5, 10],
      "konfidenz": 0.90
    }
  ],
  "tueren": [
    {
      "bezeichnung": "T1",
      "raum": "Wohnküche",
      "breite_mm": 900,
      "hoehe_mm": 2100,
      "typ": "Drehflügel",
      "position_pct": [30, 45, 3, 5],
      "konfidenz": 0.85
    }
  ],
  "gesamt_konfidenz": 0.90
}` },
        ])

      // Update log after Pass A
      await sb.from("plaene").update({
        agent_log: { start: new Date().toISOString(), passA: { ts: new Date().toISOString(), r: (passA.raeume||[]).length, f: (passA.fenster||[]).length, t: (passA.tueren||[]).length } }
      }).eq("id", plan_id)

      // ---- PASS B: Verification scan ----
      const raumListe = (passA.raeume || []).map((r: any) => `${r.name}: ${r.flaeche_m2}m², U=${r.umfang_m}m, H=${r.hoehe_m}m, ${r.bodenbelag || "?"}`).join("\n")
      const fensterListe = (passA.fenster || []).map((f: any) => `${f.bezeichnung} → ${f.raum}, AL=${f.al_breite_mm}x${f.al_hoehe_mm}mm`).join("\n")
      const tuerenListe = (passA.tueren || []).map((t: any) => `${t.bezeichnung} → ${t.raum}, ${t.breite_mm}mm`).join("\n")

      const passB = await callClaude(cfg.value,
        `Du bist ein unabhängiger Prüfingenieur. Du überprüfst die Arbeit eines Kollegen.

Hier ist der Plan NOCHMALS. Die erste Analyse hat diese Ergebnisse geliefert:

RÄUME (${(passA.raeume||[]).length} gefunden):
${raumListe}

FENSTER (${(passA.fenster||[]).length} gefunden):
${fensterListe}

TÜREN (${(passA.tueren||[]).length} gefunden):
${tuerenListe}

Prüfe GENAU:
1. Wurden Räume ÜBERSEHEN? Kleine Räume wie WC, Abstellraum, Garderobe werden oft vergessen.
2. Sind die Flächen KORREKT abgelesen? Vergleiche mit dem Plan.
3. Fehlen FENSTER? Schau besonders an den Außenwänden.
4. Fehlen TÜREN? Jeder Raum braucht mindestens eine Tür.
5. Sind die Positionen korrekt?

Gib NUR die KORREKTUREN und ERGÄNZUNGEN zurück als JSON. Wenn alles stimmt, gib leere Arrays zurück.

Antworte NUR mit validem JSON, KEIN Markdown.`,
        [
          pdfSource,
          { type: "text", text: `Überprüfe die Analyse und gib Korrekturen zurück.

JSON-Format:
{
  "neue_raeume": [
    { "name": "", "bodenbelag": "", "flaeche_m2": 0, "umfang_m": 0, "hoehe_m": 0, "position_pct": [0,0,0,0], "konfidenz": 0.85 }
  ],
  "korrigierte_raeume": [
    { "name": "ExistierenderRaum", "korrekturen": { "flaeche_m2": 12.5, "umfang_m": 14.2 } }
  ],
  "neue_fenster": [
    { "bezeichnung": "", "raum": "", "rph_mm": 0, "fph_mm": 0, "al_breite_mm": 0, "al_hoehe_mm": 0, "rb_breite_mm": 0, "rb_hoehe_mm": 0, "position_pct": [0,0,0,0], "konfidenz": 0.85 }
  ],
  "neue_tueren": [
    { "bezeichnung": "", "raum": "", "breite_mm": 0, "hoehe_mm": 0, "typ": "", "position_pct": [0,0,0,0], "konfidenz": 0.85 }
  ],
  "entfernte_elemente": [],
  "anmerkungen": ""
}` },
        ])

      // ---- MERGE Pass B corrections into Pass A ----
      const merged = { ...passA }

      // Apply room corrections
      for (const korr of (passB.korrigierte_raeume || [])) {
        const existing = (merged.raeume || []).find((r: any) => r.name === korr.name)
        if (existing && korr.korrekturen) Object.assign(existing, korr.korrekturen)
      }

      // Add newly discovered rooms
      for (const neu of (passB.neue_raeume || [])) {
        if (neu.name) (merged.raeume = merged.raeume || []).push(neu)
      }

      // Add newly discovered windows
      for (const neu of (passB.neue_fenster || [])) {
        if (neu.bezeichnung) (merged.fenster = merged.fenster || []).push(neu)
      }

      // Add newly discovered doors
      for (const neu of (passB.neue_tueren || [])) {
        if (neu.bezeichnung) (merged.tueren = merged.tueren || []).push(neu)
      }

      // Remove elements flagged for removal
      for (const name of (passB.entfernte_elemente || [])) {
        merged.raeume = (merged.raeume || []).filter((r: any) => r.name !== name)
        merged.fenster = (merged.fenster || []).filter((f: any) => f.bezeichnung !== name)
        merged.tueren = (merged.tueren || []).filter((t: any) => t.bezeichnung !== name)
      }

      // ---- Geometry fixes ----
      for (const r of (merged.raeume || [])) {
        if (!r.wandflaeche_m2 && r.umfang_m && r.hoehe_m) {
          r.wandflaeche_m2 = Math.round(r.umfang_m * r.hoehe_m * 100) / 100
        }
        if (!r.flaeche_m2 && r.umfang_m) r.flaeche_m2 = 0
      }
      for (const f of (merged.fenster || [])) {
        if (!f.flaeche_m2 && f.al_breite_mm && f.al_hoehe_mm) {
          f.flaeche_m2 = Math.round(f.al_breite_mm * f.al_hoehe_mm / 10000) / 100
        }
      }

      // ---- Store elements in DB ----
      for (const r of (merged.raeume || []))
        await sb.from("elemente").insert({ plan_id, typ: "raum", bezeichnung: r.name || "", daten: r, konfidenz: Math.round((r.konfidenz || 0.5) * 100) })
      for (const f of (merged.fenster || []))
        await sb.from("elemente").insert({ plan_id, typ: "fenster", bezeichnung: f.bezeichnung || "", daten: f, konfidenz: Math.round((f.konfidenz || 0.5) * 100) })
      for (const t of (merged.tueren || []))
        await sb.from("elemente").insert({ plan_id, typ: "tuer", bezeichnung: t.bezeichnung || "", daten: t, konfidenz: Math.round((t.konfidenz || 0.5) * 100) })

      // ---- Update agent_log ----
      const log = {
        start: new Date().toISOString(),
        step1: {
          ts: new Date().toISOString(),
          r: (merged.raeume||[]).length,
          f: (merged.fenster||[]).length,
          t: (merged.tueren||[]).length,
          passA_counts: { r: (passA.raeume||[]).length, f: (passA.fenster||[]).length, t: (passA.tueren||[]).length },
          passB_additions: { r: (passB.neue_raeume||[]).length, f: (passB.neue_fenster||[]).length, t: (passB.neue_tueren||[]).length, korrekturen: (passB.korrigierte_raeume||[]).length },
          anmerkungen: passB.anmerkungen || "",
        },
        geo: merged,
        gewerk: gewerk,
      }
      await sb.from("plaene").update({ agent_log: log }).eq("id", plan_id)

      return new Response(JSON.stringify({
        status: "step1_done",
        next_step: 2,
        raeume: (merged.raeume||[]).length,
        fenster: (merged.fenster||[]).length,
        tueren: (merged.tueren||[]).length,
        passB_korrekturen: (passB.korrigierte_raeume||[]).length,
        passB_neue: (passB.neue_raeume||[]).length + (passB.neue_fenster||[]).length + (passB.neue_tueren||[]).length,
      }), { headers: { ...corsHeaders, "Content-Type": "application/json" } })
    }

    // ========== STEP 2: Kalkulation ==========
    if (step === 2) {
      const geo = plan.agent_log?.geo
      const selectedGewerk = plan.agent_log?.gewerk || gewerk || "allgemein"
      if (!geo) throw new Error("Step 1 zuerst ausführen")

      // Build gewerk-specific prompt additions
      const gewerkPrompts: Record<string, string> = {
        verputzer: `
FOKUS: VERPUTZER / SPACHTELARBEITEN (VP/SR)
Berechne NUR Verputzerleistungen - genau wie ein Verputzerbetrieb kalkuliert.

AUSSENPOSITIONEN (pro Gebäudeansicht - Nordwest, Nordost, Südost, Südwest):
- Leichtputz mineralisch: Ansichtsfläche = Gebäudelänge × Gebäudehöhe, dann Abzüge für Öffnungen (Loggien, Eingänge)
- Gewebespachtelung: gleiche Berechnung, andere Abzüge
- Dünnputz kunstharz Rillenstruktur 3mm (Fläche >4m²)
- Dünnputz kunstharz Reibstruktur 1,5mm (Fläche >4m² und <4m²)
- Sockelputzprofil (Laufmeter Gebäudeumfang + Loggien-Leibungen)
- Glattstrich Sockelbereich (Sockellänge × 0.60m Höhe)
- Drahtrichtwinkel (4 Ecken × Gebäudehöhe)
- Fensterbankaufnahme mit Dichtebene (Anzahl Fenster × Fensterbreite)
- Rillengleitendstücke für Fensterbankkeil (2 Stk pro Fenster)
- Schacht für Jalousieneinbau (wie Fensterbankaufnahme)
- Fensterlaibungen gedämmt (Anzahl × Höhe der Fensterleibungen, Laufmeter)
- Sturzausbildung Loggien (Anzahl × Breite)
- Kantenschutz-Gewebewinkel (alle Kanten/Ecken in Laufmetern)
- Anputzleiste (Laufmeter an allen Fenstern und Türen)

INNENPOSITIONEN:
- Haftgrund (Wandfläche aller Räume)
- Innenputz Wände (Wandfläche aller Räume - Abzüge nach Putzregel)
- Kantenprofil (alle inneren Kanten in Laufmetern)
- Anputzleiste (Laufmeter an Fenstern und Türen innen)

BERECHNUNGSFORMAT: Jeder Schritt zeigt Ansicht/Raum + Anzahl × Länge × Breite × Höhe = Zwischensumme.
Negative Werte bei Abzügen (minus bei Höhe oder Breite).`,

        mauerwerk: `
FOKUS: MAUERWERK / ROHBAU
- Außenwände: Ansichtsflächen × Wandstärke = Volumen m³
- Innenwände: Wandlänge × Wandhöhe × Wandstärke = Volumen m³
- Abzüge: Öffnungen <0.5m² kein, 0.5-3m² halb, >3m² voll
- Leibungen separat`,

        maler: `
FOKUS: MALER / ANSTRICH
- Wandflächen pro Raum (Umfang × Höhe - Öffnungsabzüge)
- Deckenflächen pro Raum
- Leibungsflächen (seitlich, Sturz, Brüstung)
- Grundierung als eigene Position`,

        fliesen: `
FOKUS: FLIESEN / BELÄGE
- Bodenfliesen pro Raum (nur Räume mit Fliesen)
- Wandfliesen pro Raum (Bad, WC, Küche - typisch bis 2.10m Höhe)
- Sockelleisten
- Abzüge: <0.1m² kein, ≥0.1m² voll`,

        estrich: `
FOKUS: ESTRICH
- Zementestrich pro Raum
- Randdämmstreifen (Laufmeter Umfang)
- Trittschalldämmung (gleiche Fläche)
- Feuchtigkeitssperre (Nassräume)`,

        trockenbau: `
FOKUS: TROCKENBAU
- Gipskartonwände (Fläche, Laufmeter)
- Vorsatzschalen
- Abhangdecken
- Spachtelung und Verfugung`,

        allgemein: `
ALLE GEWERKE berechnen:
01. Mauerwerk/Rohbau (m², m³)
02. Innenputz (m², lfm)
03. Außenputz (m², lfm)
04. Malerarbeiten (m²)
05. Bodenbelag nach Typ (m²)
06. Estrich (m²)
07. Fensterbänke (lfm)
08. Leibungen (m², lfm)`,
      }

      const gewerkPrompt = gewerkPrompts[selectedGewerk] || gewerkPrompts.allgemein

      const kalk = await callClaude(cfg.value,
        `Du bist ein erfahrener österreichischer Baukalkulator. Du erstellst eine PROFESSIONELLE Massenermittlung EXAKT wie sie auf echten Baustellen verwendet wird.

WICHTIG: Eine echte Massenermittlung hat VIELE detaillierte Positionen. Nicht nur 10 - sondern 30-60+!

GEWÄHLTES GEWERK: ${selectedGewerk.toUpperCase()}
${gewerkPrompt}

POSITIONSSTRUKTUR (wie in der Praxis):
Für JEDES relevante Gewerk erstellst du Positionen mit DETAILLIERTEN Berechnungsschritten.
Jeder Berechnungsschritt zeigt: Beschreibung | Anzahl × Länge × Breite × Höhe = Zwischensumme

ÖNORM-ABZUGSREGELN:

01. MAUERWERK / ROHBAU
- Pro Raum: Wandfläche = Umfang × Höhe
- Abzüge: Öffnungen <0.5m² KEIN Abzug, 0.5-3m² HALBER Abzug, >3m² VOLLER Abzug
- Leibungen EXTRA ausweisen

02. INNENPUTZ
- Haftgrund (gleiche Fläche wie Putz)
- Innenputz Wände (Wandfläche - Abzüge nach Putzregel: <2.5m² kein, 2.5-10m² halb, >10m² voll)
- Kantenprofile (Laufmeter aller Kanten)
- Anputzleisten (Laufmeter an Fenster/Türen)

03. AUSSENPUTZ (falls Außenwände vorhanden)
- Leichtputz mineralisch (Ansicht Nord/Ost/Süd/West jeweils)
- Gewebespachtelung
- Dünnputz (Rillenstruktur/Reibstruktur nach Fläche)
- Sockelbereich
- Fensterlaibungen (Laufmeter)
- Sturzausbildung
- Fensterbankaufnahme

04. MALERARBEITEN
- Wandflächen (gleiche Abzüge wie Putz)
- Deckenflächen = Raumfläche
- Leibungsflächen extra

05. BODENBELAG
- Pro Bodenbelagstyp (Parkett, Fliesen, etc.)
- Nettofläche jedes Raums

06. ESTRICH
- Alle Raumflächen zusammen

07. FENSTERBÄNKE
- Pro Fenster: Laufmeter = RB-Breite in Metern
- Fensterbank innen: Tiefe = Wandstärke

BERECHNUNGSFORMAT pro Position:
Jede Position hat "berechnung" als Array von Strings, jeder String = ein Rechenschritt:
"Wohnküche Wandfläche: 1 × 20.66 × 1.0 × 2.42 = 50.00"
"Abzug FE_31: 1 × 1.30 × 1.0 × -2.88 = -3.74"
"Leibung FE_31 seitlich: 2 × 0.30 × 1.0 × 2.88 = 1.73"

Antworte NUR mit validem JSON, KEIN Markdown.`,
        [{ type: "text", text: `Geometriedaten:\n${JSON.stringify(geo)}\n\nErstelle eine DETAILLIERTE professionelle Massenermittlung. Mindestens 25 Positionen!

JSON-Format:
{
  "positionen": [
    {
      "pos_nr": "02.01",
      "beschreibung": "Innenputz Wände",
      "gewerk": "Innenputz",
      "raum_referenz": "Alle Räume",
      "berechnung": [
        "Wohnküche: 1 × 20.66 × 1.0 × 2.42 = 50.00",
        "Abzug FE_31 (2.28m², kein Abzug <2.5m²): 0",
        "Schlafzimmer: 1 × 17.10 × 1.0 × 2.42 = 41.38",
        "Bad: 1 × 12.30 × 1.0 × 2.42 = 29.77",
        "..."
      ],
      "endsumme": 388.89,
      "einheit": "m²",
      "konfidenz": 0.90
    }
  ],
  "zusammenfassung": {
    "innenputz_wande_m2": 388.89,
    "kantenprofile_lfm": 210.28,
    "anputzleisten_lfm": 185.68,
    "bodenbelag_parkett_m2": 0,
    "bodenbelag_fliesen_m2": 0,
    "estrich_m2": 0,
    "malerarbeiten_wande_m2": 0,
    "malerarbeiten_decken_m2": 0,
    "fensterbaenke_lfm": 0
  },
  "gesamt_konfidenz": 0.90
}` }],
        32000)

      for (const p of (kalk.positionen || []))
        await sb.from("massen").insert({
          plan_id,
          pos_nr: p.pos_nr || "",
          beschreibung: p.beschreibung || "",
          gewerk: p.gewerk || "",
          raum_referenz: p.raum_referenz || "",
          berechnung: p.berechnung || [],
          endsumme: p.endsumme || 0,
          einheit: p.einheit || "",
          konfidenz: Math.round((p.konfidenz || 0.5) * 100),
        })

      const log = plan.agent_log || {}
      log.step2 = { ts: new Date().toISOString(), pos: (kalk.positionen||[]).length, zf: kalk.zusammenfassung }
      await sb.from("plaene").update({ agent_log: log }).eq("id", plan_id)

      return new Response(JSON.stringify({
        status: "step2_done",
        next_step: 3,
        massen: (kalk.positionen||[]).length,
        zusammenfassung: kalk.zusammenfassung || {},
      }), { headers: { ...corsHeaders, "Content-Type": "application/json" } })
    }

    // ========== STEP 3: Kritik ==========
    if (step === 3) {
      const log = plan.agent_log || {}

      const kritik = await callClaude(cfg.value,
        `Du bist ein unabhängiger Prüfingenieur für Massenermittlung.

Bewerte die Analyse und Kalkulation:
1. Raumgrößen plausibel? (Wohnzimmer 15-40m², Bad 5-12m², WC 1.5-4m², Vorraum 3-10m²)
2. Berechnungen korrekt? Stimmen die Abzugsregeln?
3. Alles erfasst? Fehlen Räume, Fenster, Türen?
4. Sind die Einheiten korrekt? (m², m, lfm, Stk)
5. Stimmen die Summen?

STATUS:
- AKZEPTIERT: Qualitätsscore ≥ 75
- NACHBESSERUNG: Qualitätsscore 50-74
- KRITISCH: Qualitätsscore < 50

Antworte NUR mit validem JSON, KEIN Markdown.`,
        [{ type: "text", text: `Prüfe diese Ergebnisse:\n${JSON.stringify({ step1: log.step1, step2: log.step2 })}\n\nJSON-Format:
{
  "status": "AKZEPTIERT",
  "qualitaets_score": 85,
  "warnungen": ["Warnung 1"],
  "empfehlungen": ["Empfehlung 1"],
  "details": {
    "raeume_plausibel": true,
    "berechnungen_korrekt": true,
    "vollstaendigkeit": true
  },
  "gesamt_konfidenz": 0.87
}` }])

      const k = Math.round((kritik.gesamt_konfidenz || 0.5) * 100)

      // Delete geo data to save space
      delete log.geo
      log.step3 = { ts: new Date().toISOString(), ...kritik }
      log.kritik = kritik
      await sb.from("plaene").update({ verarbeitet: true, gesamt_konfidenz: k, agent_log: log }).eq("id", plan_id)

      return new Response(JSON.stringify({
        status: kritik.status || "AKZEPTIERT",
        konfidenz: k,
        qualitaets_score: kritik.qualitaets_score || k,
        warnungen: kritik.warnungen || [],
        empfehlungen: kritik.empfehlungen || [],
      }), { headers: { ...corsHeaders, "Content-Type": "application/json" } })
    }

    throw new Error("step muss 1, 2 oder 3 sein")
  } catch (e: any) {
    return new Response(JSON.stringify({ error: e.message }), { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } })
  }
})
