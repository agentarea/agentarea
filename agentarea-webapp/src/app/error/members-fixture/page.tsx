// TEMPORARY visual fixture — delete before commit.
import { SidebarProvider } from "@/components/ui/sidebar";
import MembersClient from "@/app/(main)/members/MembersClient";

const now = Date.now();
const day = 86_400_000;
const iso = (offsetDays: number) => new Date(now + offsetDays * day).toISOString();
const ME = "usr_4c81b2e0-aaaa-bbbb-cccc-000000000001";

export default function MembersFixturePage() {
  return (
    <SidebarProvider>
      <div className="h-screen w-screen bg-layoutBackground p-2 pl-[260px]">
        <div className="h-full overflow-hidden rounded-md border bg-white dark:bg-zinc-900">
          <MembersClient
            currentUser={{ id: ME, email: "jamakase54@gmail.com", name: "Artem Astapenko", username: null }}
            ownerUserId={ME}
            workspaceName="AgentArea"
            members={[
              { id: "m1", workspace_id: "w", user_id: ME, email: "jamakase54@gmail.com", display_name: "Artem Astapenko", joined_at: iso(-40), invitation_id: null },
            ]}
            invitations={[
              { id: "i1", workspace_id: "w", email: "test@test.ru", created_at: iso(-1), expires_at: iso(6), accepted_at: null, accepted_by_user_id: null, invited_by: ME, status: "pending" },
            ]}
          />
        </div>
      </div>
    </SidebarProvider>
  );
}
