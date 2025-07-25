import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { Breadcrumb, BreadcrumbItem, BreadcrumbLink, BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator } from "@/components/ui/breadcrumb";
import React from "react";

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
        px-[20px] py-[20px]
        md:px-[28px] md:py-[20px]
        lg:px-[40px] lg:py-[25px]
    ">

        {header && (
            <div className="
                min-h-[38px]
                flex flex-row justify-between items-center
                mb-[10px] md:mb-[20px] lg:mb-[30px]"
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
                                                        <BreadcrumbLink href={item.href || ""}>{item.label}</BreadcrumbLink>
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
                            {
                                header.description && (
                                    <p className="note">
                                        {header.description}
                                    </p>
                                )
                            }
                        </div>
                        {header.controls}
                    </>
                ) 
                }
            </div>
        )}

        <div>
            {children}
        </div>
    </div>
  )
}