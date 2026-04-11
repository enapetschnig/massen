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
        "Du bist der beste Bautechniker Österreichs. Analysiere den Bauplan präzise. Fenster: FE_[Nr]/RPH/FPH/AL/RB in mm. Werte<30=cm→×10. Wandfläche=U×H. JEDEN Raum, JEDES Fenster, JEDE Tür erfassen. Nur JSON.",
        [
          { type: "document", source: { type: "url", url: u.signedUrl } },
          { type: "text", text: 'Vollständige Analyse. JSON: {"massstab":"","geschoss":"","raeume":[{"name":"","bodenbelag":"","flaeche_m2":0,"umfang_m":0,"hoehe_m":0,"wandflaeche_m2":0,"konfidenz":0.9}],"fenster":[{"bezeichnung":"","raum":"","rph_mm":0,"fph_mm":0,"al_breite_mm":0,"al_hoehe_mm":0,"rb_breite_mm":0,"rb_hoehe_mm":0,"flaeche_m2":0,"konfidenz":0.9}],"tueren":[{"bezeichnung":"","raum":"","breite_mm":0,"hoehe_mm":0,"typ":"","konfidenz":0.85}],"wandstaerken_mm":[],"gesamt_konfidenz":0.85}' },
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
