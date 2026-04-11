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
 * Step-based orchestrator. The frontend calls 3 times:
 *   step=1 → Parser+Geometrie (stores rooms/windows/doors)
 *   step=2 → Kalkulation (stores mass positions)
 *   step=3 → Kritik (finalizes quality score)
 */
serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders })

  try {
    const { plan_id, step = 1 } = await req.json()
    if (!plan_id) throw new Error("plan_id fehlt")

    const sb = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!)
    const { data: cfg } = await sb.from("app_config").select("value").eq("key", "ANTHROPIC_API_KEY").single()
    if (!cfg?.value) throw new Error("API Key fehlt")

    const { data: plan } = await sb.from("plaene").select("*").eq("id", plan_id).single()
    if (!plan) throw new Error("Plan nicht gefunden")

    // ========== STEP 1: Parser + Geometrie ==========
    if (step === 1) {
      await sb.from("massen").delete().eq("plan_id", plan_id)
      await sb.from("elemente").delete().eq("plan_id", plan_id)
      await sb.from("plaene").update({ verarbeitet: false, agent_log: { start: new Date().toISOString() } }).eq("id", plan_id)

      const { data: u } = await sb.storage.from("plaene").createSignedUrl(plan.storage_path, 3600)
      if (!u?.signedUrl) throw new Error("PDF URL fehlt")

      const parsed = await callClaude(cfg.value,
        `Du bist der erfahrenste Bautechniker Österreichs mit 30 Jahren Praxis. Du liest Baupläne so präzise wie kein anderer.

DEINE AUFGABE: Analysiere diesen Bauplan VOLLSTÄNDIG. Übersehe NICHTS.

SO GEHST DU VOR (wie ein Profi):

SCHRITT 1 - PLAN VERSTEHEN:
- Finde den MASSSTAB (meist im Plankopf rechts unten, z.B. "M 1:100")
- Finde das GESCHOSS (EG, OG, KG, DG)
- Finde die RAUMHÖHE (steht oft nur EINMAL und gilt für alle Räume)
- Finde WANDSTÄRKEN (Außenwand typisch 25-50cm, Innenwand 10-25cm)

SCHRITT 2 - JEDEN RAUM FINDEN:
- Gehe den Plan SYSTEMATISCH durch: oben-links → oben-rechts → mitte → unten
- Typische Räume: Vorraum, Flur, Gang, Wohnzimmer, Wohnküche, Küche, Schlafzimmer, Kinderzimmer, Bad, WC, Dusche, Abstellraum, Garderobe, Schrankraum, Loggia, Balkon, Terrasse, Technikraum, Waschküche
- Jeder Raum hat: NAME (steht im Raum), FLÄCHE (z.B. "23,50 m²"), UMFANG ("U: 20,40"), HÖHE ("H: 2,60"), BODENBELAG (Parkett, Fliesen etc.)
- POSITION: Gib an wo der Raum auf dem Plan liegt als Prozent [x%, y%, breite%, höhe%] vom gesamten Plan

SCHRITT 3 - JEDES FENSTER FINDEN:
- Fenster stehen ROTIERT an den Wänden oder in Tabellen
- Format: FE_[Nr] / RPH [Wert] / FPH [Wert] / AL[Breite] / AL[Höhe] / RB[Breite] / RB[Höhe]
- RPH = Rohbauparapethöhe (Abstand Fensterunterseite zu Rohfußboden)
- FPH = Fertigparapethöhe
- AL = Architekturlichte (Fertigmaß der Fensteröffnung)
- RB = Rohbauöffnung (muss GRÖSSER als AL sein, +5-15cm pro Seite)
- Werte < 30 sind wahrscheinlich in cm → multipliziere mit 10 für mm
- Ordne jedes Fenster einem Raum zu

SCHRITT 4 - JEDE TÜR FINDEN:
- Türen: T[Nr] oder Türsymbol (Viertelkreis im Plan)
- Breite typisch: 60cm (WC), 70cm (Bad), 80cm (Zimmer), 90cm (Eingang), 100-120cm (Doppel)

SCHRITT 5 - POSITION ANGEBEN:
- Für JEDES Element: position_pct als [x%, y%, breite%, höhe%] vom Gesamtplan
- x=0% ist links, x=100% ist rechts
- y=0% ist oben, y=100% ist unten

Antworte NUR mit validem JSON, KEIN Markdown.`,
        [
          { type: "document", source: { type: "url", url: u.signedUrl } },
          { type: "text", text: `Analysiere JEDEN Raum, JEDES Fenster, JEDE Tür. Gib für alles die Position auf dem Plan an.

JSON-Format:
{
  "massstab": "1:100",
  "geschoss": "EG",
  "raumhoehe_global_m": 2.60,
  "wandstaerken_mm": [300, 200, 120],
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

      // Quick geometry fix: calculate missing wall areas
      for (const r of (parsed.raeume || [])) {
        if (!r.wandflaeche_m2 && r.umfang_m && r.hoehe_m) r.wandflaeche_m2 = Math.round(r.umfang_m * r.hoehe_m * 100) / 100
        if (!r.flaeche_m2 && r.umfang_m) r.flaeche_m2 = 0
      }
      for (const f of (parsed.fenster || [])) {
        if (!f.flaeche_m2 && f.al_breite_mm && f.al_hoehe_mm) f.flaeche_m2 = Math.round(f.al_breite_mm * f.al_hoehe_mm / 10000) / 100
      }

      for (const r of (parsed.raeume || []))
        await sb.from("elemente").insert({ plan_id, typ: "raum", bezeichnung: r.name || "", daten: r, konfidenz: Math.round((r.konfidenz || 0.5) * 100) })
      for (const f of (parsed.fenster || []))
        await sb.from("elemente").insert({ plan_id, typ: "fenster", bezeichnung: f.bezeichnung || "", daten: f, konfidenz: Math.round((f.konfidenz || 0.5) * 100) })
      for (const t of (parsed.tueren || []))
        await sb.from("elemente").insert({ plan_id, typ: "tuer", bezeichnung: t.bezeichnung || "", daten: t, konfidenz: Math.round((t.konfidenz || 0.5) * 100) })

      const log = { start: new Date().toISOString(), step1: { ts: new Date().toISOString(), r: (parsed.raeume||[]).length, f: (parsed.fenster||[]).length, t: (parsed.tueren||[]).length }, geo: parsed }
      await sb.from("plaene").update({ agent_log: log }).eq("id", plan_id)

      return new Response(JSON.stringify({ status: "step1_done", next_step: 2, raeume: (parsed.raeume||[]).length, fenster: (parsed.fenster||[]).length, tueren: (parsed.tueren||[]).length }), { headers: { ...corsHeaders, "Content-Type": "application/json" } })
    }

    // ========== STEP 2: Kalkulation ==========
    if (step === 2) {
      const geo = plan.agent_log?.geo
      if (!geo) throw new Error("Step 1 zuerst ausführen")

      const kalk = await callClaude(cfg.value,
        "Österreichischer Baukalkulator. ÖNORM-Massenermittlung. Abzüge Mauerwerk: <0.5m² kein, 0.5-3m² halb, >3m² voll. Putz/Maler: <2.5m² kein, 2.5-10m² halb, >10m² voll. Leibung: Seiten=2×Wandstärke×Höhe, Sturz=Wandstärke×Breite. Pos: 01=Mauerwerk, 02=Putz, 03=Maler, 04=Boden, 05=Estrich, 06=Fensterbänke. Nur JSON.",
        [{ type: "text", text: `Massen berechnen:\n${JSON.stringify(geo)}\n\nJSON: {"positionen":[{"pos_nr":"01.01","beschreibung":"","gewerk":"","raum_referenz":"","berechnung":[""],"endsumme":0,"einheit":"","konfidenz":0.9}],"zusammenfassung":{},"gesamt_konfidenz":0.88}` }],
        32000)

      for (const p of (kalk.positionen || []))
        await sb.from("massen").insert({ plan_id, pos_nr: p.pos_nr||"", beschreibung: p.beschreibung||"", gewerk: p.gewerk||"", raum_referenz: p.raum_referenz||"", berechnung: p.berechnung||[], endsumme: p.endsumme||0, einheit: p.einheit||"", konfidenz: Math.round((p.konfidenz||0.5)*100) })

      const log = plan.agent_log || {}
      log.step2 = { ts: new Date().toISOString(), pos: (kalk.positionen||[]).length, zf: kalk.zusammenfassung }
      await sb.from("plaene").update({ agent_log: log }).eq("id", plan_id)

      return new Response(JSON.stringify({ status: "step2_done", next_step: 3, massen: (kalk.positionen||[]).length }), { headers: { ...corsHeaders, "Content-Type": "application/json" } })
    }

    // ========== STEP 3: Kritik ==========
    if (step === 3) {
      const log = plan.agent_log || {}
      const kritik = await callClaude(cfg.value,
        "Unabhängiger Prüfingenieur. Bewerte: Raumgrößen plausibel? Berechnungen korrekt? Alles erfasst? Status: AKZEPTIERT(≥75), NACHBESSERUNG(50-74), KRITISCH(<50). Nur JSON.",
        [{ type: "text", text: `Prüfe:\n${JSON.stringify({ step1: log.step1, step2: log.step2 })}\n\nJSON: {"status":"AKZEPTIERT","qualitaets_score":85,"warnungen":[],"empfehlungen":[],"gesamt_konfidenz":0.87}` }])

      const k = Math.round((kritik.gesamt_konfidenz || 0.5) * 100)
      delete log.geo
      log.step3 = { ts: new Date().toISOString(), ...kritik }
      log.kritik = kritik
      await sb.from("plaene").update({ verarbeitet: true, gesamt_konfidenz: k, agent_log: log }).eq("id", plan_id)

      return new Response(JSON.stringify({ status: kritik.status || "AKZEPTIERT", konfidenz: k, qualitaets_score: kritik.qualitaets_score || k, warnungen: kritik.warnungen || [], empfehlungen: kritik.empfehlungen || [] }), { headers: { ...corsHeaders, "Content-Type": "application/json" } })
    }

    throw new Error("step muss 1, 2 oder 3 sein")
  } catch (e: any) {
    return new Response(JSON.stringify({ error: e.message }), { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } })
  }
})
