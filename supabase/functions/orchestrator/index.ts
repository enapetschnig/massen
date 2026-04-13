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

// ═══ DETERMINISTIC MATH ENGINE ═══

interface RoomDims {
  name: string
  wohnung: string
  flaeche: number
  umfang: number
  hoehe: number
  bodenbelag: string
  sideA: number  // longer side
  sideB: number  // shorter side
}

function calcRoomDimensions(room: any, rohbauHoehe: number): RoomDims | null {
  // Calculate room dimensions from area + perimeter
  const F = room.flaeche_m2 || 0
  const U = room.umfang_m || 0
  const H = rohbauHoehe || room.hoehe_m || 2.60

  if (F > 0 && U > 0) {
    // Quadratic formula: a + b = U/2, a * b = F
    const halfU = U / 2
    const discriminant = halfU * halfU - 4 * F
    if (discriminant >= 0) {
      const a = (halfU + Math.sqrt(discriminant)) / 2
      const b = (halfU - Math.sqrt(discriminant)) / 2
      return { name: room.name || "", wohnung: (room.wohnung || "").toUpperCase(),
               flaeche: F, umfang: U, hoehe: H, bodenbelag: room.bodenbelag || "",
               sideA: Math.round(a * 100) / 100, sideB: Math.round(b * 100) / 100 }
    }
  }

  // Fallback: use area and estimate as square
  if (F > 0) {
    const side = Math.sqrt(F)
    return { name: room.name || "", wohnung: (room.wohnung || "").toUpperCase(),
             flaeche: F, umfang: U || side * 4, hoehe: H, bodenbelag: room.bodenbelag || "",
             sideA: Math.round(side * 100) / 100, sideB: Math.round(side * 100) / 100 }
  }

  return null
}

function calcWandflaeche(room: RoomDims): number {
  // Wall area = perimeter x height
  return Math.round(room.umfang * room.hoehe * 100) / 100
}

function calcOENORMAbzug(oeffnungFlaeche: number, gewerk: string): number {
  // Returns multiplier: 0 = no deduction, 0.5 = half, 1.0 = full
  if (gewerk === "mauerwerk") {
    if (oeffnungFlaeche < 0.5) return 0
    if (oeffnungFlaeche <= 3.0) return 0.5
    return 1.0
  }
  if (gewerk === "putz" || gewerk === "maler") {
    if (oeffnungFlaeche < 2.5) return 0
    if (oeffnungFlaeche <= 10.0) return 0.5
    return 1.0
  }
  if (gewerk === "fliesen") {
    if (oeffnungFlaeche < 0.1) return 0
    return 1.0
  }
  return 0
}

function normalizeWindowDimension(val: number): number {
  // Auto-detect unit and convert to mm
  if (val < 30) return val * 100   // cm -> mm (e.g., 15 -> 1500)
  if (val < 300) return val * 10   // cm -> mm (e.g., 147 -> 1470)
  return val                        // already mm
}

function isNassraum(name: string): boolean {
  return /bad|wc|dusche|nassraum|wasch/i.test(name)
}

function isBad(name: string): boolean {
  return /bad|dusche|nassraum/i.test(name)
}

function isWC(name: string): boolean {
  return /\bwc\b|toilette/i.test(name)
}

function hasFliesenBoden(bodenbelag: string, name: string): boolean {
  if (/fliesen|feinsteinzeug|keramik|steinzeug/i.test(bodenbelag)) return true
  // Bad/WC typically have tiles even if not specified
  if (isNassraum(name) && !bodenbelag) return true
  return false
}

