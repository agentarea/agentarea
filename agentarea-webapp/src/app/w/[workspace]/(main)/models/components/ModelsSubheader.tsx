import SearchInput from "@/components/SearchInput";
import ModelsSectionTabs from "./ModelsSectionTabs";
import ProviderHeaderTabs from "./ProviderHeaderTabs";

/**
 * One subheader for both model tabs: the section switch, the search and the
 * view toggle sit in the same place and look the same whichever tab is open.
 */
export default function ModelsSubheader({
  path,
  currentTab,
}: {
  path: "/models" | "/models/specs";
  currentTab: string;
}) {
  return (
    <>
      <ModelsSectionTabs />
      <div className="flex flex-1 items-center justify-end gap-3">
        <SearchInput urlParamName="search" urlPath={path} />
        <ProviderHeaderTabs currentTab={currentTab} />
      </div>
    </>
  );
}
