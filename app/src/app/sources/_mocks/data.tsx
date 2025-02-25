import { ReactElement } from "react";
import {
  Globe,
  Mail,
  Database,
  Building2,
  MessageSquare,
  FileText,
  Github,
  Box,
  CalendarDays,
  Trello,
  Gitlab,
  LineChart,
  Users,
  ShoppingCart,
  Wallet,
  Briefcase
} from "lucide-react";

export type SourceType = 
  | "E-commerce" 
  | "Email" 
  | "Database" 
  | "Directory" 
  | "Communication" 
  | "Storage" 
  | "Analytics" 
  | "Project Management" 
  | "Version Control" 
  | "CRM" 
  | "Finance" 
  | "HR";

export type SourceStatus = "connected" | "disconnected" | "error" | "in_progress";

export interface DataSource {
  id: string;
  name: string;
  type: SourceType;
  status: SourceStatus;
  lastSync: string;
  description: string;
  icon: ReactElement;
  dataPoints: string;
  ownership: "own" | "delegated";
  visibility: "private" | "shared";
  sourceOrg: string;
  isSetup: boolean;
  resourceTypes: string[];
}

export interface Permission {
  id: string;
  type: "user" | "team" | "organization";
  name: string;
  access: "read" | "write" | "admin";
  grantedBy: string;
  grantedAt: string;
  parentId: string | null;
  children?: Permission[];
  scope: {
    resources: string[];
    actions: string[];
  };
}

const createIcon = (Icon: any) => <Icon className="h-6 w-6" />;