function calcMassen(
  raeume: any[], fenster: any[], tueren: any[],
  gewerk: string, geschosse: number, whgProOg: number, hEG: number, hOG: number
): any[] {
  const positionen: any[] = []
  const dims = raeume.map(r => calcRoomDimensions(r, hEG)).filter(d => d !== null) as RoomDims[]
  const whgNames = [...new Set(dims.map(d => d.wohnung))].filter(w => w.startsWith("TOP"))
  const egWhg = whgNames.length || 1
  const ogFloors = geschosse - 1
  const wandstaerke_m = 0.20 // default inner wall thickness

  // Normalize window dimensions
  const normalizedFenster = fenster.map(f => {
    const al_h = normalizeWindowDimension(f.al_hoehe_mm || 1470) / 1000
    const al_b = normalizeWindowDimension(f.al_breite_mm || 1200) / 1000
    const rb_h = normalizeWindowDimension(f.rb_hoehe_mm || 1570) / 1000
    const rb_b = normalizeWindowDimension(f.rb_breite_mm || 1300) / 1000
    return {
      ...f,
      al_hoehe_m: al_h,
      al_breite_m: al_b,
      rb_hoehe_m: rb_h,
      rb_breite_m: rb_b,
      flaeche_m2: Math.round(al_h * al_b * 100) / 100,
    }
  })

  // Normalize door dimensions
  const normalizedTueren = tueren.map(t => ({
    ...t,
    breite_m: (t.breite_mm || 900) / 1000,
    hoehe_m: (t.hoehe_mm || 2100) / 1000,
    flaeche_m2: Math.round(((t.breite_mm || 900) / 1000) * ((t.hoehe_mm || 2100) / 1000) * 100) / 100,
  }))

  // Total opening areas per room for deductions
  function openingsForRoom(roomName: string, whg: string): number {
    let total = 0
    for (const f of normalizedFenster) {
      if ((f.raum || "").toLowerCase() === roomName.toLowerCase() &&
          (f.wohnung || "").toUpperCase() === whg) {
        total += f.flaeche_m2
      }
    }
    for (const t of normalizedTueren) {
      if ((t.raum || "").toLowerCase() === roomName.toLowerCase() &&
          (t.wohnung || "").toUpperCase() === whg) {
        total += t.flaeche_m2
      }
    }
    return total
  }

  // ═══ MALER ═══
  if (gewerk === "maler" || gewerk === "allgemein") {
    const prefix = gewerk === "allgemein" ? "ML." : ""
    let totalWandEG = 0, totalDeckeEG = 0, totalLeibungEG = 0
    const berechnungWand: string[] = []
    const berechnungDecke: string[] = []
    const berechnungLeibung: string[] = []

    for (const d of dims) {
      const wf = calcWandflaeche(d)
      const oeffnung = openingsForRoom(d.name, d.wohnung)
      const abzugFaktor = calcOENORMAbzug(oeffnung, "maler")
      const abzug = Math.round(oeffnung * abzugFaktor * 100) / 100
      const netto = Math.round((wf - abzug) * 100) / 100

      totalWandEG += netto
      berechnungWand.push(`${d.wohnung} ${d.name}: ${d.umfang.toFixed(2)}x${d.hoehe.toFixed(2)}=${wf.toFixed(2)} -${abzug.toFixed(2)} = ${netto.toFixed(2)} m2`)

      totalDeckeEG += d.flaeche
      berechnungDecke.push(`${d.wohnung} ${d.name}: ${d.flaeche.toFixed(2)} m2`)
    }

    // Leibungen: per window 2xwandstaerkexheight + wandstaerkexwidth
    for (const f of normalizedFenster) {
      const leib = 2 * wandstaerke_m * f.al_hoehe_m + wandstaerke_m * f.al_breite_m
      const leibFlaeche = Math.round(leib * 100) / 100
      totalLeibungEG += leibFlaeche
      berechnungLeibung.push(`${f.bezeichnung || "Fenster"}: 2x${wandstaerke_m}x${f.al_hoehe_m.toFixed(2)}+${wandstaerke_m}x${f.al_breite_m.toFixed(2)} = ${leibFlaeche.toFixed(2)} m2`)
    }

    // OG multiplication
    const ogFaktorFlaeche = egWhg > 0 ? (whgProOg / egWhg) * (hOG / hEG) : 0
    const ogFaktorDecke = egWhg > 0 ? (whgProOg / egWhg) : 0
    const ogFaktorLeibung = egWhg > 0 ? (whgProOg / egWhg) : 0

    const totalWandOG = Math.round(totalWandEG * ogFaktorFlaeche * ogFloors * 100) / 100
    const totalDeckeOG = Math.round(totalDeckeEG * ogFaktorDecke * ogFloors * 100) / 100
    const totalLeibungOG = Math.round(totalLeibungEG * ogFaktorLeibung * ogFloors * 100) / 100

    positionen.push(
      { pos_nr: `${prefix}1`, beschreibung: "Grundierung Waende EG", gewerk: "Maler",
        raum_referenz: "Alle Raeume EG", berechnung: berechnungWand,
        endsumme: Math.round(totalWandEG * 100) / 100, einheit: "m2", konfidenz: 90 },
      { pos_nr: `${prefix}1-OG`, beschreibung: `Grundierung Waende OG (x${ogFloors})`, gewerk: "Maler",
        raum_referenz: "Alle Raeume OG", berechnung: [`EG ${totalWandEG.toFixed(2)} x ${(ogFaktorFlaeche * ogFloors).toFixed(2)} = ${totalWandOG.toFixed(2)}`],
        endsumme: totalWandOG, einheit: "m2", konfidenz: 85 },
      { pos_nr: `${prefix}2`, beschreibung: "Anstrich Waende EG", gewerk: "Maler",
        raum_referenz: "Alle Raeume EG", berechnung: berechnungWand,
        endsumme: Math.round(totalWandEG * 100) / 100, einheit: "m2", konfidenz: 90 },
      { pos_nr: `${prefix}2-OG`, beschreibung: `Anstrich Waende OG (x${ogFloors})`, gewerk: "Maler",
        raum_referenz: "Alle Raeume OG", berechnung: [`EG ${totalWandEG.toFixed(2)} x ${(ogFaktorFlaeche * ogFloors).toFixed(2)} = ${totalWandOG.toFixed(2)}`],
        endsumme: totalWandOG, einheit: "m2", konfidenz: 85 },
      { pos_nr: `${prefix}3`, beschreibung: "Grundierung Decken EG", gewerk: "Maler",
        raum_referenz: "Alle Raeume EG", berechnung: berechnungDecke,
        endsumme: Math.round(totalDeckeEG * 100) / 100, einheit: "m2", konfidenz: 92 },
      { pos_nr: `${prefix}3-OG`, beschreibung: `Grundierung Decken OG (x${ogFloors})`, gewerk: "Maler",
        raum_referenz: "Alle Raeume OG", berechnung: [`EG ${totalDeckeEG.toFixed(2)} x ${(ogFaktorDecke * ogFloors).toFixed(2)} = ${totalDeckeOG.toFixed(2)}`],
        endsumme: totalDeckeOG, einheit: "m2", konfidenz: 87 },
      { pos_nr: `${prefix}4`, beschreibung: "Anstrich Decken EG", gewerk: "Maler",
        raum_referenz: "Alle Raeume EG", berechnung: berechnungDecke,
        endsumme: Math.round(totalDeckeEG * 100) / 100, einheit: "m2", konfidenz: 92 },
      { pos_nr: `${prefix}4-OG`, beschreibung: `Anstrich Decken OG (x${ogFloors})`, gewerk: "Maler",
        raum_referenz: "Alle Raeume OG", berechnung: [`EG ${totalDeckeEG.toFixed(2)} x ${(ogFaktorDecke * ogFloors).toFixed(2)} = ${totalDeckeOG.toFixed(2)}`],
        endsumme: totalDeckeOG, einheit: "m2", konfidenz: 87 },
      { pos_nr: `${prefix}5`, beschreibung: "Leibungen EG", gewerk: "Maler",
        raum_referenz: "Fenster EG", berechnung: berechnungLeibung,
        endsumme: Math.round(totalLeibungEG * 100) / 100, einheit: "m2", konfidenz: 85 },
      { pos_nr: `${prefix}5-OG`, beschreibung: `Leibungen OG (x${ogFloors})`, gewerk: "Maler",
        raum_referenz: "Fenster OG", berechnung: [`EG ${totalLeibungEG.toFixed(2)} x ${(ogFaktorLeibung * ogFloors).toFixed(2)} = ${totalLeibungOG.toFixed(2)}`],
        endsumme: totalLeibungOG, einheit: "lfm", konfidenz: 80 },
    )
  }

  // ═══ FLIESEN ═══
  if (gewerk === "fliesen" || gewerk === "allgemein") {
    const prefix = gewerk === "allgemein" ? "FL." : ""
    let totalBodenEG = 0, totalWandBadEG = 0, totalWandWCEG = 0, totalSockelEG = 0
    const berechnungBoden: string[] = []
    const berechnungWandBad: string[] = []
    const berechnungWandWC: string[] = []
    const berechnungSockel: string[] = []
    const fliesenHoehe = 2.10 // standard tile height for wet rooms

    for (const d of dims) {
      if (hasFliesenBoden(d.bodenbelag, d.name)) {
        totalBodenEG += d.flaeche
        berechnungBoden.push(`${d.wohnung} ${d.name}: ${d.flaeche.toFixed(2)} m2`)

        totalSockelEG += d.umfang
        berechnungSockel.push(`${d.wohnung} ${d.name}: ${d.umfang.toFixed(2)} lfm`)
      }

      if (isBad(d.name)) {
        const wandBad = Math.round(d.umfang * fliesenHoehe * 100) / 100
        const oeffnung = openingsForRoom(d.name, d.wohnung)
        const abzug = calcOENORMAbzug(oeffnung, "fliesen") * oeffnung
        const netto = Math.round((wandBad - abzug) * 100) / 100
        totalWandBadEG += netto
        berechnungWandBad.push(`${d.wohnung} ${d.name}: ${d.umfang.toFixed(2)}x${fliesenHoehe} -${abzug.toFixed(2)} = ${netto.toFixed(2)} m2`)
      }

      if (isWC(d.name)) {
        const wandWC = Math.round(d.umfang * fliesenHoehe * 100) / 100
        const oeffnung = openingsForRoom(d.name, d.wohnung)
        const abzug = calcOENORMAbzug(oeffnung, "fliesen") * oeffnung
        const netto = Math.round((wandWC - abzug) * 100) / 100
        totalWandWCEG += netto
        berechnungWandWC.push(`${d.wohnung} ${d.name}: ${d.umfang.toFixed(2)}x${fliesenHoehe} -${abzug.toFixed(2)} = ${netto.toFixed(2)} m2`)
      }
    }

    const ogFaktor = egWhg > 0 ? (whgProOg / egWhg) * ogFloors : 0

    positionen.push(
      { pos_nr: `${prefix}1`, beschreibung: "Bodenfliesen EG", gewerk: "Fliesen",
        raum_referenz: "Nassraeume EG", berechnung: berechnungBoden,
        endsumme: Math.round(totalBodenEG * 100) / 100, einheit: "m2", konfidenz: 90 },
      { pos_nr: `${prefix}1-OG`, beschreibung: `Bodenfliesen OG (x${ogFloors})`, gewerk: "Fliesen",
        raum_referenz: "Nassraeume OG", berechnung: [`EG ${totalBodenEG.toFixed(2)} x ${ogFaktor.toFixed(2)} = ${(totalBodenEG * ogFaktor).toFixed(2)}`],
        endsumme: Math.round(totalBodenEG * ogFaktor * 100) / 100, einheit: "m2", konfidenz: 85 },
    )

    if (totalWandBadEG > 0) {
      positionen.push(
        { pos_nr: `${prefix}2`, beschreibung: "Wandfliesen Bad EG", gewerk: "Fliesen",
          raum_referenz: "Bad EG", berechnung: berechnungWandBad,
          endsumme: Math.round(totalWandBadEG * 100) / 100, einheit: "m2", konfidenz: 88 },
        { pos_nr: `${prefix}2-OG`, beschreibung: `Wandfliesen Bad OG (x${ogFloors})`, gewerk: "Fliesen",
          raum_referenz: "Bad OG", berechnung: [`EG ${totalWandBadEG.toFixed(2)} x ${ogFaktor.toFixed(2)} = ${(totalWandBadEG * ogFaktor).toFixed(2)}`],
          endsumme: Math.round(totalWandBadEG * ogFaktor * 100) / 100, einheit: "m2", konfidenz: 83 },
      )
    }

    if (totalWandWCEG > 0) {
      positionen.push(
        { pos_nr: `${prefix}3`, beschreibung: "Wandfliesen WC EG", gewerk: "Fliesen",
          raum_referenz: "WC EG", berechnung: berechnungWandWC,
          endsumme: Math.round(totalWandWCEG * 100) / 100, einheit: "m2", konfidenz: 88 },
        { pos_nr: `${prefix}3-OG`, beschreibung: `Wandfliesen WC OG (x${ogFloors})`, gewerk: "Fliesen",
          raum_referenz: "WC OG", berechnung: [`EG ${totalWandWCEG.toFixed(2)} x ${ogFaktor.toFixed(2)} = ${(totalWandWCEG * ogFaktor).toFixed(2)}`],
          endsumme: Math.round(totalWandWCEG * ogFaktor * 100) / 100, einheit: "m2", konfidenz: 83 },
      )
    }

    positionen.push(
      { pos_nr: `${prefix}4`, beschreibung: "Sockelleisten EG", gewerk: "Fliesen",
        raum_referenz: "Nassraeume EG", berechnung: berechnungSockel,
        endsumme: Math.round(totalSockelEG * 100) / 100, einheit: "lfm", konfidenz: 85 },
      { pos_nr: `${prefix}4-OG`, beschreibung: `Sockelleisten OG (x${ogFloors})`, gewerk: "Fliesen",
        raum_referenz: "Nassraeume OG", berechnung: [`EG ${totalSockelEG.toFixed(2)} x ${ogFaktor.toFixed(2)} = ${(totalSockelEG * ogFaktor).toFixed(2)}`],
        endsumme: Math.round(totalSockelEG * ogFaktor * 100) / 100, einheit: "lfm", konfidenz: 80 },
    )
  }

  // ═══ ESTRICH ═══
  if (gewerk === "estrich" || gewerk === "allgemein") {
    const prefix = gewerk === "allgemein" ? "ES." : ""
    let totalEstrichEG = 0, totalRandEG = 0, totalNassraumEG = 0
    const berechnungEstrich: string[] = []
    const berechnungRand: string[] = []
    const berechnungNass: string[] = []

    for (const d of dims) {
      totalEstrichEG += d.flaeche
      berechnungEstrich.push(`${d.wohnung} ${d.name}: ${d.flaeche.toFixed(2)} m2`)

      totalRandEG += d.umfang
      berechnungRand.push(`${d.wohnung} ${d.name}: ${d.umfang.toFixed(2)} lfm`)

      if (isNassraum(d.name)) {
        totalNassraumEG += d.flaeche
        berechnungNass.push(`${d.wohnung} ${d.name}: ${d.flaeche.toFixed(2)} m2`)
      }
    }

    const ogFaktor = egWhg > 0 ? (whgProOg / egWhg) * ogFloors : 0

    positionen.push(
      { pos_nr: `${prefix}1`, beschreibung: "Zementestrich EG", gewerk: "Estrich",
        raum_referenz: "Alle Raeume EG", berechnung: berechnungEstrich,
        endsumme: Math.round(totalEstrichEG * 100) / 100, einheit: "m2", konfidenz: 92 },
      { pos_nr: `${prefix}1-OG`, beschreibung: `Zementestrich OG (x${ogFloors})`, gewerk: "Estrich",
        raum_referenz: "Alle Raeume OG", berechnung: [`EG ${totalEstrichEG.toFixed(2)} x ${ogFaktor.toFixed(2)} = ${(totalEstrichEG * ogFaktor).toFixed(2)}`],
        endsumme: Math.round(totalEstrichEG * ogFaktor * 100) / 100, einheit: "m2", konfidenz: 87 },
      { pos_nr: `${prefix}2`, beschreibung: "Randdaemmstreifen EG", gewerk: "Estrich",
        raum_referenz: "Alle Raeume EG", berechnung: berechnungRand,
        endsumme: Math.round(totalRandEG * 100) / 100, einheit: "lfm", konfidenz: 90 },
      { pos_nr: `${prefix}2-OG`, beschreibung: `Randdaemmstreifen OG (x${ogFloors})`, gewerk: "Estrich",
        raum_referenz: "Alle Raeume OG", berechnung: [`EG ${totalRandEG.toFixed(2)} x ${ogFaktor.toFixed(2)} = ${(totalRandEG * ogFaktor).toFixed(2)}`],
        endsumme: Math.round(totalRandEG * ogFaktor * 100) / 100, einheit: "lfm", konfidenz: 85 },
      { pos_nr: `${prefix}3`, beschreibung: "Trittschalldaemmung EG", gewerk: "Estrich",
        raum_referenz: "Alle Raeume EG", berechnung: berechnungEstrich,
        endsumme: Math.round(totalEstrichEG * 100) / 100, einheit: "m2", konfidenz: 92 },
      { pos_nr: `${prefix}3-OG`, beschreibung: `Trittschalldaemmung OG (x${ogFloors})`, gewerk: "Estrich",
        raum_referenz: "Alle Raeume OG", berechnung: [`EG ${totalEstrichEG.toFixed(2)} x ${ogFaktor.toFixed(2)} = ${(totalEstrichEG * ogFaktor).toFixed(2)}`],
        endsumme: Math.round(totalEstrichEG * ogFaktor * 100) / 100, einheit: "m2", konfidenz: 87 },
      { pos_nr: `${prefix}4`, beschreibung: "Dampfsperre Nassraeume EG", gewerk: "Estrich",
        raum_referenz: "Nassraeume EG", berechnung: berechnungNass,
        endsumme: Math.round(totalNassraumEG * 100) / 100, einheit: "m2", konfidenz: 88 },
      { pos_nr: `${prefix}4-OG`, beschreibung: `Dampfsperre Nassraeume OG (x${ogFloors})`, gewerk: "Estrich",
        raum_referenz: "Nassraeume OG", berechnung: [`EG ${totalNassraumEG.toFixed(2)} x ${ogFaktor.toFixed(2)} = ${(totalNassraumEG * ogFaktor).toFixed(2)}`],
        endsumme: Math.round(totalNassraumEG * ogFaktor * 100) / 100, einheit: "m2", konfidenz: 83 },
    )
  }

  // ═══ MAUERWERK ═══
  if (gewerk === "mauerwerk" || gewerk === "allgemein") {
    const prefix = gewerk === "allgemein" ? "MW." : ""
    const aussenWandstaerke = 0.30 // 300mm typical
    let totalInnenEG = 0, totalLeibungEG = 0
    const berechnungInnen: string[] = []
    const berechnungLeibung: string[] = []

    for (const d of dims) {
      const wf = calcWandflaeche(d)
      const oeffnung = openingsForRoom(d.name, d.wohnung)
      const abzugFaktor = calcOENORMAbzug(oeffnung, "mauerwerk")
      const abzug = Math.round(oeffnung * abzugFaktor * 100) / 100
      const netto = Math.round((wf - abzug) * 100) / 100
      totalInnenEG += netto
      berechnungInnen.push(`${d.wohnung} ${d.name}: ${d.umfang.toFixed(2)}x${d.hoehe.toFixed(2)}=${wf.toFixed(2)} -${abzug.toFixed(2)} = ${netto.toFixed(2)} m2`)
    }

    // Leibungen from windows
    for (const f of normalizedFenster) {
      // Leibung = (2 x height + width) x wall thickness
      const leibLfm = 2 * f.al_hoehe_m + f.al_breite_m
      const leibFlaeche = Math.round(leibLfm * aussenWandstaerke * 100) / 100
      totalLeibungEG += leibFlaeche
      berechnungLeibung.push(`${f.bezeichnung || "Fenster"}: (2x${f.al_hoehe_m.toFixed(2)}+${f.al_breite_m.toFixed(2)})x${aussenWandstaerke} = ${leibFlaeche.toFixed(2)} m2`)
    }

    const ogFaktorWand = egWhg > 0 ? (whgProOg / egWhg) * (hOG / hEG) * ogFloors : 0
    const ogFaktorLeibung = egWhg > 0 ? (whgProOg / egWhg) * ogFloors : 0

    // Aussenwand: estimate from building dimensions if available
    const totalFloor = dims.reduce((s, d) => s + d.flaeche, 0)
    const buildingSide = Math.sqrt(totalFloor)
    const aussenWandEG = Math.round(buildingSide * 4 * hEG * 100) / 100

    positionen.push(
      { pos_nr: `${prefix}1`, beschreibung: "Aussenwand EG (Schaetzung)", gewerk: "Mauerwerk",
        raum_referenz: "Gebaeude EG", berechnung: [`Geschaetzt aus Gesamtflaeche: sqrt(${totalFloor.toFixed(1)})x4x${hEG} = ${aussenWandEG.toFixed(2)} m2`],
        endsumme: aussenWandEG, einheit: "m2", konfidenz: 60 },
      { pos_nr: `${prefix}1-OG`, beschreibung: `Aussenwand OG (x${ogFloors})`, gewerk: "Mauerwerk",
        raum_referenz: "Gebaeude OG", berechnung: [`EG ${aussenWandEG.toFixed(2)} x ${hOG/hEG} x ${ogFloors} = ${(aussenWandEG * hOG/hEG * ogFloors).toFixed(2)}`],
        endsumme: Math.round(aussenWandEG * (hOG / hEG) * ogFloors * 100) / 100, einheit: "m2", konfidenz: 55 },
      { pos_nr: `${prefix}2`, beschreibung: "Innenwaende EG", gewerk: "Mauerwerk",
        raum_referenz: "Alle Raeume EG", berechnung: berechnungInnen,
        endsumme: Math.round(totalInnenEG * 100) / 100, einheit: "m2", konfidenz: 85 },
      { pos_nr: `${prefix}2-OG`, beschreibung: `Innenwaende OG (x${ogFloors})`, gewerk: "Mauerwerk",
        raum_referenz: "Alle Raeume OG", berechnung: [`EG ${totalInnenEG.toFixed(2)} x ${ogFaktorWand.toFixed(2)} = ${(totalInnenEG * ogFaktorWand).toFixed(2)}`],
        endsumme: Math.round(totalInnenEG * ogFaktorWand * 100) / 100, einheit: "m2", konfidenz: 80 },
      { pos_nr: `${prefix}3`, beschreibung: "Leibungen EG", gewerk: "Mauerwerk",
        raum_referenz: "Fenster EG", berechnung: berechnungLeibung,
        endsumme: Math.round(totalLeibungEG * 100) / 100, einheit: "m2", konfidenz: 82 },
      { pos_nr: `${prefix}3-OG`, beschreibung: `Leibungen OG (x${ogFloors})`, gewerk: "Mauerwerk",
        raum_referenz: "Fenster OG", berechnung: [`EG ${totalLeibungEG.toFixed(2)} x ${ogFaktorLeibung.toFixed(2)} = ${(totalLeibungEG * ogFaktorLeibung).toFixed(2)}`],
        endsumme: Math.round(totalLeibungEG * ogFaktorLeibung * 100) / 100, einheit: "m2", konfidenz: 77 },
    )
  }

  return positionen
}

