"use client";

import { useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { ArrowUpRight, LayoutGrid, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { OpenAPIConnectionMark } from "./MCPCard";

interface ConnectionOption {
  id: "catalog" | "mcp" | "openapi";
  href: string;
  iconClass: string;
  icon: ReactNode;
}

const OPTIONS: ConnectionOption[] = [
  {
    id: "catalog",
    href: "/explore?type=mcp_servers",
    iconClass: "bg-primary/10 text-primary dark:bg-white/10 dark:text-white",
    icon: <LayoutGrid className="h-5 w-5" />,
  },
  {
    id: "mcp",
    href: "/connections/add",
    iconClass: "bg-[#5e6ad2]/10 dark:bg-white/10",
    // mcp.svg is fill="currentColor"; render it as a mask so its color is
    // driven by `background-color` — blue in light, white in dark.
    icon: (
      <span
        aria-hidden
        className="h-5 w-5 bg-primary [mask-image:url(/mcp.svg)] [mask-position:center] [mask-repeat:no-repeat] [mask-size:contain] [-webkit-mask-image:url(/mcp.svg)] [-webkit-mask-position:center] [-webkit-mask-repeat:no-repeat] [-webkit-mask-size:contain] dark:bg-white"
      />
    ),
  },
  {
    id: "openapi",
    href: "/connections/add-openapi",
    iconClass: "",
    icon: <OpenAPIConnectionMark className="h-[38px] w-[38px] rounded-lg text-[11px]" />,
  },
];

export function AddConnectionDropdown() {
  const t = useTranslations("MCPServersPage.addConnectionDialog");
  const router = useRouter();
  const [open, setOpen] = useState(false);

  const handleSelect = (href: string) => {
    setOpen(false);
    router.push(href);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          className="shrink-0 gap-2"
          size="xs"
          data-test="new-connection-button"
        >
          <Plus className="mr-1 h-4 w-4" />
          {t("trigger")}
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md gap-0 p-0">
        <DialogHeader className="space-y-1.5 p-6 pb-2">
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-0.5 p-3">
          {OPTIONS.map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() => handleSelect(option.href)}
              className={cn(
                "group relative flex w-full items-center gap-3.5 overflow-hidden rounded-sm border border-transparent p-3.5 text-left transition-colors",
                "hover:border-primary/20 dark:hover:border-primary/50 focus-visible:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              )}
              data-test={`new-connection-${option.id}`}
            >
              {/* brand: 135° diagonal hatch that fades in from the left on hover */}
              <span aria-hidden className="conn-opt-hatch" />
              <span
                className={cn(
                  "relative z-10 flex h-[38px] w-[38px] shrink-0 items-center justify-center rounded-lg transition-transform group-hover:scale-105",
                  option.iconClass
                )}
              >
                {option.icon}
              </span>
              <span className="relative z-10 min-w-0 flex-1 space-y-0.5">
                <span className="block text-sm font-semibold leading-tight">
                  {t(`${option.id}.title`)}
                </span>
                <span className="block text-xs text-muted-foreground">
                  {t(`${option.id}.description`)}
                </span>
              </span>
              <ArrowUpRight
                className="relative z-10 h-[18px] w-[18px] shrink-0 -translate-x-1.5 text-muted-foreground opacity-0 transition-all group-hover:translate-x-0 group-hover:text-primary group-hover:opacity-100 group-focus-visible:translate-x-0 group-focus-visible:text-primary group-focus-visible:opacity-100"
              />
            </button>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
