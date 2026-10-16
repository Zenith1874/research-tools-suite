/* Shared, first-party behavior metrics. No input text, cookies or fingerprints. */
(function () {
  'use strict';
  if (window.ZRAnalyticsBehavior) return;

  window.ZRAnalyticsBehavior = {
    start: function (send) {
      if (navigator.doNotTrack === '1' || window.doNotTrack === '1' ||
          navigator.globalPrivacyControl === true) return;
      if (window.ZRAnalyticsBehavior.started) return;
      window.ZRAnalyticsBehavior.started = true;
      var pageId = window.crypto && window.crypto.randomUUID
        ? window.crypto.randomUUID() : Date.now() + '-' + Math.random().toString(36).slice(2);
      var milestones = [15, 30, 60, 180, 600, 1800];
      var elapsed = 0, visibleSince = null, timer = null, lastSent = 0;
      var depths = {}, nextMilestone = 0, stopped = false;
      var now = function () { return performance.now(); };

      function seconds() {
        return Math.min(86400, Math.floor((elapsed +
          (visibleSince === null ? 0 : Math.max(0, now() - visibleSince))) / 1000));
      }
      function flush() {
        var value = seconds();
        if (value <= lastSent) return;
        lastSent = value;
        send('engagement', '', {page_id: pageId, dwell_seconds: value});
      }
      function schedule() {
        clearTimeout(timer);
        var value = seconds();
        while (nextMilestone < milestones.length && milestones[nextMilestone] <= value)
          nextMilestone++;
        if (visibleSince === null || nextMilestone === milestones.length) return;
        timer = setTimeout(function () { flush(); schedule(); },
          Math.max(100, (milestones[nextMilestone] - value) * 1000));
      }
      function pause() {
        if (visibleSince !== null) {
          elapsed += Math.max(0, now() - visibleSince);
          visibleSince = null;
        }
        clearTimeout(timer);
        flush();
      }
      function resume() {
        if (document.visibilityState === 'hidden' || stopped || visibleSince !== null) return;
        visibleSince = now();
        schedule();
      }
      document.addEventListener('visibilitychange', function () {
        if (document.visibilityState === 'hidden') pause();
        else resume();
      });
      window.addEventListener('pagehide', function () { stopped = true; pause(); });
      window.addEventListener('pageshow', function () { stopped = false; resume(); });
      window.addEventListener('scroll', function (event) {
        if (event.isTrusted === false || document.visibilityState === 'hidden') return;
        var height = Math.max(document.documentElement.scrollHeight,
          document.body ? document.body.scrollHeight : 0);
        // A short page or initial viewport is not evidence of scrolling.
        if (height <= window.innerHeight || window.scrollY <= 0) return;
        var percent = (window.scrollY + window.innerHeight) / height * 100;
        [25, 50, 75, 90].forEach(function (depth) {
          if (!depths[depth] && percent >= depth) {
            depths[depth] = true;
            send('scroll_depth', String(depth));
          }
        });
      }, {passive: true});
      resume();
    }
  };
})();
