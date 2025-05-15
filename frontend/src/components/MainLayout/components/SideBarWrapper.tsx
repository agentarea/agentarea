import { cookies } from 'next/headers';
import { NavSection, BottomNavContent } from '../MainLayout';
import SideBar from './SideBar';

type SideBarWrapperProps = {
    menuContent: NavSection[];
    bottomMenuContent: BottomNavContent;
}

export default async function SideBarWrapper({ menuContent, bottomMenuContent }: SideBarWrapperProps) {
    const cookieStore = await cookies();
    const sidebarCollapsed = cookieStore.get('sidebarCollapsed');
    const initialCollapsed = sidebarCollapsed?.value === 'true';
    const expandedSections = cookieStore.get('expandedSections');
    const initialExpanded = expandedSections ? JSON.parse(expandedSections.value) : [];

    return (
        <SideBar 
            menuContent={menuContent}
            bottomMenuContent={bottomMenuContent}
            initialCollapsed={initialCollapsed}
            initialExpanded={initialExpanded}
        />
    );
} 