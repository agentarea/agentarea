"use client";

import React, { useState } from "react";
import { Sidebar, SidebarBody, SidebarLink } from "@/components/ui/sidebar";
import Link from "next/link";
import Image from "next/image";
import { motion } from "framer-motion";
import { 
  Home,
  Bot,
  Database,
  Code2,
  Store,
  Building2,
  Settings
} from "lucide-react";

// Add these types at the top of the file, after the imports
type SubItem = {
  label: string;
  href: string;
}

type BaseLink = {
  label: string;
  href: string;
  icon: React.ReactElement;
  subItems?: SubItem[];
}

type SectionLink = {
  type: "section";
  label: string;
}

type Links = BaseLink | SectionLink;

const links: Links[] = [
  // Overview section
  {
    type: "section",
    label: "OVERVIEW"
  },
  {
    label: "Home",
    href: "/home", 
    icon: <Home className="text-neutral-700 dark:text-neutral-200 h-5 w-5 flex-shrink-0" />,
  },
  {
    label: "Agents",
    href: "/agents",
    icon: <Bot className="text-neutral-700 dark:text-neutral-200 h-5 w-5 flex-shrink-0" />,
    subItems: [
      { label: "Browse", href: "/agents/browse" },
      { label: "Running", href: "/agents/running" },
      { label: "History", href: "/agents/history" },
    ]
  },
  {
    label: "Sources", 
    href: "/sources",
    icon: <Database className="text-neutral-700 dark:text-neutral-200 h-5 w-5 flex-shrink-0" />,
    subItems: [
      { label: "Browse", href: "/sources/browse" },
      { label: "Connect New", href: "/sources/new" },
    ]
  },

  // Creator section
  {
    type: "section",
    label: "CREATOR"
  },
  {
    label: "Creator Hub",
    href: "/creator",
    icon: <Code2 className="text-neutral-700 dark:text-neutral-200 h-5 w-5 flex-shrink-0" />,
    subItems: [
      { label: "My Agents", href: "/creator/agents" },
      { label: "Development", href: "/creator/development" },
      { label: "Publications", href: "/creator/publications" },
      { label: "Analytics", href: "/creator/analytics" },
      { label: "Documentation", href: "/creator/docs" },
    ]
  },
  {
    label: "Marketplace",
    href: "/marketplace",
    icon: <Store className="text-neutral-700 dark:text-neutral-200 h-5 w-5 flex-shrink-0" />,
    subItems: [
      { label: "Browse", href: "/marketplace/browse" },
      { label: "Subscriptions", href: "/marketplace/subscriptions" },
    ]
  },

  // Organization section
  {
    type: "section",
    label: "ORGANIZATION"
  },
  {
    label: "Organization",
    href: "/organization",
    icon: <Building2 className="text-neutral-700 dark:text-neutral-200 h-5 w-5 flex-shrink-0" />,
    subItems: [
      { label: "Members", href: "/organization/members" },
      { label: "Teams", href: "/organization/teams" },
      { label: "Policies", href: "/organization/policies" },
      { label: "Usage", href: "/organization/usage" },
      { label: "Audit Log", href: "/organization/audit" },
    ]
  },
  {
    label: "Settings",
    href: "/settings",
    icon: <Settings className="text-neutral-700 dark:text-neutral-200 h-5 w-5 flex-shrink-0" />,
  },
];

const Logo = () => {
  return (
    <Link
      href="#"
      className="font-normal flex space-x-2 items-center text-sm text-black py-1 relative z-20"
    >
      <div className="h-5 w-6 bg-black dark:bg-white rounded-br-lg rounded-tr-sm rounded-tl-lg rounded-bl-sm flex-shrink-0" />
      <motion.span
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="font-medium text-black dark:text-white whitespace-pre"
      >
        AgentMesh
      </motion.span>
    </Link>
  );
};

const LogoIcon = () => {
  return (
    <Link
      href="#"
      className="font-normal flex space-x-2 items-center text-sm text-black py-1 relative z-20"
    >
      <div className="h-5 w-6 bg-black dark:bg-white rounded-br-lg rounded-tr-sm rounded-tl-lg rounded-bl-sm flex-shrink-0" />
    </Link>
  );
};

export default function SidebarWithState() {
  const [open, setOpen] = useState(true);

  return (
    <Sidebar open={open} setOpen={setOpen}>
      <SidebarBody className="justify-between gap-10">
        <div className="flex flex-col flex-1 overflow-y-auto overflow-x-hidden">
          {open ? <Logo /> : <LogoIcon />}
          <div className="mt-8 flex flex-col gap-4">
            {links.map((link, idx) => (
              <React.Fragment key={idx}>
                {link.type === "section" ? (
                  <div className="px-3 mb-2">
                    <span className="text-xs font-medium text-neutral-500">{link.label}</span>
                  </div>
                ) : (
                  <>
                    <SidebarLink link={link} />
                    {link.subItems && open && (
                      <div className="ml-4 flex flex-col gap-1">
                        {link.subItems.map((subItem, subIdx) => (
                          <SidebarLink
                            key={subIdx}
                            link={{
                              ...subItem,
                              icon: <div className="w-5" /> // Empty div for alignment
                            }}
                          />
                        ))}
                      </div>
                    )}
                  </>
                )}
              </React.Fragment>
            ))}
          </div>
        </div>
        <div>
          <SidebarLink
            link={{
              label: "John Doe",
              href: "#",
              icon: (
                <Image
                  src="/test.jpg"
                  className="h-7 w-7 flex-shrink-0 rounded-full"
                  width={50}
                  height={50}
                  alt="Avatar"
                />
              ),
            }}
          />
        </div>
      </SidebarBody>
    </Sidebar>
  );
}