import { getMCPServer } from '@/lib/api';
import { Card, CardContent } from '@/components/ui/card';
import type { components } from '@/api/schema';
import ContentBlock from '@/components/ContentBlock/ContentBlock';
import MCPInstanceForm from './MCPInstanceForm';

type MCPServer = components["schemas"]["MCPServerResponse"];

export default async function MCPSetupPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  // Fetch MCP server
  const serverRes = await getMCPServer(id);
  
  const server: MCPServer | undefined = serverRes.data;

  console.log(serverRes.data);

  if (!server) {
    return (
      <ContentBlock
        header={{
          title: "Server Not Found",
          backLink: {
            label: "Back to MCP Servers",
            href: "/mcp-servers"
          }
        }}
      >
        <div className="max-w-3xl mx-auto">
          <Card>
            <CardContent>
              <p>The requested MCP server could not be found.</p>
            </CardContent>
          </Card>
        </div>
      </ContentBlock>
    );
  }

  return (
    <ContentBlock
      header={{
        title: `Setup ${server.name} Instance`,
        backLink: {
          label: "Back to MCP Servers",
          href: "/mcp-servers"
        }
      }}
    >
      <div className="max-w-3xl mx-auto">
        <MCPInstanceForm server={server} />
      </div>
    </ContentBlock>
  );
}