import React from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";

type ContentBlockProps = {
  children: React.ReactNode;
  subheader?: React.ReactNode;
  className?: string;
  header?:
    | {
        title: string;
        description?: string;
        backLink?: {
          label?: string;
          href: string;
        };
        controls?: React.ReactNode;
      }
    | {
        breadcrumb: { label: string; href?: string }[];
        controls?: React.ReactNode;
        description?: string;
      };
};

export default function ContentBlock({
  children,
  header,
  className,
  subheader,
}: ContentBlockProps) {
  return (
    <div className="flex h-full flex-col overflow-hidden">
      {header && (
        <div className="flex min-h-[40px] flex-row items-center justify-between border-b border-zinc-200 bg-white px-2 sm:px-4 dark:border-zinc-700 dark:bg-zinc-800">
          {"title" in header ? (
            <>
              <div className="flex flex-col gap-1">
                <h1>{header.title}</h1>
                {header.description && (
                  <p className="note">{header.description}</p>
                )}

                {header.backLink && (
                  <Link
                    href={header.backLink.href}
                    className="note flex items-center gap-2 transition-colors duration-300 hover:text-accent"
                  >
                    <ArrowLeft className="h-4 w-4" />
                    {header.backLink.label || "Back"}
                  </Link>
                )}
              </div>
              {header.controls}
            </>
          ) : (
            <>
              <div className="flex items-start gap-1.5 md:gap-2">
                <SidebarTrigger className="h-5 w-5" />
                <div className="h-5 w-px bg-zinc-200 dark:bg-zinc-700" />
                <div className="flex flex-col gap-1">
                  <Breadcrumb>
                    <BreadcrumbList className="gap-1 sm:gap-2.5 max-sm:text-xs max-sm:leading-[22px]">
                      {header.breadcrumb.map((item, index) => (
                        <React.Fragment key={`breadcrumb-${index}`}>
                          <BreadcrumbItem>
                            {index === header.breadcrumb.length - 1 ? (
                              <BreadcrumbPage className="font-semibold">
                                {item.label}
                              </BreadcrumbPage>
                            ) : item.href ? (
                              <BreadcrumbLink asChild>
                                <Link href={item.href || ""}>{item.label}</Link>
                              </BreadcrumbLink>
                            ) : (
                              <BreadcrumbPage className="text-muted-foreground">
                                {item.label}
                              </BreadcrumbPage>
                            )}
                          </BreadcrumbItem>
                          {index < header.breadcrumb.length - 1 && (
                            <BreadcrumbSeparator />
                          )}
                        </React.Fragment>
                      ))}
                    </BreadcrumbList>
                  </Breadcrumb>
                </div>
              </div>
              {header.controls}
            </>
          )}
        </div>
      )}
      {subheader && (
        <div className="flex items-center justify-between gap-3 border-b border-zinc-200 bg-white px-4 dark:border-zinc-700 dark:bg-zinc-800 md:gap-10">
          {subheader}
        </div>
      )}

      <div className={cn("h-full overflow-auto px-4 py-5", className)}>
        {children}
      </div>
    </div>
  );
}
