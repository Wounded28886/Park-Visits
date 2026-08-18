/**
 * Recovery for cards that finish loading after the dashboard has rendered.
 *
 * Home Assistant builds a view by looking up each card's custom element. If
 * ours hasn't loaded yet — which happens on slow devices, where the browser
 * is still fetching a large frontend bundle and a pile of other resources —
 * it substitutes an error card reading "Custom element doesn't exist".
 *
 * Newer frontends re-check via customElements.whenDefined() and repair
 * themselves. The legacy ES5 bundle, which Home Assistant serves to older
 * browsers (a Samsung Family Hub reporting Chrome 108, for instance, since
 * HA wants 109+), does not reliably do that, so the error is permanent even
 * though the card is now perfectly usable.
 *
 * So once a card module has loaded, it calls in here to tell Home Assistant
 * to rebuild: `ll-rebuild` is HA's own "construct this card again" event,
 * and by the time it's handled the element exists.
 *
 * Shared by both cards, and safe to import twice — the work is idempotent
 * and rebuilding a card that was fine anyway is a no-op.
 */

/* Error cards live deep inside nested shadow roots, so an ordinary
   querySelectorAll can't see them. Depth is capped because a dashboard can
   nest a long way and this runs on the slowest device in the house. */
function findErrorCards(root, depth, seen, found) {
  if (!root || depth > 12 || seen.has(root)) return found;
  seen.add(root);

  let nodes;
  try {
    nodes = root.querySelectorAll("*");
  } catch (err) {
    return found;
  }

  for (const node of nodes) {
    const tag = node.tagName ? node.tagName.toLowerCase() : "";
    if (tag === "hui-error-card") found.push(node);
    if (node.shadowRoot) findErrorCards(node.shadowRoot, depth + 1, seen, found);
  }
  return found;
}

/** Tell Home Assistant to rebuild every card it gave up on. */
export function rebuildErrorCards() {
  const found = findErrorCards(document, 0, new Set(), []);
  for (const card of found) {
    // Bubbles and crosses shadow boundaries so it reaches the hui-card that
    // owns this placeholder — that's the element which does the rebuilding.
    card.dispatchEvent(new Event("ll-rebuild", { bubbles: true, composed: true }));
  }
  return found.length;
}

/**
 * Nudge Home Assistant a few times after this module loads.
 *
 * One attempt isn't enough: the module can land before the dashboard has
 * rendered anything (nothing to repair yet) or well after (repair needed
 * immediately), and which of those happens depends on how slow the device
 * is. A handful of tries a few seconds apart covers both without polling
 * forever — on a healthy dashboard every one of them finds nothing and
 * costs a single DOM walk.
 */
export function scheduleRebuild() {
  if (window.__parkVisitsRebuildScheduled) return;
  window.__parkVisitsRebuildScheduled = true;

  for (const delay of [0, 500, 1500, 4000, 10000]) {
    setTimeout(() => {
      try {
        rebuildErrorCards();
      } catch (err) {
        /* Never let recovery break the page it is trying to repair. */
      }
    }, delay);
  }
}
