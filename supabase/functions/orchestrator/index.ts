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
 * Step-based orchestrator with 4-PASS FOCUSED VISION SCAN.
 *   step=1 → 4 focused passes (Structure, Rooms, Windows/Doors, Dimensions) + merge
 *   step=2 → Kalkulation (ÖNORM mass calculation, gewerk-specific)
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

    // ========== STEP 1: 4-Pass Focused Vision Scan ==========
    if (step === 1) {
      // Clean old results
      await sb.from("massen").delete().eq("plan_id", plan_id)
      await sb.from("elemente").delete().eq("plan_id", plan_id)
      await sb.from("plaene").update({ verarbeitet: false, agent_log: { start: new Date().toISOString() } }).eq("id", plan_id)

      const { data: u } = await sb.storage.from("plaene").createSignedUrl(plan.storage_path, 3600)
      if (!u?.signedUrl) throw new Error("PDF URL fehlt")
      const pdfSource = { type: "document", source: { type: "url", url: u.signedUrl } }

      const errors: string[] = []

      // ---- PASS 1A: STRUCTURE ----
      let pass1A: any = {}
      try {
        pass1A = await callClaude(cfg.value,
          `Du bist Bauingenieur. Analysiere die STRUKTUR dieses Plans. Antworte NUR mit validem JSON, KEIN Markdown.`,
          [
            pdfSource,
            { type: "text", text: `Beantworte NUR diese Fragen als JSON:
1. massstab: welcher Maßstab?
2. geschoss: welches Geschoss?
3. raumhoehe_m: welche Raumhöhe steht im Plan?
4. anzahl_wohnungen: wie viele Wohnungen/Einheiten (Top) sind sichtbar?
5. wohnungen: Liste jeder Wohnung mit {name, raeume: [Raumname, ...], flaeche_wohnnutz_m2}
6. wandstaerken_mm: welche Wandstärken erkennst du?
7. gebaeude_laenge_m: Gesamtlänge des Gebäudes
8. gebaeude_tiefe_m: Gesamttiefe

JSON-Format:
{
  "massstab": "1:100",
  "geschoss": "EG",
  "raumhoehe_m": 2.60,
  "anzahl_wohnungen": 4,
  "wohnungen": [
    { "name": "Top 1", "raeume": ["Vorraum", "Wohnküche", "Bad"], "flaeche_wohnnutz_m2": 55.0 }
  ],
  "wandstaerken_mm": [300, 200, 120],
  "gebaeude_laenge_m": 24.0,
  "gebaeude_tiefe_m": 12.0
}` },
          ])
      } catch (e: any) {
        errors.push("Pass1A: " + e.message)
      }

      // Update log after Pass 1A
      await sb.from("plaene").update({
        agent_log: {
          start: new Date().toISOString(),
          pass1A: { ts: new Date().toISOString(), ok: errors.length === 0, wohnungen: (pass1A.wohnungen || []).length },
        }
      }).eq("id", plan_id)

      // ---- PASS 1B: ROOMS ----
      let pass1B: any = {}
      try {
        pass1B = await callClaude(cfg.value,
          `Du bist Bautechniker. Lies JEDEN Text in JEDEM Raum. Antworte NUR mit validem JSON, KEIN Markdown.`,
          [
            pdfSource,
            { type: "text", text: `Für JEDEN Raum im Plan lies EXAKT ab:
- Name (wie er im Plan steht)
- Fläche m² (die Zahl mit m²)
- Umfang (U: xx.xx m)
- Höhe (H: x.xx m)
- Bodenbelag
- Zu welcher Wohnung (Top) gehört der Raum?
- Position als [x%, y%, w%, h%]
Gib die EXAKTEN Zahlen aus dem Plan zurück, keine Schätzungen!

JSON-Format:
{
  "raeume": [
    {
      "name": "Wohnküche",
      "flaeche_m2": 26.37,
      "umfang_m": 20.66,
      "hoehe_m": 2.42,
      "bodenbelag": "Parkett",
      "wohnung": "Top 1",
      "position_pct": [10, 20, 35, 40],
      "konfidenz": 0.95
    }
  ]
}` },
          ])
      } catch (e: any) {
        errors.push("Pass1B: " + e.message)
      }

      // Update log after Pass 1B
      const log1B = (await sb.from("plaene").select("agent_log").eq("id", plan_id).single()).data?.agent_log || {}
      log1B.pass1B = { ts: new Date().toISOString(), ok: !errors.some(e => e.startsWith("Pass1B")), raeume: (pass1B.raeume || []).length }
      await sb.from("plaene").update({ agent_log: log1B }).eq("id", plan_id)

      // ---- PASS 1C: WINDOWS & DOORS ----
      let pass1C: any = {}
      try {
        pass1C = await callClaude(cfg.value,
          `Du bist Fenstertechniker. Lies JEDE Fenster- und Türbezeichnung. Antworte NUR mit validem JSON, KEIN Markdown.`,
          [
            pdfSource,
            { type: "text", text: `Suche ALLE Fensterbezeichnungen (FE_, F_) und Türen (T_).
Fenster: Lies RPH, FPH, AL Breite+Höhe, RB Breite+Höhe in mm.
Türen: Lies Breite, Höhe, Typ.
Ordne jedes Element einem Raum und einer Wohnung zu.

JSON-Format:
{
  "fenster": [
    {
      "bezeichnung": "FE_31",
      "raum": "Wohnküche",
      "wohnung": "Top 1",
      "rph_mm": 1010,
      "fph_mm": 480,
      "al_breite_mm": 1510,
      "al_hoehe_mm": 1510,
      "rb_breite_mm": 1760,
      "rb_hoehe_mm": 1760,
      "position_pct": [5, 35, 5, 10],
      "konfidenz": 0.90
    }
  ],
  "tueren": [
    {
      "bezeichnung": "T1",
      "raum": "Wohnküche",
      "wohnung": "Top 1",
      "breite_mm": 900,
      "hoehe_mm": 2100,
      "typ": "Drehflügel",
      "position_pct": [30, 45, 3, 5],
      "konfidenz": 0.85
    }
  ]
}` },
          ])
      } catch (e: any) {
        errors.push("Pass1C: " + e.message)
      }

      // Update log after Pass 1C
      const log1C = (await sb.from("plaene").select("agent_log").eq("id", plan_id).single()).data?.agent_log || {}
      log1C.pass1C = { ts: new Date().toISOString(), ok: !errors.some(e => e.startsWith("Pass1C")), fenster: (pass1C.fenster || []).length, tueren: (pass1C.tueren || []).length }
      await sb.from("plaene").update({ agent_log: log1C }).eq("id", plan_id)

      // ---- PASS 1D: DIMENSIONS ----
      let pass1D: any = {}
      try {
        pass1D = await callClaude(cfg.value,
          `Du bist Vermesser. Lies die MAẞKETTEN. Antworte NUR mit validem JSON, KEIN Markdown.`,
          [
            pdfSource,
            { type: "text", text: `Lies ALLE Bemaßungszahlen im Plan. Das sind Zahlen an Linien mit Pfeilen/Endstrichen.
Die Zahlen sind in ZENTIMETERN. Typische Werte: 120-800.
Suche speziell:
- Gesamtmaße an den Außenkanten
- Maße zwischen Wohnungstrennwänden
- Maße einzelner Wandabschnitte
Für JEDES Maß: {wert_cm, beschreibung, position: 'oben/unten/links/rechts/innen'}

JSON-Format:
{
  "masse": [
    { "wert_cm": 587, "beschreibung": "Wand Wohnküche Süd", "position": "unten" }
  ],
  "gebaeude_laenge_cm": 2400,
  "gebaeude_tiefe_cm": 1200
}` },
          ])
      } catch (e: any) {
        errors.push("Pass1D: " + e.message)
      }

      // ---- MERGE all 4 passes ----
      const merged: any = {
        massstab: pass1A.massstab || null,
        geschoss: pass1A.geschoss || null,
        raumhoehe_global_m: pass1A.raumhoehe_m || null,
        anzahl_wohnungen: pass1A.anzahl_wohnungen || null,
        wohnungen: pass1A.wohnungen || [],
        wandstaerken_mm: pass1A.wandstaerken_mm || [],
        gebaeude_laenge_m: pass1A.gebaeude_laenge_m || (pass1D.gebaeude_laenge_cm ? pass1D.gebaeude_laenge_cm / 100 : null),
        gebaeude_tiefe_m: pass1A.gebaeude_tiefe_m || (pass1D.gebaeude_tiefe_cm ? pass1D.gebaeude_tiefe_cm / 100 : null),
        raeume: pass1B.raeume || [],
        fenster: pass1C.fenster || [],
        tueren: pass1C.tueren || [],
        masse: pass1D.masse || [],
        gebaeude_laenge_cm: pass1D.gebaeude_laenge_cm || null,
        gebaeude_tiefe_cm: pass1D.gebaeude_tiefe_cm || null,
      }

      // Calculate wandflaeche for each room
      for (const r of merged.raeume) {
        if (r.umfang_m && r.hoehe_m) {
          r.wandflaeche_m2 = Math.round(r.umfang_m * r.hoehe_m * 100) / 100
        }
        if (!r.flaeche_m2 && r.umfang_m) r.flaeche_m2 = 0
      }

      // Calculate fensterflaeche for each window
      for (const f of merged.fenster) {
        if (f.al_breite_mm && f.al_hoehe_mm) {
          f.flaeche_m2 = Math.round(f.al_breite_mm * f.al_hoehe_mm / 10000) / 100
        }
      }

      // ---- Store elements in DB ----
      for (const r of merged.raeume)
        await sb.from("elemente").insert({ plan_id, typ: "raum", bezeichnung: r.name || "", daten: r, konfidenz: Math.round((r.konfidenz || 0.5) * 100) })
      for (const f of merged.fenster)
        await sb.from("elemente").insert({ plan_id, typ: "fenster", bezeichnung: f.bezeichnung || "", daten: f, konfidenz: Math.round((f.konfidenz || 0.5) * 100) })
      for (const t of merged.tueren)
        await sb.from("elemente").insert({ plan_id, typ: "tuer", bezeichnung: t.bezeichnung || "", daten: t, konfidenz: Math.round((t.konfidenz || 0.5) * 100) })

      // ---- Update agent_log ----
      const log = {
        start: new Date().toISOString(),
        step1: {
          ts: new Date().toISOString(),
          r: merged.raeume.length,
          f: merged.fenster.length,
          t: merged.tueren.length,
          masse: merged.masse.length,
          pass1A: { ok: !errors.some(e => e.startsWith("Pass1A")), wohnungen: (pass1A.wohnungen || []).length },
          pass1B: { ok: !errors.some(e => e.startsWith("Pass1B")), raeume: (pass1B.raeume || []).length },
          pass1C: { ok: !errors.some(e => e.startsWith("Pass1C")), fenster: (pass1C.fenster || []).length, tueren: (pass1C.tueren || []).length },
          pass1D: { ok: !errors.some(e => e.startsWith("Pass1D")), masse: (pass1D.masse || []).length },
          errors: errors.length > 0 ? errors : undefined,
        },
        geo: merged,
        gewerk: gewerk,
      }
      await sb.from("plaene").update({ agent_log: log }).eq("id", plan_id)

      return new Response(JSON.stringify({
        status: "step1_done",
        next_step: 2,
        raeume: merged.raeume.length,
        fenster: merged.fenster.length,
        tueren: merged.tueren.length,
        masse: merged.masse.length,
        wohnungen: (pass1A.wohnungen || []).length,
        errors: errors.length > 0 ? errors : undefined,
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
FOKUS: VERPUTZER / SPACHTELARBEITEN (VP/SR) nach ÖNORM B 2204

EXAKTE BERECHNUNGSMETHODE eines professionellen Verputzerbetriebs:

═══ POSITION: INNENPUTZ WÄNDE (m²) ═══

Der Verputzer verputzt NUR die WOHNUNGSTRENNWÄNDE - das sind die DICKEN Wände
zwischen den Wohnungseinheiten (Top). NICHT die Zimmerwände innerhalb der Wohnung!

Für JEDE Wohnung (Top) berechne:
- WAND 1 (Tiefe): Gebäudetiefe-Maß × Raumhöhe (z.B. 5.87m × 2.66m = 15.61m²)
- WAND 2 (Breite): Wohnungsbreite × Raumhöhe (z.B. 7.14m × 2.66m = 18.99m²)
- Bei Eckwohnungen: zusätzliche Wände (3-4 statt 2)

Die Wandlängen findest du in den MASSKETTEN des Plans. Typische Werte:
- Gebäudetiefe: 5-6m (z.B. 5.87m, 5.79m, 5.80m)
- Eckwohnung breit: 6-8m (z.B. 7.14m)
- Mittelwohnung: 3-4m (z.B. 3.27m)

RAUMHÖHE: Verwende das ROHBAUMASS (Roh-Decke bis Roh-Boden):
- EG: typisch 2.60-2.70m (z.B. 2.66m)
- OG: typisch 2.55-2.65m (z.B. 2.60m)
Das Rohbaumaß ist ca. 20-25cm HÖHER als das Fertigmaß im Plan!
Wenn im Plan H=2.42m steht → Rohbaumaß ≈ 2.42 + 0.24 = 2.66m (EG)

═══ POSITION: HAFTGRUND (m²) ═══

NUR auf Betonwänden (Zwischenwand Beton) - NICHT auf Ziegel/Mauerwerk!
Betonwände brauchen Haftgrund weil Beton glatt und nicht saugend ist.
Berechne: Betonwand-Länge × Raumhöhe × Anzahl Seiten
Bei Betontrennwänden: BEIDE Seiten verputzen → Faktor 2!

═══ POSITION: KANTENPROFIL (lfm) ═══

Pro Fenster im Innenbereich:
- Fenster Aufrecht (beide Seiten): 2 × Fensterhöhe
  - Normale Fenster: 2 × 1.47m = 2.94 lfm
  - Loggia/Balkontür: 2 × Raumhöhe (2.60m oder 2.66m)
- Fensterbank: 1 × Fensterbreite
  - Normal: 1.20m
  - Klein (WC/Bad): 0.50m
Loggia-Fenster: 2 × Raumhöhe (KEINE Fensterbank - raumhohe Verglasung)
Zwischenwand Beton: 2 × Raumhöhe (beide Kanten der Betonwand)

═══ POSITION: ANPUTZLEISTE (lfm) ═══

Pro Fenster: NUR die aufrechten Teile, KEINE Fensterbänke!
- Fenster Aufrecht: 2 × Fensterhöhe
- Loggia: 2 × Raumhöhe
Gleiche Berechnung wie Kantenprofil MINUS die Fensterbänke.

═══ ÖNORM B 2204 ABZUGSREGELN ═══
- Öffnungen bis 0.5m²: kein Abzug, Leibungen dazurechnen
- Öffnungen 0.5-4.0m² MIT Leibungen: durchgemessen (nicht abziehen)
- Öffnungen 0.5-4.0m² OHNE Leibungen: abziehen
- Öffnungen über 4.0m²: abziehen, Leibungen extra addieren

BERECHNUNGSFORMAT: Jede Zeile: Beschreibung | Anz × Länge × Breite × Höhe = Zwischensumme`,

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

      // Build the system prompt based on gewerk
      let kalkSystem = ""
      let kalkUser = ""

      if (selectedGewerk === "verputzer") {
        kalkSystem = `Du bist ein Verputzer-Kalkulator. Du berechnest EXAKT 4 Positionen für Innenputz.

KRITISCH WICHTIG:
- Berechne NUR die WOHNUNGSTRENNWÄNDE (dicke Wände ZWISCHEN Wohnungen)
- NICHT die Zimmerwände INNERHALB der Wohnungen
- NICHT die Rauminnenwände (Bad-Innenwand, Küchen-Innenwand etc.)
- Die Trennwände sind die LANGEN Wände die von Vorder- bis Rückseite des Gebäudes gehen

RAUMHÖHE: Das ROHBAUMASS verwenden!
- Im Plan steht z.B. H: 2.42m = FERTIGMASS
- ROHBAUMASS = Fertigmaß + ca. 0.24m = z.B. 2.66m (EG) oder 2.60m (OG)
- IMMER Rohbaumaß für Putzarbeiten verwenden!

POSITION 1: HAFTGRUND (m²)
- NUR auf Betonwänden (Zwischenwand Beton)
- BEIDE Seiten einer Betonwand verputzen → Faktor 2
- Formel: Anz_Seiten × Wandlänge × Rohbau-Raumhöhe

POSITION 2: INNENPUTZ WÄNDE (m²)
- NUR Wohnungstrennwände, pro Wohnung (Top):
- Jede Wohnung hat typisch 2 Trennwand-Flächen:
  * WAND A (Gebäudetiefe): ca. 5.8-5.9m × Rohbau-Höhe
  * WAND B (Wohnungsbreite): ca. 3.3-7.1m × Rohbau-Höhe
- Bei Eckwohnungen: mehr Wände + Betonzwischenwände (BEIDE Seiten!)
- Betonzwischenwände: Anz × Wandlänge × Höhe (Anz=2 für beide Seiten)
- KEINE Zimmer-Innenwände, KEINE Raumwände!

POSITION 3: KANTENPROFIL (lfm)
- Pro Fenster: 2 × Fensterhöhe + 1 × Fensterbreite
  * Normale Fenster: Höhe ca. 1.47m, Breite 1.20m oder 0.50m
  * Loggia/Balkontür: Höhe = Raumhöhe (2.60/2.66m), KEINE Fensterbank
- Pro Betonwand-Kante: 2 × Raumhöhe (beide Seiten)

POSITION 4: ANPUTZLEISTE (lfm)
- Pro Fenster: NUR 2 × Fensterhöhe (KEINE Fensterbank!)
  * Normale Fenster: 2 × 1.47m = 2.94 lfm
  * Loggia: 2 × Raumhöhe

Antworte NUR mit validem JSON.`

        kalkUser = `Geometriedaten:\n${JSON.stringify(geo)}\n\nBerechne EXAKT diese 4 Positionen:

JSON-Format:
{
  "positionen": [
    {
      "pos_nr": "2.3.1",
      "beschreibung": "Haftgrund",
      "gewerk": "Innenputz",
      "raum_referenz": "Betonwände",
      "berechnung": ["Top 26 Betonwand: 1 × 3.22 × 1.0 × 2.66 = 8.57", "Top 26 Leibung: 1 × 0.20 × 1.0 × 2.66 = 0.53"],
      "endsumme": 66.02,
      "einheit": "m²",
      "konfidenz": 0.90
    },
    {
      "pos_nr": "2.3.2",
      "beschreibung": "Innenputz Wände",
      "gewerk": "Innenputz",
      "raum_referenz": "Trennwände",
      "berechnung": ["Top 25: 1 × 5.87 × 1.0 × 2.66 = 15.61", "Top 25: 1 × 7.14 × 1.0 × 2.66 = 18.99", "Top 26: 1 × 5.87 × 1.0 × 2.66 = 15.61"],
      "endsumme": 388.89,
      "einheit": "m²",
      "konfidenz": 0.90
    },
    {
      "pos_nr": "2.3.3",
      "beschreibung": "Kantenprofil",
      "gewerk": "Innenputz",
      "raum_referenz": "Fenster",
      "berechnung": ["Fenster Aufrecht: 2 × 1.47 = 2.94", "Fensterbank: 1 × 1.20 = 1.20"],
      "endsumme": 210.28,
      "einheit": "lfm",
      "konfidenz": 0.90
    },
    {
      "pos_nr": "2.3.4",
      "beschreibung": "Anputzleiste",
      "gewerk": "Innenputz",
      "raum_referenz": "Fenster",
      "berechnung": ["Fenster Aufrecht: 2 × 1.47 = 2.94", "Loggia: 2 × 2.60 = 5.20"],
      "endsumme": 185.68,
      "einheit": "lfm",
      "konfidenz": 0.90
    }
  ],
  "zusammenfassung": {
    "haftgrund_m2": 66.02,
    "innenputz_wande_m2": 388.89,
    "kantenprofile_lfm": 210.28,
    "anputzleisten_lfm": 185.68
  },
  "gesamt_konfidenz": 0.92
}

WICHTIG: Die Beispielwerte oben sind nur zur Illustration des FORMATS.
Berechne die ECHTEN Werte aus den Geometriedaten!
NUR diese 4 Positionen, NICHTS ANDERES!`
      } else {
        kalkSystem = `Du bist ein erfahrener österreichischer Baukalkulator.

GEWÄHLTES GEWERK: ${selectedGewerk.toUpperCase()}
${gewerkPrompt}

BERECHNUNGSFORMAT: Jeder Schritt: Beschreibung | Anz × L × B × H = Zwischensumme
ROHBAUMASS verwenden (Fertigmaß + 0.24m)!
Antworte NUR mit validem JSON.`

        kalkUser = `Geometriedaten:\n${JSON.stringify(geo)}\n\nErstelle professionelle Massenermittlung.
JSON: {"positionen":[{"pos_nr":"","beschreibung":"","gewerk":"","raum_referenz":"","berechnung":[""],"endsumme":0,"einheit":"","konfidenz":0.9}],"zusammenfassung":{},"gesamt_konfidenz":0.88}`
      }

      const kalk = await callClaude(cfg.value, kalkSystem,
        [{ type: "text", text: kalkUser }],
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
