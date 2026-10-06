"use client";

import * as React from "react";
import { useTranslations } from "next-intl";
import { Eye, EyeOff } from "lucide-react";
import { Input } from "@/components/ui/input";

type PasswordInputProps = Omit<
  React.ComponentProps<typeof Input>,
  "type" | "trailing"
>;

/** {@link Input} for a secret, with an eye button that reveals what was typed. */
const PasswordInput = React.forwardRef<HTMLInputElement, PasswordInputProps>(
  (props, ref) => {
    const t = useTranslations("Common");
    const [visible, setVisible] = React.useState(false);
    const Icon = visible ? EyeOff : Eye;

    return (
      <Input
        ref={ref}
        type={visible ? "text" : "password"}
        trailing={
          <button
            type="button"
            aria-label={t(visible ? "hidePassword" : "showPassword")}
            aria-pressed={visible}
            onClick={() => setVisible((v) => !v)}
            className="grid h-full w-9 place-items-center text-muted-foreground transition-colors hover:text-foreground"
          >
            <Icon className="h-4 w-4" />
          </button>
        }
        {...props}
      />
    );
  }
);
PasswordInput.displayName = "PasswordInput";

export { PasswordInput };
