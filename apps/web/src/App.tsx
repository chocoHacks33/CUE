import { ProducerPage } from "./producer/ProducerPage";
import { PublisherPage } from "./publisher/PublisherPage";

/**
 * Stage 0 routing. `/` is A's Windows publisher. `/producer` (or `#/producer`
 * where a static host has no SPA fallback) is D's Mac receiver.
 */
function isProducerRoute(): boolean {
  const { pathname, hash } = window.location;
  return pathname.replace(/\/+$/, "") === "/producer" || hash === "#/producer";
}

export default function App() {
  return isProducerRoute() ? <ProducerPage /> : <PublisherPage />;
}