// ═══ STEP 1: TEXT-FIRST INTELLIGENT GROUPING ═══

/**
 * Check whether pdf_text has enough data for the text-first approach.
 * We need at least some room_names and some areas OR dimensions.
 */
function hasSufficientPdfText(pdfText: any): boolean {
  if (!pdfText) return false
  const hasRooms = (pdfText.room_names || []).length > 0
  const hasAreas = (pdfText.areas || []).length > 0
  const hasDimensions = (pdfText.dimensions || []).length > 0
  return hasRooms && (hasAreas || hasDimensions)
}

/**
 * TEXT-FIRST Step 1: Send extracted text data (not the PDF image) to Claude for grouping.
 * Claude groups nearby text items into rooms, fenster, tueren based on position proximity.
 */
async function step1TextFirst(apiKey: string, pdfText: any): Promise<any> {
  // Build a compact summary of extracted text for Claude
  const roomNames = (pdfText.room_names || []).map((r: any) => ({
    text: r.text, x: r.x_pct, y: r.y_pct, page: r.page
  }))
  const areas = (pdfText.areas || []).map((a: any) => ({
    text: a.text, value: a.value, x: a.x_pct, y: a.y_pct, page: a.page
  }))
  const dimensions = (pdfText.dimensions || []).map((d: any) => ({
    value_cm: d.value_cm, value_m: d.value_m, x: d.x_pct, y: d.y_pct, page: d.page
  }))
  const fensterCodes = (pdfText.fenster_codes || []).map((f: any) => ({
    text: f.text, x: f.x_pct, y: f.y_pct, page: f.page
  }))

  // Also look for umfang/hoehe/bodenbelag patterns in the raw pages data
  const textSnippets: any[] = []
  for (const page of (pdfText.pages || [])) {
    for (const item of (page.items || [])) {
      const t = (item.str || item.text || "").trim()
      if (!t) continue
      // Match patterns like "U: 20,66 m", "H: 2,42 m", "Parkett", "Fliesen", etc.
      if (/^[UH]:\s*\d/i.test(t) || /umfang|hoehe|parkett|fliesen|laminat|vinyl|teppich|feinsteinzeug/i.test(t) ||
          /^Top\s*\d/i.test(t) || /wohnnutz/i.test(t)) {
        textSnippets.push({
          text: t,
          x: item.x_pct ?? (page.width ? Math.round(item.x / page.width * 1000) / 10 : 0),
          y: item.y_pct ?? (page.height ? Math.round(item.y / page.height * 1000) / 10 : 0),
          page: page.page
        })
      }
    }
  }

  const extractedData = {
    room_names: roomNames,
    areas: areas,
    dimensions: dimensions.slice(0, 200), // limit to avoid token overflow
    fenster_codes: fensterCodes,
    additional_text: textSnippets.slice(0, 200),
    total_items: pdfText.total_items || 0,
  }

  const systemPrompt = `Du bist ein erfahrener Bauingenieur. Du bekommst maschinenlesbare Textdaten, die aus einem Bauplan (PDF) extrahiert wurden. Die Positionen (x_pct, y_pct) sind Prozentwerte relativ zur Seitengroesse.

DEINE AUFGABE: Ordne die extrahierten Texte zu sinnvollen Gruppen:
1. RAEUME: Kombiniere room_name + naechstgelegene area (m2) + naechstgelegenes Umfang-Mass + Hoehe + Bodenbelag. Texte die raeumlich nah beieinander liegen (< 5-8% Abstand) gehoeren zum selben Raum.
2. WOHNUNGEN (Top): Bestimme welche Raeume zu welcher Wohnung gehoeren basierend auf raeumlicher Naehe und Top-Bezeichnungen.
3. FENSTER: Ordne Fenster-Codes (FE_, F_) den naechstgelegenen Raeumen zu.
4. TUEREN: Identifiziere Tuer-Bezeichnungen und ordne sie Raeumen zu.
5. STRUKTUR: Bestimme Massstab, Geschoss, globale Raumhoehe, Gebaeudemasse.

WICHTIG: Die Zahlenwerte aus der Extraktion sind 100% korrekt (maschinenlesbar). Du musst NUR die ZUORDNUNG machen - welcher Text gehoert zu welchem Raum.

Antworte NUR mit validem JSON, KEIN Markdown.`

  const userPrompt = `Hier sind die maschinenlesbar extrahierten Texte aus dem Bauplan:

${JSON.stringify(extractedData, null, 2)}

Gruppiere diese Daten und gib zurueck:
{
  "massstab": "1:100",
  "geschoss": "EG",
  "raumhoehe_global_m": 2.60,
  "anzahl_wohnungen": 4,
  "wohnungen": [
    { "name": "Top 1", "raeume": ["Vorraum", "Wohnkueche", "Bad"], "flaeche_wohnnutz_m2": 55.0 }
  ],
  "wandstaerken_mm": [300, 200, 120],
  "gebaeude_laenge_m": 24.0,
  "gebaeude_tiefe_m": 12.0,
  "raeume": [
    {
      "name": "Wohnkueche",
      "flaeche_m2": 26.37,
      "umfang_m": 20.66,
      "hoehe_m": 2.42,
      "bodenbelag": "Parkett",
      "wohnung": "Top 1",
      "position_pct": [10, 20, 35, 40],
      "konfidenz": 0.98,
      "quelle": "pdf_text"
    }
  ],
  "fenster": [
    {
      "bezeichnung": "FE_31",
      "raum": "Wohnkueche",
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
      "raum": "Wohnkueche",
      "wohnung": "Top 1",
      "breite_mm": 900,
      "hoehe_mm": 2100,
      "typ": "Drehfluegel",
      "konfidenz": 0.85
    }
  ],
  "masse": [
    { "wert_cm": 587, "beschreibung": "Wandabschnitt", "position": "unten" }
  ]
}`

  return await callClaude(apiKey, systemPrompt, [{ type: "text", text: userPrompt }], 16384)
}

