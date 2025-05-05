import { LLMModel } from "@/lib/api";
import Table from "@/components/Table/Table";

export default function TableView({ list }: { list: LLMModel[] }) {
  const columns = [
    {
      header: "Name",
      accessor: "name",
      render: (value: string, item: LLMModel) => (
        <div className="font-semibold font-montserrat text-[14px] md:text-[16px] flex flex-col md:flex-row md:items-center gap-[10px] md:gap-[15px]">
          <div className="w-[27px] h-[27px] md:w-[30px] md:h-[30px] p-[1px] rounded-sm overflow-hidden dark:bg-white">
            <img
              // src={item.image}
              alt={item.name}
              className="object-contain w-full h-full rounded-sm"
            />
          </div>
          {value}
        </div>
      ),
    },
    {
      header: "Category",
      accessor: "category",
      render: (value: string) => <div className="text-accent">{value}</div>,
    },
    {
      header: "Description",
      accessor: "description",
      cellClassName: "text-[12px] md:text-[14px]",
      render: (value: string) => (
        <div className="line-clamp-3 md:line-clamp-none">{value}</div>
      ),
    },
  ];

  return <Table data={list} columns={columns} />;
}
