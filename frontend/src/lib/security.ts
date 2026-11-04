/** Public documentation links must not carry credentials or active schemes. */
export function externalReferenceUrl(value: unknown): string | null {
  if (typeof value !== "string" || /[\u0000-\u0020\u007f]/u.test(value))
    return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password
      ? url.href
      : null;
  } catch {
    return null;
  }
}
