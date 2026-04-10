import { serve } from "https://deno.land/std@0.168.0/http/server.ts"
import { createClient } from "https://esm.sh/@supabase/supabase-js@2"

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
}

serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders })
  }

  try {
    const { plan_id } = await req.json()
    if (!plan_id) throw new Error("plan_id fehlt")

    const sb = createClient(
      Deno.env.get("SUPABASE_URL")!,
      Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
    )

    const { data: cfg } = await sb.from("app_config").select("value").eq("key", "ANTHROPIC_API_KEY").single()
    if (!cfg?.value) throw new Error("API Key nicht konfiguriert")

    const { data: plan } = await sb.from("plaene").select("*").eq("id", plan_id).single()
    if (!plan) throw new Error("Plan nicht gefunden")

    // Create a signed URL instead of downloading the whole PDF
    const { data: urlData, error: urlErr } = await sb.storage.from("plaene").createSignedUrl(plan.storage_path, 600)
    if (urlErr || !urlData?.signedUrl) throw new Error("Signed URL: " + (urlErr?.message || "fehlgeschlagen"))

    // Send URL to Claude - Claude can fetch it directly
    const res = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": cfg.value,
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify({
        model: "claude-sonnet-4-20250514",
        max_tokens: 8192,
        messages: [{ role: "user", content: [
          { type: "document", source: { type: "url", url: urlData.signedUrl } },
          { type: "text", text: "Du bist der beste Bautechniker Österreichs mit 30 Jahren Erfahrung.\nAnalysiere diesen Bauplan VOLLSTÄNDIG und PRÄZISE.\n\n1. Maßstab, Geschoss, Planungsbüro\n2. JEDEN Raum: Name, Bodenbelag, Fläche m², Umfang m, Höhe m, Wandfläche=U×H\n3. JEDES Fenster: FE_Nr, alle Parameter (RPH/FPH/AL/RB) in mm, Fläche m²\n4. JEDE Tür: T-Nr, Breite×Höhe, Typ\n5. Wandstärken mm\n\nFensternotation: FE_[Nr] / RPH [mm] / FPH [mm] / AL[Breite] / AL[Höhe] / RB[Breite] / RB[Höhe]\nWenn Wert < 30 dann wahrscheinlich cm → multipliziere mit 10\n\nNUR valides JSON ohne Markdown:\n{\"massstab\":\"1:100\",\"geschoss\":\"EG\",\"raeume\":[{\"name\":\"\",\"bodenbelag\":\"\",\"flaeche_m2\":0,\"umfang_m\":0,\"hoehe_m\":0,\"wandflaeche_m2\":0,\"konfidenz\":0.9}],\"fenster\":[{\"bezeichnung\":\"\",\"raum\":\"\",\"rph_mm\":0,\"fph_mm\":0,\"al_breite_mm\":0,\"al_hoehe_mm\":0,\"rb_breite_mm\":0,\"rb_hoehe_mm\":0,\"flaeche_m2\":0,\"konfidenz\":0.9}],\"tueren\":[{\"bezeichnung\":\"\",\"raum\":\"\",\"breite_mm\":0,\"hoehe_mm\":0,\"typ\":\"\",\"konfidenz\":0.85}],\"gesamt_konfidenz\":0.87}" }
        ]}]
      })
    })

    if (!res.ok) {
      const err = await res.text()
      throw new Error("Claude " + res.status + ": " + err.substring(0, 300))
    }

    const claude = await res.json()
    const raw = claude.content?.[0]?.text || "{}"

    let result: any
    try {
      const m = raw.match(/\{[\s\S]*\}/)
      result = JSON.parse(m ? m[0] : raw)
    } catch { throw new Error("Parsing fehlgeschlagen: " + raw.substring(0, 100)) }

    // Store results
    for (const r of (result.raeume || []))
      await sb.from("elemente").insert({ plan_id, typ: "raum", bezeichnung: r.name || "", daten: r, konfidenz: Math.round((r.konfidenz || 0.5) * 100) })
    for (const f of (result.fenster || []))
      await sb.from("elemente").insert({ plan_id, typ: "fenster", bezeichnung: f.bezeichnung || "", daten: f, konfidenz: Math.round((f.konfidenz || 0.5) * 100) })
    for (const t of (result.tueren || []))
      await sb.from("elemente").insert({ plan_id, typ: "tuer", bezeichnung: t.bezeichnung || "", daten: t, konfidenz: Math.round((t.konfidenz || 0.5) * 100) })

    const k = Math.round((result.gesamt_konfidenz || 0.5) * 100)
    await sb.from("plaene").update({ verarbeitet: true, gesamt_konfidenz: k, agent_log: result }).eq("id", plan_id)

    return new Response(JSON.stringify({
      status: "ok", raeume: (result.raeume||[]).length, fenster: (result.fenster||[]).length, tueren: (result.tueren||[]).length, konfidenz: k
    }), { headers: { ...corsHeaders, "Content-Type": "application/json" } })

  } catch (err: any) {
    return new Response(JSON.stringify({ error: err.message }), {
      status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" }
    })
  }
})
