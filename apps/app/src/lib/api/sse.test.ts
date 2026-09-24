import { describe, expect, test } from "bun:test";
import { type SseEvent, SseParser } from "./sse";

function parse(chunks: string[]): { events: SseEvent[]; leftover: SseEvent | null } {
  const events: SseEvent[] = [];
  const parser = new SseParser((event) => events.push(event));
  for (const chunk of chunks) parser.push(chunk);
  return { events, leftover: parser.end() };
}

describe("SseParser", () => {
  test("LF-framed events, exactly as the backend sends them", () => {
    const { events } = parse([
      ': open\n\nevent: meta\ndata: {"a":1}\n\nevent: token\ndata: {"text":"Hi"}\n\n',
    ]);
    expect(events).toEqual([
      { event: "meta", data: '{"a":1}' },
      { event: "token", data: '{"text":"Hi"}' },
    ]);
  });

  test("CRLF framing", () => {
    const { events } = parse(['event: token\r\ndata: {"text":"a"}\r\n\r\nevent: done\r\ndata: {}\r\n\r\n']);
    expect(events).toEqual([
      { event: "token", data: '{"text":"a"}' },
      { event: "done", data: "{}" },
    ]);
  });

  test("CR-only framing", () => {
    const { events } = parse(["event: token\rdata: x\r\r"]);
    expect(events).toEqual([{ event: "token", data: "x" }]);
  });

  test("a CRLF pair split across chunks is one line end, not two", () => {
    // If the trailing CR and the leading LF were counted separately, the blank line
    // between them would dispatch an event with no data before `data:` arrived.
    const { events } = parse(["event: token\r", "\ndata: x\r", "\n\r", "\n"]);
    expect(events).toEqual([{ event: "token", data: "x" }]);
  });

  test("every possible chunk boundary gives the same result", () => {
    const stream = 'event: meta\r\ndata: {"id":"1"}\r\n\r\n: keepalive\r\n\r\nevent: done\ndata: {"ok":true}\n\n';
    const expected = parse([stream]).events;
    for (let cut = 1; cut < stream.length; cut += 1) {
      expect(parse([stream.slice(0, cut), stream.slice(cut)]).events).toEqual(expected);
    }
    // and one character at a time
    expect(parse([...stream]).events).toEqual(expected);
  });

  test("multi-line data joins with a newline", () => {
    const { events } = parse(["data: line one\ndata: line two\ndata:\n\n"]);
    expect(events).toEqual([{ event: "message", data: "line one\nline two\n" }]);
  });

  test("comments and keepalives are ignored", () => {
    const { events } = parse([": open\n\n: keepalive\n\n:\n\n"]);
    expect(events).toEqual([]);
  });

  test("only one leading space is stripped from a value", () => {
    const { events } = parse(["data:  two spaces\n\ndata:none\n\n"]);
    expect(events.map((event) => event.data)).toEqual([" two spaces", "none"]);
  });

  test("an event without data is not dispatched", () => {
    const { events } = parse(["event: meta\n\n"]);
    expect(events).toEqual([]);
  });

  test("a field without a colon and unknown fields are ignored", () => {
    const { events } = parse(["retry: 100\nid: 7\nbogus\ndata: kept\n\n"]);
    expect(events).toEqual([{ event: "message", data: "kept" }]);
  });

  test("a final frame without a blank line is returned to the caller, not dispatched", () => {
    const { events, leftover } = parse(['event: token\ndata: {"text":"a"}\n\nevent: done\ndata: {"x":1}']);
    expect(events).toEqual([{ event: "token", data: '{"text":"a"}' }]);
    expect(leftover).toEqual({ event: "done", data: '{"x":1}' });
  });

  test("no leftover when the stream ended cleanly", () => {
    expect(parse(["data: a\n\n"]).leftover).toBeNull();
  });
});
