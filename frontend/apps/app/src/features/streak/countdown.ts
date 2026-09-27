/** What is left of the learning day, for the header: "02h 14m", and in words for screen readers. */
export function describeRemaining(ms: number): { short: string; spoken: string } {
  const totalMinutes = Math.max(0, Math.floor(ms / 60_000));
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  const pad = (value: number) => String(value).padStart(2, "0");
  const unit = (value: number, word: string) => `${value} ${word}${value === 1 ? "" : "s"}`;
  const spoken = hours ? `${unit(hours, "hour")} ${unit(minutes, "minute")}` : unit(minutes, "minute");
  return { short: `${pad(hours)}h ${pad(minutes)}m`, spoken: `${spoken} left in today's learning day` };
}

/** The learning day has ended (the header then asks the server for the new day). */
export function dayHasEnded(dayEnd: string, now: number): boolean {
  return now >= Date.parse(dayEnd);
}
