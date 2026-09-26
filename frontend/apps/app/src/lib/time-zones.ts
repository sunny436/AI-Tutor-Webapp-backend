/**
 * Time zones as people know them today.
 *
 * Browsers built on ICU (Chromium, and Node) still list and detect some zones under their old
 * IANA names: India is "Asia/Calcutta", not "Asia/Kolkata". Both names are valid on the server
 * (one links to the other in the tz database), but the app shows and saves the current one, so
 * a student in India sees the name they know and matches the server's DEFAULT_TIMEZONE.
 */

const CURRENT_NAME: Record<string, string> = {
  "Asia/Calcutta": "Asia/Kolkata",
  "Asia/Katmandu": "Asia/Kathmandu",
  "Asia/Dacca": "Asia/Dhaka",
  "Asia/Thimbu": "Asia/Thimphu",
  "Asia/Rangoon": "Asia/Yangon",
  "Asia/Saigon": "Asia/Ho_Chi_Minh",
  "Asia/Ujung_Pandang": "Asia/Makassar",
  "Asia/Ulan_Bator": "Asia/Ulaanbaatar",
  "Europe/Kiev": "Europe/Kyiv",
  "Atlantic/Faeroe": "Atlantic/Faroe",
  "America/Godthab": "America/Nuuk",
  "America/Buenos_Aires": "America/Argentina/Buenos_Aires",
  "America/Indianapolis": "America/Indiana/Indianapolis",
  "America/Louisville": "America/Kentucky/Louisville",
  "Pacific/Truk": "Pacific/Chuuk",
  "Pacific/Ponape": "Pacific/Pohnpei",
  "Pacific/Enderbury": "Pacific/Kanton",
};

export function currentZoneName(zone: string): string {
  return CURRENT_NAME[zone] ?? zone;
}

/** Every zone this browser knows, by its current name, sorted. */
export function supportedZones(list?: readonly string[]): string[] {
  const source =
    list ?? (Intl as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf?.("timeZone") ?? [];
  return [...new Set(source.map(currentZoneName))].sort();
}

/** This device's zone, by its current name. */
export function deviceZone(): string | null {
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return zone ? currentZoneName(zone) : null;
  } catch {
    return null;
  }
}