/**
 * VISION FALLBACK Step 1: Send the PDF image to Claude (old 4-pass approach collapsed into 1 call).
 * Used only when pdf_text is not available.
 */
async function step1VisionFallback(apiKey: string, pdfSignedUrl: string): Promise<any> {
  const pdfSource = { type: "document", source: { type: "url", url: pdfSignedUrl } }

  const systemPrompt = `Du bist ein erfahrener Bauingenieur. Analysiere diesen Bauplan vollstaendig.
Lies JEDEN Text, JEDE Zahl, JEDES Mass exakt ab. Antworte NUR mit validem JSON, KEIN Markdown.`

  const userPrompt = `Analysiere den gesamten Bauplan und gib zurueck:

1. STRUKTUR: Massstab, Geschoss, Raumhoehe, Wohnungen (Top), Wandstaerken, Gebaeudemasse
2. RAEUME: Fuer JEDEN Raum: Name, Flaeche m2, Umfang m, Hoehe m, Bodenbelag, Wohnung (Top)
3. FENSTER: JEDE Fensterbezeichnung (FE_, F_) mit AL Breite+Hoehe, RB Breite+Hoehe in mm
4. TUEREN: JEDE Tuerbezeichnung mit Breite, Hoehe, Typ
5. MASSKETTEN: ALLE Bemasungszahlen (in cm) mit Position

JSON-Format:
{
  "massstab": "1:100",
  "geschoss": "EG",
  "raumhoehe_global_m": 2.60,
  "anzahl_wohnungen": 4,
  "wohnungen": [
    { "name": "Top 1", "raeume": ["Vorraum", "Wohnkueche", "Bad"], "flaeche_wohnnutz_m2": 55.0 }
  ],
  "wandstaerken_mm": [300, 200, 120],
  "gebaeude_laenge_m": 24.0,
  "gebaeude_tiefe_m": 12.0,
  "raeume": [
    {
      "name": "Wohnkueche",
      "flaeche_m2": 26.37,
      "umfang_m": 20.66,
      "hoehe_m": 2.42,
      "bodenbelag": "Parkett",
      "wohnung": "Top 1",
      "position_pct": [10, 20, 35, 40],
      "konfidenz": 0.90
    }
  ],
  "fenster": [
    {
      "bezeichnung": "FE_31",
      "raum": "Wohnkueche",
      "wohnung": "Top 1",
      "al_breite_mm": 1510,
      "al_hoehe_mm": 1510,
      "rb_breite_mm": 1760,
      "rb_hoehe_mm": 1760,
      "konfidenz": 0.85
    }
  ],
  "tueren": [
    {
      "bezeichnung": "T1",
      "raum": "Wohnkueche",
      "wohnung": "Top 1",
      "breite_mm": 900,
      "hoehe_mm": 2100,
      "typ": "Drehfluegel",
      "konfidenz": 0.80
    }
  ],
  "masse": [
    { "wert_cm": 587, "beschreibung": "Wandabschnitt", "position": "unten" }
  ]
}`

  return await callClaude(apiKey, systemPrompt, [pdfSource, { type: "text", text: userPrompt }], 16384)
}

