/**
 * Should this key press send the message?
 *
 * Enter sends; Shift+Enter is a newline. Enter while an input method is composing
 * (Japanese, Chinese, Korean, Hindi transliteration …) confirms the composition —
 * sending then would post half a word. Browsers flag that with `isComposing`, and
 * some (Safari) only with the legacy keyCode 229.
 */
export function shouldSubmit(event: {
  key: string;
  shiftKey: boolean;
  keyCode?: number;
  isComposing?: boolean;
  nativeEvent?: { isComposing?: boolean };
}): boolean {
  if (event.key !== "Enter" || event.shiftKey) return false;
  if (event.isComposing || event.nativeEvent?.isComposing) return false;
  if (event.keyCode === 229) return false;
  return true;
}
