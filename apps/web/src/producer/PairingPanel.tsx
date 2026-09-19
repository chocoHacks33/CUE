import {
  CAMERA_CONTRACTS,
  CAMERA_IDS,
  type CameraBinding,
  type CameraId,
  type PairingGrantResponse,
  type ProducerPairingClaimResponse,
} from "@cue/contracts";
import { useCallback, useEffect, useRef, useState } from "react";

import { createPairingGrant, decidePairingClaim, listCameraBindings, listPairingClaims } from "./pairingApi";
import { bindingForCamera, claimIsLive, claimNeedsDecision, formatExpiry, sortClaims } from "./pairingView";

export interface PairingPanelProps {
  apiBaseUrl: string;
  eventId: string;
  /** Entered once on the producer page; never stored, never sent to publishers. */
  producerSecret: string;
  /** Called with a one-line message for the receiver log. */
  onLog: (line: string) => void;
}

const POLL_MS = 2000;

/**
 * Stage 1 producer pairing (A's admission flow, D's UI). The producer secret is
 * typed here, kept in component state only, and sent as a header to producer
 * endpoints. It never appears in a pairing token, URL or publisher form.
 */
export function PairingPanel({ apiBaseUrl, eventId, producerSecret, onLog }: PairingPanelProps) {
  const [grants, setGrants] = useState<Partial<Record<CameraId, PairingGrantResponse>>>({});
  const [claims, setClaims] = useState<ProducerPairingClaimResponse[]>([]);
  const [bindings, setBindings] = useState<CameraBinding[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("Enter the producer secret in the session panel to mint pairing tokens.");
  const [polling, setPolling] = useState(false);
  const lastSeenRef = useRef<Map<string, string>>(new Map());

  const secret = producerSecret.trim();
  const ready = secret.length > 0 && eventId.length > 0;

  const refresh = useCallback(async () => {
    if (!ready) return;
    try {
      const [nextClaims, nextBindings] = await Promise.all([
        listPairingClaims(apiBaseUrl, secret, eventId),
        listCameraBindings(apiBaseUrl, secret, eventId),
      ]);
      for (const claim of nextClaims) {
        const before = lastSeenRef.current.get(claim.claimId);
        if (before !== claim.status) {
          lastSeenRef.current.set(claim.claimId, claim.status);
          if (before === undefined && claim.status === "PENDING") {
            onLog(
              `Pairing claim for ${claim.camera.cameraId} from "${claim.deviceLabel}" (${claim.displayName}); code ${claim.verificationCode}. Verify the physical laptop, then approve.`,
            );
          } else if (before !== undefined) {
            onLog(`Pairing claim ${claim.camera.cameraId}: ${before} -> ${claim.status}`);
          }
        }
      }
      setClaims(sortClaims(nextClaims));
      setBindings(nextBindings);
      setPolling(true);
    } catch (error) {
      setPolling(false);
      setMessage(error instanceof Error ? error.message : "Could not read pairing state.");
    }
  }, [apiBaseUrl, eventId, onLog, ready, secret]);

  useEffect(() => {
    if (!ready) {
      setPolling(false);
      return;
    }
    void refresh();
    const id = window.setInterval(() => void refresh(), POLL_MS);
    return () => window.clearInterval(id);
  }, [ready, refresh]);

  async function mint(cameraId: CameraId) {
    if (!ready) return;
    setBusy(`mint-${cameraId}`);
    try {
      const grant = await createPairingGrant(apiBaseUrl, secret, eventId, cameraId);
      setGrants((previous) => ({ ...previous, [cameraId]: grant }));
      setMessage(
        `Token for ${cameraId} minted; it is single-use and expires in ${formatExpiry(grant.expiresInSeconds)}. Send only the token to the operator, never the producer secret.`,
      );
      onLog(`Minted pairing token for ${cameraId} (grant ${grant.grantId}, code ${grant.verificationCode})`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : `Could not mint a token for ${cameraId}.`);
    } finally {
      setBusy(null);
    }
  }

  async function decide(claim: ProducerPairingClaimResponse, approved: boolean) {
    setBusy(`decide-${claim.claimId}`);
    try {
      const result = await decidePairingClaim(apiBaseUrl, secret, eventId, claim.claimId, approved);
      setMessage(`${result.camera.cameraId} claim ${approved ? "approved" : "rejected"}.`);
      onLog(
        `${approved ? "Approved" : "Rejected"} ${result.camera.cameraId} claim from "${claim.deviceLabel}" (${claim.displayName})`,
      );
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Decision failed.");
    } finally {
      setBusy(null);
    }
  }

  async function copy(text: string, label: string) {
    try {
      await navigator.clipboard.writeText(text);
      setMessage(`${label} copied to the clipboard.`);
    } catch {
      setMessage(`Clipboard blocked; select and copy the ${label.toLowerCase()} by hand.`);
    }
  }

  return (
    <section className="panel form-panel" aria-label="Pairing">
      <div className="preview-heading">
        <div>
          <p className="eyebrow">STAGE 1 · PAIRING</p>
          <h2>Admit cameras</h2>
        </div>
        <span className={`status ${polling ? "status-connected" : ""}`}>
          {polling ? "watching claims" : "idle"}
        </span>
      </div>

      <div className="pairing-slots">
        {CAMERA_IDS.map((cameraId) => {
          const contract = CAMERA_CONTRACTS[cameraId];
          const grant = grants[cameraId];
          const binding = bindingForCamera(bindings, cameraId);
          return (
            <article key={cameraId} className="slot">
              <header className="slot-heading">
                <div>
                  <p className="eyebrow">
                    {contract.role} · owner {contract.owner}
                  </p>
                  <h3>{cameraId}</h3>
                </div>
                <span className={`badge ${binding ? "badge-video-ready" : "badge-waiting"}`}>
                  {binding ? "bound" : "unbound"}
                </span>
              </header>

              <div className="inline-actions">
                <button
                  type="button"
                  className="primary"
                  disabled={!ready || busy !== null}
                  onClick={() => void mint(cameraId)}
                >
                  {grant ? "Mint new token" : "Mint pairing token"}
                </button>
                {grant && (
                  <button type="button" onClick={() => void copy(grant.pairingToken, "Pairing token")}>
                    Copy token
                  </button>
                )}
              </div>

              {grant && (
                <dl className="connection-details">
                  <dt>Verify code</dt>
                  <dd className="verify-code">{grant.verificationCode}</dd>
                  <dt>Token</dt>
                  <dd className="token">{grant.pairingToken}</dd>
                  <dt>Expires</dt>
                  <dd>{formatExpiry(grant.expiresInSeconds)} from minting; single use</dd>
                </dl>
              )}

              {binding && (
                <dl className="connection-details">
                  <dt>Bound to</dt>
                  <dd>
                    {binding.displayName} · {binding.participantIdentity}
                  </dd>
                  <dt>Device session</dt>
                  <dd>{binding.deviceSessionId}</dd>
                  <dt>Stream epoch</dt>
                  <dd>{binding.streamEpoch}</dd>
                  <dt>Video SID</dt>
                  <dd>{binding.currentVideoTrackSid ?? "not yet published"}</dd>
                </dl>
              )}
            </article>
          );
        })}
      </div>

      <h3>Claims</h3>
      {claims.length === 0 ? (
        <p className="detail">No claims yet. A claim appears when an operator submits a token.</p>
      ) : (
        <ul className="claims">
          {claims.map((claim) => (
            <li key={claim.claimId} className={`claim claim-${claim.status.toLowerCase()}`}>
              <div>
                <strong>{claim.camera.cameraId}</strong> · {claim.displayName} · "{claim.deviceLabel}" ·{" "}
                <span className="verify-code">{claim.verificationCode}</span> · {claim.status}
                {claimIsLive(claim.status) ? ` · ${formatExpiry(claim.expiresInSeconds)} left` : ""}
              </div>
              {claimNeedsDecision(claim.status) && (
                <div className="inline-actions">
                  <button
                    type="button"
                    className="primary"
                    disabled={busy !== null}
                    onClick={() => void decide(claim, true)}
                  >
                    Approve (code matches the laptop)
                  </button>
                  <button
                    type="button"
                    className="danger"
                    disabled={busy !== null}
                    onClick={() => void decide(claim, false)}
                  >
                    Reject
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      <p className="detail" role="status" aria-live="polite">
        {message}
      </p>
    </section>
  );
}
