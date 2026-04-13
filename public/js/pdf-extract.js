/**
 * PDF Text Extraction - extracts all text with exact positions using pdf.js
 * This gives us machine-readable dimension values (Maßketten) from the PDF.
 */
(function() {
  'use strict';

  // Extract all text items with positions from a PDF
  window.extractPdfText = async function(pdfUrl) {
    // Load pdf.js if not already loaded
    if (!window.pdfjsLib) {
      await new Promise(resolve => {
        var s = document.createElement('script');
        s.src = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js';
        s.onload = () => {
          pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
          resolve();
        };
        document.head.appendChild(s);
      });
    }

    var pdf = await pdfjsLib.getDocument(pdfUrl).promise;
    var allPages = [];

    for (var i = 1; i <= Math.min(pdf.numPages, 5); i++) {
      var page = await pdf.getPage(i);
      var viewport = page.getViewport({ scale: 1.0 });
      var textContent = await page.getTextContent();

      var pageWidth = viewport.width;
      var pageHeight = viewport.height;

      var items = textContent.items.map(function(item) {
        var tx = item.transform;  // [scaleX, skewX, skewY, scaleY, translateX, translateY]
        return {
          text: item.str,
          x: tx[4],
          y: pageHeight - tx[5],  // PDF y is bottom-up, we want top-down
          width: item.width,
          height: item.height || Math.abs(tx[3]),
          x_pct: Math.round(tx[4] / pageWidth * 1000) / 10,
          y_pct: Math.round((pageHeight - tx[5]) / pageHeight * 1000) / 10,
        };
      }).filter(function(item) { return item.text.trim().length > 0; });

      allPages.push({
        page: i,
        width: pageWidth,
        height: pageHeight,
        items: items,
      });
    }

    // Extract structured data
    var result = {
      pages: allPages,
      dimensions: [],   // Maßketten values (3-4 digit numbers = cm)
      areas: [],         // m² values
      room_names: [],    // Room name texts
      fenster_codes: [], // FE_ codes
      total_items: allPages.reduce(function(s, p) { return s + p.items.length; }, 0),
    };

    // Process all text items
    allPages.forEach(function(page) {
      // FIRST PASS: Find all number-with-comma values (potential area values like "26,37")
      // and check if a nearby text item looks like "m²" or "m2"
      var numberItems = [];
      page.items.forEach(function(item) {
        var text = item.text.trim();
        // Match numbers like 26,37 or 155,73 or 8,50
        var numMatch = text.match(/^(\d{1,3}[.,]\d{1,2})$/);
        if (numMatch) {
          numberItems.push({
            value: parseFloat(numMatch[1].replace(',', '.')),
            text: text,
            x: item.x, y: item.y, x_pct: item.x_pct, y_pct: item.y_pct,
            width: item.width, page: page.page
          });
        }
      });

      // For each number, check if a nearby item (within ~2% horizontal) contains "m" or looks like a unit
      numberItems.forEach(function(num) {
        // Check nearby items for "m²", "m2", "m" unit markers
        var isArea = false;
        page.items.forEach(function(other) {
          if (Math.abs(other.y_pct - num.y_pct) < 2 && other.x_pct > num.x_pct && other.x_pct - num.x_pct < 5) {
            var ot = other.text.trim().toLowerCase();
            if (ot === 'm²' || ot === 'm2' || ot.includes('m²') || ot.includes('m2')) {
              isArea = true;
            }
          }
        });

        // Also: values between 1-200 with one decimal that are NOT dimensions → likely areas
        if (!isArea && num.value >= 1 && num.value <= 200) {
          // Heuristic: if the number has exactly X,XX format and is in the "room area" of the plan
          // (roughly y: 10-70% of the page), it's likely an area
          if (num.y_pct > 8 && num.y_pct < 75 && num.text.includes(',')) {
            isArea = true;
          }
        }

        if (isArea) {
          result.areas.push({
            text: num.text + ' m²',
            value: num.value,
            x_pct: num.x_pct,
            y_pct: num.y_pct,
            page: num.page,
          });
        }
      });

      page.items.forEach(function(item) {
        var text = item.text.trim();

        // Dimension values (3-4 digit numbers = centimeters)
        var dimMatch = text.match(/^(\d{3,4})$/);
        if (dimMatch) {
          var val = parseInt(dimMatch[1]) / 100;
          if (val > 0.5 && val < 25) {
            result.dimensions.push({
              value_cm: parseInt(dimMatch[1]),
              value_m: Math.round(val * 100) / 100,
              x_pct: item.x_pct,
              y_pct: item.y_pct,
              page: page.page,
            });
          }
        }

        // Area values - also catch standalone "XX,XX m²" in one text
        if (/m[²2]/.test(text) || /\d+[.,]\d+\s*m/.test(text)) {
          var areaMatch = text.match(/(\d+[.,]\d+)/);
          if (areaMatch) {
            // Don't add if already found by the number-proximity method
            var val = parseFloat(areaMatch[1].replace(',', '.'));
            var alreadyFound = result.areas.some(function(a) { return Math.abs(a.value - val) < 0.01 && Math.abs(a.x_pct - item.x_pct) < 2; });
            if (!alreadyFound) {
              result.areas.push({
                text: text,
                value: val,
                x_pct: item.x_pct,
                y_pct: item.y_pct,
                page: page.page,
            });
          }
        }

        // Room names
        var roomNames = ['Wohnküche', 'Wohnk', 'Zimmer', 'Bad', 'WC', 'Vorraum', 'Flur',
                         'Gang', 'Küche', 'Loggia', 'Balkon', 'Terrasse', 'Stiegenhaus',
                         'Abstellraum', 'AR', 'Garderobe', 'Speis'];
        for (var rn of roomNames) {
          if (text.toLowerCase().includes(rn.toLowerCase())) {
            result.room_names.push({
              text: text,
              x_pct: item.x_pct,
              y_pct: item.y_pct,
              page: page.page,
            });
            break;
          }
        }

        // Fenster codes
        if (/FE[_\s-]?\d/i.test(text)) {
          result.fenster_codes.push({
            text: text,
            x_pct: item.x_pct,
            y_pct: item.y_pct,
            page: page.page,
          });
        }
      });
    });

    return result;
  };
})();
