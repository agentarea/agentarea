"use client";

import { Fragment, useState, type ReactNode } from "react";
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
    icon: <OpenAPIConnectionMark className="h-[42px] w-[42px] rounded-md text-[12px]" />,
  },
];

/* blueprint divider with crop-mark crosses at the side rails */
function BlueprintDivider() {
  return (
    <div className="conn-bp-div" aria-hidden>
      <span className="conn-bp-mkp l" />
      <span className="conn-bp-mkp r" />
    </div>
  );
}

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
          className="shrink-0"
          size="xs"
          data-test="new-connection-button"
        >
          <Plus />
          {t("trigger")}
        </Button>
      </DialogTrigger>
      <DialogContent className="gap-0 p-0 sm:max-w-[496px] sm:rounded-[10px]">
        <DialogHeader className="space-y-1.5 px-6 pb-4 pt-5">
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
        <div className="conn-bp">
          <BlueprintDivider />
          {OPTIONS.map((option) => (
            <Fragment key={option.id}>
              <button
                type="button"
                onClick={() => handleSelect(option.href)}
                className={cn(
                  "group relative z-[1] flex w-full items-center gap-4 rounded-[7px] px-4 py-4 text-left",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                )}
                data-test={`new-connection-${option.id}`}
              >
                {/* solid fill fades in on hover */}
                <span
                  aria-hidden
                  className="pointer-events-none absolute inset-0 z-0 rounded-[7px] bg-muted/60 opacity-0 transition-opacity duration-300 ease-out group-hover:opacity-100 group-focus-visible:opacity-100 dark:bg-white/[0.07]"
                />
                <span
                  className={cn(
                    "relative z-[1] flex h-[42px] w-[42px] shrink-0 items-center justify-center rounded-md",
                    option.iconClass
                  )}
                >
                  {option.icon}
                </span>
                <span className="relative z-[1] min-w-0 flex-1">
                  <span className="mb-1 block text-[12.5px] font-semibold uppercase leading-none tracking-[0.03em]">
                    {t(`${option.id}.title`)}
                  </span>
                  <span className="block text-xs leading-normal text-muted-foreground">
                    {t(`${option.id}.description`)}
                  </span>
                </span>
                <ArrowUpRight
                  className="relative z-[1] h-[18px] w-[18px] shrink-0 -translate-x-1.5 text-muted-foreground opacity-0 transition-all group-hover:translate-x-0 group-hover:text-primary group-hover:opacity-100 group-focus-visible:translate-x-0 group-focus-visible:text-primary group-focus-visible:opacity-100"
                />
              </button>
              <BlueprintDivider />
            </Fragment>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
