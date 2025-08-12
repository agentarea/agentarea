import { redirect } from 'next/navigation';

export default async function ManageMCPsPage() {
  // Redirect to the new tools page
  redirect('/mcp-servers/tools');
} 