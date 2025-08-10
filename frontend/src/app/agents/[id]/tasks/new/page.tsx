import React from 'react';
import { notFound } from 'next/navigation';
import { getAgent } from '@/lib/api';
import NewTaskClient from './NewTaskClient';

interface Props {
  params: Promise<{ id: string }>;
}

export default async function NewTaskPage({ params }: Props) {
  const { id } = await params;
  
  try {
    const { data: agent, error } = await getAgent(id);
    
    if (error || !agent) {
      notFound();
    }

    return <NewTaskClient agent={agent} />;
  } catch (error) {
    console.error('Failed to fetch agent:', error);
    notFound();
  }
}