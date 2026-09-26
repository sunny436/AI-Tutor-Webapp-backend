/**
 * A request, from the Settings workspace, to focus the next section heading that appears: the
 * section being opened may still be loading when the request is made. One request, one focus.
 */

let pending = false;

export function requestHeadingFocus(): void {
  pending = true;
}

export function cancelHeadingFocus(): void {
  pending = false;
}

export function takeHeadingFocus(): boolean {
  const requested = pending;
  pending = false;
  return requested;
}
