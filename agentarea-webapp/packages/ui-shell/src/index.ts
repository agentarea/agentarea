// The shell's public surface.
//
// Everything here is re-exported from one entry rather than reached for by deep path,
// so a consumer outside this repository — the billing UI installs this package from a
// pinned git ref — is not coupled to where a file happens to sit.

export { cn } from "./lib/utils";
export { useIsMobile } from "./hooks/use-mobile";
export { LoadingSpinner } from "./components/LoadingSpinner";

export * from "./components/ui/button";
export * from "./components/ui/input";
export * from "./components/ui/separator";
export * from "./components/ui/sheet";
export * from "./components/ui/skeleton";
export * from "./components/ui/tooltip";
export * from "./components/ui/sidebar";

export {
  SettingsSidebarView,
  type SettingsNavItem,
  type SettingsNavSection,
  type SettingsSidebarViewProps,
} from "./components/SettingsSidebarView";
