import Link from "next/link";
import { ArrowLeft } from "lucide-react";

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
  }
}

export default function ContentBlock({ children, header }: ContentBlockProps) {
  return (
    <div className="
        px-[20px] py-[20px]
        md:px-[28px] md:py-[20px]
        lg:px-[40px] lg:py-[25px]
    ">
        {
            header && (
                <div className="
                    flex flex-row justify-between items-center 
                    mb-[10px] md:mb-[20px] lg:mb-[30px]
                ">
                    <div className="flex flex-col gap-1">
                        <h1>{header.title}</h1>
                        {
                            header.description && (
                                <p className="text-xs text-zinc-400">
                                    {header.description}
                                </p>
                            )
                        }

                        {
                            header.backLink && (
                                <Link href={header.backLink.href} className="flex items-center gap-2 text-xs text-zinc-400 hover:text-accent transition-colors duration-300">
                                    <ArrowLeft className="h-4 w-4" />
                                    {header.backLink.label || "Back"}
                                </Link>
                            )
                        }
                    </div>
                    {header.controls}
                </div>
            )
        }

        <div>
            {children}
        </div>
    </div>
  )
}