// ═══ STEP 3: CROSS-VALIDATION HELPERS ═══

/**
 * Cross-validate calculated room dimensions against extracted dimension chain values.
 * Returns validation findings for the quality check.
 */
function crossValidateDimensions(geo: any, pdfText: any): any[] {
  const findings: any[] = []
  if (!pdfText?.dimensions || !geo?.raeume) return findings

  const dims = pdfText.dimensions || []

  for (const room of geo.raeume) {
    if (!room.flaeche_m2 || !room.umfang_m) continue

    const F = room.flaeche_m2
    const U = room.umfang_m
    const halfU = U / 2
    const discriminant = halfU * halfU - 4 * F
    if (discriminant < 0) continue

    const sideA = Math.round(((halfU + Math.sqrt(discriminant)) / 2) * 100) / 100
    const sideB = Math.round(((halfU - Math.sqrt(discriminant)) / 2) * 100) / 100

    // Look for dimension chain values near this room that match calculated sides
    const roomX = room.position_pct?.[0] || 50
    const roomY = room.position_pct?.[1] || 50
    const nearbyDims = dims.filter((d: any) => {
      const dx = Math.abs((d.x_pct || d.x || 50) - roomX)
      const dy = Math.abs((d.y_pct || d.y || 50) - roomY)
      return dx < 15 && dy < 15 // within 15% proximity
    })

    let matchA = false, matchB = false
    for (const d of nearbyDims) {
      const val = d.value_m || (d.value_cm ? d.value_cm / 100 : 0)
      if (Math.abs(val - sideA) < 0.05) matchA = true
      if (Math.abs(val - sideB) < 0.05) matchB = true
    }

    findings.push({
      room: room.name,
      wohnung: room.wohnung,
      calculated_sides: [sideA, sideB],
      nearby_dimensions: nearbyDims.map((d: any) => d.value_m || (d.value_cm ? d.value_cm / 100 : 0)),
      sideA_confirmed: matchA,
      sideB_confirmed: matchB,
      confidence: matchA && matchB ? "high" : (matchA || matchB ? "medium" : "low"),
    })
  }

  return findings
}

/*
 * Step-based orchestrator: Text-First, Math-Based
 *   step=1 -> Intelligent Grouping (text-first if pdf_text available, vision fallback otherwise)
 *   step=2 -> Deterministic Math (calcRoomDimensions, calcMassen, gewerk-specific)
 *   step=3 -> Quality Check with cross-validation against dimension chains
 */
serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders })

  try {
    const { plan_id, step = 1, gewerk = "allgemein", geschosse = 3, whg_pro_og = 4 } = await req.json()
    if (!plan_id) throw new Error("plan_id fehlt")

    const sb = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!)
    const { data: cfg } = await sb.from("app_config").select("value").eq("key", "ANTHROPIC_API_KEY").single()
    if (!cfg?.value) throw new Error("API Key fehlt")

    const { data: plan } = await sb.from("plaene").select("*").eq("id", plan_id).single()
    if (!plan) throw new Error("Plan nicht gefunden")

    // ========== STEP 1: INTELLIGENT GROUPING ==========
    if (step === 1) {
      // Clean old results but PRESERVE pdf_text extraction from frontend
      await sb.from("massen").delete().eq("plan_id", plan_id)
      await sb.from("elemente").delete().eq("plan_id", plan_id)
      const existingLog = plan.agent_log || {}
      const pdfTextData = existingLog.pdf_text || null
      await sb.from("plaene").update({
        verarbeitet: false,
        agent_log: { start: new Date().toISOString(), pdf_text: pdfTextData }
      }).eq("id", plan_id)

      const errors: string[] = []
      let merged: any = {}
      let approach = "unknown"

      // ---- Decide: TEXT-FIRST or VISION FALLBACK ----
      if (hasSufficientPdfText(pdfTextData)) {
        // ═══ TEXT-FIRST APPROACH ═══
        // Send extracted text data as JSON to Claude for intelligent grouping.
        // No PDF image needed - values are 100% accurate from machine-readable extraction.
        approach = "text_first"
        try {
          merged = await step1TextFirst(cfg.value, pdfTextData)
        } catch (e: any) {
          errors.push("TextFirst: " + e.message)
          // If text-first fails, fall back to vision
          approach = "text_first_failed_vision_fallback"
          try {
            const { data: u } = await sb.storage.from("plaene").createSignedUrl(plan.storage_path, 3600)
            if (!u?.signedUrl) throw new Error("PDF URL fehlt")
            merged = await step1VisionFallback(cfg.value, u.signedUrl)
          } catch (e2: any) {
            errors.push("VisionFallback: " + e2.message)
          }
        }
      } else {
        // ═══ VISION FALLBACK ═══
        // No pdf_text available - send the PDF to Claude for visual analysis
        approach = "vision_fallback"
        try {
          const { data: u } = await sb.storage.from("plaene").createSignedUrl(plan.storage_path, 3600)
          if (!u?.signedUrl) throw new Error("PDF URL fehlt")
          merged = await step1VisionFallback(cfg.value, u.signedUrl)
        } catch (e: any) {
          errors.push("Vision: " + e.message)
        }
      }

      // ---- Post-process merged data ----
      // Calculate wandflaeche for each room
      for (const r of (merged.raeume || [])) {
        if (r.umfang_m && r.hoehe_m) {
          r.wandflaeche_m2 = Math.round(r.umfang_m * r.hoehe_m * 100) / 100
        }
        if (!r.flaeche_m2 && r.umfang_m) r.flaeche_m2 = 0
      }

      // Calculate fensterflaeche for each window
      for (const f of (merged.fenster || [])) {
        if (f.al_breite_mm && f.al_hoehe_mm) {
          f.flaeche_m2 = Math.round(f.al_breite_mm * f.al_hoehe_mm / 10000) / 100
        }
      }

      // Ensure masse array exists
      if (!merged.masse) merged.masse = []

      // ---- Store elements in DB ----
      for (const r of (merged.raeume || []))
        await sb.from("elemente").insert({ plan_id, typ: "raum", bezeichnung: r.name || "", daten: r, konfidenz: Math.round((r.konfidenz || 0.5) * 100) })
      for (const f of (merged.fenster || []))
        await sb.from("elemente").insert({ plan_id, typ: "fenster", bezeichnung: f.bezeichnung || "", daten: f, konfidenz: Math.round((f.konfidenz || 0.5) * 100) })
      for (const t of (merged.tueren || []))
        await sb.from("elemente").insert({ plan_id, typ: "tuer", bezeichnung: t.bezeichnung || "", daten: t, konfidenz: Math.round((t.konfidenz || 0.5) * 100) })

      // ---- Update agent_log ----
      const log: any = {
        start: new Date().toISOString(),
        pdf_text: pdfTextData,
        step1: {
          ts: new Date().toISOString(),
          approach: approach,
          r: (merged.raeume || []).length,
          f: (merged.fenster || []).length,
          t: (merged.tueren || []).length,
          masse: (merged.masse || []).length,
          wohnungen: (merged.wohnungen || []).length,
          errors: errors.length > 0 ? errors : undefined,
        },
        geo: merged,
        gewerk: gewerk,
        geschosse: geschosse,
        whg_pro_og: whg_pro_og,
      }
      await sb.from("plaene").update({ agent_log: log }).eq("id", plan_id)

      return new Response(JSON.stringify({
        status: "step1_done",
        next_step: 2,
        approach: approach,
        raeume: (merged.raeume || []).length,
        fenster: (merged.fenster || []).length,
        tueren: (merged.tueren || []).length,
        masse: (merged.masse || []).length,
        wohnungen: (merged.wohnungen || []).length,
        errors: errors.length > 0 ? errors : undefined,
      }), { headers: { ...corsHeaders, "Content-Type": "application/json" } })
    }

    // ========== STEP 2: DETERMINISTIC MATH ==========
    if (step === 2) {
      const geo = plan.agent_log?.geo
      const selectedGewerk = plan.agent_log?.gewerk || gewerk || "allgemein"
      if (!geo) throw new Error("Step 1 zuerst ausfuehren")

      // Build gewerk-specific prompt additions (for Claude fallback only)
      const gewerkPrompts: Record<string, string> = {
        verputzer: `
FOKUS: VERPUTZER / SPACHTELARBEITEN (VP/SR) nach OENORM B 2204

EXAKTE BERECHNUNGSMETHODE eines professionellen Verputzerbetriebs:

=== POSITION: INNENPUTZ WAENDE (m2) ===

Der Verputzer verputzt NUR die WOHNUNGSTRENNWAENDE - das sind die DICKEN Waende
zwischen den Wohnungseinheiten (Top). NICHT die Zimmerwaende innerhalb der Wohnung!

Fuer JEDE Wohnung (Top) berechne:
- WAND 1 (Tiefe): Gebaeudetiefe-Mass x Raumhoehe (z.B. 5.87m x 2.66m = 15.61m2)
- WAND 2 (Breite): Wohnungsbreite x Raumhoehe (z.B. 7.14m x 2.66m = 18.99m2)
- Bei Eckwohnungen: zusaetzliche Waende (3-4 statt 2)

WANDLAENGEN - KRITISCH WICHTIG:
- WAND A = Tiefe EINER Wohnung (NICHT Gebaeudetiefe!)
  In einem Mehrfamilienhaus ist die Wohnungstiefe typisch 5-6m.
  Die Gebaeudetiefe ist 15-20m aber die Trennwand geht nur durch EINE Wohnung!
  Teile die Gebaeudetiefe durch die Anzahl der Wohnungen in der Tiefe!
  Beispiel: Gebaeudetiefe 17.8m / 3 Wohnungen = 5.93m pro Wohnung
- WAND B = Breite der Wohnung (die Querwand)
  ECKWOHNUNGEN (am Ende des Gebaeudes): BREIT! 6-8m (z.B. 7.14m)
  MITTELWOHNUNGEN (in der Mitte): SCHMAL! 3-4m (z.B. 3.27m)
  ACHTUNG: Eckwohnungen haben die BREITERE Querwand, nicht die schmale!

BESONDERHEITEN BEI ECKWOHNUNGEN:
- Eckwohnungen haben MEHR Trennwaende als Mittelwohnungen (3-5 statt 2)
- Sie haben oft BETONZWISCHENWAENDE (Zwischenwand Beton)
- Betonzwischenwaende werden BEIDSEITIG verputzt -> Faktor 2!
  Beispiel: "Zwischenwand Beton: 2 x 6.20 x 1.0 x 2.66 = 32.98"
- Die groesste Eckwohnung kann 50-90 m2 Trennwand-Putzflaeche haben

RAUMHOEHE: Verwende das ROHBAUMASS (Roh-Decke bis Roh-Boden):
- EG: typisch 2.60-2.70m (z.B. 2.66m)
- OG: typisch 2.55-2.65m (z.B. 2.60m)
Das Rohbaumass ist ca. 20-25cm HOEHER als das Fertigmass im Plan!
Wenn im Plan H=2.42m steht -> Rohbaumass ca. 2.42 + 0.24 = 2.66m (EG)

=== POSITION: HAFTGRUND (m2) ===

NUR auf Betonwaenden (Zwischenwand Beton) - NICHT auf Ziegel/Mauerwerk!
Betonwaende brauchen Haftgrund weil Beton glatt und nicht saugend ist.
Berechne: Betonwand-Laenge x Raumhoehe x Anzahl Seiten
Bei Betontrennwaenden: BEIDE Seiten verputzen -> Faktor 2!

=== POSITION: KANTENPROFIL (lfm) ===

Pro Fenster im Innenbereich:
- Fenster Aufrecht (beide Seiten): 2 x Fensterhoehe
  - Normale Fenster: 2 x 1.47m = 2.94 lfm
  - Loggia/Balkontuer: 2 x Raumhoehe (2.60m oder 2.66m)
- Fensterbank: 1 x Fensterbreite
  - Normal: 1.20m
  - Klein (WC/Bad): 0.50m
Loggia-Fenster: 2 x Raumhoehe (KEINE Fensterbank - raumhohe Verglasung)
Zwischenwand Beton: 2 x Raumhoehe (beide Kanten der Betonwand)

=== POSITION: ANPUTZLEISTE (lfm) ===

Pro Fenster: NUR die aufrechten Teile, KEINE Fensterbaenke!
- Fenster Aufrecht: 2 x Fensterhoehe
- Loggia: 2 x Raumhoehe
Gleiche Berechnung wie Kantenprofil MINUS die Fensterbaenke.

=== OENORM B 2204 ABZUGSREGELN ===
- Oeffnungen bis 0.5m2: kein Abzug, Leibungen dazurechnen
- Oeffnungen 0.5-4.0m2 MIT Leibungen: durchgemessen (nicht abziehen)
- Oeffnungen 0.5-4.0m2 OHNE Leibungen: abziehen
- Oeffnungen ueber 4.0m2: abziehen, Leibungen extra addieren

BERECHNUNGSFORMAT: Jede Zeile: Beschreibung | Anz x Laenge x Breite x Hoehe = Zwischensumme`,

        mauerwerk: `
FOKUS: MAUERWERK / ROHBAU
- Aussenwaende: Ansichtsflaechen x Wandstaerke = Volumen m3
- Innenwaende: Wandlaenge x Wandhoehe x Wandstaerke = Volumen m3
- Abzuege: Oeffnungen <0.5m2 kein, 0.5-3m2 halb, >3m2 voll
- Leibungen separat`,

        maler: `
FOKUS: MALER / ANSTRICH
- Wandflaechen pro Raum (Umfang x Hoehe - Oeffnungsabzuege)
- Deckenflaechen pro Raum
- Leibungsflaechen (seitlich, Sturz, Bruestung)
- Grundierung als eigene Position`,

        fliesen: `
FOKUS: FLIESEN / BELAEGE
- Bodenfliesen pro Raum (nur Raeume mit Fliesen)
- Wandfliesen pro Raum (Bad, WC, Kueche - typisch bis 2.10m Hoehe)
- Sockelleisten
- Abzuege: <0.1m2 kein, >=0.1m2 voll`,

        estrich: `
FOKUS: ESTRICH
- Zementestrich pro Raum
- Randdaemmstreifen (Laufmeter Umfang)
- Trittschalldaemmung (gleiche Flaeche)
- Feuchtigkeitssperre (Nassraeume)`,

        trockenbau: `
FOKUS: TROCKENBAU
- Gipskartonwaende (Flaeche, Laufmeter)
- Vorsatzschalen
- Abhangdecken
- Spachtelung und Verfugung`,

        allgemein: `
ALLE GEWERKE berechnen:
01. Mauerwerk/Rohbau (m2, m3)
02. Innenputz (m2, lfm)
03. Aussenputz (m2, lfm)
04. Malerarbeiten (m2)
05. Bodenbelag nach Typ (m2)
06. Estrich (m2)
07. Fensterbaenke (lfm)
08. Leibungen (m2, lfm)`,
      }

      // ═══ VERPUTZER: Deterministic math-based calculation (no Claude!) ═══
      if (selectedGewerk === "verputzer") {
        const geschosseVal = plan.agent_log?.geschosse || geschosse || 3
        const whgProOg = plan.agent_log?.whg_pro_og || whg_pro_og || 4
        const hEG = 2.66  // Rohbaumass EG
        const hOG = 2.60  // Rohbaumass OG
        const ogFloors = geschosseVal - 1

        // Group rooms by apartment from geo data
        const raeume = geo.raeume || []
        const fenster = geo.fenster || []
        const wohnungen: Record<string, any[]> = {}
        for (const r of raeume) {
          const w = (r.wohnung || "Unbekannt").toUpperCase()
          if (!wohnungen[w]) wohnungen[w] = []
          wohnungen[w].push(r)
        }
        const whgNames = Object.keys(wohnungen).filter(w => w.startsWith("TOP"))
        const egWhg = whgNames.length || 3

        // Calculate wall lengths from room area + perimeter
        function calcSides(F: number, U: number): [number, number] | null {
          const half = U / 2
          const d = half * half - 4 * F
          if (d < 0) return null
          return [(half + Math.sqrt(d)) / 2, (half - Math.sqrt(d)) / 2]
        }

        let totalEG = 0
        const berechnungIP: string[] = []
        const berechnungKP: string[] = []
        const berechnungAP: string[] = []
        let totalKP = 0
        let totalAP = 0

        for (const wName of whgNames) {
          const rooms = wohnungen[wName]
          // Find Vorraum (hallway) - gives apartment width
          const vorraum = rooms.find((r: any) => /vorraum|flur|gang|diele/i.test(r.name || ""))
          // Find Wohnkueche (living kitchen) - gives apartment depth
          const wohnkueche = rooms.find((r: any) => /wohnk|kueche|wohn/i.test(r.name || ""))

          let breite = 0, tiefe = 0

          // Calculate from Vorraum
          if (vorraum?.umfang_m && vorraum?.flaeche_m2) {
            const sides = calcSides(vorraum.flaeche_m2, vorraum.umfang_m)
            if (sides) breite = sides[0] // longer side = apartment width
          }

          // Calculate from Wohnkueche
          if (wohnkueche?.umfang_m && wohnkueche?.flaeche_m2) {
            const sides = calcSides(wohnkueche.flaeche_m2, wohnkueche.umfang_m)
            if (sides) {
              // The side ~5.7-5.9m is the depth
              if (sides[0] > 4.5 && sides[0] < 7) tiefe = sides[0]
              else if (sides[1] > 4.5 && sides[1] < 7) tiefe = sides[1]
              else tiefe = sides[0] // fallback
            }
          }

          // For Mittelwohnungen: Vorraum is too small, use Wohnkueche short side as width
          if (breite < 2.5 && wohnkueche?.umfang_m && wohnkueche?.flaeche_m2) {
            const sides = calcSides(wohnkueche.flaeche_m2, wohnkueche.umfang_m)
            if (sides) breite = sides[1] // shorter side = apartment width for middle units
          }

          // Fallback
          if (tiefe === 0) tiefe = 5.87
          if (breite === 0) breite = 5.00

          const wf = (tiefe + breite) * hEG
          totalEG += wf
          berechnungIP.push(`${wName}: Tiefe ${tiefe.toFixed(2)}m + Breite ${breite.toFixed(2)}m x ${hEG}m = ${wf.toFixed(2)} m2`)
        }

        // Fenster: Kantenprofil + Anputzleiste
        for (const f of fenster) {
          let fh_raw = f.al_hoehe_mm || 1470
          let fb_raw = f.al_breite_mm || 1200
          if (fh_raw < 30) fh_raw *= 100
          else if (fh_raw < 300) fh_raw *= 10
          if (fb_raw < 30) fb_raw *= 100
          else if (fb_raw < 300) fb_raw *= 10
          const fh = fh_raw / 1000
          const fb = fb_raw / 1000
          const isLoggia = fh > 2.2
          const kp = isLoggia ? 2 * hEG : 2 * fh + fb
          const ap = isLoggia ? 2 * hEG : 2 * fh
          totalKP += kp
          totalAP += ap
          berechnungKP.push(`${f.bezeichnung || "Fenster"}: ${isLoggia ? "Loggia 2x"+hEG : "2x"+fh.toFixed(2)+"+"+(isLoggia?"":fb.toFixed(2))} = ${kp.toFixed(2)} lfm`)
          berechnungAP.push(`${f.bezeichnung || "Fenster"}: ${isLoggia ? "Loggia 2x"+hEG : "2x"+fh.toFixed(2)} = ${ap.toFixed(2)} lfm`)
        }

        // OG multiplication
        const ipPerWhgEG = egWhg > 0 ? totalEG / egWhg : 0
        const ipPerWhgOG = ipPerWhgEG * (hOG / hEG)
        const totalOG_IP = ipPerWhgOG * whgProOg * ogFloors
        const kpPerWhgEG = egWhg > 0 ? totalKP / egWhg : 0
        const totalOG_KP = kpPerWhgEG * whgProOg * ogFloors
        const apPerWhgEG = egWhg > 0 ? totalAP / egWhg : 0
        const totalOG_AP = apPerWhgEG * whgProOg * ogFloors

        const positionen = [
          {
            pos_nr: "2.3.1", beschreibung: "Haftgrund", gewerk: "Innenputz",
            raum_referenz: "Betonwaende", berechnung: ["Betonwaende visuell nicht eindeutig erkennbar - manuell pruefen"],
            endsumme: 0, einheit: "m2", konfidenz: 50,
          },
          {
            pos_nr: "2.3.2", beschreibung: "Innenputz Waende EG", gewerk: "Innenputz",
            raum_referenz: "Trennwaende EG", berechnung: berechnungIP,
            endsumme: Math.round(totalEG * 100) / 100, einheit: "m2", konfidenz: 95,
          },
          {
            pos_nr: "2.3.2-OG", beschreibung: `Innenputz Waende OG (x${ogFloors} Geschosse)`, gewerk: "Innenputz",
            raum_referenz: "Trennwaende OG", berechnung: [`${egWhg} EG-Whg a ${ipPerWhgEG.toFixed(2)}m2 -> ${whgProOg} OG-Whg a ${ipPerWhgOG.toFixed(2)}m2 x ${ogFloors} Geschosse = ${totalOG_IP.toFixed(2)}m2`],
            endsumme: Math.round(totalOG_IP * 100) / 100, einheit: "m2", konfidenz: 90,
          },
          {
            pos_nr: "2.3.3", beschreibung: "Kantenprofil EG", gewerk: "Innenputz",
            raum_referenz: "Fenster EG", berechnung: berechnungKP,
            endsumme: Math.round(totalKP * 100) / 100, einheit: "lfm", konfidenz: 90,
          },
          {
            pos_nr: "2.3.3-OG", beschreibung: `Kantenprofil OG (x${ogFloors})`, gewerk: "Innenputz",
            raum_referenz: "Fenster OG", berechnung: [`EG ${totalKP.toFixed(2)} x ${(whgProOg/egWhg*ogFloors).toFixed(2)}`],
            endsumme: Math.round(totalOG_KP * 100) / 100, einheit: "lfm", konfidenz: 85,
          },
          {
            pos_nr: "2.3.4", beschreibung: "Anputzleiste EG", gewerk: "Innenputz",
            raum_referenz: "Fenster EG", berechnung: berechnungAP,
            endsumme: Math.round(totalAP * 100) / 100, einheit: "lfm", konfidenz: 90,
          },
          {
            pos_nr: "2.3.4-OG", beschreibung: `Anputzleiste OG (x${ogFloors})`, gewerk: "Innenputz",
            raum_referenz: "Fenster OG", berechnung: [`EG ${totalAP.toFixed(2)} x ${(whgProOg/egWhg*ogFloors).toFixed(2)}`],
            endsumme: Math.round(totalOG_AP * 100) / 100, einheit: "lfm", konfidenz: 85,
          },
        ]

        // Store
        for (const p of positionen) {
          await sb.from("massen").insert({ plan_id, ...p })
        }

        const log = plan.agent_log || {}
        log.step2 = {
          ts: new Date().toISOString(),
          methode: "deterministic_math",
          eg_whg: egWhg, og_floors: ogFloors, whg_pro_og: whgProOg,
          total_ip: Math.round((totalEG + totalOG_IP) * 100) / 100,
          total_kp: Math.round((totalKP + totalOG_KP) * 100) / 100,
          total_ap: Math.round((totalAP + totalOG_AP) * 100) / 100,
        }
        await sb.from("plaene").update({ agent_log: log }).eq("id", plan_id)

        return new Response(JSON.stringify({
          status: "step2_done", next_step: 3, massen: positionen.length,
          methode: "deterministic_math",
          zusammenfassung: {
            innenputz_eg: Math.round(totalEG * 100) / 100,
            innenputz_og: Math.round(totalOG_IP * 100) / 100,
            innenputz_gesamt: Math.round((totalEG + totalOG_IP) * 100) / 100,
            kantenprofil_gesamt: Math.round((totalKP + totalOG_KP) * 100) / 100,
            anputzleiste_gesamt: Math.round((totalAP + totalOG_AP) * 100) / 100,
          },
        }), { headers: { ...corsHeaders, "Content-Type": "application/json" } })
      }

      // ═══ OTHER GEWERKE: Deterministic math engine first, Claude as fallback ═══
      const geschosseVal = plan.agent_log?.geschosse || geschosse || 3
      const whgProOgVal = plan.agent_log?.whg_pro_og || whg_pro_og || 4
      const hEGOther = 2.66  // Rohbaumass EG
      const hOGOther = 2.60  // Rohbaumass OG

      // Supported gewerke for deterministic math
      const mathGewerke = ["maler", "fliesen", "estrich", "mauerwerk", "allgemein"]

      if (mathGewerke.includes(selectedGewerk)) {
        // ═══ DETERMINISTIC MATH for maler/fliesen/estrich/mauerwerk/allgemein ═══
        const mathPositionen = calcMassen(
          geo.raeume || [], geo.fenster || [], geo.tueren || [],
          selectedGewerk, geschosseVal, whgProOgVal, hEGOther, hOGOther
        )

        if (mathPositionen.length > 0) {
          // Store deterministic results
          for (const p of mathPositionen) {
            await sb.from("massen").insert({ plan_id, ...p })
          }

          const log = plan.agent_log || {}
          log.step2 = {
            ts: new Date().toISOString(),
            methode: "deterministic_math",
            gewerk: selectedGewerk,
            pos: mathPositionen.length,
            eg_whg: ([...new Set((geo.raeume || []).map((r: any) => (r.wohnung || "").toUpperCase()))] as string[]).filter(w => w.startsWith("TOP")).length || 1,
            og_floors: geschosseVal - 1,
            whg_pro_og: whgProOgVal,
          }
          await sb.from("plaene").update({ agent_log: log }).eq("id", plan_id)

          return new Response(JSON.stringify({
            status: "step2_done",
            next_step: 3,
            massen: mathPositionen.length,
            methode: "deterministic_math",
            gewerk: selectedGewerk,
          }), { headers: { ...corsHeaders, "Content-Type": "application/json" } })
        }
        // If calcMassen returned empty, fall through to Claude
      }

      // ═══ FALLBACK: Claude-based calculation for unsupported gewerke or empty math results ═══
      const gewerkPrompt = gewerkPrompts[selectedGewerk] || gewerkPrompts.allgemein

      const kalkSystem = `Du bist ein erfahrener oesterreichischer Baukalkulator.

GEWAEHLTES GEWERK: ${selectedGewerk.toUpperCase()}
${gewerkPrompt}

BERECHNUNGSFORMAT: Jeder Schritt: Beschreibung | Anz x L x B x H = Zwischensumme
ROHBAUMASS verwenden (Fertigmass + 0.24m)!
Antworte NUR mit validem JSON.`

      const kalkUser = `Geometriedaten:\n${JSON.stringify(geo)}\n\nErstelle professionelle Massenermittlung.
JSON: {"positionen":[{"pos_nr":"","beschreibung":"","gewerk":"","raum_referenz":"","berechnung":[""],"endsumme":0,"einheit":"","konfidenz":0.9}],"zusammenfassung":{},"gesamt_konfidenz":0.88}`

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
      log.step2 = { ts: new Date().toISOString(), methode: "claude_fallback", gewerk: selectedGewerk, pos: (kalk.positionen||[]).length, zf: kalk.zusammenfassung }
      await sb.from("plaene").update({ agent_log: log }).eq("id", plan_id)

      return new Response(JSON.stringify({
        status: "step2_done",
        next_step: 3,
        massen: (kalk.positionen||[]).length,
        methode: "claude_fallback",
        zusammenfassung: kalk.zusammenfassung || {},
      }), { headers: { ...corsHeaders, "Content-Type": "application/json" } })
    }

    // ========== STEP 3: QUALITY CHECK WITH CROSS-VALIDATION ==========
    if (step === 3) {
      const log = plan.agent_log || {}
      const pdfTextData = log.pdf_text || null
      const geo = log.geo || {}

      // Cross-validate calculated dimensions against extracted dimension chain values
      const dimensionValidation = crossValidateDimensions(geo, pdfTextData)
      const confirmedRooms = dimensionValidation.filter(v => v.confidence === "high").length
      const totalValidated = dimensionValidation.length
      const validationSummary = totalValidated > 0
        ? `Dimension cross-validation: ${confirmedRooms}/${totalValidated} rooms confirmed by dimension chains.`
        : "No dimension chain cross-validation possible (no pdf_text dimensions)."

      // Build validation context for Claude
      const validationContext = dimensionValidation.length > 0
        ? `\n\nDIMENSION CHAIN CROSS-VALIDATION:\n${dimensionValidation.map(v =>
            `${v.wohnung} ${v.room}: sides [${v.calculated_sides.join(", ")}]m, nearby dims [${v.nearby_dimensions.join(", ")}]m -> ${v.confidence} confidence (A:${v.sideA_confirmed}, B:${v.sideB_confirmed})`
          ).join("\n")}`
        : ""

      const kritik = await callClaude(cfg.value,
        `Du bist ein unabhaengiger Pruefingenieur fuer Massenermittlung.

Bewerte die Analyse und Kalkulation:
1. Raumgroessen plausibel? (Wohnzimmer 15-40m2, Bad 5-12m2, WC 1.5-4m2, Vorraum 3-10m2)
2. Berechnungen korrekt? Stimmen die Abzugsregeln?
3. Alles erfasst? Fehlen Raeume, Fenster, Tueren?
4. Sind die Einheiten korrekt? (m2, m, lfm, Stk)
5. Stimmen die Summen?
6. CROSS-VALIDATION: Wenn Dimension-Chain-Daten vorliegen, pruefe ob berechnete Wandlaengen (aus quadratischer Formel) mit den extrahierten Massketten-Werten uebereinstimmen. Uebereinstimmung = hohe Konfidenz. Abweichung = markiere zur Pruefung.

STATUS:
- AKZEPTIERT: Qualitaetsscore >= 75
- NACHBESSERUNG: Qualitaetsscore 50-74
- KRITISCH: Qualitaetsscore < 50

Antworte NUR mit validem JSON, KEIN Markdown.`,
        [{ type: "text", text: `Pruefe diese Ergebnisse:\n${JSON.stringify({ step1: log.step1, step2: log.step2 })}${validationContext}\n\n${validationSummary}\n\nJSON-Format:
{
  "status": "AKZEPTIERT",
  "qualitaets_score": 85,
  "warnungen": ["Warnung 1"],
  "empfehlungen": ["Empfehlung 1"],
  "details": {
    "raeume_plausibel": true,
    "berechnungen_korrekt": true,
    "vollstaendigkeit": true,
    "dimension_chain_match": true
  },
  "dimension_validation": {
    "rooms_confirmed": 0,
    "rooms_total": 0,
    "mismatches": []
  },
  "gesamt_konfidenz": 0.87
}` }])

      const k = Math.round((kritik.gesamt_konfidenz || 0.5) * 100)

      // Delete geo data to save space but keep pdf_text reference
      delete log.geo
      log.step3 = { ts: new Date().toISOString(), ...kritik }
      log.kritik = kritik
      log.dimension_validation = dimensionValidation
      await sb.from("plaene").update({ verarbeitet: true, gesamt_konfidenz: k, agent_log: log }).eq("id", plan_id)

      return new Response(JSON.stringify({
        status: kritik.status || "AKZEPTIERT",
        konfidenz: k,
        qualitaets_score: kritik.qualitaets_score || k,
        warnungen: kritik.warnungen || [],
        empfehlungen: kritik.empfehlungen || [],
        dimension_validation: {
          rooms_confirmed: confirmedRooms,
          rooms_total: totalValidated,
          details: dimensionValidation,
        },
      }), { headers: { ...corsHeaders, "Content-Type": "application/json" } })
    }

    throw new Error("step muss 1, 2 oder 3 sein")
  } catch (e: any) {
    return new Response(JSON.stringify({ error: e.message }), { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } })
  }
})
