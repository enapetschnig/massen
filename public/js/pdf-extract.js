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

        // Area values (contain m² or m2)
        if (/m[²2]/.test(text) || /\d+[.,]\d+\s*m/.test(text)) {
          var areaMatch = text.match(/(\d+[.,]\d+)/);
          if (areaMatch) {
            result.areas.push({
              text: text,
              value: parseFloat(areaMatch[1].replace(',', '.')),
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
