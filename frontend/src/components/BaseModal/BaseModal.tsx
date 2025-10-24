"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { CheckCircle, Loader2, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

interface BaseModalProps {
  title: string | React.ReactNode;
  description: string | React.ReactNode;
  children: React.ReactNode;
  onConfirm: () => void;
  type: "delete" | "confirm";
}

export default function BaseModal({
  title,
  description,
  children,
  onConfirm,
  type,
}: BaseModalProps) {
  const [isLoading, setIsLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const tCommon = useTranslations("Common");

  const handleConfirm = async () => {
    setIsLoading(true);
    await onConfirm();
    setIsLoading(false);
    setIsOpen(false);
  };

  const getIcon = () => {
    if (type === "delete") {
      return <Trash2 className="h-6 w-6" />;
    }
    return <CheckCircle className="h-6 w-6" />;
  };

  const getIconBackground = () => {
    if (type === "delete") {
      return "bg-destructive/30 text-destructive dark:bg-destructive dark:text-zinc-200";
    }
    return "bg-accent/30 text-accent dark:bg-accent-foreground/20 dark:text-accent";
  };

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent className="max-w-[400px] overflow-hidden dark:bg-zinc-800">
        <div className="relative w-max">
          <div
            data-featured-icon="true"
            className={`*:data-icon:size-6 relative flex size-12 shrink-0 items-center justify-center rounded-full ${getIconBackground()}`}
          >
            {getIcon()}
            <svg
              width="336"
              height="336"
              viewBox="0 0 336 336"
              fill="none"
              className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-zinc-300 dark:text-zinc-500"
            >
              <mask
                id="mask0_4947_375931"
                maskUnits="userSpaceOnUse"
                x="0"
                y="0"
                width="336"
                height="336"
                style={{ maskType: "alpha" }}
              >
                <rect
                  width="336"
                  height="336"
                  fill="url(#paint0_radial_4947_375931)"
                ></rect>
              </mask>
              <g mask="url(#mask0_4947_375931)">
                <circle
                  cx="168"
                  cy="168"
                  r="47.5"
                  stroke="currentColor"
                ></circle>
                <circle
                  cx="168"
                  cy="168"
                  r="47.5"
                  stroke="currentColor"
                ></circle>
                <circle
                  cx="168"
                  cy="168"
                  r="71.5"
                  stroke="currentColor"
                ></circle>
                <circle
                  cx="168"
                  cy="168"
                  r="95.5"
                  stroke="currentColor"
                ></circle>
                <circle
                  cx="168"
                  cy="168"
                  r="119.5"
                  stroke="currentColor"
                ></circle>
                <circle
                  cx="168"
                  cy="168"
                  r="143.5"
                  stroke="currentColor"
                ></circle>
                <circle
                  cx="168"
                  cy="168"
                  r="167.5"
                  stroke="currentColor"
                ></circle>
              </g>
              <defs>
                <radialGradient
                  id="paint0_radial_4947_375931"
                  cx="0"
                  cy="0"
                  r="1"
                  gradientUnits="userSpaceOnUse"
                  gradientTransform="translate(168 168) rotate(90) scale(168 168)"
                >
                  <stop></stop>
                  <stop offset="1" stopOpacity="0"></stop>
                </radialGradient>
              </defs>
            </svg>
          </div>
        </div>
        <DialogHeader className="relative z-10 mt-3">
          <DialogTitle className="pb-2">{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setIsOpen(false)}
            disabled={isLoading}
          >
            {tCommon("cancel")}
          </Button>
          <Button
            size="sm"
            onClick={handleConfirm}
            disabled={isLoading}
            variant={type === "delete" ? "destructive" : "default"}
          >
            {type === "delete" ? tCommon("delete") : tCommon("confirm")}
            {isLoading && <Loader2 className="h-4 w-4 animate-spin" />}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
