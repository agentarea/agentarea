"use client"

import * as React from "react"
import * as SwitchPrimitives from "@radix-ui/react-switch"

import { cn } from "@/lib/utils"

export interface SwitchProps
  extends React.ComponentPropsWithoutRef<typeof SwitchPrimitives.Root> {
  /**
   * Switch size variant.
   * @default "default"
   */
  size?: "default" | "xs"
}

const Switch = React.forwardRef<
  React.ElementRef<typeof SwitchPrimitives.Root>,
  SwitchProps
>(({ className, size = "default", ...props }, ref) => {
  const rootSizeClasses =
    size === "xs" ? "h-4 w-7" : "h-5 w-9"

  const thumbSizeClasses =
    size === "xs"
      ? "h-3 w-3 data-[state=checked]:translate-x-3"
      : "h-4 w-4 data-[state=checked]:translate-x-4"

  return (
    <SwitchPrimitives.Root
      className={cn(
        "peer inline-flex cursor-pointer items-center rounded-full border-2 border-transparent shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:bg-primary dark:data-[state=checked]:bg-accent-foreground data-[state=unchecked]:bg-input dark:data-[state=unchecked]:bg-zinc-700",
        rootSizeClasses,
        className
      )}
      {...props}
      ref={ref}
    >
      <SwitchPrimitives.Thumb
        className={cn(
          "pointer-events-none block rounded-full bg-background shadow-lg ring-0 transition-transform data-[state=unchecked]:translate-x-0",
          thumbSizeClasses
        )}
      />
    </SwitchPrimitives.Root>
  )
})
Switch.displayName = SwitchPrimitives.Root.displayName

export { Switch }
