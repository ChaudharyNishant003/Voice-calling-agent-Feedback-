/** @type {import('next').NextConfig} */
const nextConfig = {
  webpack: (config, { dev }) => {
    // Docker Desktop on Windows doesn't reliably forward native filesystem events across the
    // bind-mounted `dashboard/` volume (confirmed by hand: both new route files and edits to
    // existing ones were silently ignored by the dev server's default watcher, requiring a
    // container restart every time). Polling sidesteps that entirely.
    if (dev) {
      // `ignored` must be set explicitly: assigning `config.watchOptions` wholesale (rather than
      // merging into it) replaces webpack's own default ignore list, which normally excludes
      // node_modules/.next — without this, polling watches those too, including .next's own build
      // output, which caused a continuous rebuild-on-its-own-output loop (confirmed by hand: Fast
      // Refresh kept firing every few seconds with no file edited, and mid-rebuild React trees were
      // dropping click events on nav links).
      config.watchOptions = {
        poll: 1000,
        aggregateTimeout: 300,
        ignored: ["**/node_modules/**", "**/.next/**"],
      };
    }
    return config;
  },
};

export default nextConfig;