export const mockDataSources: DataSource[] = [
  {
    id: "source-1",
    name: "Shopify Store",
    type: "E-commerce",
    status: "connected",
    lastSync: "5 minutes ago",
    description: "Main e-commerce store data including products, orders, and customers",
    icon: createIcon(Globe),
    dataPoints: "15K products, 50K orders",
    ownership: "own",
    visibility: "private",
    sourceOrg: "Our Company",
    isSetup: true,
    resourceTypes: ["products", "customers", "orders", "inventory"]
  },
  {
    id: "source-2",
    name: "Customer Support Inbox",
    type: "Email",
    status: "in_progress",
    lastSync: "2 minutes ago",
    description: "Support email inbox for ticket processing and routing",
    icon: createIcon(Mail),
    dataPoints: "1K emails/day",
    ownership: "delegated",
    visibility: "shared",
    sourceOrg: "Support Team",
    isSetup: true,
    resourceTypes: ["tickets", "agents", "templates"]
  },
  {
    id: "source-3",
    name: "Analytics Database",
    type: "Database",
    status: "error",
    lastSync: "1 hour ago",
    description: "Main analytics database containing user behavior and metrics",
    icon: createIcon(Database),
    dataPoints: "500GB data",
    ownership: "own",
    visibility: "shared",
    sourceOrg: "Our Company",
    isSetup: true,
    resourceTypes: ["events", "metrics", "reports"]
  },
  {
    id: "source-4",
    name: "Enterprise Directory",
    type: "Directory",
    status: "disconnected",
    lastSync: "Never",
    description: "Corporate user directory and authentication",
    icon: createIcon(Building2),
    dataPoints: "Not connected",
    ownership: "delegated",
    visibility: "private",
    sourceOrg: "IT Department",
    isSetup: false,
    resourceTypes: ["users", "groups", "permissions"]
  },
  {
    id: "source-5",
    name: "Slack Workspace",
    type: "Communication",
    status: "connected",
    lastSync: "1 minute ago",
    description: "Team communication and collaboration platform",
    icon: createIcon(MessageSquare),
    dataPoints: "50 channels, 200 users",
    ownership: "own",
    visibility: "private",
    sourceOrg: "Our Company",
    isSetup: true,
    resourceTypes: ["messages", "channels", "users"]
  },
  {
    id: "source-6",
    name: "Google Drive",
    type: "Storage",
    status: "connected",
    lastSync: "10 minutes ago",
    description: "Company document storage and sharing",
    icon: createIcon(FileText),
    dataPoints: "100GB used",
    ownership: "own",
    visibility: "shared",
    sourceOrg: "Our Company",
    isSetup: true,
    resourceTypes: ["documents", "folders", "permissions"]
  },
  {
    id: "source-7",
    name: "GitHub Repository",
    type: "Version Control",
    status: "connected",
    lastSync: "3 minutes ago",
    description: "Main code repository for the platform",
    icon: createIcon(Github),
    dataPoints: "1K repositories",
    ownership: "own",
    visibility: "private",
    sourceOrg: "Engineering",
    isSetup: true,
    resourceTypes: ["repositories", "pull requests", "issues"]
  },
  {
    id: "source-8",
    name: "AWS S3 Storage",
    type: "Storage",
    status: "connected",
    lastSync: "15 minutes ago",
    description: "Cloud storage for application data",
    icon: createIcon(Box),
    dataPoints: "2TB data",
    ownership: "own",
    visibility: "private",
    sourceOrg: "Our Company",
    isSetup: true,
    resourceTypes: ["buckets", "objects", "permissions"]
  },
  {
    id: "source-9",
    name: "Google Calendar",
    type: "Project Management",
    status: "connected",
    lastSync: "7 minutes ago",
    description: "Team calendar and scheduling",
    icon: createIcon(CalendarDays),
    dataPoints: "100 calendars",
    ownership: "delegated",
    visibility: "shared",
    sourceOrg: "Operations",
    isSetup: true,
    resourceTypes: ["events", "calendars", "attendees"]
  },
  {
    id: "source-10",
    name: "Jira Project",
    type: "Project Management",
    status: "error",
    lastSync: "2 hours ago",
    description: "Project management and issue tracking",
    icon: createIcon(Trello),
    dataPoints: "500 active issues",
    ownership: "delegated",
    visibility: "shared",
    sourceOrg: "Product Team",
    isSetup: true,
    resourceTypes: ["issues", "sprints", "epics"]
  },
  {
    id: "source-11",
    name: "GitLab CI/CD",
    type: "Version Control",
    status: "in_progress",
    lastSync: "45 minutes ago",
    description: "Continuous integration and deployment pipeline",
    icon: createIcon(Gitlab),
    dataPoints: "100 pipelines/day",
    ownership: "own",
    visibility: "private",
    sourceOrg: "DevOps",
    isSetup: true,
    resourceTypes: ["pipelines", "builds", "artifacts"]
  },
  {
    id: "source-12",
    name: "Mixpanel Analytics",
    type: "Analytics",
    status: "connected",
    lastSync: "1 minute ago",
    description: "Product analytics and user behavior tracking",
    icon: createIcon(LineChart),
    dataPoints: "1M events/day",
    ownership: "own",
    visibility: "private",
    sourceOrg: "Product Analytics",
    isSetup: true,
    resourceTypes: ["events", "funnels", "cohorts"]
  },
  {
    id: "source-13",
    name: "Salesforce CRM",
    type: "CRM",
    status: "connected",
    lastSync: "30 minutes ago",
    description: "Customer relationship management system",
    icon: createIcon(Users),
    dataPoints: "10K contacts",
    ownership: "delegated",
    visibility: "shared",
    sourceOrg: "Sales Team",
    isSetup: true,
    resourceTypes: ["contacts", "opportunities", "accounts"]
  },
  {
    id: "source-14",
    name: "WooCommerce Store",
    type: "E-commerce",
    status: "disconnected",
    lastSync: "1 day ago",
    description: "Secondary e-commerce platform",
    icon: createIcon(ShoppingCart),
    dataPoints: "5K products",
    ownership: "own",
    visibility: "private",
    sourceOrg: "Retail Division",
    isSetup: false,
    resourceTypes: ["products", "orders", "customers"]
  },
  {
    id: "source-15",
    name: "Stripe Payments",
    type: "Finance",
    status: "connected",
    lastSync: "1 minute ago",
    description: "Payment processing and financial transactions",
    icon: createIcon(Wallet),
    dataPoints: "1K transactions/day",
    ownership: "own",
    visibility: "private",
    sourceOrg: "Finance",
    isSetup: true,
    resourceTypes: ["payments", "customers", "subscriptions"]
  },
  {
    id: "source-16",
    name: "Workday HR",
    type: "HR",
    status: "connected",
    lastSync: "1 hour ago",
    description: "Human resources management system",
    icon: createIcon(Briefcase),
    dataPoints: "500 employees",
    ownership: "delegated",
    visibility: "private",
    sourceOrg: "HR Department",
    isSetup: true,
    resourceTypes: ["employees", "positions", "benefits"]
  }
];

