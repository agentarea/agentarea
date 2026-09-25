// @modelcontextprotocol/ext-apps declares zod ^4.2 as a peer, so pnpm links it
// to this app's zod 3 — and neither `overrides` nor `packageExtensions` can
// replace a peer. Turning the peer into a regular dependency gives the SDK its
// own zod 4, the one @modelcontextprotocol/client and core already carry.
// Delete this file once the app itself is on zod ^4.2.
function readPackage(pkg) {
  if (pkg.name === "@modelcontextprotocol/ext-apps" && pkg.peerDependencies?.zod) {
    pkg.dependencies = { ...pkg.dependencies, zod: pkg.peerDependencies.zod };
    delete pkg.peerDependencies.zod;
  }
  return pkg;
}

module.exports = { hooks: { readPackage } };
