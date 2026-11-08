// Typed channel for stat-card → result-section navigation. The app's hash is
// its router, so anchors must never go through location.hash: the producer
// dispatches, WebResult switches its internal panel when the target lives
// behind one, then the section is scrolled into view and focused.

export const GOTO_SECTION_EVENT = "reachscope:goto-section";

declare global {
  interface WindowEventMap {
    [GOTO_SECTION_EVENT]: CustomEvent<string>;
  }
}

// Stat cards only navigate to blocks that actually exist in the same tab;
// keys without a matching block stay non-interactive (no fake jumps).
export const statTargets: Record<string, Record<string, string>> = {
  web: {
    assets: "result-section-assets",
    checks: "result-section-checks",
    review_checks: "result-section-checks",
    paths: "result-section-paths",
    observations: "result-section-observations",
  },
  android: {
    observations: "result-section-observations",
  },
};

export function gotoSection(id: string) {
  window.dispatchEvent(new CustomEvent(GOTO_SECTION_EVENT, { detail: id }));
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      const section = document.getElementById(id);
      if (!section) return;
      section.scrollIntoView({ block: "start" });
      section.focus({ preventScroll: true });
    });
  });
}
