/** Stubs jsdom lacks but Radix needs.
 *
 * Radix drives selects and popovers with pointer capture, scrolls the active
 * item into view and measures the trigger — none of which jsdom implements.
 * Call this from `beforeAll` in any test that renders one for real.
 */
export function installRadixJsdomStubs() {
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
  Element.prototype.scrollIntoView = () => {};
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
