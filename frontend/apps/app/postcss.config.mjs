/** @type {import('postcss-load-config').Config} */
const config = {
  plugins: {
    tailwindcss: {},
    // This is the chain that actually processes the app's CSS, including the
    // `@v1/ui/globals.css` it imports — so autoprefixer has to be here, not only
    // in the ui package, to have any effect on what ships.
    autoprefixer: {},
  },
};

export default config;
