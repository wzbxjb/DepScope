export function EvidenceLink({ uri, digest }: { uri: string; digest: string }) {
  const safe = /^https:\/\//.test(uri);
  return <span className="evidence-link">{safe ? <a href={uri} target="_blank" rel="noreferrer">Source record ↗</a> : <span>Archived source record</span>}<code title={digest}>{digest.slice(0, 12)}</code></span>;
}
