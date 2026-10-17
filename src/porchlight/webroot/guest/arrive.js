/* Loaded synchronously in <head> so the listener exists before the first render.
   Cross-document view transitions (preview landing page -> screen, the nightly
   self-refresh) hand the new document a transition on arrival; record it so a TV
   can be checked for the crossfade with document.documentElement.dataset.arrived. */
(() => {
  "use strict";
  window.addEventListener("pagereveal", (event) => {
    document.documentElement.dataset.arrived = event.viewTransition ? "transition" : "plain";
  });
})();
