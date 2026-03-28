import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { CreateBundleForm } from "./form";

export default function AddBundlePage() {
  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: "MCP Servers", href: "/mcp-servers" },
          { label: "Bundle Servers" },
        ],
        description: "Combine multiple MCP servers into a single endpoint for your clients.",
        backLink: {
          label: "Back to MCP Servers",
          href: "/mcp-servers",
        },
      }}
    >
      <CreateBundleForm />
    </ContentBlock>
  );
}
