/** @type {import('postcss-load-config').Config} */
module.exports = {
  plugins: {
    tailwindcss: {},
    // `autoprefixer` was already a devDependency here but was in neither
    // PostCSS chain, so it was installed and never run. It matters for two
    // things this design actually uses: `background-clip: text` still needs
    // `-webkit-` on Safari, and older iOS wants the prefixed form of
    // `backdrop-filter`, which `.backdrop-wash` and the composer rely on.
    autoprefixer: {},
  },
};
