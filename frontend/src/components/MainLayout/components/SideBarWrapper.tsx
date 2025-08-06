"use client";

import { useState, useEffect } from 'react';
import { NavSection, BottomNavContent } from '../MainLayout';
import SideBar from './SideBar';

type SideBarWrapperProps = {
    menuContent: NavSection[];
    bottomMenuContent: BottomNavContent;
}

export default function SideBarWrapper({ menuContent, bottomMenuContent }: SideBarWrapperProps) {
    const [initialCollapsed, setInitialCollapsed] = useState(false);
    const [initialExpanded, setInitialExpanded] = useState<string[]>([]);

    useEffect(() => {
        // Read from localStorage instead of cookies for client-side state
        const sidebarCollapsed = localStorage.getItem('sidebarCollapsed');
        setInitialCollapsed(sidebarCollapsed === 'true');
        
        const expandedSections = localStorage.getItem('expandedSections');
        setInitialExpanded(expandedSections ? JSON.parse(expandedSections) : []);
    }, []);

    return (
        <SideBar 
            menuContent={menuContent}
            bottomMenuContent={bottomMenuContent}
            initialCollapsed={initialCollapsed}
            initialExpanded={initialExpanded}
        />
    );
} 