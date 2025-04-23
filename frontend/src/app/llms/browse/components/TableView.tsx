import { LLMModel } from "../data";
import Table from "@/components/Table/Table";

export default function TableView({list}: {list: LLMModel[]}) {
    const columns = [
        {
            header: "Name", accessor: "name", render: (value: string, item: LLMModel) => (
                <div className="font-semibold font-montserrat text-[16px] flex flex-row items-center gap-[15px]">
                    <div className="w-[27px] h-[27px] p-[1px] rounded-sm overflow-hidden dark:bg-white">
                        <img src={item.image} alt={item.name} className="object-contain w-full h-full rounded-sm" />
                    </div>
                    {value}
                </div>
            ),
            sortable: true,
            sortableDirection: "asc" as "asc" | "desc"
        },
        {header: "Category", accessor: "category", render: (value: string) => <div className="text-accent">{value}</div>, sortable: true},
        {header: "Description", accessor: "description"},
    ];

    return (
        <Table data={list} columns={columns} />
    )
}