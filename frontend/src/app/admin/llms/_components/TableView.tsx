import Table from "@/components/Table/Table";
import type { components } from "@/api/schema";
type LLMModelInstance = components["schemas"]["LLMModelInstanceResponse"];

export default function TableView({ instances }: { instances: LLMModelInstance[] }) {
  const columns = [
    {
      header: "Name",
      accessor: "name",
      render: (value: string) => (
        <div className="font-semibold font-montserrat text-[14px] md:text-[16px] flex flex-col md:flex-row md:items-center gap-[10px] md:gap-[15px]">
          {value}
        </div>
      ),
    },
    {
      header: "Description",
      accessor: "description",
      cellClassName: "text-[12px] md:text-[14px]",
      render: (value: string) => (
        <div className="line-clamp-3 md:line-clamp-none">{value}</div>
      ),
    },
    {
      header: "Status",
      accessor: "status",
      render: (value: string) => <div className="text-xs text-muted-foreground">{value}</div>,
    },
  ];

  return <Table data={instances} columns={columns} />;
}
