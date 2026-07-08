/**
 * format.js — Date / time formatting helpers for the Pivot App.
 *
 * The user has asked for every date/time in the app to be shown
 * in IST (Indian Standard Time, UTC+5:30).  The server stores all
 * timestamps in UTC and converts to the configured timezone at the
 * display boundary — the frontend receives IST-formatted ISO-8601
 * strings and human-readable strings from the API, but it still
 * needs a consistent formatter for any `Date` it constructs
 * client-side (e.g. the AG Grid export header, the draft-recovery
 * "last saved" label).
 *
 * The app is configured for IST by default (timezone = "Asia/Kolkata"
 * in the singleton `app_settings` row); this formatter uses the
 * same default so every visible timestamp in the UI is in IST.
 *
 * API
 * ---
 *   `formatIst(input, opts?)`        → human-readable string, e.g.
 *                                      "08 Jul 2026, 14:30:25 IST"
 *   `formatIstShort(input)`           → "08 Jul 2026, 14:30"
 *   `formatIstDate(input)`            → "08 Jul 2026"
 *
 * `input` can be a `Date`, an ISO-8601 string, a number (epoch
 * millis), or `null` / `undefined`.  An invalid input returns `""`.
 *
 * Why pass `timeZone: "Asia/Kolkata"` to `toLocaleString`?
 * ------------------------------------------------------------
 * `Date.toLocaleString()` uses the runtime's local timezone by
 * default, which is the user's OS locale — that can be UTC, America/
 * Los_Angeles, anything.  Forcing the timezone to `Asia/Kolkata`
 * means every user sees the same IST timestamp regardless of where
 * they happen to be.
 */
(function () {
  "use strict";

  // The IST / Asia-Kolkata timezone id, which `Intl.DateTimeFormat`
  // understands on every modern browser (no system-tzdata needed).
  var IST_TZ = "Asia/Kolkata";

  // We pre-build a single formatter for each of our common formats
  // so we don't pay the `Intl.DateTimeFormat` construction cost on
  // every call (the log viewer + email history can be hundreds of
  // rows).
  var fmtFull  = new Intl.DateTimeFormat("en-GB", {
    timeZone: IST_TZ,
    year:     "numeric",
    month:    "short",
    day:      "2-digit",
    hour:     "2-digit",
    minute:   "2-digit",
    second:   "2-digit",
    hour12:   false,
  });
  var fmtShort = new Intl.DateTimeFormat("en-GB", {
    timeZone: IST_TZ,
    year:     "numeric",
    month:    "short",
    day:      "2-digit",
    hour:     "2-digit",
    minute:   "2-digit",
    hour12:   false,
  });
  var fmtDate  = new Intl.DateTimeFormat("en-GB", {
    timeZone: IST_TZ,
    year:     "numeric",
    month:    "short",
    day:      "2-digit",
  });

  function _toDate(input) {
    if (input == null) return null;
    if (input instanceof Date) {
      return isNaN(input.getTime()) ? null : input;
    }
    if (typeof input === "number") {
      var d = new Date(input);
      return isNaN(d.getTime()) ? null : d;
    }
    if (typeof input === "string") {
      // Empty string / whitespace → no date.
      var s = input.trim();
      if (!s) return null;
      // Backend timestamps arrive as ISO-8601 in IST (with the
      // "IST" suffix or "+05:30" offset) — `new Date(...)` parses
      // both.  Naive UTC ISO strings (no tz suffix) are treated as
      // UTC for backward compatibility with the older endpoints
      // that haven't been migrated yet.
      var d2;
      if (/[zZ]$|[+\-]\d{2}:?\d{2}$/.test(s)) {
        d2 = new Date(s);
      } else {
        // Assume the naive string is UTC (e.g. "2026-07-08T12:00:00").
        d2 = new Date(s + "Z");
      }
      return isNaN(d2.getTime()) ? null : d2;
    }
    return null;
  }

  function formatIst(input) {
    var d = _toDate(input);
    if (!d) return "";
    // "08 Jul 2026, 14:30:25" → append the timezone label so the
    // user is never confused about which tz the timestamp is in.
    return fmtFull.format(d) + " IST";
  }

  function formatIstShort(input) {
    var d = _toDate(input);
    if (!d) return "";
    return fmtShort.format(d) + " IST";
  }

  function formatIstDate(input) {
    var d = _toDate(input);
    if (!d) return "";
    return fmtDate.format(d);
  }

  // Expose both the bare formatter and the convenience wrappers.
  // Other modules (logs.js, audit.js, settings.js, email-history.js,
  // diagnostics.js, pivot.js) call `formatIst(...)` via the
  // `window.AppFormat` namespace.
  window.AppFormat = {
    ist:          formatIst,
    istShort:     formatIstShort,
    istDate:      formatIstDate,
    timezone:     IST_TZ,
  };
})();
