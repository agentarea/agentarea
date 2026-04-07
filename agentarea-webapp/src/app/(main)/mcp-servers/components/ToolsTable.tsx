import { Streamdown } from "streamdown";
import Table from "@/components/Table/Table";

interface Tool {
  name: string;
  description: string;
}

export function ToolsTable({ tools, label }: { tools: Tool[]; label?: string }) {
  const data = tools.map((t) => ({ id: t.name, name: t.name, description: t.description }));

  return (
    <div className="space-y-2">
      {label && (
        <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </div>
      )}
      <Table
        data={data}
        columns={[
          {
            header: "Name",
            accessor: "name",
            render: (value: string) => (
              <span className="whitespace-nowrap font-mono text-sm font-medium">{value}</span>
            ),
          },
          {
            header: "Description",
            accessor: "description",
            render: (value: string) =>
              value ? (
                <Streamdown className="prose prose-sm dark:prose-invert max-w-none text-muted-foreground">{value}</Streamdown>
              ) : (
                <span className="text-sm text-muted-foreground">-</span>
              ),
          },
        ]}
      />
    </div>
  );
}
