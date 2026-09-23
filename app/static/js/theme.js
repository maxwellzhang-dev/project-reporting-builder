// Basecoat switches palette on a `dark` class rather than on the media query,
// so the class mirrors the OS setting. A classic script in <head>, not a
// module, so it runs before first paint and a dark page never flashes white.
(() => {
  const query = window.matchMedia("(prefers-color-scheme: dark)");
  const apply = () => document.documentElement.classList.toggle("dark", query.matches);
  apply();
  query.addEventListener("change", apply);
})();
