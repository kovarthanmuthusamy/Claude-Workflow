// Minimal react/jsx-runtime on top of the UMD React global.
const R = window.React;
export const Fragment = R.Fragment;
export function jsx(type, props, key) {
  return R.createElement(type, key === undefined ? props : { ...props, key });
}
export const jsxs = jsx;
