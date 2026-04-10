/**
 * KI-Massenermittlung - WebSocket Fortschritt (Progress)
 */

(function () {
  'use strict';

  var progressSection = document.getElementById('progress-section');
  var analysisBar = document.getElementById('analysis-bar');
  var progressStatus = document.getElementById('progress-status');
  var agentCircles = {
    parser: document.getElementById('agent-parser'),
    geometrie: document.getElementById('agent-geometrie'),
    kalkulation: document.getElementById('agent-kalkulation'),
    kritik: document.getElementById('agent-kritik'),
    lern: document.getElementById('agent-lern')
  };

  var ws = null;

  // --- Agent name mapping ---
  var agentNameMap = {
    'parser': 'parser',
    'pdf_parser': 'parser',
    'geometrie': 'geometrie',
    'geometry': 'geometrie',
    'kalkulation': 'kalkulation',
    'calculation': 'kalkulation',
    'kritik': 'kritik',
    'critic': 'kritik',
    'review': 'kritik',
    'lern': 'lern',
    'learn': 'lern',
    'learning': 'lern'
  };

  function resolveAgentKey(name) {
    if (!name) return null;
    var lower = name.toLowerCase().replace(/[_-]/g, '_');
    return agentNameMap[lower] || null;
  }

  // --- Reset Agent Circles ---
  function resetAgents() {
    Object.keys(agentCircles).forEach(function (key) {
      var el = agentCircles[key];
      if (el) {
        el.classList.remove('active', 'done', 'error');
      }
    });
  }

  // --- Set Agent State ---
  function setAgentState(agentKey, state) {
    var resolved = resolveAgentKey(agentKey);
    if (!resolved || !agentCircles[resolved]) return;

    var el = agentCircles[resolved];
    el.classList.remove('active', 'done', 'error');

    if (state === 'active' || state === 'running') {
      el.classList.add('active');
    } else if (state === 'done' || state === 'finished' || state === 'completed') {
      el.classList.add('done');
    } else if (state === 'error' || state === 'failed') {
      el.classList.add('error');
    }
  }

  // --- Update Progress Bar ---
  function setProgress(pct) {
    var val = Math.max(0, Math.min(100, Math.round(pct)));
    analysisBar.style.width = val + '%';
    analysisBar.textContent = val + '%';

    if (val >= 100) {
      analysisBar.classList.remove('animated');
    } else {
      analysisBar.classList.add('animated');
    }
  }

  // --- Set Status Text ---
  function setStatusText(text) {
    progressStatus.textContent = text || '';
  }

  // --- Start Progress Tracking ---
  function startProgress(planId) {
    // Show progress section
    progressSection.classList.remove('hidden');
    resetAgents();
    setProgress(0);
    setStatusText('Analyse wird vorbereitet...');

    // Scroll to progress section
    progressSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

    // Close existing WebSocket
    if (ws) {
      try { ws.close(); } catch (e) { /* ignore */ }
    }

    // Determine WebSocket URL
    var protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    var host = window.location.host;
    var wsUrl = protocol + '//' + host + '/ws/' + planId;

    // Add token as query param for auth
    var token = localStorage.getItem('token');
    if (token) {
      wsUrl += '?token=' + encodeURIComponent(token);
    }

    ws = new WebSocket(wsUrl);

    ws.addEventListener('open', function () {
      console.log('WebSocket verbunden für Plan:', planId);
    });

    ws.addEventListener('message', function (event) {
      try {
        var data = JSON.parse(event.data);
        handleProgressMessage(data, planId);
      } catch (e) {
        console.warn('Ungültige WebSocket-Nachricht:', event.data);
      }
    });

    ws.addEventListener('close', function () {
      console.log('WebSocket geschlossen');
    });

    ws.addEventListener('error', function (err) {
      console.error('WebSocket Fehler:', err);
      setStatusText('Verbindungsfehler - bitte Seite neu laden');
    });
  }

  // Track which agents have been seen so we can mark previous ones as done
  var agentOrder = ['lern', 'parser', 'geometrie', 'kalkulation', 'kritik'];
  var lastAgentIndex = -1;

  // --- Handle Progress Message ---
  function handleProgressMessage(data, planId) {
    // Orchestrator sends: { typ, schritt, fortschritt, details, iteration }
    // Also handle: { typ: "fehler", details: "..." }

    // Update progress bar
    var pct = data.fortschritt !== undefined ? data.fortschritt : data.progress;
    if (pct !== undefined) {
      setProgress(pct);
    }

    // Update status text
    var statusText = data.details || data.message || data.status || '';
    if (statusText) {
      setStatusText(statusText);
    }

    // Update agent states based on "schritt" field
    var schritt = data.schritt || data.agent || '';
    if (schritt) {
      // Extract agent key from schritt (e.g. "parser_agent" -> "parser")
      var agentKey = schritt.replace('_agent', '');
      var idx = agentOrder.indexOf(agentKey);

      if (idx >= 0) {
        // Mark all previous agents as done
        for (var i = 0; i <= lastAgentIndex; i++) {
          setAgentState(agentOrder[i], 'done');
        }
        // Mark current agent as active
        setAgentState(agentKey, 'active');
        lastAgentIndex = idx;
      }
    }

    // Check for completion
    var isComplete = data.schritt === 'abgeschlossen' || data.typ === 'abgeschlossen' ||
      (pct !== undefined && pct >= 100);

    if (isComplete) {
      setProgress(100);
      setStatusText(statusText || 'Analyse abgeschlossen!');

      // Mark all agents as done
      Object.keys(agentCircles).forEach(function (key) {
        var el = agentCircles[key];
        if (el && !el.classList.contains('error')) {
          el.classList.remove('active');
          el.classList.add('done');
        }
      });

      // Close WebSocket
      if (ws) {
        try { ws.close(); } catch (e) { /* ignore */ }
      }

      // Trigger result loading
      setTimeout(function () {
        if (typeof window.loadResults === 'function') {
          window.loadResults(planId);
        }
        if (typeof window.loadPlans === 'function') {
          window.loadPlans();
        }
      }, 500);
    }

    // Check for error
    if (data.typ === 'fehler' || data.status === 'fehler' || data.status === 'error') {
      setStatusText('Fehler: ' + (data.details || data.message || 'Unbekannter Fehler'));
      analysisBar.classList.remove('animated');
    }
  }

  // Expose globally
  window.startProgress = startProgress;
})();
