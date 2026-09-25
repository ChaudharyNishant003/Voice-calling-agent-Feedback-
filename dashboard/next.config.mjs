/** @type {import('next').NextConfig} */
const nextConfig = {
  webpack: (config, { dev }) => {
    // Docker Desktop on Windows doesn't reliably forward native filesystem events across the
    // bind-mounted `dashboard/` volume (confirmed by hand: both new route files and edits to
    // existing ones were silently ignored by the dev server's default watcher, requiring a
    // container restart every time). Polling sidesteps that entirely.
    if (dev) {
      config.watchOptions = { poll: 1000, aggregateTimeout: 300 };
    }
    return config;
  },
};

export default nextConfig;
