import SideBar from "./components/SideBar";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { 
  Home,
  Bot,
  Play,
  History,
  Database,
  Plus,
  Code,
  BookOpen,
  BarChart2,
  FileText,
  ShoppingBag,
  CreditCard,
  Users,
  UserCircle,
  Shield,
  LineChart,
  ClipboardList,
  Settings
} from "lucide-react"
import Header from "./components/Header";

export type NavSection = {
    id: string;
    section?: string;
    icon?: React.ReactElement;
    items: {
        label: string;
        href: string;
        icon?: React.ReactElement;
    }[];
};

export type BottomNavContent = {
    user: {
        name: string;
        email: string;
        avatar: string;
    };
} & NavSection;

export const navContent: NavSection[] = [
    {
        id: "home",
        items: [
            {
                label: "Home",
                href: "/home",
                icon: <Home className="h-4 w-4" />,
            }
        ]
    },
    {
        id: "agents",
        section: "Agents",
        icon: <Bot className="h-4 w-4" />,
        items: [
          { label: "Browse", href: "/agents/browse", icon: <Bot className="h-4 w-4" /> },
          { label: "Running", href: "/agents/running", icon: <Play className="h-4 w-4" /> },
          { label: "History", href: "/agents/history", icon: <History className="h-4 w-4" /> },
        ]
    },
    {
        id: "sources",
        section: "Sources",
        icon: <Database className="h-4 w-4" />,
        items: [
          { label: "Browse", href: "/sources/browse", icon: <Database className="h-4 w-4" /> },
          { label: "Connect New", href: "/sources/new", icon: <Plus className="h-4 w-4" /> },
        ]
    },
    {
        id: "creator",
        section: "Creator Hub",
        icon: <Code className="h-4 w-4" />,
        items: [
          { label: "My Agents", href: "/creator/agents", icon: <Bot className="h-4 w-4" /> },
          { label: "Development", href: "/creator/development", icon: <Code className="h-4 w-4" /> },
          { label: "Publications", href: "/creator/publications", icon: <BookOpen className="h-4 w-4" /> },
          { label: "Analytics", href: "/creator/analytics", icon: <BarChart2 className="h-4 w-4" /> },
          { label: "Documentation", href: "/creator/docs", icon: <FileText className="h-4 w-4" /> },
        ]
    },    
    {
      id: "catalog",
      section: "Catalog",
      icon: <ShoppingBag className="h-4 w-4" />,
      items: [
        { label: "Browse", href: "/marketplace/browse", icon: <ShoppingBag className="h-4 w-4" /> },
        { label: "Subscriptions", href: "/marketplace/subscriptions", icon: <CreditCard className="h-4 w-4" /> },
      ]
    },
    {
      id: "organization",
      section: "Organization",
      icon: <Users className="h-4 w-4" />,
      items: [
        { label: "Members", href: "/organization/members", icon: <UserCircle className="h-4 w-4" /> },
        { label: "Teams", href: "/organization/teams", icon: <Users className="h-4 w-4" /> },
        { label: "Policies", href: "/organization/policies", icon: <Shield className="h-4 w-4" /> },
        { label: "Usage", href: "/organization/usage", icon: <LineChart className="h-4 w-4" /> },
        { label: "Audit Log", href: "/organization/audit", icon: <ClipboardList className="h-4 w-4" /> },
      ]
    },
  ];

    const bottomNavContent: BottomNavContent = {
        id: "settings",
        items: [{
            label: "Settings",
            href: "/settings",
            icon: <Settings className="h-4 w-4" />,
        }],
        user: {
            name: "Admin",
            email: "admin@admin.com",
            avatar: "https://github.com/shadcn.png",
        }
    };

export default function MainLayout({ children }: { children: React.ReactNode }) {
    return (
        <>
            <div className="flex md:flex-row flex-col h-screen w-screen overflow-hidden">
                <SideBar menuContent={navContent} bottomMenuContent={bottomNavContent} />
                <Header menuContent={navContent} bottomMenuContent={bottomNavContent}/>
                <main className="flex-1 overflow-y-auto">
                    {children}
                </main>
            </div>
            <ThemeToggle className="absolute bottom-2 right-2"/>
        </>
    )
}