import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { AddMCPServerForm } from "./form";
import ContentBlock from "@/components/ContentBlock/ContentBlock";

export default function AddMCPServerPage() {
  return (
    <ContentBlock
      header={{
        title: "Add MCP Server",
        backLink: {
          label: "Back to MCP Servers",
          href: "/mcp-servers"
        }
      }}
    >
      <div className="max-w-2xl mx-auto">
        <Card>
          <CardHeader>
            <CardTitle>Add MCP Server</CardTitle>
            <CardDescription>
              Connect an MCP server to your workspace
            </CardDescription>
          </CardHeader>
          <AddMCPServerForm />
        </Card>
      </div>
    </ContentBlock>
  );
} 