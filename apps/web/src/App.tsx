import { ProducerPage } from "./producer/ProducerPage";
import { PublisherPage } from "./publisher/PublisherPage";
import { RecorderPage } from "./recording/RecorderPage";

/**
 * Routing without a router library. Path first, hash as a fallback for static
 * hosts with no SPA rewrite.
 *
 *   /            A's Windows publisher
 *   /producer    D's Mac receiver
 *   /recorder    local recording test for any laptop (Stage 1, Test 1)
 */
function currentRoute(): "publisher" | "producer" | "recorder" {
  const { pathname, hash } = window.location;
  const path = pathname.replace(/\/+$/, "");
  if (path === "/producer" || hash === "#/producer") return "producer";
  if (path === "/recorder" || hash === "#/recorder") return "recorder";
  return "publisher";
}

export default function App() {
  switch (currentRoute()) {
    case "producer":
      return <ProducerPage />;
    case "recorder":
      return <RecorderPage />;
    default:
      return <PublisherPage />;
  }
}
