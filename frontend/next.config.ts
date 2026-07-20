import type { NextConfig } from "next";

/**
 * The desktop build (`build:desktop` sets NEXT_PUBLIC_DESKTOP=1) produces a
 * static export in `out/` for the Tauri shell to load from the filesystem. The
 * regular web build stays a normal server build — `output: "export"` is only
 * applied under the desktop flag so web behavior is untouched.
 *
 * `images.unoptimized` is required by static export (no image optimization
 * server exists in the packaged app).
 */
const isDesktop = process.env.NEXT_PUBLIC_DESKTOP === "1";

const nextConfig: NextConfig = isDesktop
  ? {
      output: "export",
      images: { unoptimized: true },
    }
  : {};

export default nextConfig;
