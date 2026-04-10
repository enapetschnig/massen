/**
 * Supabase-Konfiguration - wird von allen JS-Dateien verwendet.
 * Supabase JS wird via CDN geladen.
 */

var SUPABASE_URL = 'https://ndojdrjwfelykpycrdjh.supabase.co';
var SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5kb2pkcmp3ZmVseWtweWNyZGpoIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzU4MzUwNjQsImV4cCI6MjA5MTQxMTA2NH0.F72kzWQrHcSn5ckzdV16pJisvvsUvVH4pw9qM1jSt0Y';

var _sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

/**
 * RPC call helper - calls Supabase database functions.
 */
async function sbRpc(fnName, params) {
  var result = await _sb.rpc(fnName, params);
  if (result.error) throw new Error(result.error.message);
  return result.data;
}

/**
 * Simple session management using localStorage.
 * We store firma data after login/register.
 */
function getSession() {
  try {
    return JSON.parse(localStorage.getItem('firma') || 'null');
  } catch (e) {
    return null;
  }
}

function setSession(firma) {
  localStorage.setItem('firma', JSON.stringify(firma));
}

function clearSession() {
  localStorage.removeItem('firma');
}

function requireAuth() {
  if (!getSession()) {
    window.location.href = 'index.html';
    return null;
  }
  return getSession();
}
