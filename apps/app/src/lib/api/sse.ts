/**
 * A Server-Sent Events parser for `fetch` streams.
 *
 * Follows the WHATWG event-stream rules rather than splitting on "\n\n":
 *
 *   - a line ends at CRLF, LF or CR — including a CR at the end of one chunk whose
 *     LF arrives at the start of the next (that pair is ONE line end, not two;
 *     treating it as two would dispatch a half-built event early);
 *   - a blank line dispatches the event being built;
 *   - several `data:` lines join with "\n";
 *   - lines starting with ":" are comments (the API sends `: open` / `: keepalive`);
 *   - one leading space after the colon is removed, and only one;
 *   - an event with no `data` is not dispatched.
 *
 * The backend frames with LF today; the parser does not depend on it.
 *
 * Input is TEXT: decode bytes with a streaming `TextDecoder` first, so a
 * multi-byte character split across network chunks is not corrupted.
 */

export type SseEvent = { event: string; data: string };

export class SseParser {
  private line = "";
  /** The previous chunk ended in CR; a leading LF on the next chunk belongs to it. */
  private pendingCR = false;
  private eventName = "";
  private dataLines: string[] = [];

  constructor(private readonly onEvent: (event: SseEvent) => void) {}

  push(chunk: string): void {
    let start = 0;
    let index = 0;
    if (this.pendingCR) {
      this.pendingCR = false;
      if (chunk.startsWith("\n")) {
        start = 1;
        index = 1;
      }
    }
    for (; index < chunk.length; index += 1) {
      const char = chunk[index];
      if (char !== "\n" && char !== "\r") continue;

      this.line += chunk.slice(start, index);
      this.processLine(this.line);
      this.line = "";

      if (char === "\r") {
        if (index + 1 < chunk.length) {
          if (chunk[index + 1] === "\n") index += 1;
        } else {
          this.pendingCR = true;
        }
      }
      start = index + 1;
    }
    this.line += chunk.slice(start);
  }

  /**
   * End of stream. Returns the event that was being built when the stream ended
   * WITHOUT a final blank line, if it had data — the caller decides whether a
   * truncated frame is trustworthy. The spec says to discard it; the chat client
   * accepts it only when it is a complete, parseable terminal event.
   */
  end(): SseEvent | null {
    if (this.line) {
      this.processLine(this.line);
      this.line = "";
    }
    this.pendingCR = false;
    const leftover = this.dataLines.length
      ? { event: this.eventName || "message", data: this.dataLines.join("\n") }
      : null;
    this.reset();
    return leftover;
  }

  private processLine(line: string): void {
    if (line === "") {
      this.dispatch();
      return;
    }
    if (line.startsWith(":")) return;

    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);

    if (field === "event") this.eventName = value;
    else if (field === "data") this.dataLines.push(value);
    // `id` and `retry` are part of the format but unused here; anything else is ignored.
  }

  private dispatch(): void {
    if (this.dataLines.length) {
      this.onEvent({ event: this.eventName || "message", data: this.dataLines.join("\n") });
    }
    this.reset();
  }

  private reset(): void {
    this.eventName = "";
    this.dataLines = [];
  }
}
