import { ChevronDownIcon } from "lucide-react";
import type * as React from "react";

import { cn } from "../lib/utils";

/** A styled native <select>, light enough for one per table row; it matches SelectTrigger. */
function NativeSelect({
  className,
  size = "default",
  ...props
}: Omit<React.ComponentProps<"select">, "size"> & { size?: "default" | "sm" }) {
  return (
    <div data-slot="native-select-wrapper" className={cn("relative w-fit min-w-0", className)}>
      <select
        data-slot="native-select"
        data-size={size}
        className="bg-background hover:bg-accent/60 focus-visible:border-ring focus-visible:ring-ring/50 aria-invalid:border-destructive w-full min-w-0 cursor-pointer appearance-none truncate rounded-md border py-0 pr-7 pl-2.5 text-sm shadow-xs transition-[color,box-shadow] outline-none focus-visible:ring-[3px] disabled:cursor-not-allowed disabled:opacity-50 data-[size=default]:h-8 data-[size=sm]:h-7 data-[size=sm]:pl-2 data-[size=sm]:text-xs"
        {...props}
      />
      <ChevronDownIcon className="text-muted-foreground pointer-events-none absolute top-1/2 right-2 size-3.5 -translate-y-1/2 opacity-70" />
    </div>
  );
}

export { NativeSelect };
