// Exposes the UMD ReactDOM global (loaded by index.html) as an ES module.
const D = window.ReactDOM;
export default D;
export const { createPortal, createRoot, flushSync, unstable_batchedUpdates, version } = D;
