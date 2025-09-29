import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { Breadcrumb, BreadcrumbItem, BreadcrumbLink, BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator } from "@/components/ui/breadcrumb";
import React from "react";
import { SidebarTrigger } from "@/components/ui/sidebar";

type ContentBlockProps = {  
  children: React.ReactNode;
  header?: {
    title: string;
    description?: string;
    backLink?: {
      label?: string;
      href: string;
    },
    controls?: React.ReactNode;
  } | {
    breadcrumb: {label: string, href?: string}[],
    controls?: React.ReactNode;
    description?: string;
  }
}

export default function ContentBlock({ children, header }: ContentBlockProps) {
  return (
    <div className="
        h-full flex flex-col overflow-hidden
    ">
        {header && (
            <div className="
                flex flex-row justify-between items-center min-h-[50px]
                bg-white dark:bg-zinc-800 px-4 border-b border-zinc-200 dark:border-zinc-700"
            >
                {'title' in header ? (
                    <>
                        <div className="flex flex-col gap-1">
                            <h1>{header.title}</h1>
                            {
                                header.description && (
                                    <p className="note">
                                        {header.description}
                                    </p>
                                )
                            }

                            {
                                header.backLink && (
                                    <Link href={header.backLink.href} className="flex items-center gap-2 note hover:text-accent transition-colors duration-300">
                                        <ArrowLeft className="h-4 w-4" />
                                        {header.backLink.label || "Back"}
                                    </Link>
                                )
                            }
                        </div>
                        {header.controls}
                    </>
                ) : (
                    <>
                        <div className="flex items-start gap-2">
                            <SidebarTrigger className="md:hidden h-5 w-5" />
                            <div className="md:hidden h-5 w-px bg-zinc-200 dark:bg-zinc-700"/>
                            <div className="flex flex-col gap-1">
                                <Breadcrumb>
                                    <BreadcrumbList>
                                    {
                                        header.breadcrumb.map((item, index) => (
                                            <React.Fragment key={`breadcrumb-${index}`}>
                                                <BreadcrumbItem>
                                                    {
                                                        index === header.breadcrumb.length - 1 ? (
                                                            <BreadcrumbPage className="font-semibold">{item.label}</BreadcrumbPage>
                                                        ) : (
                                                            item.href ? (
                                                                <BreadcrumbLink asChild>
                                                                    <Link href={item.href || ""}>{item.label}</Link>
                                                                </BreadcrumbLink>
                                                            ) : (
                                                                <BreadcrumbPage className="text-muted-foreground">{item.label}</BreadcrumbPage>
                                                            )
                                                        )
                                                    }
                                                </BreadcrumbItem>
                                                {index < header.breadcrumb.length - 1 && (
                                                    <BreadcrumbSeparator />
                                                )}
                                            </React.Fragment>
                                        ))
                                    }
                                    </BreadcrumbList>
                                </Breadcrumb>
                                {/* {
                                    header.description && (
                                        <p className="note">
                                            {header.description}
                                        </p>
                                    )
                                } */}
                            </div>
                        </div>
                        {header.controls}
                    </>
                ) 
                }
            </div>
        )}

        <div className="px-4 py-5 overflow-auto h-full">
            {children}
        </div>
    </div>
  )
}