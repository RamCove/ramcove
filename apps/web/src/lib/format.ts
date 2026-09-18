/** Display helpers. Units and their meaning are always shown; percentages never hide their basis. */

export const RAO_PER_TAO = 1_000_000_000;

export function tao(rao: number | null | undefined, places = 4): string {
  if (rao === null || rao === undefined) return "—";
  const sign = rao < 0 ? "-" : "";
  const abs = Math.abs(rao);
  const whole = Math.floor(abs / RAO_PER_TAO);
  const frac = String(abs % RAO_PER_TAO).padStart(9, "0").slice(0, places);
  return `${sign}${whole}.${frac}`;
}

export function usd(cents: number | null | undefined): string {
  if (cents === null || cents === undefined) return "—";
  return `$${(cents / 100).toFixed(2)}`;
}

/** parts-per-million gain -> "+12.4%" */
export function gain(ppm: number | null | undefined, digits = 1): string {
  if (ppm === null || ppm === undefined) return "—";
  const pct = ppm / 10_000;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(digits)}%`;
}

/** milli requests per second -> "1.250 req/s" */
export function rps(milli: number | null | undefined, digits = 3): string {
  if (!milli) return "—";
  return `${(milli / 1000).toFixed(digits)} req/s`;
}

export function centiHours(centi: number | null | undefined): string {
  if (centi === null || centi === undefined) return "—";
  return `${(centi / 100).toFixed(2)} GPU-h`;
}

export function when(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toISOString().replace("T", " ").slice(0, 19) + " UTC";
}

export function ago(value: string | null | undefined): string {
  if (!value) return "—";
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return "—";
  const secs = Math.round((Date.now() - then) / 1000);
  if (secs < 0) return `in ${humanDuration(-secs)}`;
  if (secs < 45) return "just now";
  return `${humanDuration(secs)} ago`;
}

export function humanDuration(secs: number): string {
  if (secs < 90) return `${Math.round(secs)} s`;
  if (secs < 5400) return `${Math.round(secs / 60)} min`;
  if (secs < 172800) return `${Math.round(secs / 3600)} h`;
  return `${Math.round(secs / 86400)} days`;
}

export function shortHash(hash: string | null | undefined, head = 8): string {
  if (!hash) return "—";
  const clean = hash.startsWith("0x") ? hash.slice(2) : hash;
  return `${clean.slice(0, head)}…${clean.slice(-4)}`;
}

export function admissionKey(key: [number, number] | null | undefined): string {
  return key ? `block ${key[0]} · #${key[1]}` : "not admitted";
}
