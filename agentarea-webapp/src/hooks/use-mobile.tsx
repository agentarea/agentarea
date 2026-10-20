import * as React from "react";

const MOBILE_BREAKPOINT = 768;

/**
 * Whether the viewport is narrower than `breakpoint` pixels, following
 * resizes. False until mounted, since the server has no viewport.
 */
export function useIsBelow(breakpoint: number) {
  const [isBelow, setIsBelow] = React.useState<boolean | undefined>(undefined);

  React.useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${breakpoint - 1}px)`);
    const onChange = () => {
      setIsBelow(window.innerWidth < breakpoint);
    };
    mql.addEventListener("change", onChange);
    setIsBelow(window.innerWidth < breakpoint);
    return () => mql.removeEventListener("change", onChange);
  }, [breakpoint]);

  return !!isBelow;
}

export function useIsMobile() {
  return useIsBelow(MOBILE_BREAKPOINT);
}