export const mockPermissions: Permission[] = [
  {
    id: "perm-1",
    type: "organization",
    name: "Our Company",
    access: "admin",
    grantedBy: "System",
    grantedAt: "2024-03-20",
    parentId: null,
    scope: {
      resources: ["*"],
      actions: ["*"]
    },
    children: [
      {
        id: "perm-2",
        type: "team",
        name: "Data Science Team",
        access: "write",
        grantedBy: "John Doe",
        grantedAt: "2024-03-19",
        parentId: "perm-1",
        scope: {
          resources: ["analytics", "models", "datasets"],
          actions: ["read", "write", "execute"]
        },
        children: [
          {
            id: "perm-4",
            type: "user",
            name: "Jane Smith",
            access: "write",
            grantedBy: "John Doe",
            grantedAt: "2024-03-17",
            parentId: "perm-2",
            scope: {
              resources: ["analytics", "models"],
              actions: ["read", "write"]
            }
          }
        ]
      },
      {
        id: "perm-5",
        type: "team",
        name: "Engineering Team",
        access: "admin",
        grantedBy: "System",
        grantedAt: "2024-03-16",
        parentId: "perm-1",
        scope: {
          resources: ["infrastructure", "code", "deployments"],
          actions: ["read", "write", "execute", "delete"]
        }
      }
    ]
  },
  {
    id: "perm-3",
    type: "organization",
    name: "Analytics Department",
    access: "read",
    grantedBy: "John Doe",
    grantedAt: "2024-03-18",
    parentId: null,
    scope: {
      resources: ["analytics", "reports"],
      actions: ["read"]
    },
    children: [
      {
        id: "perm-6",
        type: "team",
        name: "Sales Department",
        access: "read",
        grantedBy: "Jane Smith",
        grantedAt: "2024-03-15",
        parentId: "perm-3",
        scope: {
          resources: ["reports"],
          actions: ["read"]
        }
      }
    ]
  }
];

export const statusColors: Record<SourceStatus, string> = {
  connected: "text-green-500 bg-green-50",
  disconnected: "text-yellow-500 bg-yellow-50",
  error: "text-red-500 bg-red-50",
  in_progress: "text-blue-500 bg-blue-50"
};

export const typeColors: Record<SourceType, string> = {
  "E-commerce": "bg-purple-100 text-purple-700",
  "Email": "bg-blue-100 text-blue-700",
  "Database": "bg-emerald-100 text-emerald-700",
  "Directory": "bg-orange-100 text-orange-700",
  "Communication": "bg-pink-100 text-pink-700",
  "Storage": "bg-indigo-100 text-indigo-700",
  "Analytics": "bg-cyan-100 text-cyan-700",
  "Project Management": "bg-violet-100 text-violet-700",
  "Version Control": "bg-gray-100 text-gray-700",
  "CRM": "bg-rose-100 text-rose-700",
  "Finance": "bg-green-100 text-green-700",
  "HR": "bg-amber-100 text-amber-700"
};

export const accessColors: Record<Permission["access"], string> = {
  read: "bg-blue-100 text-blue-700",
  write: "bg-purple-100 text-purple-700",
  admin: "bg-red-100 text-red-700"
}; 